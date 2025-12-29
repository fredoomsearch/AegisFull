from __future__ import annotations

"""
Servicio de predicción de criptomonedas para AEGIS.

Responsabilidades:
- Normalizar símbolos (BTC / ETH / etc.).
- Consultar precio spot actual (Binance).
- Ejecutar la lógica meta (ensemble 5-model) para prob. de subida.
- Mantener compatibilidad con el ensemble clásico (RF + DL + calibrado).
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple

import pandas as pd
import requests

import app.core.meta as meta_module  # type: ignore[import]
import app.services.crypto_service_legacy as legacy  # type: ignore[import]  # noqa: F401
from app.models.ml.ensemble import predict_with_ensemble
from app.schemas import CryptoModelType, CryptoPrediction, CryptoPredictionRequest, TopCoin

logger = logging.getLogger(__name__)

BUY_THRESHOLD = 0.7
SELL_THRESHOLD = 0.3

KNOWN_BASE_SYMBOLS: set[str] = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "TON",
    "LINK", "TRX", "MATIC", "LTC", "DOT", "UNI", "BCH", "XLM", "ETC", "FIL",
}
STABLECOINS: set[str] = {"USDT", "USDC", "DAI", "BUSD", "TUSD"}


class CryptoService:
    """
    Capa de servicio que expone una API única para predicciones de cripto.
    """
    BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
    PRICE_CACHE_TTL_SECONDS = 8

    def __init__(self) -> None:
        logger.info(
            "[CryptoService] Inicializado (meta 5-model ensemble como backend principal; "
            "ensemble clásico disponible como fallback)."
        )
        self._price_cache: Dict[str, Tuple[float, float]] = {}

    # -------------------------------------------------------------
    # Normalización / parsing de símbolo
    # -------------------------------------------------------------
    def _extract_base_symbol(self, raw: str) -> str:
        text = (raw or "").upper().strip()
        candidate: Optional[str] = None

        if text.endswith("USDT") and " " not in text and len(text) > 4:
            candidate = text[:-4]
        else:
            tokens = [t for t in text.replace(",", " ").split() if t]
            for tok in tokens:
                if tok in KNOWN_BASE_SYMBOLS:
                    candidate = tok
                    break
                if tok.endswith("USDT") and tok[:-4] in KNOWN_BASE_SYMBOLS:
                    candidate = tok[:-4]
                    break
            if candidate is None and len(tokens) == 1 and tokens[0].isalpha() and 1 <= len(tokens[0]) <= 5:
                candidate = tokens[0]

        if not candidate:
            raise ValueError(f"No pude extraer un símbolo cripto válido desde: {raw!r}")
        if candidate in STABLECOINS:
            raise ValueError(
                f"No tiene sentido predecir la stablecoin {candidate}. "
                "Prueba con BTC, ETH, SOL, etc."
            )
        return candidate

    # -------------------------------------------------------------
    # API principal
    # -------------------------------------------------------------
    def predict(self, request: CryptoPredictionRequest) -> CryptoPrediction:
        model_type: CryptoModelType = request.model or CryptoModelType.ensemble
        if model_type == CryptoModelType.rf:
            return self._predict_with_rf(request)
        if model_type == CryptoModelType.deep:
            return self._predict_with_deep(request)
        if model_type == CryptoModelType.ensemble:
            return self._predict_with_ensemble(request)
        if model_type == CryptoModelType.model_4:
            return self._predict_with_model_4(request)
        if model_type == CryptoModelType.model_5:
            return self._predict_with_model_5(request)
        raise ValueError(f"Modelo de cripto no soportado: {model_type}")

    # =============================================================
    # Helpers internos de mercado (live / meta)
    # =============================================================
    def _build_live_enriched_row(self, symbol_pair: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        bz = meta_module.fetch_binance(symbol_pair)
        row_dict = {
            "symbol": symbol_pair,
            "current_price": bz.get("price"),
            "high_24h": bz.get("high_24h"),
            "low_24h": bz.get("low_24h"),
            "total_volume": bz.get("volume"),
            "timestamp": bz.get("timestamp"),
        }
        df_raw = pd.DataFrame([row_dict])

        enricher = meta_module.SetaFeatureEnricher()
        if hasattr(enricher, "enrich_features"):
            df_enriched = enricher.enrich_features(df_raw)  # type: ignore[attr-defined]
        elif hasattr(enricher, "enrich"):
            df_enriched = enricher.enrich(df_raw)  # type: ignore[attr-defined]
        elif hasattr(enricher, "transform"):
            df_enriched = enricher.transform(df_raw)  # type: ignore[attr-defined]
        else:
            logger.warning("SetaFeatureEnricher sin método conocido; usando df_raw sin enriquecer.")
            df_enriched = df_raw

        return df_enriched, {"binance": bz}

    @staticmethod
    def _weights_for_model_type(model_type: CryptoModelType) -> Optional[Sequence[float]]:
        if model_type == CryptoModelType.rf:
            return [1.0, 0.0, 0.0, 0.0, 0.0]
        if model_type == CryptoModelType.deep:
            return [0.0, 1.0, 0.0, 0.0, 0.0]
        if model_type == CryptoModelType.model_4:
            return [0.0, 0.0, 1.0, 0.0, 0.0]
        if model_type == CryptoModelType.model_5:
            return [0.0, 0.0, 0.0, 0.0, 1.0]
        return None

    def _compute_probs_for_model_type(self, df_enriched: pd.DataFrame, model_type: CryptoModelType) -> Dict[str, Any]:
        weights = self._weights_for_model_type(model_type)
        return meta_module._compute_ensemble_probs(df_enriched, weights=weights)

    def _run_live_inference(
        self,
        symbol_pair: str,
        model_type: CryptoModelType,
    ) -> Tuple[float, float, str, Dict[str, Any]]:
        try:
            df_enriched, raw_market = self._build_live_enriched_row(symbol_pair)
            probs_info = self._compute_probs_for_model_type(df_enriched, model_type)

            combined = probs_info.get("combined") or []
            prob_up = float(combined[0]) if combined else 0.5

            if prob_up >= BUY_THRESHOLD:
                decision = "BUY"
            elif prob_up <= SELL_THRESHOLD:
                decision = "SELL"
            else:
                decision = "HOLD"

            current_price = float(raw_market["binance"].get("price") or 0.0)

            rf_p = float((probs_info.get("rf_probs") or [0.0])[0])
            dl_p = float((probs_info.get("dl_probs") or [0.0])[0])
            xgb_p = float((probs_info.get("xgb_probs") or [0.0])[0])
            cat_p = float((probs_info.get("cat_probs") or [0.0])[0])
            seta_p = float((probs_info.get("seta_probs") or [0.0])[0])

            raw: Dict[str, Any] = {
                "backend": "meta_5model",
                "weights": probs_info.get("weights"),
                "per_model_probs": {
                    "rf": rf_p,
                    "dl": dl_p,
                    "xgb": xgb_p,
                    "cat": cat_p,
                    "seta": seta_p,
                },
                "binance": raw_market["binance"],
            }
            return prob_up, current_price, decision, raw
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "CryptoService live inference failed for %s (model=%s): %s",
                symbol_pair,
                model_type,
                exc,
            )
            return 0.5, 0.0, "HOLD", {"error": str(exc)}

    def _build_prediction(self, request: CryptoPredictionRequest, model_type: CryptoModelType) -> CryptoPrediction:
        try:
            base_symbol = self._extract_base_symbol(request.symbol)
        except ValueError as exc:
            logger.warning("Símbolo cripto inválido recibido: %s", exc)
            raise

        symbol_pair = f"{base_symbol}USDT"
        prob_up, current_price, decision, raw = self._run_live_inference(symbol_pair, model_type)

        if "error" in raw:
            logger.warning(
                "Falling back to legacy ensemble for %s (model=%s): %s",
                request.symbol,
                model_type,
                raw.get("error"),
            )
            legacy_weights = self._weights_for_model_type(model_type)
            return self._predict_generic(request, model_type, legacy_weights)

        return CryptoPrediction(
            symbol=base_symbol,
            horizon_minutes=request.horizon_minutes,
            model=model_type,
            predicted_price=current_price,
            probability_up=prob_up,
            decision=decision,
            raw=raw,
        )

    # -------------------------------------------------------------
    # Implementaciones por modelo (live/meta)
    # -------------------------------------------------------------
    def _predict_with_rf(self, request: CryptoPredictionRequest) -> CryptoPrediction:
        return self._build_prediction(request, CryptoModelType.rf)

    def _predict_with_deep(self, request: CryptoPredictionRequest) -> CryptoPrediction:
        return self._build_prediction(request, CryptoModelType.deep)

    def _predict_with_ensemble(self, request: CryptoPredictionRequest) -> CryptoPrediction:
        return self._build_prediction(request, CryptoModelType.ensemble)

    def _predict_with_model_4(self, request: CryptoPredictionRequest) -> CryptoPrediction:
        return self._build_prediction(request, CryptoModelType.model_4)

    def _predict_with_model_5(self, request: CryptoPredictionRequest) -> CryptoPrediction:
        return self._build_prediction(request, CryptoModelType.model_5)

    # =============================================================
    # Helpers internos (legacy ensemble v1)
    # =============================================================
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        s = symbol.upper().strip()
        return s[:-4] if s.endswith("USDT") else s

    def _fetch_current_price(self, base_symbol: str) -> float:
        pair = f"{base_symbol}USDT"
        now = time.time()
        cached = self._price_cache.get(pair)
        if cached:
            price_cached, ts = cached
            if now - ts <= self.PRICE_CACHE_TTL_SECONDS:
                return price_cached

        try:
            resp = requests.get(self.BINANCE_TICKER_URL, params={"symbol": pair}, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            price_str = data.get("lastPrice") or data.get("weightedAvgPrice") or "0"
            price = float(price_str)
            self._price_cache[pair] = (price, now)
            return price
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch Binance price for %sUSDT: %s", base_symbol, exc)
            return 0.0

    def _predict_generic(
        self,
        request: CryptoPredictionRequest,
        model_type: CryptoModelType,
        weights: Optional[Sequence[float]],
    ) -> CryptoPrediction:
        base_symbol = self._normalize_symbol(request.symbol)
        current_price = self._fetch_current_price(base_symbol)

        row = {"symbol": base_symbol, "current_price": current_price, "timestamp": datetime.utcnow()}
        raw_result = predict_with_ensemble([row], buy_thresh=BUY_THRESHOLD, sell_thresh=SELL_THRESHOLD, weights=weights)

        preds = raw_result.get("predictions") or []
        if not preds:
            logger.warning("Ensemble returned no predictions; using neutral fallback.")
            return CryptoPrediction(
                symbol=request.symbol,
                horizon_minutes=request.horizon_minutes,
                model=model_type,
                predicted_price=current_price,
                probability_up=0.5,
                confidence=None,
                decision="HOLD",
                raw={
                    "backend": "ml_ensemble_v1",
                    "weights": raw_result.get("weights"),
                    "per_model_probs": raw_result.get("per_model_probs") or {},
                    "base_symbol": base_symbol,
                    "warning": "No predictions returned by ensemble",
                },
                additional_info={
                    "backend": "ml_ensemble_v1",
                    "warning": "No predictions returned by ensemble",
                    "weights": raw_result.get("weights"),
                },
            )

        pred0 = preds[0]
        prob_up = float(pred0.get("probability_up", 0.5))
        decision = pred0.get("decision", "HOLD")
        per_model_probs = raw_result.get("per_model_probs") or {}

        return CryptoPrediction(
            symbol=request.symbol,
            horizon_minutes=request.horizon_minutes,
            model=model_type,
            predicted_price=float(pred0.get("current_price", current_price)),
            probability_up=prob_up,
            decision=decision,
            raw={
                "backend": "ml_ensemble_v1",
                "weights": raw_result.get("weights"),
                "per_model_probs": per_model_probs,
                "base_symbol": base_symbol,
            },
            confidence=prob_up,
            additional_info={
                "decision": decision,
                "backend": "ml_ensemble_v1",
                "weights": raw_result.get("weights"),
                "per_model_probs": per_model_probs,
                "base_symbol": base_symbol,
            },
        )

    def fetch_top_coins(self, per_page: int = 30) -> list[TopCoin]:
        """
        Fetch top coins by market cap desde CoinGecko y mapear a TopCoin.
        """
        per_page = max(1, min(per_page, 250))
        url = (
            "https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=market_cap_desc&sparkline=false"
        )
        try:
            resp = requests.get(url, params={"per_page": per_page, "page": 1}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error fetching top coins from CoinGecko: %s", exc)
            return []

        coins: list[TopCoin] = []
        for item in data:
            coins.append(
                TopCoin(
                    symbol=(item.get("symbol") or "").upper(),
                    name=item.get("name") or "",
                    current_price=float(item.get("current_price") or 0.0),
                    market_cap=float(item.get("market_cap") or 0.0) if item.get("market_cap") is not None else None,
                    price_change_24h=float(item.get("price_change_percentage_24h") or 0.0)
                    if item.get("price_change_percentage_24h") is not None
                    else None,
                    image=item.get("image"),
                )
            )
        return coins
