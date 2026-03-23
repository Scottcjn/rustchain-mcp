"""Tests for wallet management tools (v0.4 — bounty #2302)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any
from unittest.mock import patch

import pytest

# Ensure the package root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rustchain_mcp.server as srv


# ── Helpers ────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeClient:
    """Minimal httpx client stub."""

    def __init__(self, get_resp: Any = None, post_resp: Any = None):
        self._get_resp = get_resp or {"balance": 42.0}
        self._post_resp = post_resp or {"tx_id": "txABC123", "balance": 40.0}
        self.posted: list[tuple[str, Any]] = []

    def get(self, url: str, params: dict | None = None) -> _FakeResponse:  # noqa: ARG002
        return _FakeResponse(self._get_resp)

    def post(self, url: str, json: Any = None) -> _FakeResponse:
        self.posted.append((url, json))
        return _FakeResponse(self._post_resp)


# ── Keystore fixtures ──────────────────────────────────────────

@pytest.fixture()
def tmp_keystore(tmp_path, monkeypatch):
    """Point the server at a temporary keystore directory."""
    monkeypatch.setattr(srv, "_KEYSTORE_DIR", str(tmp_path))
    return tmp_path


# ── wallet_create ──────────────────────────────────────────────

def test_wallet_create_returns_wallet_id(tmp_keystore):
    result = srv.wallet_create("test-bot")
    assert result["wallet_id"].startswith("RTC")
    assert result["label"] == "test-bot"
    assert "created_at" in result
    # Private key must NOT appear in response
    assert "private_key" not in result
    assert "seed_phrase" not in result


def test_wallet_create_persists_keystore_file(tmp_keystore):
    result = srv.wallet_create("persist-bot")
    wallet_id = result["wallet_id"]
    path = srv._wallet_path(wallet_id)
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["wallet_id"] == wallet_id
    assert "private_key_hex" in data  # stored locally
    assert "seed_phrase" in data


def test_wallet_create_keystore_permissions(tmp_keystore):
    result = srv.wallet_create("perms-bot")
    path = srv._wallet_path(result["wallet_id"])
    mode = oct(os.stat(path).st_mode)[-3:]
    assert mode == "600", f"Expected 600 permissions, got {mode}"


def test_wallet_create_unique_ids(tmp_keystore):
    id1 = srv.wallet_create("bot-a")["wallet_id"]
    id2 = srv.wallet_create("bot-b")["wallet_id"]
    assert id1 != id2


# ── wallet_balance ─────────────────────────────────────────────

def test_wallet_balance_queries_node(tmp_keystore):
    fake = _FakeClient(get_resp={"balance": 99.5})
    with patch.object(srv, "get_client", return_value=fake):
        result = srv.wallet_balance("RTCabc123")
    assert result["wallet_id"] == "RTCabc123"
    assert result["balance_rtc"] == 99.5


def test_wallet_balance_alt_key(tmp_keystore):
    fake = _FakeClient(get_resp={"balance_rtc": 10.0})
    with patch.object(srv, "get_client", return_value=fake):
        result = srv.wallet_balance("RTCdef456")
    assert result["balance_rtc"] == 10.0


# ── wallet_history ─────────────────────────────────────────────

def test_wallet_history_returns_transactions(tmp_keystore):
    txns = [{"tx_id": "t1", "amount": 5}, {"tx_id": "t2", "amount": 3}]
    fake = _FakeClient(get_resp={"transactions": txns})
    with patch.object(srv, "get_client", return_value=fake):
        result = srv.wallet_history("RTCaaa", limit=10)
    assert result["count"] == 2
    assert result["transactions"][0]["tx_id"] == "t1"


def test_wallet_history_list_response(tmp_keystore):
    txns = [{"tx_id": "t3"}]
    fake = _FakeClient(get_resp=txns)
    with patch.object(srv, "get_client", return_value=fake):
        result = srv.wallet_history("RTCbbb", limit=5)
    assert result["count"] == 1


# ── wallet_transfer_signed ─────────────────────────────────────

def test_wallet_transfer_signed_signs_and_posts(tmp_keystore):
    # Create a wallet first so keystore has the private key.
    created = srv.wallet_create("sender")
    wallet_id = created["wallet_id"]

    fake = _FakeClient(post_resp={"tx_id": "txXYZ", "balance": 50.0})
    with patch.object(srv, "get_client", return_value=fake):
        result = srv.wallet_transfer_signed(wallet_id, "RTCrecipient", 5.0, "test memo")

    assert result.get("tx_id") == "txXYZ"
    assert len(fake.posted) == 1
    url, payload = fake.posted[0]
    assert "transfer/signed" in url
    # Private key must NOT be in the payload sent to the node.
    assert "private_key" not in str(payload)
    assert payload["from_address"] == wallet_id
    assert payload["to_address"] == "RTCrecipient"
    assert payload["amount_rtc"] == 5.0
    assert "signature" in payload
    assert "public_key" in payload


def test_wallet_transfer_signed_missing_wallet_raises(tmp_keystore):
    with pytest.raises(FileNotFoundError):
        srv.wallet_transfer_signed("RTCnonexistent999", "RTCother", 1.0)


# ── wallet_list ────────────────────────────────────────────────

def test_wallet_list_empty_keystore(tmp_keystore):
    result = srv.wallet_list()
    assert result["count"] == 0
    assert result["wallets"] == []


def test_wallet_list_shows_created_wallets(tmp_keystore):
    srv.wallet_create("list-bot-1")
    srv.wallet_create("list-bot-2")
    result = srv.wallet_list()
    assert result["count"] == 2
    ids = {w["wallet_id"] for w in result["wallets"]}
    # All wallet IDs start with RTC
    assert all(wid.startswith("RTC") for wid in ids)


def test_wallet_list_no_private_keys_in_output(tmp_keystore):
    srv.wallet_create("secret-bot")
    result = srv.wallet_list()
    for w in result["wallets"]:
        assert "private_key" not in w
        assert "seed_phrase" not in w


# ── wallet_export / wallet_import ─────────────────────────────

def test_wallet_export_and_reimport(tmp_keystore):
    created = srv.wallet_create("export-bot")
    wallet_id = created["wallet_id"]

    export_result = srv.wallet_export(wallet_id, passphrase="s3cur3p@ss")
    assert "keystore" in export_result
    ks = export_result["keystore"]
    assert ks["wallet_id"] == wallet_id
    # Private key must NOT appear in export response.
    assert "private_key_hex" not in ks
    assert "seed_phrase" not in ks
    assert "encrypted_private_key" in ks

    # Now import into a fresh keystore path.
    import_result = srv.wallet_import(json.dumps(ks), passphrase="s3cur3p@ss", label="reimported")
    assert import_result["wallet_id"] == wallet_id
    assert import_result["label"] == "reimported"


def test_wallet_export_short_passphrase_error(tmp_keystore):
    created = srv.wallet_create("pass-bot")
    result = srv.wallet_export(created["wallet_id"], passphrase="short")
    assert "error" in result


def test_wallet_import_seed_phrase(tmp_keystore):
    seed = "word0000 word0001 word0002 word0003 word0004 word0005 word0006 word0007 word0008 word0009 word0010 word0011"
    result = srv.wallet_import(seed, passphrase="", label="seed-import")
    assert result["wallet_id"].startswith("RTC")
    assert result["source"] == "seed_phrase"


def test_wallet_import_bad_json(tmp_keystore):
    result = srv.wallet_import("{not json}", passphrase="pass1234")
    assert "error" in result


def test_wallet_import_round_trip_private_key(tmp_keystore):
    """Exported + imported wallet must have the same private key hex."""
    created = srv.wallet_create("roundtrip-bot")
    wallet_id = created["wallet_id"]

    original = srv._load_wallet(wallet_id)
    orig_priv = original["private_key_hex"]

    export_ks = srv.wallet_export(wallet_id, passphrase="MyP@ss1234")["keystore"]

    # Import into a new wallet ID slot (simulate a different machine).
    import_result = srv.wallet_import(json.dumps(export_ks), passphrase="MyP@ss1234")
    imported = srv._load_wallet(import_result["wallet_id"])
    assert imported["private_key_hex"] == orig_priv
