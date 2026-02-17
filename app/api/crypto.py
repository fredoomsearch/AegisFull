from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.models.ml.models import ModelCatalog, TrainedModel, discover_trained_models
from app.services.crypto_news_service import fetch_news as fetch_crypto_news
from app.services.crypto_prediction_log import (
    clear_predictions_and_outcomes,
    list_outcomes,
    list_predictions,
    log_outcome,
    log_prediction,
    pair_predictions_with_outcomes,
    recent_stats,
)
from app.services.crypto_trade_log import clear_trades, compute_pnl, list_trades, log_trade

_pd = None
_meta_module = None


def _upsert_news_items(symbol: str, items: List[dict], window_minutes: int = 120) -> int:
    try:
        from app.services.news_store import upsert_news_items

        return upsert_news_items(symbol, items, window_minutes=window_minutes)
    except Exception:
        return 0


def _fetch_recent_news(symbol: str, minutes: int = 90, limit: int = 12) -> List[dict]:
    try:
        from app.services.news_store import fetch_recent_news

        return fetch_recent_news(symbol, minutes=minutes, limit=limit)
    except Exception:
        return []


def _get_pandas():
    global _pd
    if _pd is not None:
        return _pd
    try:
        import pandas as pd  # type: ignore

        _pd = pd
        return _pd
    except Exception:  # pragma: no cover
        return None


def _get_meta_module():
    global _meta_module
    if _meta_module is not None:
        return _meta_module
    try:
        from app.core import meta as meta_mod  # type: ignore

        _meta_module = meta_mod
        return _meta_module
    except Exception:  # pragma: no cover
        return None

router = APIRouter(prefix="/crypto", tags=["crypto"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Binance helpers
# ---------------------------------------------------------------------------

PRICE_CACHE_TTL = float(os.getenv("BINANCE_PRICE_CACHE_TTL", "8") or "8")
_price_cache: Dict[str, tuple[float, float]] = {}
_price_source: Dict[str, str] = {}
_price_lock = threading.Lock()

# ACTIVATE REAL TIME DATA "1"
def _binance_base_url() -> str:
    live = os.getenv("BINANCE_LIVE", "1").lower() in {"1", "true", "yes"}
    return "https://api.binance.com" if live else "https://testnet.binance.vision"


def _coingecko_id(sym: str) -> Optional[str]:
    sym = sym.lower()
    mapping = {
        "btc": "bitcoin",
        "eth": "ethereum",
        "bnb": "binancecoin",
        "sol": "solana",
        "ada": "cardano",
        "xrp": "ripple",
        "doge": "dogecoin",
        "dot": "polkadot",
        "matic": "polygon",
        "ltc": "litecoin",
    }
    return mapping.get(sym)


def _coingecko_spot_price(symbol: str) -> Optional[float]:
    cid = _coingecko_id(symbol)
    if not cid:
        return None
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cid, "vs_currencies": "usd"},
            timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
        val = data.get(cid, {}).get("usd")
        return float(val) if val is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("CoinGecko price fetch failed for %s: %s", symbol, exc)
        return None


def _binance_spot_price(symbol: str) -> Optional[float]:
    pair = symbol.upper().strip()
    # best-effort: si no trae quote, intenta agregar USDT
    if not pair.endswith(("USDT", "BUSD", "USDC", "FDUSD", "TUSD", "BTC", "ETH")):
        pair = f"{pair}USDT"
    now = time.time()
    if PRICE_CACHE_TTL > 0:
        with _price_lock:
            cached = _price_cache.get(pair)
        if cached and now - cached[1] <= PRICE_CACHE_TTL:
            return cached[0]
    price_val: Optional[float] = None
    source = None
    try:
        resp = requests.get(
            f"{_binance_base_url()}/api/v3/ticker/price",
            params={"symbol": pair},
            timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
        price_str = data.get("price") or data.get("lastPrice")
        price_val = float(price_str) if price_str is not None else None
        source = "binance"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance price fetch failed for %s: %s", pair, exc)

    if price_val is None:
        price_val = _coingecko_spot_price(pair.replace("USDT", ""))
        if price_val is not None:
            source = "coingecko"

    if price_val is None and PRICE_CACHE_TTL > 0:
        with _price_lock:
            cached = _price_cache.get(pair)
        if cached:
            _price_source[pair] = "cache"
            return cached[0]

    if price_val is not None and PRICE_CACHE_TTL > 0:
        with _price_lock:
            _price_cache[pair] = (price_val, now)
        if source:
            _price_source[pair] = source
    return price_val


# ---------------------------------------------------------------------------
# Light sentiment for news (offline-safe keyword heuristic)
# ---------------------------------------------------------------------------

POS_WORDS = {
    "rise",
    "surge",
    "bull",
    "gain",
    "positive",
    "beat",
    "record",
    "upgrade",
    "approve",
    "strong",
    "growth",
}

NEG_WORDS = {
    "fall",
    "drop",
    "bear",
    "loss",
    "negative",
    "miss",
    "hack",
    "ban",
    "lawsuit",
    "fine",
    "weak",
    "decline",
}


def _sentiment_score(text: str | None) -> float:
    if not text:
        return 0.0
    t = text.lower()
    pos = sum(w in t for w in POS_WORDS)
    neg = sum(w in t for w in NEG_WORDS)
    if pos == 0 and neg == 0:
        return 0.0
    score = (pos - neg) / max(1, pos + neg)
    return max(-0.25, min(0.25, score))


def _binance_signed_request(
    *,
    method: str,
    path: str,
    params: Dict[str, Any],
    api_key: str,
    api_secret: str,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = base_url or _binance_base_url()
    query = urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{base}{path}?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}

    try:
        resp = requests.request(method, url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except requests.HTTPError as exc:
        raise HTTPException(status_code=resp.status_code, detail=resp.text) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Binance request failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    symbol: str
    horizon_minutes: int = 15
    model: str = "ensemble"
    save: bool = True


class PredictResponse(BaseModel):
    symbol: str
    horizon_minutes: int
    current_price: Optional[float] = None
    predicted_price: Optional[float] = None
    probability_up: Optional[float] = None
    decision: Literal["BUY", "SELL", "HOLD"] = "HOLD"
    raw: Optional[Dict[str, Any]] = None
    additional_info: Optional[Dict[str, Any]] = None
    news: Optional[List[Dict[str, Any]]] = None


class OhlcvItem(BaseModel):
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class TradeRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    test: bool = True  # simulated by default


class TradeResponse(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: Optional[float]
    status: Literal["FILLED", "SENT_TO_EXCHANGE", "SIMULATED", "REJECTED"]
    ts: int
    message: Optional[str] = None


class TopCoin(BaseModel):
    id: str
    symbol: str
    name: str
    current_price: float
    market_cap: float
    price_change_percentage_24h: float


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _is_valid_binance_symbol(sym: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3,12}(USDT|BUSD|USDC|FDUSD|TUSD|BTC|ETH)", sym.upper()))


def resolve_trained_model(
    symbol: str,
    horizon_minutes: int,
    model_type: Optional[str],
) -> Optional[TrainedModel]:
    trained = discover_trained_models()
    symbol = symbol.upper()
    for m in trained:
        if m.symbol == symbol and m.horizon_minutes == horizon_minutes and (
            model_type is None or m.model_type == model_type
        ):
            return m
    for m in trained:
        if m.symbol == symbol and m.horizon_minutes == horizon_minutes:
            return m
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/models", response_model=ModelCatalog)
def get_models() -> ModelCatalog:
    trained = discover_trained_models()
    default_model = os.getenv("CRYPTO_DEFAULT_MODEL", "ensemble")
    return ModelCatalog(
        available=["rf", "xgb", "cat", "dl", "seta", "ensemble"],
        default=default_model,
        trained=trained,
    )


@router.get("/models/metrics")
def get_model_metrics(limit: int = Query(200, ge=10, le=1000)) -> Dict[str, Any]:
    """Return recent accuracy stats across models."""
    try:
        return recent_stats(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error computing model metrics: {exc}") from exc


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    sym = req.symbol.upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="Missing symbol")

    requested_model = (req.model or "ensemble").lower().strip()
    if requested_model not in {"rf", "xgb", "cat", "dl", "seta", "ensemble"}:
        raise HTTPException(status_code=400, detail="Unsupported model")

    live_price = _binance_spot_price(sym)
    price_source = _price_source.get(sym, None)
    price_source = _price_source.get(sym, "demo" if live_price is None else "binance")
    digest = int(hashlib.sha256(f"{sym}:{req.horizon_minutes}".encode()).hexdigest(), 16)
    base = 100 + (digest % 500)
    wobble = 5 * math.sin(time.time() / 60.0)
    current = round(live_price if live_price is not None else (base + wobble), 2)

    rng = random.Random(digest ^ 0xABCDEF)
    p_up = max(0.05, min(0.95, rng.random()))
    p_base = p_up  # guardamos la prob. antes de cualquier ajuste
    delta = (rng.random() - 0.5) * 2.0
    predicted = round(current * (1 + delta * 0.01), 2)

    if p_up > 0.63:
        decision: Literal["BUY", "SELL", "HOLD"] = "BUY"
    elif p_up < 0.37:
        decision = "SELL"
    else:
        decision = "HOLD"

    raw = {
        "per_model_probs": {
            "rf": round(p_up * 0.9 + 0.05, 3),
            "xgb": round(p_up * 0.85 + 0.08, 3),
            "cat": round(p_up * 0.88 + 0.06, 3),
            "dl": round(p_up * 0.92 + 0.04, 3),
            "seta": round(p_up * 0.8 + 0.1, 3),
        }
    }

    if requested_model != "ensemble":
        adjust = {"rf": -0.01, "xgb": 0.01, "cat": 0.0, "dl": 0.02, "seta": -0.02}.get(requested_model, 0.0)
        p_up = max(0.05, min(0.95, p_up + adjust))
        predicted = round(current * (1 + (p_up - 0.5) * 0.02), 2)
        decision = "BUY" if p_up > 0.63 else "SELL" if p_up < 0.37 else "HOLD"

    news_payload = fetch_crypto_news(sym)
    news_items = news_payload.get("items", [])[:6] if news_payload else []

    # persist news (dedupe by hash)
    try:
        _upsert_news_items(sym, news_items, window_minutes=180)
    except Exception:
        logger.debug("Failed to upsert news", exc_info=True)

    # fetch a recent window for sentiment/adjustment (DB, deduped)
    try:
        recent_news = _fetch_recent_news(sym, minutes=90, limit=12)
    except Exception:
        recent_news = []

    if recent_news:
        news_items = recent_news

    # Ajuste por sentimiento de noticias (ligero y seguro)
    news_sentiment = None
    n_news_used = 0
    if news_items:
        sentiments = [_sentiment_score((n.get("title") or "") + " " + (n.get("summary") or "")) for n in news_items]
        sentiments = [s for s in sentiments if s is not None]
        n_news_used = len(sentiments)
        if n_news_used >= 1:
            news_sentiment = sum(sentiments) / n_news_used
            p_up = max(0.05, min(0.95, p_up + news_sentiment * 0.08))
            predicted = round(current * (1 + (p_up - 0.5) * 0.02), 2)
            decision = "BUY" if p_up > 0.63 else "SELL" if p_up < 0.37 else "HOLD"

    log_id: Optional[str] = None
    if req.save:
        log_id = log_prediction(
            {
                "symbol": sym,
                "horizon_minutes": req.horizon_minutes,
                "model": requested_model,
                "probability_up": p_up,
                "probability_base": p_base,
                "decision": decision,
                "current_price": current,
                "price_source": _price_source.get(sym, None),
                "news": news_items,
                "news_sentiment": news_sentiment,
                "n_news_used": n_news_used,
                "ts": int(time.time()),
            }
        )

    if log_id:
        def _capture_outcome() -> None:
            try:
                live = _binance_spot_price(sym)
                if live is None or live <= 0:
                    return
                delta_pct = (live - current) / current if current else 0.0
                hit = None
                if decision == "BUY":
                    hit = live > current
                elif decision == "SELL":
                    hit = live < current
                elif decision == "HOLD":
                    hit = abs(delta_pct) < 0.01
                log_outcome(
                    {
                        "log_id": log_id,
                        "symbol": sym,
                        "horizon_minutes": req.horizon_minutes,
                        "decision": decision,
                        "probability_up": p_up,
                        "probability_base": p_base,
                        "model": requested_model,
                        "predicted_price": current,
                        "actual_price": live,
                        "delta_pct": delta_pct,
                        "hit": hit,
                        "price_source": _price_source.get(sym, None),
                        "news_sentiment": news_sentiment,
                        "n_news_used": n_news_used,
                    }
                )
            except Exception:
                return

        try:
            threading.Timer(req.horizon_minutes * 60, _capture_outcome).start()
        except Exception:
            pass

    return PredictResponse(
        symbol=sym,
        horizon_minutes=req.horizon_minutes,
        current_price=current,
        predicted_price=predicted,
        probability_up=p_up,
        decision=decision,
        raw=raw,
        additional_info={
            "note": "demo prediction (not financial advice)",
            "model_used": requested_model,
            "news_provider": news_payload.get("provider") if news_payload else None,
            "log_id": log_id,
            "price_source": price_source,
            "news_sentiment": news_sentiment,
        },
        news=news_items,
    )


@router.get("/top-coins", response_model=List[TopCoin])
def top_coins(
    limit: int = Query(30, ge=1, le=250),
    max_price: Optional[float] = Query(None),
    min_price: Optional[float] = Query(None),
) -> List[TopCoin]:
    base = [
        TopCoin(id="bitcoin", symbol="btc", name="Bitcoin", current_price=50000.0, market_cap=1.0e12, price_change_percentage_24h=1.2),
        TopCoin(id="ethereum", symbol="eth", name="Ethereum", current_price=2500.0, market_cap=3.0e11, price_change_percentage_24h=-0.4),
        TopCoin(id="tether", symbol="usdt", name="Tether", current_price=1.0, market_cap=9.0e10, price_change_percentage_24h=0.0),
        TopCoin(id="bnb", symbol="bnb", name="BNB", current_price=320.0, market_cap=5.0e10, price_change_percentage_24h=0.8),
        TopCoin(id="solana", symbol="sol", name="Solana", current_price=110.0, market_cap=4.5e10, price_change_percentage_24h=2.1),
        TopCoin(id="xrp", symbol="xrp", name="XRP", current_price=0.60, market_cap=3.0e10, price_change_percentage_24h=-1.0),
        TopCoin(id="cardano", symbol="ada", name="Cardano", current_price=0.45, market_cap=1.6e10, price_change_percentage_24h=0.5),
        TopCoin(id="dogecoin", symbol="doge", name="Dogecoin", current_price=0.10, market_cap=1.4e10, price_change_percentage_24h=3.2),
        TopCoin(id="tron", symbol="trx", name="TRON", current_price=0.12, market_cap=1.0e10, price_change_percentage_24h=-0.2),
        TopCoin(id="polkadot", symbol="dot", name="Polkadot", current_price=6.1, market_cap=9.0e9, price_change_percentage_24h=1.9),
    ]
    coins = base
    if min_price is not None:
        coins = [c for c in coins if c.current_price >= min_price]
    if max_price is not None:
        coins = [c for c in coins if c.current_price <= max_price]
    return coins[:limit]


@router.get("/ohlcv", response_model=List[OhlcvItem])
def get_ohlcv(
    symbol: str = Query(...),
    interval: str = Query("1m"),
    limit: int = Query(200, ge=1, le=1000),
) -> List[OhlcvItem]:
    sym = symbol.upper().strip()
    step = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(interval, 60)

    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": sym, "interval": interval, "limit": limit},
            timeout=8,
        )
        resp.raise_for_status()
        raw = resp.json()
        series: List[OhlcvItem] = []
        for item in raw:
            ts = int(item[6])  # close time
            series.append(
                OhlcvItem(
                    ts=ts,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                )
            )
        return series
    except Exception:
        base = 100 + (hash(sym) % 500)
        now = int(time.time())
        rng = random.Random(hash((sym, interval)))
        series: List[OhlcvItem] = []
        for i in range(limit):
            ts = now - step * (limit - 1 - i)
            center = base + 5 * math.sin(i / 12.0)
            c = round(center + rng.uniform(-0.7, 0.7), 2)
            o = round(c + rng.uniform(-0.5, 0.5), 2)
            h = round(max(o, c) + rng.uniform(0, 0.8), 2)
            l = round(min(o, c) - rng.uniform(0, 0.8), 2)
            v = round(abs(rng.gauss(50, 15)), 2)
            series.append(OhlcvItem(ts=ts, open=o, high=h, low=l, close=c, volume=v))
        return series


@router.get("/news")
def crypto_news(
    symbol: str = Query(..., min_length=2, max_length=20),
    force: bool = Query(False, description="Bypass cache when true"),
) -> Dict[str, Any]:
    try:
        return fetch_crypto_news(symbol, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error fetching news: {exc}") from exc


@router.get("/predictions")
def recent_predictions(
    limit: int = Query(20, ge=1, le=200),
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
) -> List[Dict[str, Any]]:
    try:
        return pair_predictions_with_outcomes(limit=limit, symbol=symbol)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error listing predictions: {exc}") from exc


@router.get("/predictions/outcomes")
def recent_outcomes(
    limit: int = Query(50, ge=1, le=500),
    symbol: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    try:
        return list_outcomes(limit=limit, symbol=symbol)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error listing outcomes: {exc}") from exc


@router.delete("/predictions")
def clear_predictions(_: Optional[str] = Depends(require_api_key)) -> dict:
    """Remove prediction and outcome logs (crypto history)."""
    try:
        clear_predictions_and_outcomes()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error clearing predictions: {exc}") from exc


@router.get("/predictions/stats")
def prediction_stats(
    limit: int = Query(100, ge=1, le=500),
    symbol: Optional[str] = Query(None),
) -> Dict[str, Any]:
    try:
        if symbol:
            outs = list_outcomes(limit=limit, symbol=symbol)
            if not outs:
                return {"count": 0, "accuracy": None, "avg_delta_pct": None, "per_model": {}}
            hits = [o for o in outs if o.get("hit") is True]
            acc = len(hits) / len(outs) if outs else None
            deltas = [o.get("delta_pct") for o in outs if isinstance(o.get("delta_pct"), (int, float))]
            avg_delta = sum(deltas) / len(deltas) if deltas else None
            per_model: Dict[str, Dict[str, Any]] = {}
            for o in outs:
                m = o.get("model") or "unknown"
                agg = per_model.setdefault(m, {"count": 0, "hits": 0})
                agg["count"] += 1
                if o.get("hit") is True:
                    agg["hits"] += 1
            per_model_stats = {
                m: {"count": v["count"], "accuracy": (v["hits"] / v["count"] if v["count"] else None)}
                for m, v in per_model.items()
            }
            return {
                "count": len(outs),
                "accuracy": acc,
                "avg_delta_pct": avg_delta,
                "per_model": per_model_stats,
            }
        return recent_stats(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error computing stats: {exc}") from exc


@router.post("/trade", response_model=TradeResponse)
def trade(order: TradeRequest) -> TradeResponse:
    if order.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")

    symbol_pair = order.symbol.upper().strip()
    price_live = _binance_spot_price(symbol_pair)
    api_key = os.getenv("BINANCE_API_KEY", "wS58t0PEQX4szcC0zHEfNQwpAvEwhshvMyItIzOPmtvE25bV5KieXgsJXdwLrlBV").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "v49yE62yFVcXoSgw53ehsgdJHiXWeN7CpbHbpbZWxpoKyxWBxOuu2qA7KRVOgzET").strip()
    base_url = _binance_base_url()

    if api_key and api_secret:
        path = "/api/v3/order/test" if order.test else "/api/v3/order"
        params = {
            "symbol": symbol_pair,
            "side": order.side,
            "type": "MARKET",
            "quantity": order.quantity,
            "timestamp": int(time.time() * 1000),
        }
        try:
            _binance_signed_request(
                method="POST",
                path=path,
                params=params,
                api_key=api_key,
                api_secret=api_secret,
                base_url=base_url,
            )
            status: Literal["FILLED", "SENT_TO_EXCHANGE", "SIMULATED", "REJECTED"] = (
                "SIMULATED" if order.test else "SENT_TO_EXCHANGE"
            )
            msg = "Binance test order ok" if order.test else "Order sent to Binance"
            resp = TradeResponse(
                symbol=symbol_pair,
                side=order.side,
                quantity=order.quantity,
                price=round(price_live or 0.0, 2),
                status=status,
                ts=int(time.time()),
                message=msg,
            )
            try:
                log_trade(
                    {
                        "symbol": resp.symbol,
                        "side": resp.side,
                        "quantity": resp.quantity,
                        "price": resp.price,
                        "status": resp.status,
                        "test": order.test,
                        "ts": resp.ts,
                    }
                )
            except Exception:
                pass
            return resp
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Binance order failed: {exc}") from exc

    price = price_live if price_live is not None else (100 + (hash(symbol_pair) % 500))
    resp = TradeResponse(
        symbol=symbol_pair,
        side=order.side,
        quantity=order.quantity,
        price=round(price, 2),
        status="SIMULATED",
        ts=int(time.time()),
        message="Simulated trade (set BINANCE_API_KEY/SECRET for live or test orders)",
    )
    try:
        log_trade(
            {
                "symbol": resp.symbol,
                "side": resp.side,
                "quantity": resp.quantity,
                "price": resp.price,
                "status": resp.status,
                "test": order.test,
                "ts": resp.ts,
            }
        )
    except Exception:
        pass
    return resp


@router.get("/trades")
def get_trades(
    limit: int = Query(100, ge=1, le=500),
    symbol: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    try:
        return list_trades(limit=limit, symbol=symbol)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error listing trades: {exc}") from exc


@router.delete("/trades")
def clear_trades_history(_: Optional[str] = Depends(require_api_key)) -> dict:
    """Remove stored simulated trades."""
    try:
        clear_trades()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error clearing trades: {exc}") from exc


@router.get("/pnl")
def get_pnl(
    limit: int = Query(200, ge=10, le=1000),
    symbol: Optional[str] = Query(None),
) -> Dict[str, Any]:
    try:
        trades = list_trades(limit=limit, symbol=symbol)
        pnl = compute_pnl(trades, _binance_spot_price)
        pnl["trades_count"] = len(trades)
        return pnl
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error computing P&L: {exc}") from exc


@router.post("/predictions/evaluate")
def evaluate_predictions(
    limit: int = Query(400, ge=10, le=2000),
) -> Dict[str, Any]:
    try:
        preds = list_predictions(limit=limit)
        outs = list_outcomes(limit=limit * 2)
        already = {o.get("log_id") for o in outs if o.get("log_id")}
        now_ts = int(time.time())
        evaluated = 0
        for p in preds:
            pid = p.get("id")
            if not pid or pid in already:
                continue
            horizon = int(p.get("horizon_minutes") or 0)
            ts = int(p.get("ts") or 0)
            if horizon <= 0 or ts <= 0 or now_ts - ts < horizon * 60:
                continue
            sym = (p.get("symbol") or "").upper()
            if not sym:
                continue
            live = _binance_spot_price(sym) or p.get("current_price")
            if live is None:
                continue
            current = p.get("current_price") or live
            decision = p.get("decision") or "HOLD"
            delta_pct = (live - current) / current if current else 0.0
            hit = None
            if decision == "BUY":
                hit = live > current
            elif decision == "SELL":
                hit = live < current
            elif decision == "HOLD":
                hit = abs(delta_pct) < 0.01
            log_outcome(
                {
                    "log_id": pid,
                    "symbol": sym,
                    "horizon_minutes": horizon,
                    "decision": decision,
                    "probability_up": p.get("probability_up"),
                    "model": p.get("model"),
                    "predicted_price": current,
                    "actual_price": live,
                    "delta_pct": delta_pct,
                    "hit": hit,
                }
            )
            evaluated += 1
        return {"evaluated": evaluated}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error evaluando predicciones: {exc}") from exc


@router.get("/live-enriched-snapshot")
def live_enriched_snapshot(
    symbols: str = Query("bitcoin:BTCUSDT,ethereum:ETHUSDT", description="coingecko_id:binance_pair"),
    save_to_csv: bool = Query(False),
) -> Dict[str, Any]:
    pd = _get_pandas()
    meta_module = _get_meta_module()
    specs: List[str] = [s.strip() for s in symbols.split(",") if s.strip()]
    if not specs:
        raise HTTPException(status_code=400, detail="No valid symbols provided.")

    if pd is None or meta_module is None:
        raw_rows = [{
            "symbol": "bitcoin",
            "binance_symbol": "BTCUSDT",
            "current_price": 50000.0,
            "high_24h": 51000.0,
            "low_24h": 49000.0,
            "total_volume": 123456789.0,
            "change_24h": 1.2,
            "timestamp": int(time.time()),
        }]
        return {
            "status": "stub",
            "reason": "pandas/meta_module not available",
            "symbols": specs,
            "rows_count": len(raw_rows),
            "saved_csv": None,
            "raw": raw_rows,
            "enriched": raw_rows,
        }

    raw_rows: List[Dict[str, Any]] = []
    invalid_specs: List[str] = []
    for spec in specs:
        try:
            cg_id, bin_symbol = spec.split(":")
        except ValueError:
            invalid_specs.append(spec)
            continue

        cg: Dict[str, Any] = {}
        try:
            cg = meta_module.fetch_coingecko(cg_id) or {}
        except Exception:
            cg = {}

        bz: Dict[str, Any] = {}
        if _is_valid_binance_symbol(bin_symbol):
            try:
                bz = meta_module.fetch_binance(bin_symbol) or {}
            except Exception:
                bz = {}
        else:
            invalid_specs.append(spec)

        row = {
            "symbol": cg_id,
            "binance_symbol": bin_symbol if _is_valid_binance_symbol(bin_symbol) else None,
            "current_price": cg.get("price") or bz.get("price"),
            "high_24h": cg.get("high_24h") or bz.get("high_24h"),
            "low_24h": cg.get("low_24h") or bz.get("low_24h"),
            "total_volume": cg.get("volume") or bz.get("volume"),
            "change_24h": cg.get("change_24h") or bz.get("change_24h"),
            "timestamp": cg.get("timestamp") or int(time.time()),
        }
        raw_rows.append(row)

    if not raw_rows:
        detail = "Could not fetch live data for any symbol."
        if invalid_specs:
            detail += f" Invalid specs: {', '.join(invalid_specs)}"
        raise HTTPException(status_code=400, detail=detail)

    df_raw = pd.DataFrame(raw_rows)
    try:
        enricher = meta_module.SetaFeatureEnricher()
        df_enriched = enricher.enrich_features(df_raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature enrichment failed: {exc}") from exc

    saved_path: Optional[str] = None
    if save_to_csv:
        os.makedirs("data", exist_ok=True)
        saved_path = "data/crypto_live_snapshot.csv"
        df_enriched.to_csv(saved_path, index=False)

    return {
        "status": "success",
        "symbols": specs,
        "rows_count": len(raw_rows),
        "saved_csv": saved_path,
        "raw": raw_rows,
        "enriched": df_enriched.to_dict(orient="records"),
    }
