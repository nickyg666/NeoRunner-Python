"""Tests for network channel analyzer."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.network_channel_analyzer import NetworkChannelAnalyzer, ChannelMismatch


class TestNetworkChannelAnalyzer:
    """Test NetworkChannelAnalyzer."""
    
    def test_analyze_unknown_packet_identifier(self):
        """Detects unknown custom packet identifier."""
        log = "Unknown custom packet identifier: emi"
        
        analyzer = NetworkChannelAnalyzer()
        results = analyzer.analyze_log(log)
        
        assert len(results) == 1
        assert results[0].channel == "emi"
        assert results[0].severity == "critical"
    
    def test_analyze_channel_not_registered(self):
        """Detects channel not registered."""
        log = "Channel not registered: voicechat"
        
        analyzer = NetworkChannelAnalyzer()
        results = analyzer.analyze_log(log)
        
        assert len(results) == 1
        assert results[0].channel == "voicechat"
    
    def test_channel_to_mod_mapping(self):
        """Maps channel names to mod names."""
        analyzer = NetworkChannelAnalyzer()
        
        assert analyzer._channel_to_mod("emi") == "emi"
        assert analyzer._channel_to_mod("voicechat") == "voicechat"
        assert analyzer._channel_to_mod("ae2") == "appliedenergistics2"
    
    def test_is_vanilla_channel(self):
        """Identifies vanilla channels."""
        analyzer = NetworkChannelAnalyzer()
        
        assert analyzer._is_vanilla_channel("minecraft:register") is True
        assert analyzer._is_vanilla_channel("fml:play") is True
        assert analyzer._is_vanilla_channel("emi") is False
    
    def test_determine_direction(self):
        """Determines mismatch direction."""
        analyzer = NetworkChannelAnalyzer()
        
        result = analyzer._determine_direction("client missing channel")
        assert result == "server_has_client_missing"
        
        result = analyzer._determine_direction("server missing channel")
        assert result == "client_has_server_missing"
    
    def test_generate_events_no_duplicates(self):
        """Doesn't duplicate events for same channel."""
        mismatches = [
            ChannelMismatch(None, "emi", "client_has_server_missing", "emi", "critical"),
            ChannelMismatch(None, "emi", "client_has_server_missing", "emi", "critical"),
        ]
        
        analyzer = NetworkChannelAnalyzer()
        analyzer.generate_events(mismatches)
