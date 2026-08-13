"""Network channel analyzer for detecting client/server mod mismatches."""


import re
from dataclasses import dataclass
from typing import ClassVar

from .log import log_event


def _installer_link(cfg=None) -> str:
    """Public installer download URL (via the shared mod_hosting helper)."""
    from .mod_hosting import public_download_link
    if cfg is None:
        from .config import load_cfg
        cfg = load_cfg()
    return public_download_link(cfg)


@dataclass
class ChannelMismatch:
    """Represents a network channel mismatch between client and server."""
    client_ip: str | None
    channel: str
    direction: str  # "client_has_server_missing", "server_has_client_missing", "connection_rejected"
    mod_suggestion: str | None
    severity: str  # critical, high, medium
    player: str | None = None
    reason: str | None = None


class NetworkChannelAnalyzer:
    """Analyze server logs for network channel mismatches."""
    
    # Patterns for detecting channel issues
    CHANNEL_MISMATCH_PATTERNS: ClassVar[list[str]] = [
        # Unknown custom packet identifier
        r"Unknown custom packet identifier: ([a-zA-Z0-9_.:]+)",
        r"Unknown custom packet identifier \(channel: ([a-zA-Z0-9_.]+)\)",
        
        # Channel not registered
        r"Channel not registered: ([a-zA-Z0-9_.]+)",
        r"Channel .* not found: ([a-zA-Z0-9_.]+)",
        
        # Missing channel
        r"Missing channel: ([a-zA-Z0-9_.]+)",
        r"Client missing required channel: ([a-zA-Z0-9_.]+)",
        
        # Custom payload issues
        r"CustomPayload.*channel=([a-zA-Z0-9_.]+)",
        r"Failed to handle custom payload.*channel ([a-zA-Z0-9_.]+)",
    ]

    # Config-phase connection rejections. NeoForge/Forge reject the handshake
    # before the player joins; the player name + reason identify who to kick
    # with a download link.
    CONFIG_REJECTION_PATTERNS: ClassVar[list[str]] = [
        # dadoflorenzog (21dc29b4-...) lost connection: Incompatible client! Please use NeoForge 26.1.2.87
        r"([A-Za-z0-9_]{1,16}) \([0-9a-fA-F-]{36}\) lost connection: (.+)",
        # Modern NeoForge: "lost connection: Incompatible client!" style
        r"([A-Za-z0-9_]{1,16}) \([0-9a-fA-F-]{36}\) lost connection: (Incompatible client.*)",
    ]

    REJECTION_REASONS = (
        "incompatible client",
        "missing mod",
        "mod mismatch",
        "channel",
        "please use neoforge",
        "please use forge",
        "please use fabric",
        "version mismatch",
        "mod version",
        "required mod",
    )
    
    # IP extraction patterns. Require an IP-ish prefix ("from ", "/", ":") so we
    # don't mistake NeoForge version strings like "26.1.2.87" for an address.
    IP_PATTERNS: ClassVar[list[str]] = [
        r"(?:from |/)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
        r"/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):",
    ]
    
    # Common mod channels - map to mod names
    CHANNEL_TO_MOD: ClassVar[dict[str, str | None]] = {
        "minecraft:register": None,  # Vanilla, ignore
        "minecraft:brand": None,  # Vanilla, ignore
        "fml:play": None,  # Forge/NeoForge protocol
        "fml:login": None,
        "modernfix": "modernfix",
        "reeses_sodium_options": "reeses-sodium-options",
        "dab": "dab",
        "emi": "emi",
        "emi_jei": "emi",
        "emi_rei": "emi",
        "engineerust": "engineersdecor",
        "playerrevive": "playerrevive",
        "suppseries": "supplementaries",
        "curios": "curios",
        "ae2": "appliedenergistics2",
        "ftbchunks": "ftb-chunks",
        "ftbteams": "ftb-teams",
        "ftbessentials": "ftb-essentials",
        "xat": "xaeroworldmap",
        "xaero": "xaerominimap",
        "voicechat": "voicechat",
        "trinkets": "trinkets",
        "blueprint": "blueprint",
        "citadel": "citadel",
        "pehkui": "pehkui",
        "kyrptonaught": "kyrptonaught",
    }
    
    def __init__(self, cfg=None):
        self.cfg = cfg
        self._link = _installer_link(cfg)
    
    def analyze_log(self, log_text: str) -> list[ChannelMismatch]:
        """Analyze log text for channel mismatches."""
        results = []
        log_lines = log_text.split('\n')
        
        for line in log_lines:
            # Try each pattern
            for pattern in self.CHANNEL_MISMATCH_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    channel = match.group(1)
                    
                    # Skip vanilla channels
                    if self._is_vanilla_channel(channel):
                        continue
                    
                    # Extract client IP if present
                    client_ip = self._extract_client_ip(line)
                    
                    # Determine direction and severity
                    direction = self._determine_direction(line)
                    
                    # Get suggested mod
                    mod_suggestion = self._channel_to_mod(channel)
                    
                    severity = "critical" if direction == "client_has_server_missing" else "high"
                    
                    results.append(ChannelMismatch(
                        client_ip=client_ip,
                        channel=channel,
                        direction=direction,
                        mod_suggestion=mod_suggestion,
                        severity=severity
                    ))

            # Config-phase rejection: player kicked during handshake with a mod/loader mismatch
            for pattern in self.CONFIG_REJECTION_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    player, reason = match.group(1), match.group(2)
                    if not any(term in reason.lower() for term in self.REJECTION_REASONS):
                        continue
                    # Server-side logs never include the client IP here; the
                    # generic IP matcher can also grab loader version strings
                    # like "26.1.2.87", so don't attempt IP extraction.
                    results.append(ChannelMismatch(
                        client_ip=None,
                        channel="connection",
                        direction="connection_rejected",
                        mod_suggestion=None,
                        severity="critical",
                        player=player,
                        reason=reason.strip()
                    ))
                    break
        
        return results
    
    def _is_vanilla_channel(self, channel: str) -> bool:
        """Check if channel is vanilla Minecraft."""
        vanilla_prefixes = [
            "minecraft:",
            "fml:",  # FML/NeoForge protocol
            "brand",
            "register",
        ]
        return any(channel.startswith(p) for p in vanilla_prefixes)
    
    def _extract_client_ip(self, line: str) -> str | None:
        """Extract client IP from log line."""
        for pattern in self.IP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
    
    def _determine_direction(self, line: str) -> str:
        """Determine which side is missing the channel."""
        line_lower = line.lower()
        
        if "client" in line_lower and ("missing" in line_lower or "not" in line_lower):
            return "server_has_client_missing"
        elif "server" in line_lower and ("missing" in line_lower or "not" in line_lower):
            return "client_has_server_missing"
        
        # Default to client has more mods than server
        return "client_has_server_missing"
    
    def _channel_to_mod(self, channel: str) -> str | None:
        """Map channel name to likely mod."""
        channel_lower = channel.lower()
        
        # Direct lookup
        if channel_lower in self.CHANNEL_TO_MOD:
            return self.CHANNEL_TO_MOD[channel_lower]
        
        # Try partial match
        for chan_pattern, mod in self.CHANNEL_TO_MOD.items():
            if mod and chan_pattern in channel_lower:
                return mod
        
        # Extract likely mod name from channel (often format: modid:channelname)
        if ":" in channel:
            parts = channel.split(":")
            if len(parts) >= 2:
                potential_mod = parts[0]
                # Clean up
                potential_mod = potential_mod.replace("mod_", "").replace("-", "_")
                return potential_mod
        
        return None
    
    def generate_events(self, mismatches: list[ChannelMismatch]) -> None:
        """Generate log events for channel mismatches."""
        seen = set()
        
        for mismatch in mismatches:
            # Deduplicate
            key = (mismatch.channel, mismatch.direction)
            if key in seen:
                continue
            seen.add(key)
            
            if mismatch.direction == "connection_rejected":
                msg = (f"Connection rejected: player '{mismatch.player}' during handshake "
                       f"({mismatch.reason or 'mod/version mismatch'}). "
                       f"Client should download: {self._link}")
                if mismatch.client_ip:
                    msg = f"Connection rejected: {mismatch.client_ip} ('{mismatch.player}') during handshake ({mismatch.reason or 'mod/version mismatch'}). Client should download: {self._link}"
                log_event("PLAYER_REJECTED", msg)
            elif mismatch.direction == "client_has_server_missing":
                msg = f"Channel mismatch: client has mod '{mismatch.mod_suggestion or mismatch.channel}' that server doesn't"
                if mismatch.client_ip:
                    msg = f"Connection rejected: client {mismatch.client_ip} has mod '{mismatch.mod_suggestion or mismatch.channel}' that server doesn't"
            else:
                msg = f"Channel mismatch: server has mod '{mismatch.mod_suggestion or mismatch.channel}' that client doesn't"
                if mismatch.client_ip:
                    msg = f"Client {mismatch.client_ip} missing channel '{mismatch.channel}' from server"
            
            log_event("CHANNEL_MISMATCH", msg)

    def kick_reason(self, mismatch: ChannelMismatch) -> str | None:
        """Build the kick message to send a mismatched player.

        Returns a message for every mismatch direction so the server can kick
        clients whose mod set diverges from the server's, pointing them at the
        modpack download link. Returns None only when there is no player to kick.
        """
        if not mismatch.player:
            return None
        return ("Your client mods do not match the server. "
                f"Download the modpack: {self._link}")


def analyze_network_channels(log_text: str) -> list[ChannelMismatch]:
    """Convenience function to analyze network channels."""
    analyzer = NetworkChannelAnalyzer()
    return analyzer.analyze_log(log_text)


__all__ = ["ChannelMismatch", "NetworkChannelAnalyzer", "analyze_network_channels"]
