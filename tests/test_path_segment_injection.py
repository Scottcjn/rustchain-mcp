"""Tool arguments interpolated into URL paths must stay one path segment.

Without encoding, httpx resolves "../" in the path and treats "?"/"#" as the
start of a query/fragment, so an argument such as video_id="x/../../upload"
re-targets an authenticated request (bottube_comment/bottube_vote send the
caller's X-API-Key) to a different endpoint on the same host.
"""

from unittest import mock

import httpx
import pytest

from rustchain_mcp import server


def _raw(tool):
    return getattr(tool, "fn", tool)


def _call(tool_name, **kwargs):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[] if request.url.path.endswith("/api/agents") else {})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        mock.patch.object(server, "get_client", return_value=client),
        mock.patch.object(server, "RUSTCHAIN_NODE", "https://node.test"),
        mock.patch.object(server, "BOTTUBE_URL", "https://tube.test"),
        mock.patch.object(server, "BEACON_URL", "https://beacon.test/beacon"),
    ):
        result = _raw(getattr(server, tool_name))(**kwargs)
    return result, seen


CASES = [
    ("bottube_comment", "video_id", {"content": "hi", "api_key": "k"}, "/api/videos/", "/comment"),
    ("bottube_vote", "video_id", {"api_key": "k"}, "/api/videos/", "/vote"),
    ("bottube_agent_profile", "agent_name", {}, "/api/agents/", ""),
    ("bcos_verify", "cert_id", {}, "/bcos/verify/", ""),
    ("beacon_agent_status", "agent_id", {}, "/beacon/relay/status/", ""),
]


@pytest.mark.parametrize("tool,arg,extra,prefix,suffix", CASES)
@pytest.mark.parametrize("hostile", ["abc/../../upload", "../../admin", "abc?admin=1", "abc#frag"])
def test_hostile_argument_cannot_leave_its_path_segment(tool, arg, extra, prefix, suffix, hostile):
    _result, seen = _call(tool, **{arg: hostile}, **extra)

    first = seen[0]
    assert first.url.path.startswith(prefix)
    assert first.url.path.endswith(suffix) if suffix else True
    assert first.url.query == b""
    # The whole argument lands, encoded, in the single segment after prefix.
    raw_path = first.url.raw_path.decode().split("?")[0]
    segment = raw_path[len(prefix):len(raw_path) - len(suffix)]
    assert "/" not in segment and "?" not in segment and "#" not in segment


@pytest.mark.parametrize("tool,arg,extra,prefix,suffix", CASES)
@pytest.mark.parametrize("dot", [".", "..", "  "])
def test_dot_or_blank_segment_is_rejected_without_a_request(tool, arg, extra, prefix, suffix, dot):
    result, seen = _call(tool, **{arg: dot}, **extra)

    assert seen == []
    assert result["ok"] is False
    assert result["code"] == "INVALID_ARGUMENT"


def test_ordinary_ids_are_unchanged():
    _result, seen = _call("bottube_comment", video_id="Ab_c-123", content="hi", api_key="k")
    assert seen[0].url.path == "/api/videos/Ab_c-123/comment"
