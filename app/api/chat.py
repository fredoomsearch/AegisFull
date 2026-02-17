from __future__ import annotations

import asyncio
import logging
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.memory import (
    delete_conversation as delete_memory_conversation,
    get_or_create_conversation,
    update_memory,
)
from app.models.llm_client import generate_response
from app.models.llm_utils import (
    _LINKY_WORDS,
    build_messages,
    is_code_question,
    is_market_question,
    is_repo_content_question,
)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationArchiveResponse,
    ConversationCreateResponse,
    ConversationDeleteResponse,
    ConversationItem,
    ConversationListResponse,
)
from app.services.time_service import maybe_answer_time_question
from app.services.conversation_events import list_events as list_conversation_events
from app.services.conversation_events import record_event
from app.services.upload_inspector import (
    extract_upload_path_from_text,
    format_upload_summary,
    get_last_upload_path,
    inspect_upload_tree,
    resolve_upload_path,
)
from app.services.web_search import web_search_structured
from app.services.web_snippets import fetch_snippets_from_sources
from app.services.crypto_prediction_log import pair_predictions_with_outcomes
from app.services.crypto_trade_log import compute_pnl, list_trades
from app.services import health_state
from app.tools import fetch_url, fetch_url_via_tor, is_onion, sanitize_web_context
from app.vision_client import analyze_image_bytes

logger = logging.getLogger(__name__)


# 1 ACTIVATE 0 OFF
# -----------------------------------------------------------------------------
# Feature flags
# -----------------------------------------------------------------------------
DISABLE_DB = (os.getenv("AEGIS_DISABLE_DB", "0") or "0").lower() in {"1", "true", "yes", "on"}
ENABLE_CONVERSATIONS_API = (os.getenv("AEGIS_ENABLE_CONVERSATIONS_API", "1") or "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
} and not DISABLE_DB

if not DISABLE_DB:
    from sqlalchemy.orm import Session
    from app.db import crud_conversation
    from app.db.deps import get_db
else:
    Session = Any  # type: ignore[misc,assignment]
    crud_conversation = None  # type: ignore[assignment]

    def get_db():  # type: ignore[override]
        raise HTTPException(status_code=503, detail="Database disabled")

# -----------------------------------------------------------------------------
# Router + executor
# -----------------------------------------------------------------------------
router = APIRouter(tags=["chat"], dependencies=[Depends(require_api_key)])
_executor = ThreadPoolExecutor(max_workers=2)

MAX_RAW_FETCH_BYTES = 200_000
DEFAULT_WEB_CONTEXT_CHARS = 1200
MAX_PROMPT_CHARS = int(os.getenv("AEGIS_MAX_PROMPT_CHARS", "5000"))
HISTORY_FETCH_LIMIT = int(os.getenv("AEGIS_HISTORY_FETCH_LIMIT", "24"))
MAX_RESPONSE_CHARS = int(os.getenv("AEGIS_MAX_RESPONSE_CHARS", "8000"))



_QUERY_NORMALIZATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bformulary\b", flags=re.IGNORECASE), "form"),
    (re.compile(r"\bformularie\b", flags=re.IGNORECASE), "form"),
)


def _prepare_web_query(msg: str) -> str:
    m = msg or ""
    m = re.sub(r"```.*?```", " ", m, flags=re.DOTALL)  # drop fenced blocks
    m = re.sub(r"`([^`]*)`", r"\1", m)                # drop inline backticks
    parts = [p.strip() for p in m.split("\n\n") if p.strip()]
    if parts:
        m = parts[0]
    m = " ".join(m.split())
    for pattern, replacement in _QUERY_NORMALIZATIONS:
        m = pattern.sub(replacement, m)
    trimmed = (m[:160].rsplit(" ", 1)[0] or m[:160]).strip()
    return trimmed


def wants_links_or_sources(message: str) -> bool:
    msg = (message or "").lower()
    return any(w in msg for w in _LINKY_WORDS)


def _maybe_local_upload_summary_response(message: str, lang: str) -> str | None:
    """
    Deterministic fallback for questions like:
      - "what contains /data/uploads/..."
      - "qué contiene /home/.../data/uploads/..."
    This avoids LLM hallucinations when user asks for concrete file inventory.
    """
    if not is_repo_content_question(message):
        return None
    raw = message or ""
    raw_path = extract_upload_path_from_text(raw)
    resolved = resolve_upload_path(raw_path) if raw_path else None
    if resolved is None:
        lower = raw.lower()
        asks_last = any(
            hint in lower
            for hint in (
                "last upload",
                "latest upload",
                "ultimo upload",
                "último upload",
                "ultimo zip",
                "último zip",
                "last zip",
                "my upload",
                "mi upload",
                "archivo subido",
                "proyecto subido",
            )
        )
        if asks_last:
            resolved = get_last_upload_path()
    if resolved is None:
        return None
    info = inspect_upload_tree(resolved, sample_limit=80)
    return format_upload_summary(info, lang=lang)


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        scheme = (p.scheme or "").lower()
        netloc = (p.netloc or "").lower()
        path = (p.path or "").rstrip("/")
        return f"{scheme}://{netloc}{path}?{p.query}".rstrip("?")
    except Exception:
        return u


def clean_model_output(t: str) -> str:
    bad = ["[INST]", "[/INST]", "<<SYS>>", "<</SYS>>"]
    for b in bad:
        t = (t or "").replace(b, "")
    cleaned = (t or "").strip()
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _truncate_response(text: str, lang: str = "es") -> str:
    if not text:
        return text
    max_chars = MAX_RESPONSE_CHARS
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rstrip()
    if truncated.count("```") % 2 == 1:
        truncated += "\n```"
    note = "\n\n[respuesta truncada]" if (lang or "es").lower().startswith("es") else "\n\n[response truncated]"
    return truncated + note


def _ws_to_dict(r: Any) -> dict:
    if r is None:
        return {}
    if isinstance(r, dict):
        return r
    if hasattr(r, "model_dump"):
        try:
            return r.model_dump()
        except Exception:
            return {}
    if hasattr(r, "dict"):
        try:
            return r.dict()
        except Exception:
            return {}
    return {
        "title": getattr(r, "title", ""),
        "snippet": getattr(r, "snippet", ""),
        "link": getattr(r, "link", ""),
        "url": getattr(r, "url", ""),
        "href": getattr(r, "href", ""),
    }


def _as_sources(raw_results: list[Any], limit: int = 6) -> list[dict]:
    seen: set[str] = set()
    cleaned: list[dict] = []

    for rr in raw_results or []:
        r = _ws_to_dict(rr)

        title = (r.get("title") or r.get("name") or "").strip()
        snippet = (r.get("snippet") or r.get("description") or "").strip()
        link = (r.get("link") or r.get("url") or r.get("href") or "").strip()

        n = _norm_url(link)
        if not n or n in seen:
            continue

        seen.add(n)
        cleaned.append({"title": title, "snippet": snippet, "link": link, "url": link})

        if len(cleaned) >= limit:
            break

    return cleaned


# =============================================================================
# Models
# =============================================================================
class ImageAnalysisResponse(BaseModel):
    description: str


class WebResult(BaseModel):
    title: str = ""
    snippet: str = ""
    link: str = ""


class WebSearchResponse(BaseModel):
    results: List[WebResult]


class FetchUrlRequest(BaseModel):
    url: str


def _conversation_to_item(conv) -> ConversationItem:
    created_ts = int(conv.created_at.timestamp()) if conv.created_at else 0
    updated_ts = int(conv.updated_at.timestamp()) if conv.updated_at else created_ts
    title = (conv.summary or "").strip().splitlines()[0] if conv.summary else None
    if title:
        title = title[:120]
    summary = (conv.summary or None)
    return ConversationItem(
        id=conv.id,
        created_at=created_ts,
        updated_at=updated_ts,
        title=title,
        summary=summary,
        archived=bool(getattr(conv, "archived", False)),
    )


def _open_db_session() -> tuple[Session | None, Any | None, bool]:
    if DISABLE_DB:
        return None, None, False
    try:
        from app.db.base import SessionLocal
        from app.db import crud_conversation as crud_mod

        db = SessionLocal()
        return db, crud_mod, True
    except Exception:
        logger.debug("DB not available; falling back to memory-only conversations.", exc_info=True)
        return None, None, False


def _close_db_session(db: Session | None) -> None:
    if db is None:
        return
    try:
        db.close()
    except Exception:
        logger.exception("Failed to close DB session cleanly.")


def _ensure_conversation_id(
    raw_conv: str | None,
    db: Session | None,
    crud,
    db_available: bool,
) -> str:
    conv_id = str(raw_conv).strip() if raw_conv else None

    if conv_id and db_available and crud is not None and db is not None:
        try:
            if crud.get_conversation(db, conv_id) is None:
                conv_id = None
        except Exception:
            logger.debug("Conversation lookup failed; starting a new conversation.", exc_info=True)
            conv_id = None

    if not db_available or crud is None or db is None:
        return get_or_create_conversation(conv_id)

    if conv_id is None:
        conv_id = str(crud.create_conversation(db, None))
    return conv_id


def _respond_with_url_fetch(conv_id: str, url: str, lang: str, db, crud, db_available: bool) -> ChatResponse:
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url.lstrip("/")

    try:
        if is_onion(url):
            res = fetch_url_via_tor(url)
        else:
            res = fetch_url(url)
    except Exception as exc:
        logger.exception("URL fetch failed for %s: %s", url, exc)
        res = {"ok": False, "error": "fetch error"}

    if isinstance(res, dict):
        if not res.get("ok"):
            detail = res.get("error") or ("URL fetch failed" if lang.startswith("en") else "Fallo al leer la URL")
            return ChatResponse(response=str(detail), conversation_id=conv_id, timestamp=datetime.utcnow(), sources=[])
        text = (res.get("text") or "")[:MAX_RAW_FETCH_BYTES]
    else:
        text = str(res)[:MAX_RAW_FETCH_BYTES]

    resp = text or ("URL vacía" if lang.startswith("es") else "Empty URL response")

    try:
        _append_db_message(db, crud, conv_id, "assistant", resp)
        update_memory(conv_id, url, resp)
    except Exception:
        logger.exception("Failed to store URL response")

    return ChatResponse(
        response=resp,
        conversation_id=conv_id,
        timestamp=datetime.utcnow(),
        sources=[{"url": url}],
    )


_CRYPTO_TICKERS = {
    "btc",
    "eth",
    "bnb",
    "sol",
    "ada",
    "xrp",
    "doge",
    "dot",
    "avax",
    "matic",
    "link",
    "ltc",
    "trx",
    "atom",
    "uni",
    "usdt",
    "usdc",
}


def _extract_crypto_symbol(text: str) -> str | None:
    """
    Best-effort coin symbol extractor from free text (BTC, ETH, SOL, or pairs like BTC/USDT).
    """
    t = text or ""
    pair = re.search(r"\b([A-Za-z]{2,10})(?:/)?(USDT|USD|USDC|BUSD|BTC|ETH)\b", t, flags=re.IGNORECASE)
    if pair:
        sym = pair.group(1)
        if sym.lower() in _CRYPTO_TICKERS:
            return sym.upper()
    for token in re.findall(r"[A-Za-z]{2,10}", t):
        if token.lower() in _CRYPTO_TICKERS:
            return token.upper()
    return None


def _format_crypto_prediction(pred, lang: str) -> str:
    prob = pred.probability_up
    prob_pct = f"{prob*100:.1f}%" if isinstance(prob, (int, float)) else "N/A"
    curr = pred.current_price if pred.current_price is not None else "?"
    nxt = pred.predicted_price if pred.predicted_price is not None else "?"
    decision = pred.decision or "HOLD"
    if lang.startswith("es"):
        return f"Predicción demo para {pred.symbol} ({pred.horizon_minutes}m): precio actual {curr}, predicción {nxt}, prob. subida {prob_pct}, señal {decision}."
    return f"Demo prediction for {pred.symbol} ({pred.horizon_minutes}m): current {curr}, predicted {nxt}, prob up {prob_pct}, signal {decision}."


def _prediction_stats(symbol: str) -> dict:
    from app.api.crypto import prediction_stats as _prediction_stats_impl

    return _prediction_stats_impl(symbol=symbol)  # type: ignore[call-arg]


def _spot_price(symbol: str) -> float | None:
    from app.api.crypto import _binance_spot_price as _spot_price_impl

    return _spot_price_impl(symbol)


def _build_crypto_context(symbol: str, horizon_minutes: int = 15, recent: int = 5) -> str:
    """Build a short context string from recent predictions/outcomes and P&L."""
    try:
        sym = symbol.upper()
        preds = pair_predictions_with_outcomes(limit=recent, symbol=sym)
        stats = _prediction_stats(symbol=sym)
        pnl = compute_pnl(list_trades(limit=200, symbol=sym), _spot_price)
    except Exception:
        return ""

    lines = []
    if preds:
        last = preds[0]
        lines.append(
            f"last {sym}: {last.get('decision')} p={last.get('probability_up')} px={last.get('current_price')} ts={last.get('ts')}"
        )
    acc = stats.get("accuracy") if isinstance(stats, dict) else None
    if isinstance(acc, (int, float)):
        lines.append(f"hit_rate≈{acc:.2f}")
    if isinstance(pnl, dict):
        per = pnl.get("per_symbol", {}).get(sym)
        if per:
            lines.append(
                f"pos={per.get('position')} avg={per.get('avg_price')} unrlzd={per.get('unrealized')}"
            )
    return " | ".join(lines)


def _maybe_crypto_prediction(symbol: str):
    """Call the internal crypto predictor without saving logs."""
    try:
        from app.api.crypto import PredictRequest, predict  # local import to avoid cycles

        return predict(PredictRequest(symbol=symbol, save=False))
    except Exception:
        logger.debug("Crypto prediction failed for %s", symbol, exc_info=True)
        return None


def _append_db_message(
    db: Session | None,
    crud,
    conv_id: str,
    role: str,
    content: str,
) -> bool:
    if not db or crud is None:
        return False
    try:
        crud.append_message(db, conv_id, role, content)
        return True
    except Exception:
        logger.exception("DB append failed for role=%s conv_id=%s", role, conv_id)
        return False


def _load_db_history(
    db: Session | None,
    crud,
    conv_id: str,
    limit: int,
    new_user_message: str,
) -> list[dict] | None:
    if not db or crud is None:
        return None

    try:
        recent_msgs = crud.get_recent_messages(db, conv_id, limit=limit)
        history_override = [{"role": m.role, "content": m.content} for m in recent_msgs if m.content]
        if history_override:
            last_msg = history_override[-1]
            if last_msg.get("role") == "user" and (last_msg.get("content", "").strip() == new_user_message):
                history_override = history_override[:-1]
        return history_override or None
    except Exception:
        logger.exception("Failed to load DB history; falling back to memory.")
        return None


def _normalize_lang(raw_lang: str | None) -> str:
    lang = str(raw_lang or "es")
    return lang


def _format_links_response(raw_sources: list[dict], lang: str) -> str:
    lines: list[str] = []
    lines.append(
        "Aquí tienes algunas fuentes (búsqueda web):\n"
        if lang.startswith("es")
        else "Here are some web-search sources:\n"
    )
    for i, s in enumerate(raw_sources[:6], 1):
        t = s.get("title") or f"Source {i}"
        lines.append(f"{i}. {t}\n{s.get('url','')}\n{s.get('snippet','')}\n")
    return "\n".join(lines).strip()


def _apply_snippets_to_sources(raw_sources: list[dict]) -> tuple[str, list[str]]:
    snippets: list[dict] = []
    snippet_errors: list[str] = []

    if not raw_sources:
        return "", snippet_errors

    try:
        snippets, snippet_errors = fetch_snippets_from_sources(raw_sources)
    except Exception:
        logger.exception("Snippet fetch failed")
        return "", snippet_errors

    snippet_map = {sn.get("url"): sn.get("snippet") for sn in snippets if sn.get("url")}
    for src in raw_sources:
        url = src.get("url")
        snippet_text = snippet_map.get(url)
        if snippet_text:
            src["snippet"] = snippet_text

    web_context_raw = "\n\n".join(
        f"[{i}] {s.get('title','')}\n{s.get('snippet','')}\n{s.get('url','')}"
        for i, s in enumerate(raw_sources, 1)
        if s.get("snippet")
    )
    if not web_context_raw:
        return "", snippet_errors
    return sanitize_web_context(web_context_raw, DEFAULT_WEB_CONTEXT_CHARS), snippet_errors


async def _build_web_context(
    conv_id: str,
    user_message: str,
    web_query: str,
    lang: str,
    allow_web: bool,
    loop: asyncio.AbstractEventLoop,
) -> tuple[list[dict], str]:
    raw_sources: list[dict] = []
    web_context = ""

    if not (allow_web or wants_links_or_sources(user_message)):
        return raw_sources, web_context

    try:
        search_results = 8 if wants_links_or_sources(user_message) else 4
        record_event(conv_id, "web_search_start", data={"query": web_query, "limit": search_results})
        raw_results = await loop.run_in_executor(
            _executor,
            lambda: web_search_structured(web_query, search_results, lang=lang) or [],
        )
        raw_sources = _as_sources(raw_results, limit=min(search_results, 8))
        record_event(conv_id, "web_search_done", data={"sources": len(raw_sources)})

        if raw_sources:
            web_context, snippet_errors = _apply_snippets_to_sources(raw_sources)
            if snippet_errors:
                logger.debug("Snippet fetch errors: %s", snippet_errors)
    except Exception:
        logger.exception("Auto web search failed")
        record_event(conv_id, "web_search_failed", level="warn")

    return raw_sources, web_context


# =============================================================================
# Conversation management endpoints (OPTIONAL / DISABLED by default)
# =============================================================================
if ENABLE_CONVERSATIONS_API:

    @router.get("/chat/list", response_model=ConversationListResponse)
    async def list_conversations_endpoint(
        limit: int = Query(20, ge=1, le=200),
        include_archived: bool = Query(False),
        db: Session = Depends(get_db),
    ) -> ConversationListResponse:
        rows = crud_conversation.list_conversations(db, limit=limit, include_archived=include_archived)
        items = [_conversation_to_item(conv) for conv in rows]
        return ConversationListResponse(items=items)

    @router.post("/chat/{conversation_id}/archive", response_model=ConversationArchiveResponse)
    async def archive_conversation_endpoint(
        conversation_id: str,
        db: Session = Depends(get_db),
    ) -> ConversationArchiveResponse:
        ok = crud_conversation.set_conversation_archived(db, conversation_id, archived=True)
        if not ok:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return ConversationArchiveResponse(conversation_id=conversation_id, archived=True)

    @router.post("/chat/{conversation_id}/unarchive", response_model=ConversationArchiveResponse)
    async def unarchive_conversation_endpoint(
        conversation_id: str,
        db: Session = Depends(get_db),
    ) -> ConversationArchiveResponse:
        ok = crud_conversation.set_conversation_archived(db, conversation_id, archived=False)
        if not ok:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return ConversationArchiveResponse(conversation_id=conversation_id, archived=False)

    @router.delete("/chat/{conversation_id}", response_model=ConversationDeleteResponse)
    async def delete_conversation_endpoint(
        conversation_id: str,
        db: Session = Depends(get_db),
    ) -> ConversationDeleteResponse:
        deleted = False
        try:
            deleted = crud_conversation.delete_conversation(db, conversation_id)
        except Exception:
            logger.exception("DB delete conversation failed; falling back to memory store.")

        if not deleted:
            deleted = delete_memory_conversation(conversation_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return ConversationDeleteResponse(conversation_id=conversation_id, deleted=True)

    @router.post("/chat/new", response_model=ConversationCreateResponse)
    async def create_conversation_endpoint() -> ConversationCreateResponse:
        db = None
        db_available = False
        crud = None
        try:
            from app.db.base import SessionLocal
            from app.db import crud_conversation as crud_mod
            db = SessionLocal()
            crud = crud_mod
            db_available = True
        except Exception:
            logger.debug("DB not available; falling back to memory-only conversations.", exc_info=True)

        try:
            if db_available and crud is not None and db is not None:
                conv_id = str(crud.create_conversation(db, None))
            else:
                conv_id = get_or_create_conversation(None)
            return ConversationCreateResponse(conversation_id=str(conv_id))
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    logger.exception("Failed to close DB session cleanly.")


# =============================================================================
# Web tools endpoints (always enabled)
# =============================================================================
@router.get("/websearch", response_model=WebSearchResponse)
async def websearch(
    q: str = Query(..., min_length=1, description="Search query"),
    n: int = Query(3, ge=1, le=10, description="Number of results"),
    lang: str | None = Query(None, description="Language hint (es, en, es-ES, en-US)"),
) -> WebSearchResponse:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    try:
        raw_results = await loop.run_in_executor(_executor, lambda: web_search_structured(q, n, lang=lang) or [])
    except Exception as exc:
        logger.exception("websearch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Error performing web search.")

    raw_results = [_ws_to_dict(r) for r in raw_results]
    results = [
        WebResult(
            title=r.get("title") or r.get("name") or "",
            snippet=r.get("snippet") or r.get("description") or "",
            link=r.get("link") or r.get("url") or r.get("href") or "",
        )
        for r in raw_results
    ]
    return WebSearchResponse(results=results)


@router.post("/fetch_url")
async def fetch_url_endpoint(req: FetchUrlRequest) -> Dict[str, Any]:
    url = (req.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="missing url")

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url.lstrip("/")

    if is_onion(url):
        res = fetch_url_via_tor(url)
        if not isinstance(res, dict):
            return {"status": None, "text": str(res)[:MAX_RAW_FETCH_BYTES]}
        if not res.get("ok"):
            raise HTTPException(status_code=502, detail=res.get("error"))
        return {"status": res.get("status"), "text": res.get("text", "")[:MAX_RAW_FETCH_BYTES]}

    res = fetch_url(url)
    if isinstance(res, dict):
        if not res.get("ok"):
            raise HTTPException(status_code=502, detail=res.get("error"))
        return {"status": res.get("status"), "text": res.get("text", "")}

    text = str(res)
    if text.startswith("(error"):
        raise HTTPException(status_code=502, detail=text)
    return {"status": 200, "text": text[:MAX_RAW_FETCH_BYTES]}


@router.post("/analyze_image", response_model=ImageAnalysisResponse)
async def analyze_image_endpoint(
    file: UploadFile = File(...),
    lang: str = Form("es"),
    mode: str = Form("text"),
    psm: int | None = Form(None, description="tesseract PSM, default 6"),
    oem: int | None = Form(None, description="tesseract OEM, default 1"),
) -> ImageAnalysisResponse:
    MAX_IMAGE_BYTES = int(os.getenv("AEGIS_MAX_IMAGE_BYTES", "5242880"))
    try:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image.")
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Empty file.")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail="Image too large.")

        lang_norm = "es" if (lang or "es").lower().startswith("es") else "en"
        mode_norm = "code" if (mode or "text").lower() == "code" else "text"
        description = analyze_image_bytes(image_bytes, lang=lang_norm, mode=mode_norm, psm=psm, oem=oem)
        return ImageAnalysisResponse(description=description)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("analyze_image_endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail="Error analyzing image.")


# =============================================================================
# Main chat endpoint (always enabled) — NO frontend /chat/new needed
# =============================================================================
@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    db, crud, db_available = _open_db_session()
    try:
        conv_id = _ensure_conversation_id(getattr(body, "conversation_id", None), db, crud, db_available)

        new_user_message = (body.message or "").strip()
        if not new_user_message:
            return ChatResponse(response="No message received.", conversation_id=conv_id, timestamp=datetime.utcnow())

        trace_id = getattr(request.state, "trace_id", None)
        record_event(
            conv_id,
            "request_received",
            data={"trace_id": trace_id, "message": new_user_message},
        )
        logger.info("Incoming message: %s (conv=%s)", new_user_message, conv_id)

        db_user_stored = _append_db_message(db, crud, conv_id, "user", new_user_message)
        if db_user_stored:
            record_event(conv_id, "user_message_stored", data={"store": "db"})
        elif db_available:
            record_event(conv_id, "user_message_store_failed", level="warn", data={"store": "db"})

        lang = _normalize_lang(getattr(body, "lang", None))

        quick_time = maybe_answer_time_question(new_user_message, lang=lang)
        if quick_time:
            resp = quick_time
            try:
                _append_db_message(db, crud, conv_id, "assistant", resp)
                update_memory(conv_id, new_user_message, resp)
                record_event(conv_id, "quick_time_response", data={"response": resp, "lang": lang})
            except Exception:
                logger.exception("Failed to store quick time response")
                record_event(conv_id, "quick_time_store_failed", level="warn")
            return ChatResponse(response=resp, conversation_id=conv_id, timestamp=datetime.utcnow())

        upload_summary = _maybe_local_upload_summary_response(new_user_message, lang)
        if upload_summary:
            try:
                _append_db_message(db, crud, conv_id, "assistant", upload_summary)
                update_memory(conv_id, new_user_message, upload_summary)
                record_event(conv_id, "upload_summary_response", data={"path_hint": True})
            except Exception:
                logger.exception("Failed to store upload summary response")
                record_event(conv_id, "upload_summary_store_failed", level="warn")
            return ChatResponse(response=upload_summary, conversation_id=conv_id, timestamp=datetime.utcnow())

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        mode_value = str(getattr(body, "mode", "")).lower()
        ui_web_mode = bool(getattr(body, "use_web", False) or getattr(body, "web", False) or mode_value == "web")
        is_crypto_mode = mode_value == "crypto"
        is_web_mode = mode_value == "web"
        is_url_mode = mode_value == "url"

        force_web_prefix = new_user_message.lower().startswith("web:")
        force_url_prefix = new_user_message.lower().startswith("url:")

        force_web = (ui_web_mode or force_web_prefix) and not is_crypto_mode and not is_url_mode
        user_msg_for_llm = new_user_message[4:].strip() if force_web_prefix else new_user_message
        if force_url_prefix:
            user_msg_for_llm = new_user_message[4:].strip()

        web_query = _prepare_web_query(user_msg_for_llm)
        record_event(
            conv_id,
            "mode_selected",
            data={"mode": mode_value or "general", "force_web": force_web},
        )

        # Direct URL mode: fetch and return without hitting the LLM
        if is_url_mode or force_url_prefix:
            return _respond_with_url_fetch(conv_id, user_msg_for_llm, lang, db, crud, db_available)

        allow_web = force_web or is_web_mode

        raw_sources: List[Dict[str, str]] = []
        web_context = ""
        if allow_web or (wants_links_or_sources(new_user_message) and not is_crypto_mode):
            raw_sources, web_context = await _build_web_context(
                conv_id,
                new_user_message,
                web_query,
                lang,
                allow_web,
                loop,
            )

        if wants_links_or_sources(new_user_message):
            if is_crypto_mode:
                msg = "En modo cripto no se buscan fuentes web." if lang.startswith("es") else "Web sources are disabled in crypto mode."
                record_event(conv_id, "links_response", data={"sources": 0, "lang": lang, "mode": "crypto"})
                return ChatResponse(response=msg, conversation_id=conv_id, timestamp=datetime.utcnow(), sources=[])
            if not raw_sources or len(raw_sources) < 2:
                msg = "No encontré fuentes web suficientes para darte enlaces." if lang.startswith("es") \
                    else "I couldn't find enough web sources to provide reliable links."
                record_event(conv_id, "links_response", data={"sources": 0, "lang": lang})
                return ChatResponse(response=msg, conversation_id=conv_id, timestamp=datetime.utcnow(), sources=[])

            resp = _format_links_response(raw_sources, lang)

            try:
                _append_db_message(db, crud, conv_id, "assistant", resp)
                update_memory(conv_id, new_user_message, resp)
                record_event(conv_id, "links_response", data={"sources": len(raw_sources), "response": resp})
            except Exception:
                logger.exception("Failed to store links response")
                record_event(conv_id, "links_store_failed", level="warn")

            return ChatResponse(
                response=resp,
                conversation_id=conv_id,
                timestamp=datetime.utcnow(),
                sources=raw_sources,
            )

        history_override = _load_db_history(db, crud, conv_id, HISTORY_FETCH_LIMIT, new_user_message)

        summary_override = "" if history_override is not None else None
        messages_for_llm = build_messages(
            conv_id,
            user_msg_for_llm,
            web_context,
            max_total_chars=MAX_PROMPT_CHARS,
            history_messages=history_override,
            summary_override=summary_override,
        )

        is_code = is_code_question(new_user_message)
        is_market = is_market_question(new_user_message)

        mode = "general"
        if is_code:
            mode = "code"
        elif is_market:
            mode = "crypto"
        if mode_value in {"code", "crypto"}:
            mode = mode_value

        crypto_summary = ""
        if mode == "crypto":
            sym = _extract_crypto_symbol(user_msg_for_llm)
            if sym:
                pred = _maybe_crypto_prediction(sym)
                context_line = _build_crypto_context(sym)
                if pred:
                    crypto_summary = _format_crypto_prediction(pred, lang)
                    ctx = "Crypto prediction context: " + crypto_summary
                    if context_line:
                        ctx += " | " + context_line
                    messages_for_llm.append({"role": "system", "content": ctx})
                    record_event(
                        conv_id,
                        "crypto_prediction",
                        data={
                            "symbol": sym,
                            "decision": getattr(pred, "decision", None),
                            "probability_up": getattr(pred, "probability_up", None),
                        },
                    )

        prompt_chars = sum(len(m.get("content") or "") for m in messages_for_llm)

        try:
            record_event(conv_id, "llm_start", data={"mode": mode, "prompt_chars": prompt_chars})
            resp_raw: str = await loop.run_in_executor(_executor, lambda: generate_response(messages_for_llm, mode=mode))
            resp = clean_model_output(resp_raw or "(empty response)")
            if not resp:
                resp = "El modelo no devolvió texto; intenta de nuevo." if lang.startswith("es") else "The model returned empty text; please retry."
            resp = _truncate_response(resp, lang=lang)
            if crypto_summary:
                resp = f"{crypto_summary}\n\n{resp}"
            record_event(conv_id, "llm_done", data={"response": resp})
        except Exception:
            health_state.record("llm_error", "generate_response failed")
            traceback.print_exc()
            resp = "(error generating response)"
            record_event(conv_id, "llm_failed", level="error")

        try:
            db_assistant_stored = _append_db_message(db, crud, conv_id, "assistant", resp)
            if not db_assistant_stored and db_available:
                record_event(conv_id, "assistant_store_failed", level="warn", data={"store": "db"})
            update_memory(conv_id, new_user_message, resp)
            record_event(conv_id, "response_stored", data={"response": resp})
        except Exception:
            logger.exception("Memory save failed")
            record_event(conv_id, "memory_store_failed", level="warn")

        logger.info("Reply (conv=%s): %s", conv_id, resp[:300].replace("\n", " "))
        return ChatResponse(response=resp, conversation_id=conv_id, timestamp=datetime.utcnow(), sources=raw_sources or None)

    finally:
        _close_db_session(db)


@router.get("/chat/{conversation_id}/events")
async def conversation_events(
    conversation_id: str,
    since: int | None = Query(None, description="Return events after this epoch ms"),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    items = list_conversation_events(conversation_id, since_ts=since, limit=limit)
    return {"conversation_id": conversation_id, "items": items}
