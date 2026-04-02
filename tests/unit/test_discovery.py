"""
Unit tests for agent discovery functions.
"""
import pytest
from unittest.mock import Mock, patch
import evangelist_agent
from tests.mocks.mock_beacon import MockBeaconService, setup_beacon_mocks
from tests.mocks.mock_bottube import MockBoTTubeService, setup_bottube_mocks


class TestDiscoverAgentsFromBeacon:
    """Tests for discover_agents_from_beacon() function."""
    
    def test_successful_discovery(self, monkeypatch):
        """Test successful agent discovery from Beacon Atlas."""
        # Setup mock with sample agents
        mock_beacon = MockBeaconService()
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        agents = evangelist_agent.discover_agents_from_beacon()
        
        assert len(agents) == 3
        assert agents[0]["id"] == "beacon-agent-1"
        assert agents[1]["name"] == "Beacon Test Agent 2"
        assert agents[2]["wallet"] == "wallet-3"
    
    def test_empty_response(self, monkeypatch):
        """Test Beacon returns empty agent list."""
        mock_beacon = MockBeaconService()
        mock_beacon.agents = []  # Empty agent list
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        agents = evangelist_agent.discover_agents_from_beacon()
        
        assert agents == []
    
    def test_non_object_json_response(self, monkeypatch):
        """Test Beacon returns non-object JSON (edge case)."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=200,
            json=lambda: ["not", "an", "object"]  # Array instead of object
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_beacon()
        
        assert agents == []
    
    def test_network_error(self, monkeypatch):
        """Test network error when calling Beacon API."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("Network error")
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_beacon()
        
        assert agents == []
    
    def test_http_error_status(self, monkeypatch):
        """Test Beacon returns HTTP error status."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=500,
            json=lambda: {"error": "Internal server error"}
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_beacon()
        
        assert agents == []
    
    def test_missing_agents_key(self, monkeypatch):
        """Test Beacon response missing 'agents' key."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=200,
            json=lambda: {"data": [], "total": 0}  # No 'agents' key
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_beacon()
        
        assert agents == []
    
    def test_limit_parameter(self, monkeypatch):
        """Test limit parameter is passed correctly."""
        mock_beacon = MockBeaconService()
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        # Call function (implicit limit through client params)
        evangelist_agent.discover_agents_from_beacon()
        
        # Verify mock was called with limit param
        mock_client = evangelist_agent.client
        call_args = mock_client.get.call_args
        
        assert call_args is not None
        assert "params" in call_args.kwargs
        assert call_args.kwargs["params"]["limit"] == 50


class TestDiscoverAgentsFromBoTTube:
    """Tests for discover_agents_from_bottube() function."""
    
    def test_successful_discovery(self, monkeypatch):
        """Test successful agent discovery from BoTTube."""
        mock_bottube = MockBoTTubeService()
        setup_bottube_mocks(monkeypatch, mock_bottube)
        
        agents = evangelist_agent.discover_agents_from_bottube()
        
        assert len(agents) == 5
        assert agents[0] == "bottube-top-1"
        assert agents[1] == "bottube-top-2"
        assert agents[4] == "bottube-top-5"
    
    def test_filter_invalid_entries(self, monkeypatch):
        """Test filtering of invalid agent entries."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=200,
            json=lambda: {
                "top_agents": [
                    {"agent_name": "valid-agent"},  # Valid
                    {"agent_name": 123},  # Invalid: integer name
                    {"wrong_field": "test"},  # Missing agent_name
                    "not_a_dict",  # Not a dictionary
                    {},  # Empty dict
                    {"agent_name": "another-valid"},  # Valid
                ]
            }
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_bottube()
        
        assert agents == ["valid-agent", "another-valid"]
    
    def test_empty_top_agents(self, monkeypatch):
        """Test empty top_agents list."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=200,
            json=lambda: {"top_agents": []}
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_bottube()
        
        assert agents == []
    
    def test_missing_top_agents_key(self, monkeypatch):
        """Test response missing 'top_agents' key."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=200,
            json=lambda: {"data": [], "total": 0}  # No 'top_agents' key
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_bottube()
        
        assert agents == []
    
    def test_network_error(self, monkeypatch):
        """Test network error when calling BoTTube API."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("Network error")
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_bottube()
        
        assert agents == []
    
    def test_http_error_status(self, monkeypatch):
        """Test BoTTube returns HTTP error status."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=500,
            json=lambda: {"error": "Internal server error"}
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        agents = evangelist_agent.discover_agents_from_bottube()
        
        assert agents == []


class TestDiscoverAgentsFromA2A:
    """Tests for discover_agents_from_a2a() function."""
    
    def test_successful_a2a_check(self, monkeypatch):
        """Test successful A2A endpoint check."""
        mock_client = Mock()
        
        # Mock successful responses for both URLs
        mock_client.get.side_effect = [
            Mock(status_code=200, json=lambda: {"name": "RustChain Agent"}),
            Mock(status_code=200, json=lambda: {"name": "BoTTube Agent"})
        ]
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        # Function returns None, we just test it doesn't crash
        result = evangelist_agent.discover_agents_from_a2a()
        
        # Verify both URLs were called
        assert mock_client.get.call_count == 2
        call_urls = [call[0][0] for call in mock_client.get.call_args_list]
        
        assert "rustchain.org/.well-known/agent.json" in call_urls[0]
        assert "bottube.ai/.well-known/agent.json" in call_urls[1]
    
    def test_partial_failures(self, monkeypatch):
        """Test some A2A endpoints fail."""
        mock_client = Mock()
        
        # First succeeds, second fails
        mock_client.get.side_effect = [
            Mock(status_code=200, json=lambda: {"name": "RustChain Agent"}),
            Mock(status_code=404, json=lambda: {"error": "Not found"})
        ]
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.discover_agents_from_a2a()
        
        # Should still complete without error
        assert mock_client.get.call_count == 2
    
    def test_all_failures(self, monkeypatch):
        """Test all A2A endpoints fail."""
        mock_client = Mock()
        
        # Both fail
        mock_client.get.side_effect = [
            Mock(status_code=404, json=lambda: {"error": "Not found"}),
            Mock(status_code=500, json=lambda: {"error": "Server error"})
        ]
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.discover_agents_from_a2a()
        
        # Should still complete without error
        assert mock_client.get.call_count == 2
    
    def test_network_errors(self, monkeypatch):
        """Test network errors for A2A endpoints."""
        mock_client = Mock()
        
        # Both throw network errors
        mock_client.get.side_effect = [
            Exception("DNS failure"),
            Exception("Connection timeout")
        ]
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.discover_agents_from_a2a()
        
        # Should still complete without error
        assert mock_client.get.call_count == 2
    
    @patch.object(evangelist_agent.log, 'info')
    def test_logging_on_success(self, mock_log, monkeypatch):
        """Test logging when A2A endpoints are accessible."""
        mock_client = Mock()
        mock_client.get.return_value = Mock(
            status_code=200,
            json=lambda: {"name": "Test Agent"}
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        evangelist_agent.discover_agents_from_a2a()
        
        # Verify info log was called
        assert mock_log.called