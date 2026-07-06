"""
Tests for RustChain CrewAI Tools
"""

from unittest.mock import patch
from rustchain_crewai import (
    RustChainCheckBalance,
    RustChainListBounties,
    RustChainGetNodeHealth,
    RustChainGetCurrentEpoch,
    RustChainGetMiners,
    RustChainBoTTubeSearch,
    RustChainBoTTubeStats,
    RustChainBeaconDiscover,
    RustChainBeaconNetworkStats,
    RustChainBeaconChat,
)


class TestRustChainCheckBalance:
    """Tests for RustChainCheckBalance tool."""

    def test_tool_initialization(self):
        tool = RustChainCheckBalance()
        assert tool.name == "rustchain_check_balance"
        assert "RTC token balance" in tool.description

    @patch("rustchain_crewai._get")
    def test_check_balance_success(self, mock_get):
        mock_get.return_value = {"balance": 100.5}
        tool = RustChainCheckBalance()
        result = tool._run(wallet_id="test-wallet")
        assert "100.5" in result
        assert "test-wallet" in result

    @patch("rustchain_crewai._get")
    def test_check_balance_error(self, mock_get):
        mock_get.return_value = {"error": "Connection failed"}
        tool = RustChainCheckBalance()
        result = tool._run(wallet_id="test-wallet")
        assert "Error" in result


class TestRustChainListBounties:
    """Tests for RustChainListBounties tool."""

    def test_tool_initialization(self):
        tool = RustChainListBounties()
        assert tool.name == "rustchain_list_bounties"
        assert "bounties" in tool.description.lower()

    def test_list_bounties(self):
        tool = RustChainListBounties()
        result = tool._run()
        assert "RustChain Bounty Program" in result
        assert "RTC" in result


class TestRustChainGetNodeHealth:
    """Tests for RustChainGetNodeHealth tool."""

    def test_tool_initialization(self):
        tool = RustChainGetNodeHealth()
        assert tool.name == "rustchain_get_node_health"
        assert "health" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_get_health_success(self, mock_get):
        mock_get.return_value = {"ok": True, "version": "1.0.0", "uptime_s": 3600}
        tool = RustChainGetNodeHealth()
        result = tool._run()
        assert "Healthy" in result
        assert "1.0.0" in result

    @patch("rustchain_crewai._get")
    def test_get_health_error(self, mock_get):
        mock_get.return_value = {"error": "Timeout"}
        tool = RustChainGetNodeHealth()
        result = tool._run()
        assert "Error" in result


class TestRustChainGetCurrentEpoch:
    """Tests for RustChainGetCurrentEpoch tool."""

    def test_tool_initialization(self):
        tool = RustChainGetCurrentEpoch()
        assert tool.name == "rustchain_get_current_epoch"
        assert "epoch" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_get_epoch_success(self, mock_get):
        mock_get.return_value = {
            "epoch": 42,
            "slot": 1234,
            "enrolled_miners": 100,
            "epoch_pot": 5000,
        }
        tool = RustChainGetCurrentEpoch()
        result = tool._run()
        assert "42" in result
        assert "100" in result


class TestRustChainGetMiners:
    """Tests for RustChainGetMiners tool."""

    def test_tool_initialization(self):
        tool = RustChainGetMiners()
        assert tool.name == "rustchain_get_miners"
        assert "miners" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_get_miners_success(self, mock_get):
        mock_get.return_value = [
            {"miner": "test-miner", "hardware_type": "PowerPC G4", "antiquity_multiplier": 2.5}
        ]
        tool = RustChainGetMiners()
        result = tool._run()
        assert "1" in result
        assert "PowerPC G4" in result


class TestRustChainBoTTubeSearch:
    """Tests for RustChainBoTTubeSearch tool."""

    def test_tool_initialization(self):
        tool = RustChainBoTTubeSearch()
        assert tool.name == "rustchain_bottube_search"
        assert "search" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_search_success(self, mock_get):
        mock_get.return_value = [
            {"title": "Test Video", "creator": "test-agent", "views": 100}
        ]
        tool = RustChainBoTTubeSearch()
        result = tool._run(query="test")
        assert "Test Video" in result

    @patch("rustchain_crewai._get")
    def test_search_no_results(self, mock_get):
        mock_get.return_value = []
        tool = RustChainBoTTubeSearch()
        result = tool._run(query="nonexistent")
        assert "No videos found" in result


class TestRustChainBoTTubeStats:
    """Tests for RustChainBoTTubeStats tool."""

    def test_tool_initialization(self):
        tool = RustChainBoTTubeStats()
        assert tool.name == "rustchain_bottube_stats"
        assert "stats" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_get_stats_success(self, mock_get):
        mock_get.return_value = {
            "videos": 1000,
            "agents": 50,
            "total_views": 100000,
        }
        tool = RustChainBoTTubeStats()
        result = tool._run()
        assert "1000" in result
        assert "50" in result


class TestRustChainBeaconDiscover:
    """Tests for RustChainBeaconDiscover tool."""

    def test_tool_initialization(self):
        tool = RustChainBeaconDiscover()
        assert tool.name == "rustchain_beacon_discover"
        assert "discover" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_discover_success(self, mock_get):
        mock_get.return_value = [
            {"agent_id": "test-agent", "name": "Test Agent", "status": "active"}
        ]
        tool = RustChainBeaconDiscover()
        result = tool._run()
        assert "1" in result
        assert "test-agent" in result


class TestRustChainBeaconNetworkStats:
    """Tests for RustChainBeaconNetworkStats tool."""

    def test_tool_initialization(self):
        tool = RustChainBeaconNetworkStats()
        assert tool.name == "rustchain_beacon_network_stats"
        assert "stats" in tool.description.lower()

    @patch("rustchain_crewai._get")
    def test_get_stats_success(self, mock_get):
        mock_get.return_value = {
            "native_agents": 10,
            "total_relay_agents": 50,
            "active": 40,
        }
        tool = RustChainBeaconNetworkStats()
        result = tool._run()
        assert "10" in result
        assert "50" in result


class TestRustChainBeaconChat:
    """Tests for RustChainBeaconChat tool."""

    def test_tool_initialization(self):
        tool = RustChainBeaconChat()
        assert tool.name == "rustchain_beacon_chat"
        assert "chat" in tool.description.lower()

    @patch("rustchain_crewai._post")
    def test_chat_success(self, mock_post):
        mock_post.return_value = {
            "agent": "Sophia Elya",
            "response": "Hello! How can I help you today?",
        }
        tool = RustChainBeaconChat()
        result = tool._run(agent_id="bcn_sophia_elya", message="Hi!")
        assert "Sophia Elya" in result
        assert "Hello!" in result

    @patch("rustchain_crewai._post")
    def test_chat_error(self, mock_post):
        mock_post.return_value = {"error": "Agent not found"}
        tool = RustChainBeaconChat()
        result = tool._run(agent_id="invalid", message="Hi!")
        assert "Error" in result
