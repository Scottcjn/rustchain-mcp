"""
Unit tests for evangelist agent actions and workflows.
"""
import pytest
from unittest.mock import Mock, patch, call
import evangelist_agent
from tests.mocks.mock_beacon import MockBeaconService, setup_beacon_mocks
from tests.mocks.mock_bottube import MockBoTTubeService, setup_bottube_mocks
from tests.mocks.mock_moltbook import MockMoltbookService, setup_moltbook_mocks, mock_moltbook_key_env


class TestGenerateOnboardingPost:
    """Tests for generate_onboarding_post() function."""
    
    def test_successful_generation_with_live_stats(self, monkeypatch):
        """Test post generation with successful API calls."""
        mock_client = Mock()
        
        # Mock health and stats responses
        mock_client.get.side_effect = [
            Mock(status_code=200, json=lambda: {"version": "2.3.0", "ok": True, "uptime_s": 86400}),
            Mock(status_code=200, json=lambda: {"agents": 150, "videos": 900, "total_views": 60000})
        ]
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        post = evangelist_agent.generate_onboarding_post()
        
        assert "title" in post
        assert "submolt" in post
        assert "content" in post
        
        # Should contain live stats
        assert "2.3.0" in post["content"]  # Version from health
        assert "150" in post["content"]  # Agents from stats
        assert "900" in post["content"]  # Videos from stats
    
    def test_fallback_when_apis_fail(self, monkeypatch):
        """Test post generation when APIs fail (fallback to defaults)."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("API unavailable")
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        post = evangelist_agent.generate_onboarding_post()
        
        # Should still generate post with fallback values
        assert "title" in post
        assert "submolt" in post
        assert "content" in post
        
        # Should contain fallback values
        assert "2.2.1" in post["content"]  # Fallback version
        assert "130" in post["content"]  # Fallback agents
        assert "850" in post["content"]  # Fallback videos
    
    def test_template_rotation_by_hour(self, monkeypatch):
        """Test post template rotates based on UTC hour."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("API unavailable")
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        # Test different hours
        test_cases = [
            (0, "rustchain"),   # Hour 0 -> template 0 -> rustchain submolt
            (1, "proofofwork"), # Hour 1 -> template 1 -> proofofwork submolt
            (2, "rustchain"),   # Hour 2 -> template 0 -> rustchain submolt
        ]
        
        for hour, expected_submolt in test_cases:
            with patch('evangelist_agent.datetime') as mock_datetime:
                # Mock datetime.now() to return a mock with .hour attribute
                mock_now = Mock()
                mock_now.hour = hour
                # Also need to mock timezone.utc
                mock_datetime.now.return_value = mock_now
                mock_datetime.timezone.utc = Mock()  # Mock timezone.utc
                
                post = evangelist_agent.generate_onboarding_post()
                assert post["submolt"] == expected_submolt
    
    def test_post_structure(self):
        """Test generated post has correct structure."""
        # Mock APIs to fail so we get consistent output
        with patch.object(evangelist_agent.client, 'get', side_effect=Exception("API fail")):
            post = evangelist_agent.generate_onboarding_post()
            
            assert isinstance(post, dict)
            assert all(key in post for key in ["title", "submolt", "content"])
            assert len(post["title"]) > 10
            assert len(post["content"]) > 100
            assert post["submolt"] in ["rustchain", "proofofwork"]


class TestBeaconPingAgent:
    """Tests for beacon_ping_agent() function."""
    
    def test_successful_ping(self, monkeypatch):
        """Test successful Beacon ping."""
        mock_client = Mock()
        mock_client.post.return_value = Mock(status_code=202, json=lambda: {"status": "sent"})
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.beacon_ping_agent("agent-123", "Test message")
        
        assert result is True
        
        # Verify correct payload structure
        call_args = mock_client.post.call_args
        assert call_args is not None
        json_payload = call_args.kwargs["json"]
        
        assert json_payload["to"] == "agent-123"
        assert json_payload["message"] == "Test message"
        assert json_payload["from"] == evangelist_agent.AGENT_WALLET
        assert json_payload["type"] == "onboarding_offer"
        assert "tip_rtc" in json_payload["offer"]
        assert json_payload["offer"]["tip_rtc"] == 5
    
    def test_dry_run_mode(self, monkeypatch):
        """Test ping in dry-run mode doesn't call API."""
        mock_client = Mock()
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.beacon_ping_agent("agent-123", "Test message", dry_run=True)
        
        assert result is True
        assert not mock_client.post.called  # Should not call API in dry-run
    
    @patch.object(evangelist_agent.log, 'info')
    def test_dry_run_logging(self, mock_log, monkeypatch):
        """Test dry-run mode logs appropriately."""
        mock_client = Mock()
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        evangelist_agent.beacon_ping_agent("agent-123", "Test message", dry_run=True)
        
        # Verify dry-run log message
        assert mock_log.called
        log_message = mock_log.call_args[0][0]
        assert "DRY RUN" in log_message
        assert "agent-123" in log_message
    
    def test_ping_failure_http_error(self, monkeypatch):
        """Test ping fails with HTTP error response."""
        mock_client = Mock()
        mock_client.post.return_value = Mock(status_code=404, json=lambda: {"error": "Not found"})
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.beacon_ping_agent("agent-123", "Test message")
        
        assert result is False
    
    def test_ping_failure_exception(self, monkeypatch):
        """Test ping fails with network exception."""
        mock_client = Mock()
        mock_client.post.side_effect = Exception("Network error")
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.beacon_ping_agent("agent-123", "Test message")
        
        assert result is False
    
    def test_success_status_codes(self, monkeypatch):
        """Test various success status codes (200, 201, 202)."""
        mock_client = Mock()
        
        for status_code in [200, 201, 202]:
            mock_client.post.return_value = Mock(
                status_code=status_code, 
                json=lambda: {"status": "success"}
            )
            # Ensure BEACON_URL is mocked to prevent real requests
            monkeypatch.setattr(evangelist_agent, "BEACON_URL", "https://test-beacon.example.com")
            monkeypatch.setattr(evangelist_agent, "client", mock_client)
            
            result = evangelist_agent.beacon_ping_agent("agent-123", "Test message")
            assert result is True
    
    @patch.object(evangelist_agent.log, 'warning')
    def test_failure_logging(self, mock_log, monkeypatch):
        """Test failure scenarios are logged."""
        mock_client = Mock()
        mock_client.post.return_value = Mock(status_code=500, json=lambda: {"error": "Server error"})
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        evangelist_agent.beacon_ping_agent("agent-123", "Test message")
        
        # Verify warning log was called
        assert mock_log.called
        log_message = mock_log.call_args[0][0]
        assert "500" in log_message


class TestPostToMoltbook:
    """Tests for post_to_moltbook() function."""
    
    def test_successful_post(self, monkeypatch):
        """Test successful post to Moltbook."""
        # Set API key directly in module variable (not just env var)
        monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "valid-key")
        monkeypatch.setattr(evangelist_agent, "MOLTBOOK_URL", "https://test-moltbook.example.com")
        
        mock_client = Mock()
        mock_client.post.return_value = Mock(
            status_code=201, 
            json=lambda: {"id": "post-123", "url": "https://moltbook.com/m/rustchain/post-123"}
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.post_to_moltbook(
            "Test Title", 
            "Test content", 
            "rustchain"
        )
        
        assert result is True
        
        # Verify correct request
        call_args = mock_client.post.call_args
        assert call_args is not None
        
        headers = call_args.kwargs["headers"]
        json_payload = call_args.kwargs["json"]
        
        assert headers["Authorization"] == "Bearer valid-key"
        assert json_payload["title"] == "Test Title"
        assert json_payload["content"] == "Test content"
        assert json_payload["submolt"] == "rustchain"
    
    def test_dry_run_mode(self, monkeypatch):
        """Test dry-run mode doesn't call API."""
        monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "valid-key")
        monkeypatch.setattr(evangelist_agent, "MOLTBOOK_URL", "https://test-moltbook.example.com")
        mock_client = Mock()
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.post_to_moltbook(
            "Test Title", 
            "Test content", 
            "rustchain",
            dry_run=True
        )
        
        assert result is True
        assert not mock_client.post.called
    
    def test_missing_api_key(self, monkeypatch):
        """Test post fails when API key is missing."""
        # Ensure no API key
        monkeypatch.delenv("MOLTBOOK_API_KEY", raising=False)
        
        mock_client = Mock()
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain")
        
        assert result is False
        assert not mock_client.post.called
    
    @patch.object(evangelist_agent.log, 'info')
    def test_missing_key_logging(self, mock_log, monkeypatch):
        """Test missing API key logs info message."""
        monkeypatch.delenv("MOLTBOOK_API_KEY", raising=False)
        mock_client = Mock()
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        evangelist_agent.post_to_moltbook("Test", "Content", "rustchain")
        
        # Verify info log about missing key
        assert mock_log.called
        log_message = mock_log.call_args[0][0]
        assert "MOLTBOOK_API_KEY" in log_message or "No MOLTBOOK_API_KEY" in log_message
    
    def test_api_failure_http_error(self, monkeypatch):
        """Test post fails with HTTP error."""
        monkeypatch.setenv("MOLTBOOK_API_KEY", "valid-key")
        
        mock_client = Mock()
        mock_client.post.return_value = Mock(
            status_code=401,
            json=lambda: {"error": "Unauthorized"},
            text="Unauthorized"
        )
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain")
        
        assert result is False
    
    def test_api_failure_exception(self, monkeypatch):
        """Test post fails with network exception."""
        monkeypatch.setenv("MOLTBOOK_API_KEY", "valid-key")
        
        mock_client = Mock()
        mock_client.post.side_effect = Exception("Network error")
        monkeypatch.setattr(evangelist_agent, "client", mock_client)
        
        result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain")
        
        assert result is False
    
    def test_success_status_codes(self, monkeypatch):
        """Test various success status codes (200, 201)."""
        monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "valid-key")
        monkeypatch.setattr(evangelist_agent, "MOLTBOOK_URL", "https://test-moltbook.example.com")
        mock_client = Mock()
        
        for status_code in [200, 201]:
            mock_client.post.return_value = Mock(
                status_code=status_code,
                json=lambda: {"id": "post-123"}
            )
            monkeypatch.setattr(evangelist_agent, "client", mock_client)
            
            result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain")
            assert result is True


class TestRunOnce:
    """Tests for run_once() function."""
    
    def test_dry_run_complete_workflow(self, monkeypatch):
        """Test complete workflow in dry-run mode."""
        # Mock all dependencies
        mock_beacon = MockBeaconService()
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        mock_bottube = MockBoTTubeService()
        setup_bottube_mocks(monkeypatch, mock_bottube)
        
        # Mock API key for Moltbook
        monkeypatch.setenv("MOLTBOOK_API_KEY", "valid-key")
        
        # Track function calls
        ping_calls = []
        post_calls = []
        
        # Mock beacon_ping_agent
        original_ping = evangelist_agent.beacon_ping_agent
        def mock_ping(agent_id, message, dry_run=False):
            ping_calls.append((agent_id, dry_run))
            return True
        monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", mock_ping)
        
        # Mock post_to_moltbook
        original_post = evangelist_agent.post_to_moltbook
        def mock_post(title, content, submolt, dry_run=False):
            post_calls.append((title, submolt, dry_run))
            return True
        monkeypatch.setattr(evangelist_agent, "post_to_moltbook", mock_post)
        
        # Run in dry-run mode
        result = evangelist_agent.run_once(dry_run=True)
        
        # Verify results
        assert result >= 0  # Should return number of pings
        
        # Should ping up to MAX_PINGS_PER_RUN agents
        assert len(ping_calls) <= evangelist_agent.MAX_PINGS_PER_RUN
        
        # Should create one post
        assert len(post_calls) == 1
        assert post_calls[0][2] == True  # dry_run=True
    
    def test_normal_run_with_agents(self, monkeypatch):
        """Test normal run with discovered agents."""
        # Setup mocks with agents
        mock_beacon = MockBeaconService()
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        mock_bottube = MockBoTTubeService()
        setup_bottube_mocks(monkeypatch, mock_bottube)
        
        # Mock API key
        monkeypatch.setenv("MOLTBOOK_API_KEY", "valid-key")
        
        # Mock ping and post functions
        ping_count = 0
        def mock_ping(agent_id, message, dry_run=False):
            nonlocal ping_count
            ping_count += 1
            return True
        
        post_called = False
        def mock_post(title, content, submolt, dry_run=False):
            nonlocal post_called
            post_called = True
            return True
        
        monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", mock_ping)
        monkeypatch.setattr(evangelist_agent, "post_to_moltbook", mock_post)
        
        # Run
        result = evangelist_agent.run_once(dry_run=False)
        
        # Verify
        assert result > 0  # Should ping some agents
        assert post_called  # Should post to Moltbook
    
    def test_run_with_no_agents(self, monkeypatch):
        """Test run when no agents are discovered."""
        # Setup empty mocks
        mock_beacon = MockBeaconService()
        mock_beacon.agents = []  # No agents
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        mock_bottube = MockBoTTubeService()
        mock_bottube.stats["top_agents"] = []  # No top agents
        setup_bottube_mocks(monkeypatch, mock_bottube)
        
        # Mock API key
        monkeypatch.setenv("MOLTBOOK_API_KEY", "valid-key")
        
        # Track calls
        ping_calls = []
        def mock_ping(agent_id, message, dry_run=False):
            ping_calls.append(agent_id)
            return True
        
        post_called = False
        def mock_post(title, content, submolt, dry_run=False):
            nonlocal post_called
            post_called = True
            return True
        
        monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", mock_ping)
        monkeypatch.setattr(evangelist_agent, "post_to_moltbook", mock_post)
        
        # Run
        result = evangelist_agent.run_once(dry_run=False)
        
        # Verify no pings but still posts
        assert result == 0  # No agents to ping
        assert len(ping_calls) == 0
        assert post_called  # Should still post to Moltbook
    
    @patch.object(evangelist_agent.log, 'info')
    def test_logging_during_run(self, mock_log, monkeypatch):
        """Test logging during run execution."""
        # Setup basic mocks
        mock_beacon = MockBeaconService()
        setup_beacon_mocks(monkeypatch, mock_beacon)
        
        mock_bottube = MockBoTTubeService()
        setup_bottube_mocks(monkeypatch, mock_bottube)
        
        # Mock other functions
        monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", lambda *args, **kwargs: True)
        monkeypatch.setattr(evangelist_agent, "post_to_moltbook", lambda *args, **kwargs: True)
        monkeypatch.setenv("MOLTBOOK_API_KEY", "valid-key")
        
        evangelist_agent.run_once(dry_run=False)
        
        # Verify logs were called
        assert mock_log.called
        # Should log start, discovered agents, and completion
        log_messages = [call[0][0] for call in mock_log.call_args_list]
        assert any("Evangelist Agent" in msg for msg in log_messages)
        assert any("Discovered" in msg for msg in log_messages)
        assert any("Run complete" in msg for msg in log_messages)


class TestMainFunction:
    """Tests for main() function."""
    
    def test_single_run(self, monkeypatch):
        """Test single run mode (no daemon)."""
        # Mock run_once and parse_args
        run_once_called = False
        def mock_run_once(dry_run=False):
            nonlocal run_once_called
            run_once_called = True
            return 3
        
        monkeypatch.setattr(evangelist_agent, "run_once", mock_run_once)
        
        # Mock argparse
        mock_args = Mock()
        mock_args.daemon = False
        mock_args.dry_run = False
        
        with patch('evangelist_agent.argparse.ArgumentParser') as mock_parser:
            mock_parser.return_value.parse_args.return_value = mock_args
            
            evangelist_agent.main()
        
        assert run_once_called
    
    def test_daemon_mode(self, monkeypatch):
        """Test daemon mode (continuous runs)."""
        # Mock run_once to run twice then raise exception to break loop
        run_count = 0
        def mock_run_once(dry_run=False):
            nonlocal run_count
            run_count += 1
            if run_count >= 2:
                raise KeyboardInterrupt  # Break loop
            return 3
        
        # Mock sleep to track calls
        sleep_calls = []
        def mock_sleep(seconds):
            sleep_calls.append(seconds)
        
        monkeypatch.setattr(evangelist_agent, "run_once", mock_run_once)
        monkeypatch.setattr(evangelist_agent.time, 'sleep', mock_sleep)
        
        # Mock argparse for daemon mode
        mock_args = Mock()
        mock_args.daemon = True
        mock_args.dry_run = False
        
        with patch('evangelist_agent.argparse.ArgumentParser') as mock_parser:
            mock_parser.return_value.parse_args.return_value = mock_args
            
            # Run with timeout to prevent infinite loop
            try:
                evangelist_agent.main()
            except KeyboardInterrupt:
                pass  # Expected
        
        # Verify daemon behavior
        assert run_count >= 2
        assert sleep_calls
        assert sleep_calls[0] == evangelist_agent.INTERVAL_SECONDS
    
    def test_dry_run_argument(self, monkeypatch):
        """Test dry-run argument is passed correctly."""
        # Track dry_run parameter
        captured_dry_run = None
        def mock_run_once(dry_run=False):
            nonlocal captured_dry_run
            captured_dry_run = dry_run
            return 3
        
        monkeypatch.setattr(evangelist_agent, "run_once", mock_run_once)
        
        # Mock argparse with dry-run
        mock_args = Mock()
        mock_args.daemon = False
        mock_args.dry_run = True
        
        with patch('evangelist_agent.argparse.ArgumentParser') as mock_parser:
            mock_parser.return_value.parse_args.return_value = mock_args
            
            evangelist_agent.main()
        
        assert captured_dry_run is True