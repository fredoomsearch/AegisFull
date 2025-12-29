from __future__ import annotations

"""
Endpoints relacionados con notificaciones (emails, alerts, etc).

Por ahora:
- Define un APIRouter con prefix `/notifications`
- Expone un endpoint GET `/notifications/health` para que
  `app.api.__init__` pueda incluir este router sin romper nada.

Más adelante aquí podemos:
- Conectar con app.services.email_service.EmailService
- Exponer endpoints para enviar correos de prueba, alertas de trading, etc.
"""

from typing import Dict, Any

from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.services.email_service import email_service

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
    html = email_service.render_template("prediction_email.html", context={"signal": signal})
    if not html:
        return False
    return email_service.send_email(
        to=to,
        subject=f"Señal AEGIS para {signal.get('symbol', '').upper()}",
        html_body=html,
    )

