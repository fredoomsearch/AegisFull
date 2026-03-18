from __future__ import annotations

"""
Aggregate API router composition.

Why this module exists:
- Build the canonical HTTP surface from feature routers.
- Keep env-driven enable/disable logic centralized.
- Always mount legacy `/tools/*` as deterministic 410 shim.
"""

import importlib
import logging
import os

from fastapi import APIRouter
from app.api.router_status import record_router_status

logger = logging.getLogger(__name__)

router = APIRouter()

def _env_flag(name: str, default: str = "1") -> bool:
    """Parse feature flags from env using AEGIS boolean conventions."""
    return (os.getenv(name, default) or default).strip().lower() in {"1", "true", "yes", "on"}


def _include_router(module_path: str, label: str) -> None:
    """Best-effort include for optional routers; logs and skips on import failures."""
    try:
        mod = importlib.import_module(module_path)
        sub_router = getattr(mod, "router", None)
        if sub_router is None:
            logger.warning("Skipping router '%s': %s has no attribute 'router'.", label, module_path)
            record_router_status(label, enabled=True, mounted=False, detail="missing-router-attribute")
            return
        router.include_router(sub_router)
        record_router_status(label, enabled=True, mounted=True, detail="ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Skipping router '%s' due to import error (%s): %s",
            label,
            module_path,
            str(exc)[:200],
        )
        record_router_status(label, enabled=True, mounted=False, detail=f"import-error:{str(exc)[:200]}")


_ROUTER_SPECS = [
    ("AEGIS_ENABLE_CHAT_API", "1", "app.api.chat", "chat"),
    ("AEGIS_ENABLE_CRYPTO_API", "1", "app.api.crypto", "crypto"),
    ("AEGIS_ENABLE_DATA_API", "1", "app.api.data", "data"),
    ("AEGIS_ENABLE_NOTIFICATIONS_API", "1", "app.api.notifications", "notifications"),
    ("AEGIS_ENABLE_SYSTEM_API", "1", "app.api.system", "system"),
    ("AEGIS_ENABLE_ADMIN_API", "1", "app.core.admin", "admin"),
    ("AEGIS_ENABLE_AUTH_API", "1", "app.api.auth", "auth"),
    ("AEGIS_ENABLE_IMAGE_API", "1", "app.api.image", "image"),
]

for flag, default, module_path, label in _ROUTER_SPECS:
    if _env_flag(flag, default=default):
        _include_router(module_path, label)
    else:
        logger.info("Router '%s' disabled via %s=0", label, flag)
        record_router_status(label, enabled=False, mounted=False, detail=f"{flag}=0")

# Legacy tools router stays mounted so `/tools/*` returns a deterministic 410 Gone.
_include_router("app.api.toolssupport", "toolssupport")

ENABLE_META_API = _env_flag("AEGIS_ENABLE_META_API", default="0")

if ENABLE_META_API:
    _include_router("app.core.meta", "meta")
else:
    record_router_status("meta", enabled=False, mounted=False, detail="AEGIS_ENABLE_META_API=0")


@router.get("/health")
async def health() -> dict:
    """Tiny aggregate health endpoint for router composition sanity."""
    return {"status": "ok"}
