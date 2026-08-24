"""Entrance dispatcher: picks which backend owns the public MC port.

``cfg.entrance_backend`` selects between:
  - "python"   -> ConnectionProxy (neorunner_pkg.connection_proxy)
  - "velocity" -> VelocityManager  (neorunner_pkg.velocity_proxy)

Both expose the same lifecycle surface: start()/stop()/status()/is_running().
"""

from __future__ import annotations

import threading
from typing import Protocol

from .config import ServerConfig


class Entrance(Protocol):
    """Common lifecycle surface shared by both entrance implementations."""

    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def status(self) -> dict: ...


_lock = threading.Lock()
_instances: dict[str, object] = {}


class _VelocityFacade:
    """Adapts VelocityManager.start() signature to the common surface."""

    def __init__(self, manager):
        self._m = manager

    def start(self) -> bool:
        return self._m.start()

    def stop(self) -> None:
        self._m.stop()

    def is_running(self) -> bool:
        return self._m.is_running()

    def status(self) -> dict:
        return self._m.status()


def get_entrance(cfg: ServerConfig | None = None) -> Entrance:
    """Return the configured entrance implementation (cached per backend)."""
    from .config import ensure_config, load_cfg

    if cfg is None:
        cfg = ensure_config(load_cfg())
    backend = str(getattr(cfg, "entrance_backend", "python") or "python").lower()

    with _lock:
        inst: Entrance | None = _instances.get(backend)  # type: ignore[assignment]
        if inst is None:
            if backend == "velocity":
                from .velocity_proxy import get_velocity_manager
                inst = _VelocityFacade(get_velocity_manager(cfg))
            else:
                from .connection_proxy import get_connection_proxy
                inst = get_connection_proxy(cfg)
            _instances[backend] = inst
        else:
            # keep the live instance pointed at fresh config
            try:
                inst.cfg = cfg  # type: ignore[attr-defined]
            except AttributeError:
                pass
    return inst


def reset_entrances() -> None:
    """Forget cached instances (tests only)."""
    with _lock:
        _instances.clear()


__all__ = ["get_entrance", "reset_entrances"]
