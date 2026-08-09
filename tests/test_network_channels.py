"""Tests for network channel analyzer."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.network_channel_analyzer import NetworkChannelAnalyzer, ChannelMismatch


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

    def test_ip_extraction(self):
        """Extracts client IP from log line."""
        analyzer = NetworkChannelAnalyzer()
        assert analyzer._extract_client_ip("Connecting from 192.168.1.100:52345") == "192.168.1.100"
        assert analyzer._extract_client_ip("/10.0.0.5:9999 connected") == "10.0.0.5"
        assert analyzer._extract_client_ip("no ip here") is None

    def test_full_analysis_with_ip(self):
        """Full analysis extracts IP, direction, severity and mod suggestion."""
        log = (
            "12:00:01 [Netty] Unknown custom packet identifier: reeses_sodium_options "
            "from /192.168.1.55:54321 - client missing channel from server"
        )
        results = NetworkChannelAnalyzer().analyze_log(log)
        assert len(results) == 1
        r = results[0]
        assert r.channel == "reeses_sodium_options"
        assert r.client_ip == "192.168.1.55"
        assert r.mod_suggestion == "reeses-sodium-options"
        assert r.severity == "high"  # server_has_client_missing is not critical

    def test_partial_channel_match(self):
        """Partial channel match maps engineernst-style channels to mods."""
        analyzer = NetworkChannelAnalyzer()
        assert analyzer._channel_to_mod("ae2:network") == "appliedenergistics2"
        assert analyzer._channel_to_mod("custommod:channel1") == "custommod"
        assert analyzer._channel_to_mod("unknown_no_colon") is None

    def test_generate_events_with_ip(self, caplog):
        """Events include client IP and channel for both directions."""
        import logging
        with caplog.at_level(logging.INFO):
            analyzer = NetworkChannelAnalyzer()
            analyzer.generate_events([
                ChannelMismatch("192.168.1.10", "voicechat", "client_has_server_missing", "voicechat", "critical"),
                ChannelMismatch("192.168.1.11", "emi", "server_has_client_missing", "emi", "high"),
            ])
        msgs = [r.message for r in caplog.records if r.message]
        assert any("Connection rejected: client 192.168.1.10" in m for m in msgs)
        assert any("192.168.1.11 missing channel 'emi'" in m for m in msgs)

    def test_vanilla_channels_skipped(self):
        """Vanilla/FML channels produce no mismatches."""
        log = (
            "Unknown custom packet identifier: minecraft:brand\n"
            "Unknown custom packet identifier: fml:play\n"
            "Unknown custom packet identifier: emi\n"
        )
        results = NetworkChannelAnalyzer().analyze_log(log)
        assert len(results) == 1
        assert results[0].channel == "emi"

    def test_analyze_network_channels_helper(self):
        """Convenience function wraps the analyzer."""
        from neorunner_pkg.network_channel_analyzer import analyze_network_channels
        results = analyze_network_channels("Channel not registered: trinkets")
        assert len(results) == 1
        assert results[0].channel == "trinkets"
