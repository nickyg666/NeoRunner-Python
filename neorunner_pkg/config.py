"""Configuration management for NeoRunner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .constants import CWD, PARALLEL_PORTS, MOD_LOADERS


def _get_default_version() -> str:
    """Get default Minecraft version dynamically."""
    try:
        from .version import get_latest_minecraft_version
        return get_latest_minecraft_version()
    except Exception:
        return "1.21.11"


@dataclass
class ServerConfig:
    """Main server configuration."""
    rcon_pass: str = "1"
    rcon_port: str = "25575"
    rcon_host: str = "localhost"
    http_port: int = 8000
    mc_port: int = 1234
    mods_dir: str = "mods"
    clientonly_dir: str = "clientonly"
    quarantine_dir: str = "quarantine"
    mc_version: str = field(default_factory=_get_default_version)
    loader: str = "neoforge"
    max_download_mb: int = 600
    rate_limit_seconds: int = 2
    run_curator_on_startup: bool = True
    curator_limit: int = 100
    curator_show_optional_audit: bool = True
    curator_max_depth: int = 3
    server_jar: str | None = None
    hostname: str = ""
    broadcast_enabled: bool = True
    broadcast_auto_on_install: bool = True
    nag_show_mod_list_on_join: bool = False
    nag_first_visit_modal: bool = False
    motd_show_download_url: bool = False
    install_script_types: str = "all"
    curator_sort: str = "downloads"
    ferium_update_interval_hours: int = 4
    ferium_weekly_update_day: str = "mon"
    ferium_weekly_update_hour: int = 2
    forced_server_mods: list[str] = field(default_factory=list)
    forced_client_mods: list[str] = field(default_factory=list)
    mod_blacklist: list[str] = field(default_factory=list)
    use_parallel_ports: bool = False
    xmx: str = "6G"
    xms: str = "4G"
    view_distance: str = "10"
    simulation_distance: str = "8"
    max_tick_time: str = "120000"
    log_retention_days: int = 30
    crash_report_retention_days: int = 30
    live_log_max_size_mb: int = 10
    live_log_backup_count: int = 5
    version_check_interval_hours: int = 24  # How often to check for version updates

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerConfig:
        """Create config from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)

    def with_parallel_ports(self) -> ServerConfig:
        """Return a new config with parallel ports."""
        return ServerConfig(
            rcon_pass=self.rcon_pass,
            rcon_port=str(PARALLEL_PORTS["rcon"]),
            rcon_host=self.rcon_host,
            http_port=PARALLEL_PORTS["http"],
            mc_port=PARALLEL_PORTS["minecraft"],
            mods_dir=self.mods_dir,
            clientonly_dir=self.clientonly_dir,
            quarantine_dir=self.quarantine_dir,
            mc_version=self.mc_version,
            loader=self.loader,
            max_download_mb=self.max_download_mb,
            rate_limit_seconds=self.rate_limit_seconds,
            run_curator_on_startup=self.run_curator_on_startup,
            curator_limit=self.curator_limit,
            curator_show_optional_audit=self.curator_show_optional_audit,
            curator_max_depth=self.curator_max_depth,
            server_jar=self.server_jar,
            hostname=self.hostname,
            broadcast_enabled=self.broadcast_enabled,
            broadcast_auto_on_install=self.broadcast_auto_on_install,
            nag_show_mod_list_on_join=self.nag_show_mod_list_on_join,
            nag_first_visit_modal=self.nag_first_visit_modal,
            motd_show_download_url=self.motd_show_download_url,
            install_script_types=self.install_script_types,
            curator_sort=self.curator_sort,
            ferium_update_interval_hours=self.ferium_update_interval_hours,
            ferium_weekly_update_day=self.ferium_weekly_update_day,
            ferium_weekly_update_hour=self.ferium_weekly_update_hour,
            forced_server_mods=self.forced_server_mods,
            forced_client_mods=self.forced_client_mods,
            mod_blacklist=self.mod_blacklist,
            use_parallel_ports=True,
        )


def load_cfg() -> ServerConfig:
    """Load configuration from config.json."""
    config_path = CWD / "config.json"
    
    if not config_path.exists():
        return ServerConfig()
    
    try:
        with open(config_path) as f:
            data = json.load(f)
        return ServerConfig.from_dict(data)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error loading config: {e}")
        return ServerConfig()


def save_cfg(cfg: ServerConfig) -> None:
    """Save configuration to config.json and regenerate install scripts."""
    config_path = CWD / "config.json"
    
    with open(config_path, "w") as f:
        json.dump(cfg.to_dict(), f, indent=2)
    
    # Regenerate install scripts with new IP/port
    try:
        from .mod_hosting import generate_bat_script
        bat_script = generate_bat_script(cfg)
        
        mods_dir = Path(cfg.mods_dir)
        if not mods_dir.is_absolute():
            mods_dir = CWD / mods_dir
        
        bat_path = mods_dir.parent / "mods" / "install-mods.bat"
        bat_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bat_path, "w") as f:
            f.write(bat_script)
    except Exception:
        pass  # Non-critical


REQUIRED_CONFIG_FIELDS = [
    "mc_version",
    "loader",
    "mods_dir",
    "clientonly_dir",
    "quarantine_dir",
    "xmx",
    "xms",
]


def validate_config(cfg: ServerConfig, fail_on_error: bool = True) -> tuple[bool, list[str]]:
    """
    Validate that required config fields are present and valid.
    Returns (is_valid, list_of_errors).
    """
    errors = []
    
    if not cfg.mc_version:
        errors.append("mc_version is required")
    
    if not cfg.loader:
        errors.append("loader is required")
    elif cfg.loader not in MOD_LOADERS:
        errors.append(f"loader must be one of: {', '.join(MOD_LOADERS)}")
    
    if not cfg.mods_dir:
        errors.append("mods_dir is required")
    
    if not cfg.clientonly_dir:
        errors.append("clientonly_dir is required")
    
    if not cfg.quarantine_dir:
        errors.append("quarantine_dir is required")
    
    if not cfg.xmx:
        errors.append("xmx is required (e.g., '4G')")
    
    if not cfg.xms:
        errors.append("xms is required (e.g., '2G')")
    
    is_valid = len(errors) == 0
    
    if not is_valid and fail_on_error:
        raise ValueError(f"Config validation failed: {'; '.join(errors)}")
    
    return is_valid, errors


def ensure_config(cfg: ServerConfig) -> ServerConfig:
    """Ensure config has required fields, using defaults for missing values."""
    validated, errors = validate_config(cfg, fail_on_error=False)
    
    if not validated:
        import warnings
        warnings.warn(f"Config has missing/invalid fields: {'; '.join(errors)} - using defaults")
    
    result = ServerConfig(
        mc_version=cfg.mc_version or "1.21.11",
        loader=cfg.loader or "neoforge",
        mods_dir=cfg.mods_dir or "mods",
        clientonly_dir=cfg.clientonly_dir or "clientonly",
        quarantine_dir=cfg.quarantine_dir or "quarantine",
        xmx=cfg.xmx or "4G",
        xms=cfg.xms or "2G",
        rcon_pass=cfg.rcon_pass or "1",
        rcon_port=cfg.rcon_port or "25575",
        rcon_host=cfg.rcon_host or "localhost",
        http_port=cfg.http_port or 8000,
        mc_port=cfg.mc_port or 1234,
        max_download_mb=cfg.max_download_mb or 600,
        rate_limit_seconds=cfg.rate_limit_seconds or 2,
        run_curator_on_startup=cfg.run_curator_on_startup,
        curator_limit=cfg.curator_limit or 100,
        curator_show_optional_audit=cfg.curator_show_optional_audit,
        curator_max_depth=cfg.curator_max_depth or 3,
        server_jar=cfg.server_jar,
        hostname=cfg.hostname or "",
        broadcast_enabled=cfg.broadcast_enabled,
        broadcast_auto_on_install=cfg.broadcast_auto_on_install,
        nag_show_mod_list_on_join=cfg.nag_show_mod_list_on_join,
        nag_first_visit_modal=cfg.nag_first_visit_modal,
        motd_show_download_url=cfg.motd_show_download_url,
        install_script_types=cfg.install_script_types or "all",
        curator_sort=cfg.curator_sort or "downloads",
        ferium_update_interval_hours=cfg.ferium_update_interval_hours or 4,
        ferium_weekly_update_day=cfg.ferium_weekly_update_day or "mon",
        ferium_weekly_update_hour=cfg.ferium_weekly_update_hour or 2,
        forced_server_mods=cfg.forced_server_mods or [],
        forced_client_mods=cfg.forced_client_mods or [],
        mod_blacklist=cfg.mod_blacklist or [],
        use_parallel_ports=cfg.use_parallel_ports,
        view_distance=cfg.view_distance or "10",
        simulation_distance=cfg.simulation_distance or "8",
        max_tick_time=cfg.max_tick_time or "120000",
        log_retention_days=cfg.log_retention_days or 30,
        crash_report_retention_days=cfg.crash_report_retention_days or 30,
        live_log_max_size_mb=cfg.live_log_max_size_mb or 10,
        live_log_backup_count=cfg.live_log_backup_count or 5,
    )
    
    return result
