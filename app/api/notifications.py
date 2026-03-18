from __future__ import annotations

"""
Notification/email API surface.

Why this module exists:
- Keep notification integrations isolated from core chat/project flows.
- Provide a health-ready router that can be extended safely.
"""

from typing import Dict, Any

from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.services.email_service import get_email_service

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/health")
async def notifications_health() -> dict:
    """
    Endpoint simple de salud para el módulo de notificaciones.
    """
    return {"status": "ok"}


def send_crypto_signal_email(to: str, signal: Dict[str, Any]) -> bool:
    """Send templated crypto signal email through configured email provider."""
    email_service = get_email_service()
    html = email_service.render_template("prediction_email.html", context={"signal": signal})
    if not html:
        return False
    return email_service.send_email(
        to=to,
        subject=f"Señal AEGIS para {signal.get('symbol', '').upper()}",
        html_body=html,
    )
