from __future__ import annotations

import pytest
import pandas as pd
from pydantic import ValidationError


def test_predict_prefers_trained_engine_when_available(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(crypto_api, "optimize_thresholds", lambda **_kwargs: None)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.87,
            "predicted_price": 203.5,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.symbol == "BTCUSDT"
    assert resp.decision == "BUY"
    assert resp.additional_info["engine"] == "trained"
    assert resp.additional_info["model_used"] == "ensemble"
    assert "trained-model prediction" in (resp.additional_info["note"] or "")
    assert (resp.raw or {}).get("trained_artifact") == "models/rf_model.joblib"


def test_predict_with_trained_models_uses_window_bundle_and_regime(monkeypatch):
    import app.api.crypto as crypto_api
    from app.models.ml.models import TrainedModel

    class _FakeModel:
        def __init__(self, prob: float):
            self.prob = prob

        def predict_proba(self, X):
            return [[1.0 - self.prob, self.prob] for _ in range(len(X))]

    class _FakeEnricher:
        def enrich_features(self, df):
            out = df.copy()
            out["rolling_vol_14"] = 0.01
            out["atr_14"] = 1.0
            out["market_regime"] = "bull_high_vol"
            return out

    class _FakeMeta:
        SetaFeatureEnricher = _FakeEnricher
        RF_MODEL_PATH = "rf"
        DL_MODEL_PATH = "dl"
        XGB_MODEL_PATH = "xgb"
        CAT_MODEL_PATH = "cat"
        CALIBRATED_MODEL_PATH = "cal"

        @staticmethod
        def ensure_price_direction(df, price_col="current_price", label_col="price_direction"):
            out = df.copy()
            out[label_col] = 1
            return out

        @staticmethod
        def load_model_safe(_path):
            return None

    monkeypatch.setattr(crypto_api, "_get_pandas", lambda: pd)
    monkeypatch.setattr(crypto_api, "_get_meta_module", lambda: _FakeMeta)
    monkeypatch.setattr(
        crypto_api,
        "resolve_trained_model",
        lambda *_a, **_k: TrainedModel(
            symbol="BTCUSDT",
            horizon_minutes=15,
            model_type="ensemble",
            artifact_path="artifacts/crypto_models/latest/rf_model.joblib",
            interval_minutes=1,
            dataset_hash="hash123",
            trained_at="2026-03-16T12:00:00+00:00",
            validation_mode="walk_forward",
        ),
    )
    monkeypatch.setattr(
        crypto_api,
        "_binance_ohlcv_window",
        lambda *_a, **_k: [
            crypto_api.OhlcvItem(ts=1000 + i * 60, open=100 + i, high=101 + i, low=99 + i, close=100 + i, volume=10 + i)
            for i in range(90)
        ],
    )
    monkeypatch.setattr(
        crypto_api,
        "_trained_bundle_for_model",
        lambda *_a, **_k: {
            "feature_columns": ["current_price", "total_volume"],
            "stacking_feature_names": ["rf", "xgb", "cat"],
            "rf": _FakeModel(0.71),
            "dl": _FakeModel(0.55),
            "xgb": _FakeModel(0.69),
            "cat": _FakeModel(0.67),
            "calibrated": _FakeModel(0.74),
            "meta": {},
        },
    )

    payload = crypto_api._predict_with_trained_models("BTCUSDT", 15, "ensemble", 190.0)

    assert payload is not None
    assert payload["decision"] == "BUY"
    assert payload["dataset_hash"] == "hash123"
    assert payload["validation_mode"] == "walk_forward"
    assert payload["regime"] == "bull_high_vol"
    assert payload["interval_minutes"] == 1


def test_predict_falls_back_to_demo_engine_when_trained_unavailable(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 120.0)
    monkeypatch.setattr(crypto_api, "_predict_with_trained_models", lambda *_a, **_k: None)
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="ETH", horizon_minutes=15, model="rf", save=False)
    resp = crypto_api.predict(req)

    assert resp.symbol == "ETHUSDT"
    assert resp.additional_info["engine"] == "demo"
    assert resp.additional_info["model_used"] == "rf"
    assert "demo fallback prediction" in (resp.additional_info["note"] or "")
    assert resp.additional_info["degraded"] is True


def test_predict_rejects_when_trained_engine_is_required(monkeypatch):
    import app.api.crypto as crypto_api
    from fastapi import HTTPException

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 120.0)
    monkeypatch.setattr(crypto_api, "_predict_with_trained_models", lambda *_a, **_k: None)
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="ETH", horizon_minutes=15, model="rf", save=False, require_trained=True)
    with pytest.raises(HTTPException) as excinfo:
        crypto_api.predict(req)

    assert excinfo.value.status_code == 503
    assert "demo fallback disabled" in str(excinfo.value.detail)


def test_predict_uses_scope_threshold_recommendation(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.85,
            "predicted_price": 203.5,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.9, "sell_threshold": 0.1, "trade_count": 12},
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.decision == "HOLD"
    assert resp.additional_info["buy_threshold"] == 0.9
    assert resp.additional_info["sell_threshold"] == 0.1
    assert (resp.raw or {}).get("threshold_strategy", {}).get("trade_count") == 12


def test_predict_reapplies_news_adjustment_with_scope_thresholds(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.85,
            "predicted_price": 203.5,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.95, "sell_threshold": 0.05, "trade_count": 12},
    )
    monkeypatch.setattr(
        crypto_api,
        "fetch_crypto_news",
        lambda *_a, **_k: {"provider": "stub", "items": [{"title": "bullish", "summary": "strong upside"}]},
    )
    monkeypatch.setattr(crypto_api, "_fetch_recent_news", lambda *_a, **_k: [])
    monkeypatch.setattr(crypto_api, "_sentiment_score", lambda *_a, **_k: 0.8)

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.decision == "HOLD"
    assert resp.additional_info["buy_threshold"] == 0.95
    assert resp.probability_up < 0.95


def test_predict_logs_threshold_fields(monkeypatch):
    import app.api.crypto as crypto_api

    captured = {}

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.87,
            "predicted_price": 203.5,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.9, "sell_threshold": 0.1, "trade_count": 12},
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})
    monkeypatch.setattr(
        crypto_api,
        "log_prediction",
        lambda entry: captured.setdefault("entry", dict(entry)) or "pred-1",
    )

    class _NoopTimer:
        def __init__(self, *_a, **_k):
            pass
        def start(self):
            return None

    monkeypatch.setattr(crypto_api.threading, "Timer", _NoopTimer)

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=True)
    crypto_api.predict(req)

    assert captured["entry"]["buy_threshold"] == 0.9
    assert captured["entry"]["sell_threshold"] == 0.1
    assert captured["entry"]["threshold_strategy"]["trade_count"] == 12


def test_predict_blocks_weak_scope_with_action_hold(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.88,
            "predicted_price": 204.0,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 12},
    )
    monkeypatch.setattr(
        crypto_api,
        "assess_scope_credibility",
        lambda **_kwargs: {
            "status": "blocked",
            "actionable": False,
            "should_abstain": True,
            "score": 0.41,
            "reasons": ["precision_below_threshold"],
            "trade_count": 12,
            "recommendation": {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 12},
        },
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.decision == "HOLD"
    assert resp.additional_info["model_decision"] == "BUY"
    assert resp.additional_info["action_decision"] == "HOLD"
    assert resp.additional_info["actionable"] is False
    assert resp.additional_info["credibility_status"] == "blocked"
    assert (resp.raw or {}).get("model_decision") == "BUY"
    assert (resp.raw or {}).get("action_decision") == "HOLD"
    assert resp.additional_info["execution_gate_reason"] == "credibility_abstain"


def test_predict_requires_margin_edge_for_cautious_scope(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.83,
            "predicted_price": 203.0,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 18},
    )
    monkeypatch.setattr(
        crypto_api,
        "assess_scope_credibility",
        lambda **_kwargs: {
            "status": "cautious",
            "actionable": True,
            "should_abstain": False,
            "score": 0.66,
            "reasons": ["thin_edge"],
            "trade_count": 18,
            "recommendation": {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 18},
        },
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.decision == "HOLD"
    assert resp.additional_info["model_decision"] == "BUY"
    assert resp.additional_info["action_decision"] == "HOLD"
    assert resp.additional_info["actionable"] is False
    assert resp.additional_info["execution_gate_reason"] == "edge_below_margin"
    assert resp.additional_info["execution_margin"] == pytest.approx(0.05)
    assert resp.additional_info["threshold_edge"] == pytest.approx(0.03)


def test_predict_keeps_strong_edge_for_cautious_scope(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.9,
            "predicted_price": 205.0,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.81, "dl": 0.8, "xgb": 0.79, "cat": 0.78, "seta": 0.82},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 18},
    )
    monkeypatch.setattr(
        crypto_api,
        "assess_scope_credibility",
        lambda **_kwargs: {
            "status": "cautious",
            "actionable": True,
            "should_abstain": False,
            "score": 0.66,
            "reasons": ["thin_edge"],
            "trade_count": 18,
            "recommendation": {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 18},
        },
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.decision == "BUY"
    assert resp.additional_info["action_decision"] == "BUY"
    assert resp.additional_info["execution_gate_reason"] is None
    assert resp.additional_info["execution_margin"] == pytest.approx(0.05)
    assert resp.additional_info["threshold_edge"] == pytest.approx(0.1)


def test_predict_blocks_low_consensus_support(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 200.0)
    monkeypatch.setattr(
        crypto_api,
        "_predict_with_trained_models",
        lambda *_a, **_k: {
            "model_used": "ensemble",
            "probability_up": 0.9,
            "predicted_price": 206.0,
            "decision": "BUY",
            "current_price": 200.0,
            "trained_model_type": "ensemble",
            "trained_artifact": "models/rf_model.joblib",
            "dataset_hash": "hash123",
            "trained_at": "2026-03-16T12:00:00+00:00",
            "validation_mode": "walk_forward",
            "interval_minutes": 5,
            "regime": "bull_high_vol",
            "per_model_probs": {"rf": 0.91, "dl": 0.88, "xgb": 0.52, "cat": 0.41, "seta": 0.36},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "optimize_thresholds",
        lambda **_kwargs: {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 22},
    )
    monkeypatch.setattr(
        crypto_api,
        "assess_scope_credibility",
        lambda **_kwargs: {
            "status": "cautious",
            "actionable": True,
            "should_abstain": False,
            "score": 0.72,
            "reasons": ["mixed_scope"],
            "trade_count": 22,
            "recommendation": {"buy_threshold": 0.8, "sell_threshold": 0.2, "trade_count": 22},
        },
    )
    monkeypatch.setattr(crypto_api, "fetch_crypto_news", lambda *_a, **_k: {"provider": "stub", "items": []})

    req = crypto_api.PredictRequest(symbol="BTC", horizon_minutes=15, model="ensemble", save=False)
    resp = crypto_api.predict(req)

    assert resp.decision == "HOLD"
    assert resp.additional_info["action_decision"] == "HOLD"
    assert resp.additional_info["actionable"] is False
    assert resp.additional_info["execution_gate_reason"] == "low_consensus_support"
    assert (resp.raw or {}).get("consensus", {}).get("supporters") == 3
    assert (resp.raw or {}).get("consensus", {}).get("total_models") == 5
    assert (resp.raw or {}).get("consensus", {}).get("support_ratio") == pytest.approx(0.6)


def test_recent_stats_separates_trained_and_demo_engines(tmp_path, monkeypatch):
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_outcome(
        {
            "log_id": "one",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "delta_pct": 0.02,
            "hit": True,
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "two",
            "symbol": "BTCUSDT",
            "model": "rf",
            "engine": "demo",
            "decision": "SELL",
            "delta_pct": -0.01,
            "hit": False,
        }
    )

    stats = pred_log.recent_stats(limit=10, symbol="BTCUSDT")

    assert stats["count"] == 2
    assert stats["trained_count"] == 1
    assert stats["demo_count"] == 1
    assert stats["trained_accuracy"] == 1.0
    assert stats["demo_accuracy"] == 0.0
    assert stats["per_engine"]["trained"]["count"] == 1
    assert stats["per_engine"]["demo"]["count"] == 1


def test_recent_stats_can_filter_single_engine(tmp_path, monkeypatch):
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_outcome(
        {
            "log_id": "one",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "delta_pct": 0.02,
            "hit": True,
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "two",
            "symbol": "BTCUSDT",
            "model": "rf",
            "engine": "demo",
            "decision": "SELL",
            "delta_pct": -0.01,
            "hit": False,
        }
    )

    stats = pred_log.recent_stats(limit=10, symbol="BTCUSDT", engine="trained")

    assert stats["engine_filter"] == "trained"
    assert stats["count"] == 1
    assert list(stats["per_engine"]) == ["trained"]
    assert stats["demo_count"] == 0
    assert stats["trained_accuracy"] == 1.0
    assert stats["round_trip_cost_bps"] == 30.0
    assert stats["trade_count"] == 1
    assert pytest.approx(stats["net_expectancy_pct"], rel=1e-6) == 0.017
    assert pytest.approx(stats["positive_net_rate"], rel=1e-6) == 1.0


def test_recent_stats_groups_symbol_horizon_and_regime(tmp_path, monkeypatch):
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_outcome(
        {
            "log_id": "one",
            "symbol": "BTCUSDT",
            "horizon_minutes": 15,
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "delta_pct": 0.03,
            "hit": True,
            "regime": "bull_high_vol",
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "two",
            "symbol": "ETHUSDT",
            "horizon_minutes": 60,
            "model": "ensemble",
            "engine": "trained",
            "decision": "SELL",
            "delta_pct": -0.02,
            "hit": True,
            "regime": "bear_low_vol",
        }
    )

    stats = pred_log.recent_stats(limit=10, engine="trained")

    assert stats["per_symbol"]["BTCUSDT"]["count"] == 1
    assert stats["per_symbol"]["ETHUSDT"]["trade_count"] == 1
    assert stats["per_horizon"]["15m"]["count"] == 1
    assert stats["per_horizon"]["60m"]["count"] == 1
    assert stats["per_regime"]["bull_high_vol"]["accuracy"] == 1.0
    assert stats["per_regime"]["bear_low_vol"]["positive_net_rate"] == 1.0


def test_recent_stats_prefers_action_decision_over_model_decision(tmp_path, monkeypatch):
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_outcome(
        {
            "log_id": "one",
            "symbol": "BTCUSDT",
            "horizon_minutes": 15,
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "model_decision": "BUY",
            "action_decision": "HOLD",
            "delta_pct": -0.03,
            "hit": True,
            "regime": "bull_high_vol",
        }
    )

    stats = pred_log.recent_stats(limit=10, engine="trained")

    assert stats["trade_count"] == 0
    assert stats["hold_count"] == 1
    assert stats["net_expectancy_pct"] is None


def test_crypto_prediction_stats_export_and_filters(tmp_path, monkeypatch):
    import app.api.crypto as crypto_api
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_prediction(
        {
            "id": "one",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "probability_up": 0.81,
        }
    )
    pred_log.log_prediction(
        {
            "id": "two",
            "symbol": "BTCUSDT",
            "model": "rf",
            "engine": "demo",
            "decision": "SELL",
            "probability_up": 0.23,
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "one",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "delta_pct": 0.02,
            "hit": True,
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "two",
            "symbol": "BTCUSDT",
            "model": "rf",
            "engine": "demo",
            "decision": "SELL",
            "delta_pct": -0.01,
            "hit": False,
        }
    )

    predictions = crypto_api.recent_predictions(limit=10, symbol="BTCUSDT", engine="trained")
    stats = crypto_api.prediction_stats(limit=10, symbol="BTCUSDT", engine="trained")
    csv_resp = crypto_api.export_prediction_stats(limit=10, symbol="BTCUSDT", engine="trained", format="csv")
    json_resp = crypto_api.export_prediction_stats(limit=10, symbol="BTCUSDT", engine="trained", format="json")
    md_resp = crypto_api.export_prediction_stats(limit=10, symbol="BTCUSDT", engine="trained", format="md")

    assert len(predictions) == 1
    assert predictions[0]["engine"] == "trained"
    assert stats["engine_filter"] == "trained"
    assert stats["count"] == 1
    assert stats["trained_count"] == 1
    assert stats["demo_count"] == 0
    assert pytest.approx(stats["net_expectancy_pct"], rel=1e-6) == 0.017
    assert csv_resp.media_type == "text/csv"
    csv_body = csv_resp.body.decode("utf-8")
    assert "section,name,count,accuracy,avg_delta_pct,net_expectancy_pct,positive_net_rate,max_drawdown_pct" in csv_body
    assert "engine,trained,1,1.0,0.02,0.017,1.0,0.0" in csv_body
    assert json_resp.media_type == "application/json"
    json_body = json_resp.body.decode("utf-8")
    assert "\"engine\": \"trained\"" in json_body
    assert "\"net_expectancy_pct\": 0.017" in json_body
    assert md_resp.media_type == "text/markdown"
    md_body = md_resp.body.decode("utf-8")
    assert "# AEGIS Crypto Evaluation Report" in md_body
    assert "Engine scope: `trained`" in md_body
    assert "Net expectancy: `1.70%`" in md_body


def test_crypto_prediction_stats_can_filter_horizon_and_regime(tmp_path, monkeypatch):
    import app.api.crypto as crypto_api
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_prediction(
        {
            "id": "one",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "probability_up": 0.81,
            "horizon_minutes": 15,
            "regime": "bull_high_vol",
        }
    )
    pred_log.log_prediction(
        {
            "id": "two",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "probability_up": 0.61,
            "horizon_minutes": 60,
            "regime": "sideways_mid_vol",
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "one",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "delta_pct": 0.02,
            "hit": True,
            "horizon_minutes": 15,
            "regime": "bull_high_vol",
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "two",
            "symbol": "BTCUSDT",
            "model": "ensemble",
            "engine": "trained",
            "decision": "BUY",
            "delta_pct": -0.01,
            "hit": False,
            "horizon_minutes": 60,
            "regime": "sideways_mid_vol",
        }
    )

    stats = crypto_api.prediction_stats(limit=10, symbol="BTCUSDT", engine="trained", horizon_minutes=15, regime="bull_high_vol")
    rows = crypto_api.recent_predictions(limit=10, symbol="BTCUSDT", engine="trained", horizon_minutes=15, regime="bull_high_vol")

    assert stats["count"] == 1
    assert stats["horizon_filter"] == 15
    assert stats["regime_filter"] == "bull_high_vol"
    assert len(rows) == 1
    assert rows[0]["horizon_minutes"] == 15
    assert rows[0]["regime"] == "bull_high_vol"


def test_crypto_prediction_stats_reject_invalid_engine():
    import app.api.crypto as crypto_api
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        crypto_api.prediction_stats(limit=10, symbol="BTCUSDT", engine="bad-engine")

    assert excinfo.value.status_code == 400
    assert "engine must be one of" in str(excinfo.value.detail)


def test_crypto_thresholds_and_leaderboard_endpoints(tmp_path, monkeypatch):
    import app.api.crypto as crypto_api
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    for idx in range(12):
        pred_log.log_outcome(
            {
                "log_id": f"btc-{idx}",
                "symbol": "BTCUSDT",
                "model": "ensemble",
                "engine": "trained",
                "decision": "BUY",
                "probability_up": 0.82 if idx < 10 else 0.61,
                "delta_pct": 0.018 if idx < 10 else -0.01,
                "hit": idx < 10,
                "horizon_minutes": 15,
                "regime": "bull_high_vol",
                "ts": 1_700_000_000 + idx,
            }
        )
    for idx in range(12):
        pred_log.log_outcome(
            {
                "log_id": f"eth-{idx}",
                "symbol": "ETHUSDT",
                "model": "ensemble",
                "engine": "trained",
                "decision": "SELL",
                "probability_up": 0.18 if idx < 7 else 0.44,
                "delta_pct": -0.012 if idx < 7 else 0.006,
                "hit": idx < 7,
                "horizon_minutes": 60,
                "regime": "bear_low_vol",
                "ts": 1_700_000_100 + idx,
            }
        )

    thresholds = crypto_api.prediction_thresholds(
        limit=100,
        symbol="BTCUSDT",
        engine="trained",
        horizon_minutes=15,
        regime="bull_high_vol",
        min_trades=5,
    )
    leaderboard = crypto_api.prediction_leaderboard(limit=100, engine="trained", min_trades=5, top_n=5)

    assert thresholds["scope"]["symbol"] == "BTCUSDT"
    assert thresholds["recommendation"]["trade_count"] >= 5
    assert 0.55 <= thresholds["recommendation"]["buy_threshold"] <= 0.95
    assert thresholds["recommendation"]["sell_threshold"] < thresholds["recommendation"]["buy_threshold"]
    assert leaderboard[0]["symbol"] == "BTCUSDT"
    assert leaderboard[0]["regime"] == "bull_high_vol"
    assert leaderboard[0]["trade_count"] >= 5


def test_crypto_credibility_endpoint(tmp_path, monkeypatch):
    import app.api.crypto as crypto_api
    from app.services import crypto_prediction_log as pred_log

    log_dir = tmp_path / "pred_logs"
    monkeypatch.setattr(pred_log, "LOG_DIR", log_dir)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    for idx in range(12):
        pred_log.log_outcome(
            {
                "log_id": f"btc-{idx}",
                "symbol": "BTCUSDT",
                "model": "ensemble",
                "engine": "trained",
                "decision": "BUY",
                "action_decision": "BUY",
                "probability_up": 0.84 if idx < 9 else 0.61,
                "delta_pct": 0.018 if idx < 9 else -0.01,
                "hit": idx < 9,
                "horizon_minutes": 15,
                "regime": "bull_high_vol",
                "ts": 1_700_000_000 + idx,
            }
        )

    payload = crypto_api.prediction_credibility(
        symbol="BTCUSDT",
        engine="trained",
        horizon_minutes=15,
        regime="bull_high_vol",
    )

    assert payload["scope"]["symbol"] == "BTCUSDT"
    assert payload["assessment"]["trade_count"] >= 8
    assert payload["assessment"]["status"] in {"trusted", "cautious", "blocked"}


def test_predict_request_validates_horizon_bounds():
    import app.api.crypto as crypto_api

    with pytest.raises(ValidationError):
        crypto_api.PredictRequest(symbol="BTC", horizon_minutes=0)
