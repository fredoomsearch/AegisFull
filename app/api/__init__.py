from __future__ import annotations

import importlib
import logging
import os

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()

def _env_flag(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or default).strip().lower() in {"1", "true", "yes", "on"}


def _include_router(module_path: str, label: str) -> None:
    try:
        mod = importlib.import_module(module_path)
        sub_router = getattr(mod, "router", None)
        if sub_router is None:
            logger.warning("Skipping router '%s': %s has no attribute 'router'.", label, module_path)
            return
        router.include_router(sub_router)
    except Exception:  # noqa: BLE001
        logger.exception("Skipping router '%s' due to import error (%s).", label, module_path)


_ROUTER_SPECS = [
    ("AEGIS_ENABLE_CHAT_API", "1", "app.api.chat", "chat"),
    ("AEGIS_ENABLE_CRYPTO_API", "1", "app.api.crypto", "crypto"),
    ("AEGIS_ENABLE_DATA_API", "1", "app.api.data", "data"),
    ("AEGIS_ENABLE_NOTIFICATIONS_API", "1", "app.api.notifications", "notifications"),
    ("AEGIS_ENABLE_TOOLS_API", "1", "app.api.toolssupport", "toolssupport"),
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

ENABLE_META_API = _env_flag("AEGIS_ENABLE_META_API", default="0")

if ENABLE_META_API:
    _include_router("app.core.meta", "meta")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
