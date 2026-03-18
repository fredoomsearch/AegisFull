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
    synthesize: bool = Field(
        True, description="Whether to synthesize a final answer via the LLM"
    )
    use_web: Optional[bool] = Field(
        False, description="Force web-search mode for this request"
    )
    web: Optional[bool] = Field(
        False, description="Legacy alias for web-search mode"
    )
    mode: Optional[str] = Field(
        None, description="Interaction mode: general|chat|web|crypto|url|code"
    )
    active_project_id: Optional[str] = Field(
        None, description="Optional active project bound to this turn/conversation"
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
                "mode": "web",
                "use_web": True,
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
    sources: Optional[List[Dict[str, Any]]] = Field(
        None, description="Optional list of search sources [{'title','snippet','link'}]"
    )
    context: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional response context metadata (source origin, active project, source plan, etc.)",
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
                "context": {
                    "source_plan": "hybrid",
                    "source_origin": ["local", "web"],
                    "active_project_id": "demo_proj",
                },
            }
        },
    )


# ---------------------------------------------------------------------------
# Tool execution schemas (agent-ish UI helpers)
# ---------------------------------------------------------------------------

class ToolExecuteRequest(BaseModel):
    tool: str = Field(..., min_length=1, description="Tool name (allowlisted)")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments (small JSON)")
    approval_token: Optional[str] = Field(None, description="Approval token for sensitive tools (if required)")
    continue_after: bool = Field(default=False, description="If true, run agent_continue after tool execution when continuation is available")
    continue_message: Optional[str] = Field(default=None, description="Optional continuation prompt override")
    continue_lang: Optional[str] = Field(default=None, description="Continuation language override (es/en)")
    continue_use_web: bool = Field(default=False, description="Allow web usage for automatic continuation")
    continue_synthesize: bool = Field(default=True, description="Synthesize assistant answer on continuation")
    continue_max_iterations: int = Field(default=2, ge=1, le=10, description="Continuation max iterations")
    continue_max_total_tool_calls: int = Field(default=6, ge=0, le=40, description="Continuation max total tool calls")
    continue_max_tool_retries: int = Field(default=1, ge=0, le=3, description="Continuation retries per tool call")
    continue_tool_retry_backoff_ms: int = Field(default=150, ge=0, le=2000, description="Continuation retry backoff (ms)")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ToolExecuteResponse(BaseModel):
    ok: bool = Field(..., description="Whether tool execution succeeded")
    tool: str = Field(..., description="Tool name executed")
    result: Optional[Any] = Field(None, description="Tool result payload")
    context: Optional[Dict[str, Any]] = Field(None, description="Execution context metadata")
    continued: bool = Field(False, description="Whether server performed automatic agent continuation")
    continue_result: Optional[Dict[str, Any]] = Field(None, description="Continuation summary payload when continued=true")
    approval_required: bool = Field(False, description="Whether approval is required before executing this tool")
    approval: Optional[Dict[str, Any]] = Field(None, description="Approval details when approval_required=true")

    model_config = ConfigDict(
        validate_assignment=True,
    )


# ---------------------------------------------------------------------------
# Agent step schemas (planner/executor loop)
# ---------------------------------------------------------------------------

class AgentStepRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message")
    lang: Optional[str] = Field(default="es", description="Language hint (es/en)")
    use_web: bool = Field(default=False, description="Allow web search when needed")
    max_tool_calls: int = Field(default=3, ge=0, le=10, description="Max local tool calls in this step")
    synthesize: bool = Field(default=True, description="Whether to synthesize a final answer via LLM")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class EvidenceItem(BaseModel):
    origin: str = Field(..., description="manifest|local|web|log")
    kind: str = Field(..., description="summary|symbols|excerpt|files|status")
    project_id: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(
        validate_assignment=True,
    )


class AgentStepResponse(BaseModel):
    ok: bool
    conversation_id: str
    response: str
    plan: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    sources: Optional[List[Dict[str, Any]]] = None
    web_meta: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(
        validate_assignment=True,
    )


class AgentRunRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message")
    lang: Optional[str] = Field(default="es", description="Language hint (es/en)")
    use_web: bool = Field(default=False, description="Allow web search when needed")
    max_iterations: int = Field(default=3, ge=1, le=10, description="Max plan/execute/verify iterations")
    max_total_tool_calls: int = Field(default=8, ge=0, le=40, description="Max total tool calls across iterations")
    max_tool_retries: int = Field(default=1, ge=0, le=3, description="Retries per tool call when a tool fails")
    tool_retry_backoff_ms: int = Field(default=150, ge=0, le=2000, description="Linear backoff per retry attempt (milliseconds)")
    synthesize: bool = Field(default=True, description="Whether to synthesize a final answer via LLM")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class AgentRunResponse(BaseModel):
    ok: bool
    conversation_id: str
    response: str
    iterations: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    sources: Optional[List[Dict[str, Any]]] = None
    web_meta: Optional[Dict[str, Any]] = None
    stop_reason: Optional[str] = Field(default=None, description="Planner stop reason for this run")
    budget_exhausted: bool = Field(default=False, description="Whether the run hit max_total_tool_calls")
    total_tool_calls: int = Field(default=0, description="Total tools executed in this run")
    iterations_completed: int = Field(default=0, description="Iterations executed in this run")

    model_config = ConfigDict(
        validate_assignment=True,
    )


class AgentContinueRequest(BaseModel):
    message: Optional[str] = Field(default=None, description="Optional override message; if omitted, uses session state next_step/task")
    lang: Optional[str] = Field(default="es", description="Language hint (es/en)")
    use_web: bool = Field(default=False, description="Allow web search when needed")
    max_iterations: int = Field(default=2, ge=1, le=10, description="Max plan/execute/verify iterations")
    max_total_tool_calls: int = Field(default=6, ge=0, le=40, description="Max total tool calls across iterations")
    max_tool_retries: int = Field(default=1, ge=0, le=3, description="Retries per tool call when a tool fails")
    tool_retry_backoff_ms: int = Field(default=150, ge=0, le=2000, description="Linear backoff per retry attempt (milliseconds)")
    synthesize: bool = Field(default=True, description="Whether to synthesize a final answer via LLM")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
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


class ConversationProjectBindRequest(BaseModel):
    project_id: Optional[str] = None


class ConversationItem(BaseModel):
    id: str
    created_at: int
    updated_at: int
    title: Optional[str] = None
    summary: Optional[str] = None
    archived: bool = False
    turn_count: Optional[int] = None
    last_turn_id: Optional[str] = None


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
