"""
Mock BoTTube service for testing.
"""
from typing import Dict, Any, List
import json


class MockBoTTubeService:
    """Mock implementation of BoTTube API."""
    
    def __init__(self):
        self.stats = {
            "total_videos": 1500,
            "total_agents": 85,
            "top_agents": [
                {"agent_name": "bottube-top-1", "videos": 45, "views": 12000},
                {"agent_name": "bottube-top-2", "videos": 32, "views": 8500},
                {"agent_name": "bottube-top-3", "videos": 28, "views": 7200},
                {"agent_name": "bottube-top-4", "videos": 22, "views": 5400},
                {"agent_name": "bottube-top-5", "videos": 18, "views": 4200},
            ],
            "recent_videos": [
                {"id": "video-1", "title": "Test Video 1", "agent": "bottube-top-1"},
                {"id": "video-2", "title": "Test Video 2", "agent": "bottube-top-2"},
            ]
        }
        self.agent_profiles = {
            "bottube-top-1": {
                "name": "BoTTube Top Agent 1",
                "wallet": "bottube-wallet-1",
                "videos_count": 45,
                "subscribers": 1200
            },
            "bottube-top-2": {
                "name": "BoTTube Top Agent 2",
                "wallet": "bottube-wallet-2",
                "videos_count": 32,
                "subscribers": 850
            }
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Mock GET /api/stats endpoint."""
        return self.stats
    
    def get_agent_profile(self, agent_name: str) -> Dict[str, Any]:
        """Mock GET /api/agents/{agent_name} endpoint."""
        return self.agent_profiles.get(agent_name, {"error": "Agent not found"})
    
    def reset(self):
        """Reset mock state."""
        self.__init__()


# Global instance for easy import
mock_bottube = MockBoTTubeService()


def create_bottube_response(status_code: int = 200, **kwargs) -> Dict[str, Any]:
    """Create response data for BoTTube API."""
    response_data = kwargs.get("response_data", {})
    
    if not response_data:
        response_data = mock_bottube.get_stats()
    
    return response_data


def setup_bottube_mocks(monkeypatch, mock_bottube_service: MockBoTTubeService = None):
    """Setup monkeypatch mocks for BoTTube API calls."""
    from unittest.mock import Mock
    import evangelist_agent
    
    if mock_bottube_service is None:
        mock_bottube_service = MockBoTTubeService()
    
    def mock_get(url, **kwargs):
        mock_response = Mock()
        
        if "stats" in url:
            response_data = mock_bottube_service.get_stats()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
        elif "agents" in url:
            # Extract agent name from URL
            agent_name = url.split("/")[-1]
            response_data = mock_bottube_service.get_agent_profile(agent_name)
            mock_response.status_code = 200 if "error" not in response_data else 404
            mock_response.json.return_value = response_data
        else:
            mock_response.status_code = 404
            mock_response.json.return_value = {"error": "Not found"}
            
        mock_response.text = json.dumps(mock_response.json.return_value)
        return mock_response
    
    # Create mock client
    mock_client = Mock()
    mock_client.get = Mock(side_effect=mock_get)
    
    monkeypatch.setattr(evangelist_agent, "client", mock_client)
    
    return mock_bottube_service


def create_invalid_bottube_response() -> Dict[str, Any]:
    """Create invalid BoTTube response for error testing."""
    return {
        "top_agents": [
            {"agent_name": 123},  # Invalid: name should be string
            {"wrong_field": "test"},  # Missing agent_name
            "not_a_dict",  # Not a dictionary
            {},  # Empty dict
            {"agent_name": "valid-agent"},  # One valid entry
        ]
    }


def create_empty_bottube_response() -> Dict[str, Any]:
    """Create empty BoTTube response."""
    return {
        "total_videos": 0,
        "total_agents": 0,
        "top_agents": [],
        "recent_videos": []
    }