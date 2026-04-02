"""
Mock Moltbook service for testing.
"""
from typing import Dict, Any, List
import json
import time


class MockMoltbookService:
    """Mock implementation of Moltbook API."""
    
    def __init__(self):
        self.posts = []
        self.api_keys = {
            "valid-key": {
                "user_id": "user-123",
                "username": "test_user",
                "permissions": ["create_post", "read_posts"]
            },
            "expired-key": {
                "user_id": "user-456",
                "username": "expired_user",
                "permissions": [],
                "expired": True
            }
        }
        self.submolts = ["rustchain", "bottube", "a2a", "test"]
    
    def create_post(self, title: str, content: str, submolt: str, 
                   api_key: str = "") -> Dict[str, Any]:
        """Mock POST /api/v1/posts endpoint."""
        
        # Check API key
        if not api_key:
            return {"error": "Missing authorization"}, 401
        
        key_info = self.api_keys.get(api_key.replace("Bearer ", ""))
        if not key_info:
            return {"error": "Invalid API key"}, 401
        
        if key_info.get("expired"):
            return {"error": "API key expired"}, 403
        
        if "create_post" not in key_info.get("permissions", []):
            return {"error": "Insufficient permissions"}, 403
        
        # Validate submolt
        if submolt not in self.submolts:
            return {"error": f"Submolt '{submolt}' not found"}, 400
        
        # Create post
        post_id = f"post-{len(self.posts) + 1}"
        post = {
            "id": post_id,
            "title": title,
            "content": content,
            "submolt": submolt,
            "author": key_info["username"],
            "created_at": "2026-04-02T14:00:00Z",
            "upvotes": 0,
            "comments": 0
        }
        
        self.posts.append(post)
        
        return {
            "id": post_id,
            "title": title,
            "submolt": submolt,
            "created_at": post["created_at"],
            "url": f"https://moltbook.com/m/{submolt}/{post_id}"
        }, 201
    
    def get_posts(self, submolt: str = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Mock GET /api/v1/posts endpoint."""
        posts = self.posts
        
        if submolt:
            posts = [p for p in posts if p["submolt"] == submolt]
        
        return posts[:limit]
    
    def reset(self):
        """Reset mock state."""
        self.__init__()


# Global instance for easy import
mock_moltbook = MockMoltbookService()


def create_moltbook_response(status_code: int = 200, **kwargs) -> Dict[str, Any]:
    """Create response data for Moltbook API."""
    response_data = kwargs.get("response_data", {})
    
    if not response_data and status_code == 201:
        response_data = {
            "id": "post-123",
            "title": "Test Post",
            "submolt": "rustchain",
            "created_at": "2026-04-02T14:00:00Z",
            "url": "https://moltbook.com/m/rustchain/post-123"
        }
    
    return response_data


def setup_moltbook_mocks(monkeypatch, mock_moltbook_service: MockMoltbookService = None):
    """Setup monkeypatch mocks for Moltbook API calls."""
    from unittest.mock import Mock
    import evangelist_agent
    
    if mock_moltbook_service is None:
        mock_moltbook_service = MockMoltbookService()
    
    def mock_post(url, **kwargs):
        mock_response = Mock()
        
        if "posts" in url:
            headers = kwargs.get("headers", {})
            api_key = headers.get("Authorization", "").replace("Bearer ", "")
            
            json_data = kwargs.get("json", {})
            title = json_data.get("title", "")
            content = json_data.get("content", "")
            submolt = json_data.get("submolt", "")
            
            response_data, status_code = mock_moltbook_service.create_post(
                title, content, submolt, api_key
            )
            
            mock_response.status_code = status_code
            mock_response.json.return_value = response_data
            mock_response.text = json.dumps(response_data)
        else:
            mock_response.status_code = 404
            mock_response.json.return_value = {"error": "Not found"}
            mock_response.text = json.dumps({"error": "Not found"})
            
        return mock_response
    
    # Create mock client
    mock_client = Mock()
    mock_client.post = Mock(side_effect=mock_post)
    
    monkeypatch.setattr(evangelist_agent, "client", mock_client)
    
    return mock_moltbook_service


def create_moltbook_error_response(error_type: str = "auth") -> Dict[str, Any]:
    """Create error responses for Moltbook API testing."""
    errors = {
        "auth": {"error": "Missing authorization"},
        "invalid_key": {"error": "Invalid API key"},
        "expired_key": {"error": "API key expired"},
        "permission": {"error": "Insufficient permissions"},
        "invalid_submolt": {"error": "Submolt 'invalid' not found"},
        "server_error": {"error": "Internal server error"},
    }
    
    return errors.get(error_type, {"error": "Unknown error"})


def mock_moltbook_key_env(monkeypatch, key_type: str = "valid"):
    """Mock MOLTBOOK_API_KEY environment variable."""
    keys = {
        "valid": "valid-key",
        "expired": "expired-key",
        "invalid": "invalid-key",
        "empty": "",
        "none": None
    }
    
    key_value = keys.get(key_type, "")
    
    if key_value is None:
        monkeypatch.delenv("MOLTBOOK_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MOLTBOOK_API_KEY", key_value)