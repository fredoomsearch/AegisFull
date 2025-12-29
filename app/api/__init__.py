from __future__ import annotations

from fastapi import APIRouter

from app.api import chat, crypto, data, notifications, toolssupport
from app.core import admin, meta

router = APIRouter()

router.include_router(chat.router)           # /chat, /websearch, etc.
router.include_router(crypto.router)         # /crypto/...
router.include_router(data.router)           # /data/...
router.include_router(meta.router)           # /meta/...
router.include_router(notifications.router)  # /notifications/...
router.include_router(toolssupport.router)   # /tools/...
router.include_router(admin.router)          # /admin/...


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
