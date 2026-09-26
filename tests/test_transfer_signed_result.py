"""wallet_transfer_signed must report what the node actually said.

The RustChain node's POST /wallet/transfer/signed answers an accepted transfer
with ``{"ok": true, "phase": "pending", "pending_id", "tx_hash",
"confirms_at", ...}`` and a rejection with an HTTP 4xx and ``{"error": ...}``.
Earlier releases read ``transaction_id``/``new_balance`` (fields the node never
sends), so an accepted transfer came back as ``success: True`` with
``transaction_id: None``, and a rejection surfaced only as a bare
``HTTPStatusError`` with the node's reason discarded.
"""

import shutil
import tempfile
from pathlib import Path
from unittest import mock

import httpx
import pytest

from rustchain_mcp import rustchain_crypto, server

NODE = "https://rustchain.test"
TO = "RTC" + "c" * 40


def _raw(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def sender():
    temp_dir = tempfile.mkdtemp()
    with mock.patch.object(rustchain_crypto.Path, "home", return_value=Path(temp_dir)):
        rustchain_crypto.create_wallet("result-sender", password="pw-result")
        yield "result-sender"
    shutil.rmtree(temp_dir, ignore_errors=True)


def _transfer(handler):
    """Run wallet_transfer_signed against an httpx.MockTransport node."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        mock.patch.object(server, "RUSTCHAIN_NODE", NODE),
        mock.patch.object(server, "get_client", return_value=client),
        mock.patch.object(
            server, "rustchain_transfer_signed", _raw(server.rustchain_transfer_signed)
        ),
    ):
        return _raw(server.wallet_transfer_signed)(
            from_wallet_id="result-sender",
            to_address=TO,
            amount_rtc=2.0,
            password="pw-result",
            memo="m",
        )


def test_accepted_transfer_surfaces_tx_hash_and_pending_phase(sender):
    def handler(request):
        return httpx.Response(200, json={
            "ok": True, "verified": True, "phase": "pending", "pending_id": 42,
            "tx_hash": "ab" * 16, "confirms_at": 1790000000,
            "message": "Transfer pending. Will confirm in 24 hours unless voided.",
        })

    result = _transfer(handler)

    assert result["success"] is True
    assert result["tx_hash"] == "ab" * 16
    assert result["transaction_id"] == "ab" * 16
    assert result["pending_id"] == 42
    assert result["phase"] == "pending"
    assert result["confirms_at"] == 1790000000


def test_rejected_transfer_is_not_success_and_keeps_node_reason(sender):
    def handler(request):
        return httpx.Response(400, json={"error": "Insufficient available balance"})

    result = _transfer(handler)

    assert result["success"] is False
    assert result["ok"] is False
    assert result["code"] == "TRANSFER_REJECTED"
    assert result["status_code"] == 400
    assert result["error"] == "Insufficient available balance"


def test_bad_signature_401_is_reported_not_raised(sender):
    def handler(request):
        return httpx.Response(401, json={"error": "Invalid signature"})

    result = _transfer(handler)

    assert result["success"] is False
    assert result["error"] == "Invalid signature"


def test_200_without_ok_true_is_not_success(sender):
    def handler(request):
        return httpx.Response(200, json={"ok": False, "error": "nonce replay"})

    result = _transfer(handler)

    assert result["success"] is False
    assert result["error"] == "nonce replay"


def test_read_timeout_is_flagged_outcome_unknown(sender):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    result = _transfer(handler)

    assert result["success"] is False
    assert result["code"] == "TRANSFER_OUTCOME_UNKNOWN"
    assert result["outcome_unknown"] is True
    assert "wallet_history" in result["error"]


def test_connect_error_is_known_not_submitted(sender):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    result = _transfer(handler)

    assert result["success"] is False
    assert result["code"] == "NODE_UNREACHABLE"
    assert result["outcome_unknown"] is False
