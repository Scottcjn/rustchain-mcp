"""Offline tests for the rustchain-mcp streaming / long-running tool contract.

Answers rustchain-mcp#231 authoritatively: tools are synchronous
request/response — no progressive partial results — bounded by
RUSTCHAIN_TIMEOUT, with a structured error contract on HTTP failures.

Run:  python -m pytest tests/test_streaming_contract.py -v   (no network)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rustchain_mcp import server

# ── helpers ─────────────────────────────────────────────────────

class FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError
            raise HTTPStatusError(
                f"HTTP {self.status_code}", request=SimpleNamespace(), response=self
            )

    def json(self):
        return self._payload


class FakeClient:
    """Stand-in for the shared httpx.Client with scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, *args, **kwargs):
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("no scripted response left")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _install_client(fake: FakeClient):
    return patch.object(server, "get_client", return_value=fake)


# ── contract tests ──────────────────────────────────────────────

def test_long_running_tool_is_request_response_full_result():
    """rustchain_miners blocks until the node responds and returns the full result.

    This is the documented streaming contract: no partial/progressive
    results are emitted; the caller receives the complete dict.
    """
    payload = {"miners": [{"wallet": "RTCaaa", "hw": "486"} for _ in range(25)]}
    fake = FakeClient([FakeResponse(200, payload)])
    with _install_client(fake):
        result = server.rustchain_miners()
    assert result["total_miners"] == 25
    assert "miners" in result and len(result["miners"]) == 20  # bounded output
    assert fake.calls[0].endswith("/api/miners")


def test_network_exception_propagates_immediately():
    """A dead node surfaces the network error right away (no silent hang, no fake data)."""
    from httpx import ConnectError

    fake = FakeClient([ConnectError("could not connect")])
    with _install_client(fake):
        with pytest.raises(ConnectError):
            server.rustchain_miners()


def test_timeout_bounds_long_running_calls():
    """ReadTimeout honors the configured RUSTCHAIN_TIMEOUT (no infinite wait)."""
    from httpx import ReadTimeout

    fake = FakeClient([ReadTimeout("timed out")])
    with _install_client(fake):
        with pytest.raises(ReadTimeout):
            server.rustchain_stats()


def test_http_error_returns_structured_contract():
    """HTTP 5xx from the node yields a structured error dict, never silent data."""
    fake = FakeClient([FakeResponse(503, {"error": "maintenance"})])
    with _install_client(fake):
        result = server.rustchain_miners()
    assert result["status"] == "error"
    assert "maintenance" in result["error"]


def test_http_404_returns_structured_contract():
    fake = FakeClient([FakeResponse(404, {"message": "not found"})])
    with _install_client(fake):
        result = server.rustchain_health()
    assert result["status"] == "unhealthy"
    assert "not found" in result["error"]


def test_default_timeout_is_documented_and_sane():
    """The configured timeout must be finite and positive."""
    assert server.RUSTCHAIN_TIMEOUT > 0
    assert server.RUSTCHAIN_TIMEOUT <= 60


def test_no_tool_accepts_progress_callback():
    """Confirms the honest contract: this server does not expose per-tool
    streaming/progress parameters (tools are synchronous)."""
    import inspect

    for name in dir(server):
        obj = getattr(server, name)
        if callable(obj) and getattr(obj, "__module__", "") == server.__name__:
            params = inspect.signature(obj).parameters
            assert "progress" not in params, f"{name} unexpectedly supports progress"
            assert "on_progress" not in params, f"{name} unexpectedly supports on_progress"
