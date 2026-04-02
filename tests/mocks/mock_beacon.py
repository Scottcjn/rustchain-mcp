"""
Mock Beacon Atlas service for testing.
"""
from typing import Optional, Dict, Any, List
import json


class MockBeaconService:
    """Mock implementation of Beacon Atlas API."""
    
    def __init__(self):
        self.agents = [
            {
                "id": "beacon-agent-1",
                "name": "Beacon Test Agent 1",
                "wallet": "wallet-1",
                "endpoints": ["https://agent1.example.com"],
                "capabilities": ["mcp", "a2a"],
                "last_seen": "2026-04-02T12:00:00Z"
            },
            {
                "id": "beacon-agent-2",
                "name": "Beacon Test Agent 2",
                "wallet": "wallet-2",
                "endpoints": ["https://agent2.example.com"],
                "capabilities": ["mcp"],
                "last_seen": "2026-04-02T11:30:00Z"
            },
            {
                "id": "beacon-agent-3",
                "name": "Beacon Test Agent 3",
                "wallet": "wallet-3",
                "endpoints": ["https://agent3.example.com"],
                "capabilities": ["a2a"],
                "last_seen": "2026-04-02T10:15:00Z"
            }
        ]
        self.pings = []
    
    def get_agents(self, limit: int = 50) -> Dict[str, Any]:
        """Mock GET /atlas/agents endpoint."""
        return {
            "agents": self.agents[:limit],
            "total": len(self.agents),
            "limit": limit
        }
    
    def post_ping(self, ping_data: Dict[str, Any]) -> Dict[str, Any]:
        """Mock POST /ping endpoint."""
        ping_id = f"ping-{len(self.pings) + 1}"
        ping_record = {
            "id": ping_id,
            **ping_data,
            "status": "sent",
            "created_at": "2026-04-02T14:00:00Z"
        }
        self.pings.append(ping_record)
        
        # Simulate different responses based on agent_id
        agent_id = ping_data.get("to", "")
        if "invalid" in agent_id:
            return {
                "error": "Agent not found",
                "status": "failed"
            }, 404
        
        return {
            "id": ping_id,
            "status": "sent",
            "message": "Ping delivered to agent queue"
        }, 202
    
    def reset(self):
        """Reset mock state."""
        self.agents = self.agents[:3]  # Keep original 3 agents
        self.pings = []


# Global instance for easy import
mock_beacon = MockBeaconService()


def create_beacon_response(status_code: int = 200, **kwargs):
    """Create a mock httpx response for Beacon API."""
    from unittest.mock import Mock
    
    response_data = kwargs.get("response_data", {})
    
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_data
    mock_response.text = json.dumps(response_data)
    
    return mock_response


def setup_beacon_mocks(monkeypatch, mock_beacon_service: Optional[MockBeaconService] = None):
    """Setup monkeypatch mocks for Beacon API calls."""
    from unittest.mock import Mock
    import evangelist_agent
    
    if mock_beacon_service is None:
        mock_beacon_service = MockBeaconService()
    
    # Mock client.get for /atlas/agents
    def mock_get(url, **kwargs):
        mock_response = Mock()
        
        if "atlas/agents" in url:
            response_data = mock_beacon_service.get_agents(
                limit=kwargs.get("params", {}).get("limit", 50)
            )
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
        else:
            mock_response.status_code = 404
            mock_response.json.return_value = {"error": "Not found"}
            
        mock_response.text = json.dumps(mock_response.json.return_value)
        return mock_response
    
    # Mock client.post for /ping
    def mock_post(url, **kwargs):
        mock_response = Mock()
        
        if "ping" in url:
            ping_data = kwargs.get("json", {})
            response_data, status_code = mock_beacon_service.post_ping(ping_data)
            mock_response.status_code = status_code
            mock_response.json.return_value = response_data
        else:
            mock_response.status_code = 404
            mock_response.json.return_value = {"error": "Not found"}
            
        mock_response.text = json.dumps(mock_response.json.return_value)
        return mock_response
    
    # Create mock client
    mock_client = Mock()
    mock_client.get = Mock(side_effect=mock_get)
    mock_client.post = Mock(side_effect=mock_post)
    
    monkeypatch.setattr(evangelist_agent, "client", mock_client)
    
    return mock_beacon_service