# SPDX-License-Identifier: MIT
"""Hardening regression tests for evangelist_agent.py."""

from __future__ import annotations

from typing import Any

import evangelist_agent


class _Resp:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, payloads: list[tuple[int, Any]]):
        self._payloads = list(payloads)

    def get(self, *args: Any, **kwargs: Any) -> _Resp:  # noqa: ARG002
        code, payload = self._payloads.pop(0)
        return _Resp(code, payload)


def test_discover_agents_from_beacon_accepts_list_of_dicts_and_filters_invalid(monkeypatch):
    monkeypatch.setattr(
        evangelist_agent,
        "client",
        _Client(
            [
                (
                    200,
                    [
                        {"agent_id": "bcn_alpha"},
                        "non-dict-entry",
                        42,
                        {"id": "legacy_beta"},
                    ],
                )
            ]
        ),
    )
    assert evangelist_agent.discover_agents_from_beacon() == [
        {"agent_id": "bcn_alpha"},
        {"id": "legacy_beta"},
    ]

    monkeypatch.setattr(
        evangelist_agent,
        "client",
        _Client([(200, {"agents": [{"agent_id": "bcn_1"}, None, "bad"]})]),
    )
    assert evangelist_agent.discover_agents_from_beacon() == [{"agent_id": "bcn_1"}]


def test_run_once_handles_live_beacon_agent_id_dicts_without_type_error(monkeypatch):
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_a2a", lambda: [])
    monkeypatch.setattr(
        evangelist_agent,
        "discover_agents_from_beacon",
        lambda: [
            {"agent_id": "bcn_alpha"},
            {"agent_id": "bcn_beta"},
            {"name": "missing-id-dict"},
            {"id": {"nested": "unhashable"}},
            {"id": "   "},
        ],
    )
    monkeypatch.setattr(
        evangelist_agent,
        "discover_agents_from_bottube",
        lambda: ["bcn_beta", "bcn_gamma"],
    )
    monkeypatch.setattr(evangelist_agent, "AGENT_WALLET", "evangelist-self")
    monkeypatch.setattr(evangelist_agent, "wallet_can_cover_tip", lambda _amt: False)
    monkeypatch.setattr(evangelist_agent, "generate_onboarding_post", lambda: None)

    pinged_ids: list[str] = []

    def _mock_ping(agent_id: str, message: str, dry_run: bool = False, offer_tip: bool = False) -> bool:
        del message, dry_run, offer_tip
        pinged_ids.append(agent_id)
        return True

    monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", _mock_ping)

    count = evangelist_agent.run_once(dry_run=True)
    assert count == 3
    assert pinged_ids == ["bcn_alpha", "bcn_beta", "bcn_gamma"]


def test_wallet_can_cover_tip_fails_closed_on_nan_inf_and_invalid_tip_amount(monkeypatch):
    for bad_balance in (float("nan"), float("inf"), float("-inf"), True, False, None):
        monkeypatch.setattr(
            evangelist_agent,
            "client",
            _Client([(200, {"amount_rtc": bad_balance})]),
        )
        assert evangelist_agent.wallet_can_cover_tip(5) is False

    for bad_amount in (float("nan"), float("inf"), float("-inf"), -1, True):
        monkeypatch.setattr(
            evangelist_agent,
            "client",
            _Client([(200, {"amount_rtc": 100.0})]),
        )
        assert evangelist_agent.wallet_can_cover_tip(bad_amount) is False  # type: ignore[arg-type]


def test_stats_post_handles_nonfinite_uptime_without_overflow():
    stats = {"agents": 10, "videos": 20, "total_views": 300}
    for bad_uptime in (float("inf"), float("-inf"), float("nan")):
        post = evangelist_agent._stats_post(
            {"version": "2.2.1", "uptime_s": bad_uptime},
            stats,
        )
        assert "Node: v2.2.1\n" in post["content"]
        assert "uptime" not in post["content"]


def test_run_once_filters_self_before_cap_and_counts_only_successful_pings(monkeypatch):
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_a2a", lambda: [])
    monkeypatch.setattr(evangelist_agent, "AGENT_WALLET", "self-agent")
    monkeypatch.setattr(
        evangelist_agent,
        "discover_agents_from_beacon",
        lambda: [
            {"agent_id": "self-agent"},
            {"agent_id": "a1"},
            {"agent_id": "a2"},
            {"agent_id": "a3"},
            {"agent_id": "a4"},
            {"agent_id": "a5"},
            {"agent_id": "a6"},
        ],
    )
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_bottube", lambda: [])
    monkeypatch.setattr(evangelist_agent, "generate_onboarding_post", lambda: None)

    asked_amounts: list[float] = []
    monkeypatch.setattr(
        evangelist_agent,
        "wallet_can_cover_tip",
        lambda amt: asked_amounts.append(amt) or True,
    )

    attempted: list[str] = []

    def _partial_ping(agent_id: str, message: str, dry_run: bool = False, offer_tip: bool = False) -> bool:
        del message, dry_run, offer_tip
        attempted.append(agent_id)
        return agent_id in {"a1", "a3", "a5"}

    monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", _partial_ping)

    succeeded = evangelist_agent.run_once(dry_run=False)
    assert attempted == ["a1", "a2", "a3", "a4", "a5"]
    assert "self-agent" not in attempted
    assert asked_amounts == [5 * evangelist_agent.TIP_RTC]
    assert succeeded == 3


def test_run_once_skips_balance_query_when_only_self_discovered(monkeypatch):
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_a2a", lambda: [])
    monkeypatch.setattr(evangelist_agent, "AGENT_WALLET", "self-agent")
    monkeypatch.setattr(
        evangelist_agent,
        "discover_agents_from_beacon",
        lambda: [{"agent_id": "self-agent"}],
    )
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_bottube", lambda: [])
    monkeypatch.setattr(evangelist_agent, "generate_onboarding_post", lambda: None)

    balance_checked = []
    monkeypatch.setattr(
        evangelist_agent,
        "wallet_can_cover_tip",
        lambda amt: balance_checked.append(amt) or True,
    )

    assert evangelist_agent.run_once(dry_run=True) == 0
    assert balance_checked == []
