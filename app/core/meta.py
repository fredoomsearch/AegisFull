from __future__ import annotations

"""
Meta-crypto module: models, feature engineering and ensemble utilities.

Key pieces:
  - SetaFeatureEnricher: enrich raw crypto data with TA, sentiment, etc.
  - fetch_coingecko / fetch_binance helpers.
  - Internal ensemble helpers used by higher-level endpoints.
"""

import datetime
import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
import pandas_ta as ta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sklearn.metrics import brier_score_loss
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)
CG_TIMEOUT = float(os.getenv("COINGECKO_TIMEOUT", "8"))
BN_TIMEOUT = float(os.getenv("BINANCE_TIMEOUT", "6"))
FAST_MODE = os.getenv("AEGIS_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
_CRYPTO_EXTERNAL_RAW = os.getenv("AEGIS_CRYPTO_EXTERNAL_FEATURES", "").strip().lower()
# External features hit network (reddit/orderbook); allow disabling for speed or offline runs.
CRYPTO_EXTERNAL_FEATURES = (
    not FAST_MODE if not _CRYPTO_EXTERNAL_RAW else _CRYPTO_EXTERNAL_RAW in {"1", "true", "yes", "on"}
)

# Reddit sentiment controls
REDDIT_SENTIMENT_SKIP = os.getenv("AEGIS_SKIP_REDDIT_SENTIMENT", "").strip().lower() in {"1", "true", "yes", "on"}
REDDIT_SENTIMENT_TIMEOUT = float(os.getenv("AEGIS_REDDIT_TIMEOUT", "6") or "6")
REDDIT_SENTIMENT_RETRIES = int(os.getenv("AEGIS_REDDIT_RETRIES", "2") or "2")
REDDIT_SENTIMENT_BACKOFF = float(os.getenv("AEGIS_REDDIT_BACKOFF", "0.6") or "0.6")
REDDIT_SENTIMENT_MAX_CALLS = int(os.getenv("AEGIS_REDDIT_MAX_CALLS", "12") or "12")
_REDDIT_SENTIMENT_CACHE: Dict[str, float] = {}
_reddit_sentiment_calls = 0
ORDERBOOK_CACHE_TTL = float(os.getenv("AEGIS_ORDERBOOK_CACHE_TTL", "20"))
_ORDERBOOK_CACHE: Dict[str, tuple[float, float]] = {}


def _requests_session(total_retries: int = 2, backoff: float = 0.5) -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=total_retries,
        read=total_retries,
        connect=total_retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({"User-Agent": "AegisChat/crypto-fetch"})
    return sess


_http = _requests_session()
_sentiment_http = _requests_session(total_retries=REDDIT_SENTIMENT_RETRIES, backoff=REDDIT_SENTIMENT_BACKOFF)

router = APIRouter(prefix="/meta", tags=["meta_crypto"])

# ---------------------------------------------------------------------
# Model paths (5 models)
# ---------------------------------------------------------------------
MODEL_DIR = os.getenv("MODEL_DIR", "models")

CALIBRATED_MODEL_PATH = os.path.join(
    MODEL_DIR,
    "calibrated_stacking_model.joblib",
)  # "seta"
RF_MODEL_PATH = os.path.join(MODEL_DIR, "rf_model.joblib")
DL_MODEL_PATH = os.path.join(MODEL_DIR, "lstm_model.joblib")
XGB_MODEL_PATH = os.path.join(MODEL_DIR, "xgb_model.joblib")
CAT_MODEL_PATH = os.path.join(MODEL_DIR, "cat_model.joblib")

_cached_models: Dict[str, Any] = {
    "rf": None,
    "dl": None,
    "xgb": None,
    "cat": None,
    "calibrated": None,  # seta
    "meta": None,
}


# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------
def load_model_safe(path: str):
    if os.path.exists(path):
        try:
            return joblib.load(path)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to load model %s: %s", path, e)
            return None

    # Fallback: look for the newest artifact with the same filename under CRYPTO_ARTIFACTS_DIR
    artifacts_dir = Path(os.getenv("CRYPTO_ARTIFACTS_DIR", "artifacts/crypto_models"))
    target_name = Path(path).name
    if artifacts_dir.exists():
        candidates = sorted(
            (p for p in artifacts_dir.rglob(target_name) if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for cand in candidates:
            try:
                logger.info("Loading fallback model from %s", cand)
                return joblib.load(cand)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load fallback model %s: %s", cand, e)
                continue

    logger.info("Model path does not exist: %s", path)
    return None


def _load_meta_json(path: str) -> Optional[dict]:
    target = Path(path)
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read meta JSON at %s: %s", target, exc)

    artifacts_dir = Path(os.getenv("CRYPTO_ARTIFACTS_DIR", "artifacts/crypto_models"))
    latest_txt = artifacts_dir / "latest.txt"
    previous_txt = artifacts_dir / "previous.txt"

    candidates: List[Path] = []
    for pointer in (latest_txt, previous_txt):
        if pointer.exists():
            try:
                ts = pointer.read_text(encoding="utf-8").strip()
                if not ts:
                    continue
                version_dir = artifacts_dir / ts
                cand = version_dir / target.name
                if cand.exists():
                    candidates.append(cand)
            except Exception:
                logger.debug("Could not read %s for meta fallback", pointer.name, exc_info=True)

    if not candidates and artifacts_dir.exists():
        candidates = sorted(
            (p for p in artifacts_dir.rglob(target.name) if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    for cand in candidates:
        try:
            logger.info("Loading fallback meta JSON from %s", cand)
            return json.loads(cand.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read fallback meta JSON %s: %s", cand, exc)
            continue

    return None


def load_csv(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)
    sample = pd.read_csv(csv_path, nrows=0)
    possible_date_cols = [
        c
        for c in ["timestamp", "date", "time", "last_updated", "datetime"]
        if c in sample.columns
    ]
    try:
        df = pd.read_csv(csv_path, parse_dates=possible_date_cols, low_memory=False)
    except Exception:  # noqa: BLE001
        df = pd.read_csv(csv_path, low_memory=False)
    return df


def ensure_price_direction(
    df: pd.DataFrame,
    price_col: str = "current_price",
    label_col: str = "price_direction",
) -> pd.DataFrame:
    """
    Adds a binary label: 1 if next price > current price, else 0.
    Used as target for classification models.
    """
    df = df.copy()
    if label_col in df.columns:
        return df

    if price_col not in df.columns:
        raise ValueError(
            f"Cannot generate {label_col}: '{price_col}' missing from dataframe"
        )

    df[label_col] = (df[price_col].shift(-1) > df[price_col]).astype(int)
    df[label_col] = df[label_col].fillna(0).astype(int)
    return df


def _choose_features(df: pd.DataFrame, meta_path: Optional[str] = None) -> List[str]:
    """
    Prefer the feature list stored in meta JSON if present; otherwise fallback
    to all numeric columns.
    """
    if meta_path:
        meta = _load_meta_json(meta_path)
        if meta:
            try:
                cols = meta.get("feature_columns", [])
                cols = [c for c in cols if c in df.columns]
                if cols:
                    return cols
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to read meta feature_columns: %s", e)
    return list(df.select_dtypes(include=[np.number]).columns)


def _ensemble_probs(
    weights,
    rf_probs,
    dl_probs,
    xgb_probs,
    cat_probs,
    seta_probs,
):
    return (
        weights[0] * rf_probs
        + weights[1] * dl_probs
        + weights[2] * xgb_probs
        + weights[3] * cat_probs
        + weights[4] * seta_probs
    )


def _precision_and_coverage(
    y_true: np.ndarray,
    probs: np.ndarray,
    threshold: float,
):
    mask = probs >= threshold
    if mask.sum() == 0:
        return None, 0.0, 0
    precision = float((y_true[mask] == 1).mean())
    coverage = float(mask.mean())
    return precision, coverage, int(mask.sum())


def _calibration_summary(y_true: np.ndarray, probs: np.ndarray) -> Dict[str, Any]:
    try:
        bs = float(brier_score_loss(y_true, probs))
    except Exception as e:  # noqa: BLE001
        logger.warning("Brier score computation failed: %s", e)
        return {"brier_score": None, "reliability": []}

    cuts = np.linspace(0, 1, 11)
    out = []
    for i in range(10):
        lo, hi = cuts[i], cuts[i + 1]
        m = (probs >= lo) & (probs < hi)
        if m.sum() == 0:
            out.append(
                {
                    "bin": f"[{lo:.1f},{hi:.1f})",
                    "count": 0,
                    "avg_prob": None,
                    "empirical": None,
                }
            )
        else:
            out.append(
                {
                    "bin": f"[{lo:.1f},{hi:.1f})",
                    "count": int(m.sum()),
                    "avg_prob": float(probs[m].mean()),
                    "empirical": float(y_true[m].mean()),
                }
            )
    return {"brier_score": bs, "reliability": out}


# ---------------------------------------------------------------------
# Feature Enricher (SetaFeatureEnricher)
# ---------------------------------------------------------------------
class SetaFeatureEnricher:
    """
    Adds technical indicators, volatility, sentiment, simple on-chain / orderbook
    proxies, and temporal features on top of raw crypto market data.
    This is used by the 5-model ensemble.
    """

    def __init__(self, twitter_api=None, etherscan_api_key: Optional[str] = None):
        self.sentiment_analyzer = SentimentIntensityAnalyzer()
        self.twitter_api = twitter_api
        self.etherscan_key = etherscan_api_key or os.getenv("ETHERSCAN_API_KEY")

    def enrich_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        df = df.copy()

        # Make sure numeric columns are numeric
        for col in [
            "current_price",
            "high_24h",
            "low_24h",
            "total_volume",
            "market_cap",
            "circulating_supply",
            "max_supply",
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.sort_values("timestamp").reset_index(drop=True)

        df = self._add_technical_indicators(df)
        df = self._add_volatility_features(df)
        df = self._add_lagged_features(df)
        df = self._add_normalized_ratios(df)
        df = self._add_sentiment_features(df)
        df = self._add_market_correlation(df)
        df = self._add_temporal_features(df)
        df = self._add_meta_labels(df)
        df = self._add_orderbook_imbalance(df)

        return df.fillna(0)

    # ---- Sub-components ------------------------------------------------

    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            if "current_price" not in df.columns:
                return df
            price = df["current_price"]

            df["sma_20"] = ta.sma(price, length=20)
            df["sma_50"] = ta.sma(price, length=50)
            df["ema_20"] = ta.ema(price, length=20)
            df["ema_50"] = ta.ema(price, length=50)
            df["rsi_14"] = ta.rsi(price, length=14)

            bb = ta.bbands(price, length=20)
            if isinstance(bb, pd.DataFrame):
                df["bb_upper"], df["bb_middle"], df["bb_lower"] = (
                    bb.iloc[:, 0],
                    bb.iloc[:, 1],
                    bb.iloc[:, 2],
                )
                df["bb_percent"] = (price - df["bb_lower"]) / (
                    df["bb_upper"] - df["bb_lower"] + 1e-8
                )

            if all(c in df.columns for c in ["high_24h", "low_24h"]):
                df["atr_14"] = ta.atr(
                    df["high_24h"],
                    df["low_24h"],
                    price,
                    length=14,
                )

            if "total_volume" in df.columns:
                df["vwap"] = (price * df["total_volume"]).cumsum() / (
                    df["total_volume"].cumsum() + 1e-8
                )
                df["obv"] = ta.obv(price, df["total_volume"])

            return df
        except Exception as e:  # noqa: BLE001
            logger.error("Error in _add_technical_indicators: %s", e)
            return df

    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "current_price" in df.columns:
            df["return_1"] = df["current_price"].pct_change(1)
            df["return_3"] = df["current_price"].pct_change(3)
            df["rolling_vol_7"] = df["return_1"].rolling(7).std()
            df["rolling_vol_14"] = df["return_1"].rolling(14).std()
        return df

    def _add_lagged_features(
        self,
        df: pd.DataFrame,
        lags=(1, 3, 5, 7),
        windows=(3, 7, 14),
    ) -> pd.DataFrame:
        for col in ["current_price", "total_volume"]:
            if col in df.columns:
                for lag in lags:
                    df[f"{col}_lag_{lag}"] = df[col].shift(lag)
                for w in windows:
                    df[f"{col}_roll_mean_{w}"] = df[col].rolling(window=w).mean()
                    df[f"{col}_roll_std_{w}"] = df[col].rolling(window=w).std()
        return df

    def _add_normalized_ratios(self, df: pd.DataFrame) -> pd.DataFrame:
        if "total_volume" in df.columns and "market_cap" in df.columns:
            df["vol_over_marketcap"] = df["total_volume"] / df["market_cap"].replace(
                {0: np.nan}
            )
        if "circulating_supply" in df.columns and "max_supply" in df.columns:
            df["supply_ratio"] = df["circulating_supply"] / df["max_supply"].replace(
                {0: np.nan}
            )
        return df

    @lru_cache(maxsize=100)
    def _get_reddit_sentiment(self, symbol: str, limit: int = 50) -> float:
        if REDDIT_SENTIMENT_SKIP or not CRYPTO_EXTERNAL_FEATURES:
            return 0.0
        if not symbol:
            return 0.0
        sym = str(symbol).strip().lower()
        if not sym or not sym.replace("-", "").replace("_", "").isalnum():
            return 0.0
        global _reddit_sentiment_calls
        if sym in _REDDIT_SENTIMENT_CACHE:
            return _REDDIT_SENTIMENT_CACHE[sym]
        if _reddit_sentiment_calls >= max(REDDIT_SENTIMENT_MAX_CALLS, 0):
            return 0.0
        _reddit_sentiment_calls += 1
        try:
            url = "https://api.pushshift.io/reddit/search/comment/"
            r = _sentiment_http.get(url, params={"q": sym, "size": limit}, timeout=REDDIT_SENTIMENT_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            comments = [c.get("body", "") for c in payload.get("data", []) if isinstance(c, dict)]
            if not comments:
                _REDDIT_SENTIMENT_CACHE[sym] = 0.0
                return 0.0
            scores = [
                self.sentiment_analyzer.polarity_scores(c)["compound"]
                for c in comments
            ]
            val = float(np.mean(scores)) if scores else 0.0
            _REDDIT_SENTIMENT_CACHE[sym] = val
            return val
        except requests.HTTPError as e:  # noqa: BLE001
            status = getattr(e.response, "status_code", None)
            if status == 403:
                logger.warning("Reddit sentiment blocked (403) for %s; skipping.", sym)
            else:
                logger.warning("Error fetching Reddit sentiment for %s: %s", sym, e)
            _REDDIT_SENTIMENT_CACHE[sym] = 0.0
            return 0.0
        except Exception as e:  # noqa: BLE001
            logger.warning("Error fetching Reddit sentiment for %s: %s", sym, e)
            _REDDIT_SENTIMENT_CACHE[sym] = 0.0
            return 0.0

    def _add_sentiment_features(self, df: pd.DataFrame) -> pd.DataFrame:
        # Safe handling when "news_headlines" is missing
        if "news_headlines" in df.columns:
            headlines = df["news_headlines"].fillna("").astype(str)
        else:
            headlines = pd.Series([""] * len(df), index=df.index)

        df["sentiment_score"] = headlines.apply(
            lambda t: self.sentiment_analyzer.polarity_scores(t)["compound"]
        )

        if not CRYPTO_EXTERNAL_FEATURES:
            df["reddit_sentiment"] = 0.0
            return df

        df["reddit_sentiment"] = df.apply(
            lambda r: self._get_reddit_sentiment(r.get("symbol")), axis=1
        )
        return df

    def _add_market_correlation(self, df: pd.DataFrame) -> pd.DataFrame:
        # Simplest version – you can later plug real BTC/ETH correlations
        df["btc_correlation"] = 0.5
        df["eth_correlation"] = 0.5
        df["market_correlation"] = (df["btc_correlation"] + df["eth_correlation"]) / 2
        return df

    def _add_temporal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df["hour"] = df["timestamp"].dt.hour
            df["day_of_week"] = df["timestamp"].dt.dayofweek
            df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
            df["month"] = df["timestamp"].dt.month
            df["quarter"] = df["timestamp"].dt.quarter
        return df

    def _add_meta_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        if "current_price" in df.columns and "price_direction" not in df.columns:
            df["price_direction"] = (
                df["current_price"].shift(-1) > df["current_price"]
            ).astype(int)
        return df

    def _add_orderbook_imbalance(self, df: pd.DataFrame) -> pd.DataFrame:
        if not CRYPTO_EXTERNAL_FEATURES:
            df["orderbook_imbalance"] = 0.0
            return df
        df["orderbook_imbalance"] = df.apply(
            lambda r: self.fetch_order_book_imbalance(r.get("symbol")), axis=1
        )
        return df

    @staticmethod
    def fetch_order_book_imbalance(symbol: Optional[str], depth: int = 20) -> float:
        if not CRYPTO_EXTERNAL_FEATURES:
            return 0.0
        if not symbol:
            return 0.0
        try:
            sym = symbol.upper().strip()
            pair = sym if sym.endswith("USDT") else f"{sym}USDT"
            if not pair.isalnum():
                return 0.0
            now = time.time()
            cached = _ORDERBOOK_CACHE.get(pair)
            if cached and now - cached[0] <= ORDERBOOK_CACHE_TTL:
                return float(cached[1])
            url = (
                "https://api.binance.com/api/v3/depth?"
                f"symbol={pair}&limit={depth}"
            )
            data = requests.get(url, timeout=5).json()
            bids = np.array([float(b[1]) for b in data.get("bids", [])])
            asks = np.array([float(a[1]) for a in data.get("asks", [])])
            if bids.size == 0 and asks.size == 0:
                return 0.0
            imbalance = (bids.sum() - asks.sum()) / (bids.sum() + asks.sum() + 1e-8)
            _ORDERBOOK_CACHE[pair] = (now, float(imbalance))
            return float(imbalance)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Error fetching order book imbalance for %s: %s",
                symbol,
                e,
            )
            return 0.0


# ---------------------------------------------------------------------
# HTTP helpers for live market data (CoinGecko + Binance)
# ---------------------------------------------------------------------
def _safe_get(url: str, timeout: float = 10.0, params: Optional[dict] = None):
    r = _http.get(url, timeout=timeout, params=params or {}, allow_redirects=False)
    r.raise_for_status()
    return r


def fetch_coingecko(symbol_id: str = "bitcoin") -> Dict[str, Any]:
    r = _safe_get(f"https://api.coingecko.com/api/v3/coins/{symbol_id}", timeout=CG_TIMEOUT)
    data = r.json().get("market_data", {})
    return {
        "price": data.get("current_price", {}).get("usd"),
        "high_24h": data.get("high_24h", {}).get("usd"),
        "low_24h": data.get("low_24h", {}).get("usd"),
        "volume": data.get("total_volume", {}).get("usd"),
        "change_24h": data.get("price_change_percentage_24h"),
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }


def fetch_binance(symbol_pair: str = "BTCUSDT") -> Dict[str, Any]:
    r = _safe_get(
        "https://api.binance.com/api/v3/ticker/24hr",
        params={"symbol": symbol_pair},
        timeout=BN_TIMEOUT,
    )
    data = r.json()
    return {
        "price": float(data.get("lastPrice", 0.0)),
        "high_24h": float(data.get("highPrice", 0.0)),
        "low_24h": float(data.get("lowPrice", 0.0)),
        "volume": float(data.get("volume", 0.0)),
        "change_24h": float(data.get("priceChangePercent", 0.0)),
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------
# Core: compute 5-model probabilities on a dataframe
# ---------------------------------------------------------------------
def _compute_ensemble_probs(
    df_enriched: pd.DataFrame,
    feature_columns: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Ejecuta el ensemble de 5 modelos sobre un dataframe enriquecido.
    Devuelve las probabilidades de cada modelo + la combinada.
    """
    meta_path = CALIBRATED_MODEL_PATH + ".meta.json"

    # 1) Elegir columnas de features
    if feature_columns is None:
        feature_columns = _choose_features(df_enriched, meta_path=meta_path)

    X = df_enriched.reindex(columns=feature_columns).fillna(0)
    n = len(X)

    # 2) Cargar modelos (usando caché en memoria si ya se cargaron antes)
    rf = _cached_models.get("rf") or load_model_safe(RF_MODEL_PATH)
    dl = _cached_models.get("dl") or load_model_safe(DL_MODEL_PATH)
    xgb = _cached_models.get("xgb") or load_model_safe(XGB_MODEL_PATH)
    cat = _cached_models.get("cat") or load_model_safe(CAT_MODEL_PATH)
    seta = _cached_models.get("calibrated") or load_model_safe(CALIBRATED_MODEL_PATH)

    _cached_models["rf"] = rf
    _cached_models["dl"] = dl
    _cached_models["xgb"] = xgb
    _cached_models["cat"] = cat
    _cached_models["calibrated"] = seta

    available_flags = np.array(
        [
            rf is not None,
            dl is not None,
            xgb is not None,
            cat is not None,
            seta is not None,
        ],
        dtype=bool,
    )

    # 🔹 Si NO hay ningún modelo cargado → devolvemos algo neutro en vez de explotar
    if not available_flags.any():
        logger.warning(
            "No crypto ML models found on disk; returning neutral probabilities."
        )
        zeros = np.zeros(n, dtype=float)
        combined = np.full(n, 0.5, dtype=float)

        return {
            "weights": [0.2, 0.2, 0.2, 0.2, 0.2],
            "feature_columns": feature_columns,
            "rf_probs": zeros,
            "dl_probs": zeros,
            "xgb_probs": zeros,
            "cat_probs": zeros,
            "seta_probs": zeros,
            "combined": combined,
        }

    def safe_probs(model):
        if model is None:
            return np.zeros(n)
        try:
            return model.predict_proba(X)[:, 1]
        except Exception as e:  # noqa: BLE001
            logger.warning("predict_proba failed for %s: %s", type(model), e)
            return np.zeros(n)

    rf_probs = safe_probs(rf)
    dl_probs = safe_probs(dl)
    xgb_probs = safe_probs(xgb)
    cat_probs = safe_probs(cat)
    seta_probs = safe_probs(seta)

    # 5) Calcular pesos
    if weights is None:
        # Equal-weight solo los modelos que existen
        k = int(available_flags.sum())
        weights = [1.0 / k if f else 0.0 for f in available_flags]
    else:
        # Validación de pesos personalizados
        if len(weights) != 5 or any((w < 0) or (w > 1) for w in weights):
            raise HTTPException(
                status_code=400,
                detail="weights must be 5 floats between 0 and 1",
            )
        w_arr = np.array(weights, dtype=float)
        # Poner a 0 los modelos que no existen
        w_arr[~available_flags] = 0.0
        tot = float(w_arr.sum())
        if tot == 0.0:
            # Si “apagaste” todos los modelos, volvemos a equal-weight sobre los que sí hay
            k = int(available_flags.sum())
            if k == 0:
                w_arr = np.zeros_like(w_arr)
            else:
                w_arr = np.array(
                    [1.0 / k if f else 0.0 for f in available_flags],
                    dtype=float,
                )
        else:
            w_arr = w_arr / tot
        weights = w_arr.tolist()

    combined = _ensemble_probs(
        weights,
        rf_probs,
        dl_probs,
        xgb_probs,
        cat_probs,
        seta_probs,
    )

    return {
        "weights": weights,
        "feature_columns": feature_columns,
        "rf_probs": rf_probs,
        "dl_probs": dl_probs,
        "xgb_probs": xgb_probs,
        "cat_probs": cat_probs,
        "seta_probs": seta_probs,
        "combined": combined,
    }


# ---------------------------------------------------------------------
# Endpoint 1: simple ensemble predictions on arbitrary payload
# ---------------------------------------------------------------------
@router.post("/crypto/predict-ensemble")
async def predict_ensemble(
    data: List[dict],
    weights: Optional[List[float]] = None,
):
    """
    Run the 5-model ensemble on arbitrary crypto data (e.g. top coins from CoinGecko).

    Body:
      [
        { "symbol": "btc", "current_price": ..., "total_volume": ..., "timestamp": ... },
        ...
      ]
    """
    try:
        df_raw = pd.DataFrame(data)
        if df_raw.empty:
            raise HTTPException(status_code=400, detail="Empty payload")

        enricher = SetaFeatureEnricher()
        df_enriched = enricher.enrich_features(df_raw)

        # If price_direction missing, synthesize from current_price for internal metrics
        df_enriched = ensure_price_direction(
            df_enriched,
            price_col="current_price",
            label_col="price_direction",
        )

        y = df_enriched["price_direction"].astype(int).values

        probs_info = _compute_ensemble_probs(df_enriched, weights=weights)
        combined = probs_info["combined"]

        results = []
        for i, (_, row) in enumerate(df_enriched.iterrows()):
            prob_up = float(combined[i])
            decision = "HOLD"
            if prob_up >= 0.7:
                decision = "BUY"
            elif prob_up <= 0.3:
                decision = "SELL"
            results.append(
                {
                    "symbol": row.get("symbol", f"asset_{i}"),
                    "current_price": float(row.get("current_price", 0.0) or 0.0),
                    "probability_up": prob_up,
                    "decision": decision,
                }
            )

        acc = float(((combined >= 0.5).astype(int) == y).mean())

        return {
            "status": "ok",
            "weights": probs_info["weights"],
            "overall_accuracy_at_0_5": acc,
            "predictions": results,
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("predict_ensemble error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------
# Endpoint 2: target-precision search + live signals
# ---------------------------------------------------------------------
@router.get("/crypto/target-precision-meta-live")
def target_precision_meta_live(
    csv_path: str = "data/crypto_data.csv",
    target_precision: float = 0.82,
    weight_step: float = 0.1,
    threshold_min: float = 0.55,
    threshold_max: float = 0.95,
    threshold_step: float = 0.02,
    symbols: str = Query(
        "bitcoin:BTCUSDT,ethereum:ETHUSDT,tether:USDT",
        description="Format: coingecko_id:binance_pair, multiple separated by comma",
    ),
):
    """
    Offline:
      - Load historical crypto_data.csv
      - Enrich & compute price_direction
      - Grid search over 5-model weights + threshold to hit target_precision

    Online:
      - Fetch live prices for given symbols
      - Apply chosen weights + threshold and return BUY/HOLD/SELL signals
    """
    try:
        if not os.path.exists(csv_path):
            raise HTTPException(status_code=404, detail="csv_path not found")

        df_raw = load_csv(csv_path)
        df_raw = ensure_price_direction(
            df_raw,
            price_col="current_price",
            label_col="price_direction",
        )

        enricher = SetaFeatureEnricher()
        df_enriched = enricher.enrich_features(df_raw)
        df_enriched = ensure_price_direction(
            df_enriched,
            price_col="current_price",
            label_col="price_direction",
        )

        y = df_enriched["price_direction"].astype(int).values

        probs_info = _compute_ensemble_probs(df_enriched, weights=None)
        rf_probs = probs_info["rf_probs"]
        dl_probs = probs_info["dl_probs"]
        xgb_probs = probs_info["xgb_probs"]
        cat_probs = probs_info["cat_probs"]
        seta_probs = probs_info["seta_probs"]

        vals = np.arange(0.0, 1.0 + 1e-9, weight_step)
        thresholds = np.arange(threshold_min, threshold_max + 1e-9, threshold_step)

        best_hit_target = None
        best_overall = None

        def eval_combo(
            w_rf: float,
            w_dl: float,
            w_xgb: float,
            w_cat: float,
            w_seta: float,
            thr: float,
        ):
            weights_local = (w_rf, w_dl, w_xgb, w_cat, w_seta)
            combined_local = _ensemble_probs(
                weights_local,
                rf_probs,
                dl_probs,
                xgb_probs,
                cat_probs,
                seta_probs,
            )
            prec, cov, cnt = _precision_and_coverage(y, combined_local, thr)
            if prec is None:
                return None
            return {
                "weights": [
                    float(w_rf),
                    float(w_dl),
                    float(w_xgb),
                    float(w_cat),
                    float(w_seta),
                ],
                "threshold": float(thr),
                "precision": float(prec),
                "coverage": float(cov),
                "samples": int(cnt),
            }

        for w_rf in vals:
            for w_dl in vals:
                for w_xgb in vals:
                    for w_cat in vals:
                        w_seta = 1.0 - w_rf - w_dl - w_xgb - w_cat
                        if w_seta < 0 or w_seta > 1:
                            continue
                        for thr in thresholds:
                            res = eval_combo(
                                w_rf,
                                w_dl,
                                w_xgb,
                                w_cat,
                                w_seta,
                                thr,
                            )
                            if not res:
                                continue
                            # best combo that hits target precision with max coverage
                            if res["precision"] >= target_precision:
                                if (
                                    not best_hit_target
                                    or res["coverage"] > best_hit_target["coverage"]
                                ):
                                    best_hit_target = res
                            # global best (closest precision to target)
                            if (not best_overall) or (
                                abs(res["precision"] - target_precision)
                                < abs(best_overall["precision"] - target_precision)
                            ):
                                best_overall = res

        chosen = best_hit_target or best_overall
        if not chosen:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No valid weight/threshold combos found. "
                    "Try relaxing target_precision or search grid."
                ),
            )

        chosen_weights = chosen["weights"]
        chosen_thr = chosen["threshold"]
        combined = _ensemble_probs(
            chosen_weights,
            rf_probs,
            dl_probs,
            xgb_probs,
            cat_probs,
            seta_probs,
        )

        overall_acc = float(((combined >= 0.5).astype(int) == y).mean())
        calib = _calibration_summary(y, combined)

        # --------- Live signals for given symbols ---------
        live_results: Dict[str, Any] = {}
        enricher_live = SetaFeatureEnricher()

        feature_columns = _choose_features(
            df_enriched,
            meta_path=CALIBRATED_MODEL_PATH + ".meta.json",
        )

        def predict_single(row_dict: Dict[str, Any]) -> float:
            df_row = pd.DataFrame([row_dict])
            df_en = enricher_live.enrich_features(df_row)
            X_row = df_en.reindex(columns=feature_columns).fillna(0)
            n_local = len(X_row)
            if n_local == 0:
                return 0.5

            rf_local = _cached_models.get("rf") or load_model_safe(RF_MODEL_PATH)
            dl_local = _cached_models.get("dl") or load_model_safe(DL_MODEL_PATH)
            xgb_local = _cached_models.get("xgb") or load_model_safe(XGB_MODEL_PATH)
            cat_local = _cached_models.get("cat") or load_model_safe(CAT_MODEL_PATH)
            seta_local = _cached_models.get("calibrated") or load_model_safe(
                CALIBRATED_MODEL_PATH
            )

            def safe_probs_local(model):
                if model is None:
                    return np.zeros(n_local)
                try:
                    return model.predict_proba(X_row)[:, 1]
                except Exception:  # noqa: BLE001
                    return np.zeros(n_local)

            rf_p = safe_probs_local(rf_local)
            dl_p = safe_probs_local(dl_local)
            xgb_p = safe_probs_local(xgb_local)
            cat_p = safe_probs_local(cat_local)
            seta_p = safe_probs_local(seta_local)

            prob = float(
                _ensemble_probs(
                    chosen_weights,
                    rf_p,
                    dl_p,
                    xgb_p,
                    cat_p,
                    seta_p,
                )[0]
            )
            return prob

        for spec in [s.strip() for s in symbols.split(",") if s.strip()]:
            try:
                cg_id, bin_symbol = spec.split(":")
            except ValueError:
                continue

            try:
                cg = fetch_coingecko(cg_id)
                bz = fetch_binance(bin_symbol)
            except Exception as e:  # noqa: BLE001
                logger.warning("Live fetch failed for %s: %s", spec, e)
                continue

            row_dict = {
                "symbol": cg_id,
                "current_price": cg.get("price") or bz.get("price"),
                "high_24h": cg.get("high_24h") or bz.get("high_24h"),
                "low_24h": cg.get("low_24h") or bz.get("low_24h"),
                "total_volume": cg.get("volume") or bz.get("volume"),
                "timestamp": cg.get("timestamp"),
            }

            prob_up = predict_single(row_dict)
            decision = (
                "BUY"
                if prob_up >= chosen_thr
                else "SELL"
                if prob_up <= (1 - chosen_thr)
                else "HOLD"
            )

            live_results[cg_id] = {
                "coingecko": {
                    "price": cg.get("price"),
                    "change_24h": cg.get("change_24h"),
                },
                "binance": {
                    "price": bz.get("price"),
                    "change_24h": bz.get("change_24h"),
                },
                "ensemble": {
                    "probability_up": prob_up,
                    "decision": decision,
                },
            }

        return {
            "status": "success",
            "chosen_combo": chosen,
            "ensemble_metrics": {
                "weights": chosen_weights,
                "threshold": chosen_thr,
                "overall_accuracy_at_0_5": overall_acc,
            },
            "calibration": calib,
            "live": live_results,
        }

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("target_precision_meta_live error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
