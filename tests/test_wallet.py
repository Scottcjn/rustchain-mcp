"""Unit tests for RustChain MCP wallet management tools (v0.4).

Tests cover all 7 wallet tools:
  - wallet_create
  - wallet_balance
  - wallet_history
  - wallet_transfer_signed
  - wallet_list
  - wallet_export
  - wallet_import

Uses a temporary directory for the keystore so tests are isolated.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import pytest

# Override wallet directory BEFORE importing wallet module
_tmpdir = tempfile.mkdtemp(prefix="rustchain_test_wallets_")
os.environ["RUSTCHAIN_WALLET_DIR"] = _tmpdir

import rustchain_mcp.wallet as wallet_mod  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_wallet_dir():
    """Remove all wallet files between tests."""
    d = Path(_tmpdir)
    d.mkdir(parents=True, exist_ok=True)
    yield
    for f in d.glob("*.json"):
        f.unlink()


@pytest.fixture()
def created_wallet():
    """Create a wallet and return its info."""
    return wallet_mod.wallet_create_impl(label="test-wallet", passphrase="testpass")


# ── Mnemonic / Crypto Helpers ─────────────────────────────────


class TestMnemonicGeneration:

    def test_generate_mnemonic_returns_12_words(self):
        mnemonic = wallet_mod._generate_mnemonic(12)
        words = mnemonic.split()
        assert len(words) == 12

    def test_generate_mnemonic_unique(self):
        m1 = wallet_mod._generate_mnemonic(12)
        m2 = wallet_mod._generate_mnemonic(12)
        assert m1 != m2, "Two mnemonics should not be identical"

    def test_seed_from_mnemonic_deterministic(self):
        mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        s1 = wallet_mod._seed_from_mnemonic(mnemonic)
        s2 = wallet_mod._seed_from_mnemonic(mnemonic)
        assert s1 == s2
        assert len(s1) == 64

    def test_keypair_from_seed_deterministic(self):
        seed = wallet_mod._seed_from_mnemonic("test mnemonic one two three four five six seven eight nine ten")
        priv1, pub1 = wallet_mod._ed25519_keypair_from_seed(seed)
        priv2, pub2 = wallet_mod._ed25519_keypair_from_seed(seed)
        assert priv1 == priv2
        assert pub1 == pub2
        assert len(priv1) == 32
        assert len(pub1) == 32


class TestWalletAddress:

    def test_address_starts_with_rtc(self):
        pub = bytes(32)
        addr = wallet_mod._wallet_address(pub)
        assert addr.startswith("RTC_")
        assert len(addr) == 44  # "RTC_" + 40 hex chars

    def test_address_deterministic(self):
        pub = b"\x01" * 32
        a1 = wallet_mod._wallet_address(pub)
        a2 = wallet_mod._wallet_address(pub)
        assert a1 == a2


class TestSignMessage:

    def test_sign_produces_64_bytes(self):
        seed = wallet_mod._seed_from_mnemonic("test sign message one two three four five six seven eight nine")
        priv, _pub = wallet_mod._ed25519_keypair_from_seed(seed)
        sig = wallet_mod._sign_message(priv, b"hello world")
        assert len(sig) == 64

    def test_sign_deterministic(self):
        seed = wallet_mod._seed_from_mnemonic("test sign two one two three four five six seven eight nine ten")
        priv, _pub = wallet_mod._ed25519_keypair_from_seed(seed)
        s1 = wallet_mod._sign_message(priv, b"data")
        s2 = wallet_mod._sign_message(priv, b"data")
        assert s1 == s2

    def test_different_messages_different_sigs(self):
        seed = wallet_mod._seed_from_mnemonic("test sign three one two three four five six seven eight nine ten")
        priv, _pub = wallet_mod._ed25519_keypair_from_seed(seed)
        s1 = wallet_mod._sign_message(priv, b"message A")
        s2 = wallet_mod._sign_message(priv, b"message B")
        assert s1 != s2


# ── Encryption / Decryption ───────────────────────────────────


class TestKeystoreEncryption:

    def test_encrypt_decrypt_roundtrip(self):
        data = {"key": "value", "number": 42}
        encrypted = wallet_mod._encrypt_keystore(data, "password123")
        assert "ciphertext" in encrypted
        assert "salt" in encrypted
        decrypted = wallet_mod._decrypt_keystore(encrypted, "password123")
        assert decrypted == data

    def test_wrong_passphrase_fails(self):
        data = {"secret": "data"}
        encrypted = wallet_mod._encrypt_keystore(data, "correct")
        with pytest.raises(Exception):
            wallet_mod._decrypt_keystore(encrypted, "wrong")


# ── wallet_create ─────────────────────────────────────────────


class TestWalletCreate:

    def test_create_returns_required_fields(self):
        result = wallet_mod.wallet_create_impl(label="my-agent", passphrase="p@ss")
        assert "wallet_id" in result
        assert "address" in result
        assert "public_key" in result
        assert "mnemonic" in result
        assert "security_warning" in result
        assert result["label"] == "my-agent"

    def test_create_wallet_id_format(self):
        result = wallet_mod.wallet_create_impl()
        assert result["wallet_id"].startswith("rtc_")

    def test_create_address_format(self):
        result = wallet_mod.wallet_create_impl()
        assert result["address"].startswith("RTC_")

    def test_create_mnemonic_has_12_words(self):
        result = wallet_mod.wallet_create_impl()
        words = result["mnemonic"].split()
        assert len(words) == 12

    def test_create_saves_keystore_file(self):
        result = wallet_mod.wallet_create_impl(passphrase="test")
        filepath = Path(result["keystore_path"])
        assert filepath.exists()
        data = json.loads(filepath.read_text())
        assert "ciphertext" in data
        assert "private_key" not in data  # Private key must be encrypted

    def test_create_does_not_expose_private_key(self):
        result = wallet_mod.wallet_create_impl()
        assert "private_key" not in result

    def test_create_unique_wallets(self):
        r1 = wallet_mod.wallet_create_impl()
        r2 = wallet_mod.wallet_create_impl()
        assert r1["wallet_id"] != r2["wallet_id"]
        assert r1["address"] != r2["address"]
        assert r1["mnemonic"] != r2["mnemonic"]


# ── wallet_balance ────────────────────────────────────────────


class TestWalletBalance:

    def test_balance_resolves_local_wallet_id(self, created_wallet):
        """If a local wallet_id is given, address should be resolved."""
        wid = created_wallet["wallet_id"]
        result = wallet_mod.wallet_balance_impl(wallet_id=wid)
        assert result["address"] == created_wallet["address"]

    def test_balance_passes_raw_address(self):
        """If an RTC address is given directly, it's used as-is."""
        result = wallet_mod.wallet_balance_impl(wallet_id="RTC_abc123")
        assert result["address"] == "RTC_abc123"

    def test_balance_handles_node_error(self):
        """Should return graceful error if node is unreachable."""
        result = wallet_mod.wallet_balance_impl(
            wallet_id="RTC_nonexistent",
            node_url="http://127.0.0.1:1",  # Unreachable
        )
        assert "error" in result
        assert result["balance_rtc"] == 0.0


# ── wallet_history ────────────────────────────────────────────


class TestWalletHistory:

    def test_history_returns_structure(self, created_wallet):
        result = wallet_mod.wallet_history_impl(
            wallet_id=created_wallet["wallet_id"],
            node_url="http://127.0.0.1:1",
        )
        assert "transactions" in result
        assert "wallet_id" in result

    def test_history_handles_node_error(self):
        result = wallet_mod.wallet_history_impl(
            wallet_id="RTC_test",
            node_url="http://127.0.0.1:1",
        )
        assert "error" in result
        assert isinstance(result["transactions"], list)


# ── wallet_transfer_signed ────────────────────────────────────


class TestWalletTransferSigned:

    def test_transfer_rejects_zero_amount(self, created_wallet):
        result = wallet_mod.wallet_transfer_signed_impl(
            wallet_id=created_wallet["wallet_id"],
            to_address="RTC_recipient",
            amount_rtc=0,
            passphrase="testpass",
        )
        assert "error" in result

    def test_transfer_rejects_negative_amount(self, created_wallet):
        result = wallet_mod.wallet_transfer_signed_impl(
            wallet_id=created_wallet["wallet_id"],
            to_address="RTC_recipient",
            amount_rtc=-5.0,
            passphrase="testpass",
        )
        assert "error" in result

    def test_transfer_rejects_nonexistent_wallet(self):
        result = wallet_mod.wallet_transfer_signed_impl(
            wallet_id="rtc_nonexistent",
            to_address="RTC_recipient",
            amount_rtc=10.0,
            passphrase="whatever",
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_transfer_rejects_wrong_passphrase(self, created_wallet):
        result = wallet_mod.wallet_transfer_signed_impl(
            wallet_id=created_wallet["wallet_id"],
            to_address="RTC_recipient",
            amount_rtc=10.0,
            passphrase="wrong_passphrase",
        )
        assert "error" in result

    def test_transfer_signs_and_submits(self, created_wallet):
        """Transfer should sign locally and attempt to submit."""
        result = wallet_mod.wallet_transfer_signed_impl(
            wallet_id=created_wallet["wallet_id"],
            to_address="RTC_recipient",
            amount_rtc=10.0,
            passphrase="testpass",
            node_url="http://127.0.0.1:1",  # Will fail at submission
        )
        # Should have attempted — error is from network, not signing
        assert "error" in result
        assert result["from_address"] == created_wallet["address"]
        assert result["to_address"] == "RTC_recipient"
        assert result["amount_rtc"] == 10.0


# ── wallet_list ───────────────────────────────────────────────


class TestWalletList:

    def test_list_empty_keystore(self):
        result = wallet_mod.wallet_list_impl()
        assert result["total"] == 0
        assert result["wallets"] == []

    def test_list_after_create(self, created_wallet):
        result = wallet_mod.wallet_list_impl()
        assert result["total"] == 1
        assert result["wallets"][0]["wallet_id"] == created_wallet["wallet_id"]
        assert result["wallets"][0]["address"] == created_wallet["address"]

    def test_list_multiple_wallets(self):
        wallet_mod.wallet_create_impl(label="w1", passphrase="p1")
        wallet_mod.wallet_create_impl(label="w2", passphrase="p2")
        wallet_mod.wallet_create_impl(label="w3", passphrase="p3")
        result = wallet_mod.wallet_list_impl()
        assert result["total"] == 3

    def test_list_does_not_expose_keys(self, created_wallet):
        result = wallet_mod.wallet_list_impl()
        wallet_entry = result["wallets"][0]
        assert "private_key" not in wallet_entry
        assert "mnemonic" not in wallet_entry


# ── wallet_export ─────────────────────────────────────────────


class TestWalletExport:

    def test_export_returns_encrypted_keystore(self, created_wallet):
        result = wallet_mod.wallet_export_impl(
            wallet_id=created_wallet["wallet_id"],
            passphrase="testpass",
        )
        assert "keystore_json" in result
        ks = result["keystore_json"]
        assert "ciphertext" in ks
        assert "salt" in ks
        # Must NOT contain plaintext private key
        assert "private_key" not in json.dumps(ks)

    def test_export_nonexistent_wallet(self):
        result = wallet_mod.wallet_export_impl(
            wallet_id="rtc_doesnotexist",
            passphrase="test",
        )
        assert "error" in result

    def test_export_wrong_passphrase(self, created_wallet):
        result = wallet_mod.wallet_export_impl(
            wallet_id=created_wallet["wallet_id"],
            passphrase="wrong_pass",
        )
        assert "error" in result


# ── wallet_import ─────────────────────────────────────────────


class TestWalletImport:

    def test_import_from_mnemonic(self, created_wallet):
        mnemonic = created_wallet["mnemonic"]
        result = wallet_mod.wallet_import_impl(
            passphrase="import_pass",
            mnemonic=mnemonic,
            label="recovered",
        )
        assert "wallet_id" in result
        assert result["address"] == created_wallet["address"]
        assert result["imported_from"] == "mnemonic"
        # Must NOT expose private key
        assert "private_key" not in result

    def test_import_from_keystore_json(self, created_wallet):
        # Export first
        exported = wallet_mod.wallet_export_impl(
            wallet_id=created_wallet["wallet_id"],
            passphrase="testpass",
        )
        ks_json = json.dumps(exported["keystore_json"])

        # Delete original
        orig_path = Path(_tmpdir) / f"{created_wallet['wallet_id']}.json"
        if orig_path.exists():
            orig_path.unlink()

        # Import
        result = wallet_mod.wallet_import_impl(
            passphrase="testpass",
            keystore_json=ks_json,
            label="from-export",
        )
        assert "wallet_id" in result
        assert result["address"] == created_wallet["address"]
        assert result["imported_from"] == "keystore"

    def test_import_rejects_both_mnemonic_and_keystore(self):
        result = wallet_mod.wallet_import_impl(
            mnemonic="word " * 12,
            keystore_json='{"some": "json"}',
        )
        assert "error" in result

    def test_import_rejects_neither_mnemonic_nor_keystore(self):
        result = wallet_mod.wallet_import_impl()
        assert "error" in result

    def test_import_rejects_invalid_mnemonic_length(self):
        result = wallet_mod.wallet_import_impl(mnemonic="only three words")
        assert "error" in result
        assert "12-24 words" in result["error"]

    def test_import_rejects_invalid_keystore_json(self):
        result = wallet_mod.wallet_import_impl(keystore_json="not valid json {{{")
        assert "error" in result


# ── Integration: create → export → import roundtrip ───────────


class TestCreateExportImportRoundtrip:

    def test_full_roundtrip(self):
        """Create a wallet, export it, delete it, import it, verify address matches."""
        # Create
        created = wallet_mod.wallet_create_impl(label="roundtrip", passphrase="secret")
        wallet_id = created["wallet_id"]
        address = created["address"]
        pub_key = created["public_key"]

        # Export
        exported = wallet_mod.wallet_export_impl(wallet_id=wallet_id, passphrase="secret")
        ks_json = json.dumps(exported["keystore_json"])

        # Delete
        (Path(_tmpdir) / f"{wallet_id}.json").unlink()

        # Import via keystore
        imported = wallet_mod.wallet_import_impl(
            passphrase="secret",
            keystore_json=ks_json,
            label="restored",
        )
        assert imported["address"] == address
        assert imported["public_key"] == pub_key

    def test_mnemonic_roundtrip(self):
        """Create a wallet, recover from mnemonic, verify same address."""
        created = wallet_mod.wallet_create_impl(label="mnem-test", passphrase="pw")
        mnemonic = created["mnemonic"]
        address = created["address"]

        recovered = wallet_mod.wallet_import_impl(
            passphrase="different_pw",
            mnemonic=mnemonic,
            label="recovered",
        )
        assert recovered["address"] == address
