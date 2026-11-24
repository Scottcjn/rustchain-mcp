# SPDX-License-Identifier: MIT
"""Regression tests for import_wallet export_keystore roundtrip and signing."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from rustchain_mcp import rustchain_crypto


@pytest.fixture
def temp_keystore():
    temp_dir = tempfile.mkdtemp()
    with mock.patch.object(rustchain_crypto.Path, "home", return_value=Path(temp_dir)):
        yield Path(temp_dir) / ".rustchain" / "mcp_wallets"
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_export_import_seed_and_legacy_wallet_roundtrip(temp_keystore):
    created = rustchain_crypto.create_wallet("roundtrip-seed", "pass-1")
    loaded = rustchain_crypto.load_wallet("roundtrip-seed", "pass-1")
    assert loaded is not None

    res = rustchain_crypto.import_wallet(
        loaded["mnemonic"],
        wallet_id="reimported-seed",
        password="pass-2",
    )
    assert res["wallet_id"] == "reimported-seed"
    assert res["address"] == created["address"]
    loaded2 = rustchain_crypto.load_wallet("reimported-seed", "pass-2")
    assert loaded2 is not None
    assert loaded2["private_key"] == loaded["private_key"]
    sig = rustchain_crypto.sign_message(b"seed-check", loaded2["private_key"])
    assert rustchain_crypto.verify_signature(b"seed-check", sig, created["public_key"])


def test_export_import_roundtrip_same_and_cross_password_produces_working_signer(temp_keystore):
    created = rustchain_crypto.create_wallet("signer-wallet", "src-pass")
    orig_loaded = rustchain_crypto.load_wallet("signer-wallet", "src-pass")
    exported_same = rustchain_crypto.export_keystore("src-pass")

    # 1. Direct encrypted export_keystore string with same password
    res_direct = rustchain_crypto.import_wallet(
        exported_same["encrypted_keystore"],
        wallet_id="restored-same",
        password="src-pass",
    )
    assert res_direct["wallets_imported"] == 1
    loaded_same = rustchain_crypto.load_wallet("restored-same", "src-pass")
    assert loaded_same is not None
    assert loaded_same["private_key"] == orig_loaded["private_key"]
    assert loaded_same["mnemonic"] == orig_loaded["mnemonic"]
    sig1 = rustchain_crypto.sign_message(b"tx-payload", loaded_same["private_key"])
    assert rustchain_crypto.verify_signature(b"tx-payload", sig1, created["public_key"])

    # 2. Decrypted backup JSON with different source_password -> new password
    decrypted_json = rustchain_crypto._decrypt_data(exported_same["encrypted_keystore"], "src-pass")
    res_cross = rustchain_crypto.import_wallet(
        decrypted_json,
        wallet_id="restored-cross",
        password="brand-new-pass",
        source_password="src-pass",
    )
    assert res_cross["wallets_imported"] == 1
    loaded_cross = rustchain_crypto.load_wallet("restored-cross", "brand-new-pass")
    assert loaded_cross is not None
    assert loaded_cross["private_key"] == orig_loaded["private_key"]
    assert loaded_cross["mnemonic"] == orig_loaded["mnemonic"]
    sig2 = rustchain_crypto.sign_message(b"tx-payload-2", loaded_cross["private_key"])
    assert rustchain_crypto.verify_signature(b"tx-payload-2", sig2, created["public_key"])


def test_import_wrong_source_password_fails_closed(temp_keystore):
    rustchain_crypto.create_wallet("locked-wallet", "right-pass")
    exported = rustchain_crypto.export_keystore("right-pass")
    res = rustchain_crypto.import_wallet(
        exported["encrypted_keystore"],
        wallet_id="should-fail",
        password="new-pass",
        source_password="wrong-pass",
    )
    assert "error" in res
    assert rustchain_crypto.load_wallet("should-fail", "new-pass") is None


def test_import_malformed_keystore_json_does_not_crash(temp_keystore):
    bad_scalar = rustchain_crypto.import_wallet(json.dumps([1, 2, 3]), "", "new-pass")
    assert "error" in bad_scalar

    missing_addr = rustchain_crypto.import_wallet(
        json.dumps({"wallets": [{"wallet_id": "no-addr", "encrypted_private_key": "x"}]}),
        "",
        "new-pass",
    )
    assert missing_addr["wallets_imported"] == 0
    assert missing_addr["failed"][0]["wallet_id"] == "no-addr"
