"""Regression tests for the /wallet/transfer/signed message format.

These guard the exact class of bug that made signed transfers unusable: the
client must sign *byte-for-byte* the message the RustChain node reconstructs
and verifies. The node handler (createkr/Rustchain,
node/rustchain_v2_integrated_v2.2.1_rip200.py, POST /wallet/transfer/signed)
reconstructs:

    tx_data = {"from", "to", "amount", "memo", "nonce"}   (+ "chain_id" iff sent)
    message = json.dumps(tx_data, sort_keys=True, separators=(",", ":"))

Key invariants verified here:
  * NO `fee` key in the signed message (the node does not sign fee).
  * `nonce` is signed as a STRING.
  * The POST body carries the legacy field names the node reads
    (from_address / to_address / amount_rtc) plus public_key — and NOT the
    redundant canonical duplicates or any fee field.
  * The signature produced by the client verifies against the node's exact
    reconstruction.
"""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from rustchain_mcp import rustchain_crypto
from rustchain_mcp import server

# The @mcp.tool() decorator wraps these as FunctionTool; .fn is the raw function.
_wallet_transfer_signed = server.wallet_transfer_signed.fn


@pytest.fixture
def temp_keystore():
    """Temporary keystore dir (mirrors tests/test_wallet_tools.py)."""
    temp_dir = tempfile.mkdtemp()
    with mock.patch.object(rustchain_crypto.Path, "home", return_value=Path(temp_dir)):
        yield Path(temp_dir) / ".rustchain" / "mcp_wallets"
    shutil.rmtree(temp_dir, ignore_errors=True)


def _node_reconstruct(payload: dict) -> bytes:
    """Rebuild the exact bytes the node signs/verifies, from the POST body."""
    tx = {
        "from": str(payload["from_address"]).strip(),
        "to": str(payload["to_address"]).strip(),
        "amount": float(payload["amount_rtc"]),
        "memo": str(payload.get("memo", "")),
        "nonce": str(int(str(payload["nonce"]))),
    }
    chain_id = str(payload.get("chain_id", "")).strip()
    if chain_id:
        tx["chain_id"] = chain_id
    return json.dumps(tx, sort_keys=True, separators=(",", ":")).encode()


def _run_transfer(temp_keystore, memo="", amount_rtc=1.5):
    rustchain_crypto.create_wallet("signed-fmt-sender", password="")
    captured = {}

    resp = mock.Mock()
    resp.json.return_value = {"transaction_id": "tx_test", "new_balance": 0.0}
    resp.raise_for_status = mock.Mock()

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return resp

    # Under the installed fastmcp, @mcp.tool() wraps module functions as
    # FunctionTool, so the internal wallet_transfer_signed -> rustchain_transfer_signed
    # call must be pointed at the raw .fn to run. This still exercises the real
    # payload-construction code under test.
    with mock.patch("rustchain_mcp.server.get_client") as gc, \
         mock.patch("rustchain_mcp.server.rustchain_transfer_signed",
                    server.rustchain_transfer_signed.fn):
        client = mock.Mock()
        client.post.side_effect = fake_post
        gc.return_value = client
        _wallet_transfer_signed(
            from_wallet_id="signed-fmt-sender",
            to_address="RTC" + "b" * 40,
            amount_rtc=amount_rtc,
            password="",
            memo=memo,
        )
    return captured["payload"]


def test_signed_message_has_no_fee_and_verifies(temp_keystore):
    payload = _run_transfer(temp_keystore, memo="bounty payment")
    msg = _node_reconstruct(payload)
    assert b'"fee"' not in msg
    assert rustchain_crypto.verify_signature(
        msg, payload["signature"], payload["public_key"]
    ), "client signature must verify against the node's reconstructed message"


def test_signed_message_verifies_with_empty_memo(temp_keystore):
    payload = _run_transfer(temp_keystore, memo="")
    msg = _node_reconstruct(payload)
    assert rustchain_crypto.verify_signature(
        msg, payload["signature"], payload["public_key"]
    )


def test_payload_uses_node_field_names_only(temp_keystore):
    payload = _run_transfer(temp_keystore, memo="x")
    # Fields the node's preflight requires:
    for field in ("from_address", "to_address", "amount_rtc", "nonce",
                  "signature", "public_key"):
        assert field in payload, f"missing node-required field: {field}"
    # No fee anywhere, and no redundant canonical duplicates.
    assert "fee" not in payload and "fee_rtc" not in payload
    assert "from" not in payload and "to" not in payload and "amount" not in payload


def test_nonce_is_signed_as_string(temp_keystore):
    payload = _run_transfer(temp_keystore)
    msg = _node_reconstruct(payload)
    obj = json.loads(msg)
    assert isinstance(obj["nonce"], str), "nonce must be signed as a string"


def test_with_fee_key_would_not_verify(temp_keystore):
    """Guard: a message that includes `fee` (the old bug) must NOT verify —
    proving the node-format is fee-free."""
    payload = _run_transfer(temp_keystore, memo="regression")
    tx = {
        "from": payload["from_address"], "to": payload["to_address"],
        "amount": float(payload["amount_rtc"]), "fee": 0.0,
        "memo": payload.get("memo", ""), "nonce": str(int(str(payload["nonce"]))),
    }
    bad_msg = json.dumps(tx, sort_keys=True, separators=(",", ":")).encode()
    assert not rustchain_crypto.verify_signature(
        bad_msg, payload["signature"], payload["public_key"]
    ), "signature must NOT verify against a message that adds a fee field"
