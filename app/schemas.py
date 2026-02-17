from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class Language(str, Enum):
    es = "es"
    en = "en"


# ---------------------------------------------------------------------------
# Chat schemas (current API)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message")
    use_existing: Optional[bool] = Field(
        False, description="Use conversation_id only when explicitly selected"
    )
    conversation_id: Optional[str] = Field(
        None, description="Existing conversation id (UUID string) or None"
    )
    lang: Optional[Language] = Field(None, description="'es' or 'en' (optional)")

    @field_validator("conversation_id")
    @classmethod
    def validate_conv_id(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        if not v:
            return None
        if not (info.data or {}).get("use_existing"):
            return None
        try:
            uuid.UUID(str(v))
            return str(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("conversation_id must be a valid UUID string") from exc

    model_config = ConfigDict(
        use_enum_values=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "message": "¿Cuánto vale un dólar hoy?",
                "conversation_id": None,
                "lang": "es",
            }
        },
    )


class ChatResponse(BaseModel):
    response: str = Field(..., description="Assistant response text")
    conversation_id: Optional[str] = Field(
        None, description="Conversation id returned by server (UUID string)"
    )
    timestamp: Optional[datetime] = Field(
        None, description="When the response was created (server side timestamp)"
    )
    sources: Optional[List[Dict[str, str]]] = Field(
        None, description="Optional list of search sources [{'title','snippet','link'}]"
    )

    @field_validator("conversation_id")
    @classmethod
    def validate_conv_id_resp(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        try:
            uuid.UUID(str(v))
            return str(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("conversation_id must be a valid UUID string") from exc

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "response": "Hoy el dólar está en X COP. (Fuente: ejemplo.com)",
                "conversation_id": "23b7afdb-1acc-4c9b-befc-add6df189070",
                "timestamp": "2025-11-19T00:00:00Z",
                "sources": [
                    {
                        "title": "Banco X: cotización",
                        "snippet": "Resumen...",
                        "link": "https://ejemplo.com",
                    }
                ],
            }
        },
    )


# ---------------------------------------------------------------------------
# Legacy/bulk chat schemas (kept for compatibility; rename to avoid clashes)
# ---------------------------------------------------------------------------

class MessageIn(BaseModel):
    role: str = Field(default="user", description="system|user|assistant")
    content: str = Field(default="")


class ChatRequestBulk(BaseModel):
    conversation_id: Optional[str] = Field(default=None)
    messages: List[MessageIn] = Field(default_factory=list)
    max_new_tokens: int = Field(default=256, ge=1, le=2048)


class ChatResponseBulk(BaseModel):
    conversation_id: str
    assistant: str
    used_backend: str
    meta: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Conversation schemas
# ---------------------------------------------------------------------------

class ConversationCreateResponse(BaseModel):
    conversation_id: str


class ConversationItem(BaseModel):
    id: str
    created_at: int
    updated_at: int
    title: Optional[str] = None
    summary: Optional[str] = None
    archived: bool = False


class ConversationListResponse(BaseModel):
    items: List[ConversationItem]


class ConversationArchiveResponse(BaseModel):
    conversation_id: str
    archived: bool


class ConversationDeleteResponse(BaseModel):
    conversation_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Crypto schemas
# ---------------------------------------------------------------------------

class CryptoNewsResponse(BaseModel):
    symbol: str
    provider: str
    fetched_at: int
    momentum: float
    trust_avg: float
    items: List[Dict[str, Any]]


class CryptoPredictRequest(BaseModel):
    symbol: str = Field(default="BTC")
    horizon_minutes: int = Field(default=30, ge=1, le=1440)
    price: Optional[float] = Field(default=None)
    features: Dict[str, Any] = Field(default_factory=dict)


class CryptoPredictResponse(BaseModel):
    symbol: str
    decision: str
    prob_up: float
    prob_down: float
    confidence: float
    expected_delta_pct: float
    horizon_minutes: int
    used_signals: Dict[str, Any] = Field(default_factory=dict)
    log_id: Optional[str] = None


class CryptoModelType(str, Enum):
    rf = "rf"
    deep = "deep"
    ensemble = "ensemble"
    model_4 = "model_4"
    model_5 = "model_5"


class CryptoPredictionRequest(BaseModel):
    symbol: str = Field(
        ...,
        description=(
            "Ticker de la criptomoneda. Puede ser 'BTC', 'BTCUSDT', "
            "'precio de btc', etc. El servicio normaliza internamente."
        ),
    )
    horizon_minutes: int = Field(
        15,
        description="Horizonte temporal en minutos para la predicción.",
        ge=1,
        le=1440,
    )
    model: Optional[CryptoModelType] = Field(
        None,
        description=(
            "Modelo a usar: 'rf', 'deep', 'ensemble', 'model_4', 'model_5'. "
            "Si no se envía, se usa 'ensemble'."
        ),
    )


class CryptoPrediction(BaseModel):
    symbol: str
    horizon_minutes: int
    model: CryptoModelType
    predicted_price: float = Field(
        ..., description="Precio predicho (normalmente el spot actual en USD si es live)."
    )
    probability_up: Optional[float] = Field(
        None, description="Probabilidad estimada de que el precio suba (0-1).", ge=0.0, le=1.0
    )
    decision: Optional[str] = Field(
        None, description="Recomendación derivada de probability_up (BUY / SELL / HOLD)."
    )
    raw: Optional[Dict[str, Any]] = Field(
        default=None, description="Información cruda / de depuración (per_model_probs, binance, etc.)."
    )
    confidence: Optional[float] = Field(
        None, description="Alias legacy de probability_up (si aplica).", ge=0.0, le=1.0
    )
    additional_info: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata extra legacy (decision, backend, etc.)."
    )


class TopCoin(BaseModel):
    symbol: str
    name: str
    current_price: float
    market_cap: float | None = None
    price_change_24h: float | None = None
    image: str | None = None
