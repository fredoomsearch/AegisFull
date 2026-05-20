from __future__ import annotations

import asyncio

import pytest


def test_build_crypto_state_snapshot_unifies_predictions_trades_and_execution(tmp_path, monkeypatch):
    from app.services import crypto_prediction_log as pred_log
    from app.services import crypto_trade_log as trade_log
    from app.services import crypto_runtime

    log_dir = tmp_path / "crypto"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    monkeypatch.setattr(trade_log, "TRADE_FILE", log_dir / "trades.jsonl")
    pred_log.clear_predictions_and_outcomes()
    trade_log.clear_trades()

    pred_log.log_prediction(
        {
            "id": "pred_1",
            "symbol": "BTCUSDT",
            "horizon_minutes": 15,
            "decision": "BUY",
            "action_decision": "BUY",
            "current_price": 100.0,
            "predicted_price": 105.0,
            "probability_up": 0.72,
            "engine": "trained",
            "ts": 1000,
        }
    )
    pred_log.log_outcome(
        {
            "log_id": "pred_1",
            "symbol": "BTCUSDT",
            "horizon_minutes": 15,
            "decision": "BUY",
            "action_decision": "BUY",
            "probability_up": 0.72,
            "actual_price": 108.0,
            "delta_pct": 0.08,
            "hit": True,
            "engine": "trained",
            "ts": 2000,
        }
    )
    trade_log.log_trade(
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.1,
            "price": 100.0,
            "status": "SIMULATED",
            "execution_mode": "testnet",
            "test": True,
            "ts": 3000,
        }
    )

    snapshot = crypto_runtime.build_crypto_state_snapshot(
        symbol="BTCUSDT",
        horizon_minutes=15,
        price_lookup=lambda _sym: 111.0,
        order_book_lookup=lambda _sym: {
            "source": "binance",
            "best_bid": 99.5,
            "best_ask": 100.5,
            "mid_price": 100.0,
            "spread_bps": 100.0,
            "imbalance": 0.55,
            "bid_notional": 500.0,
            "ask_notional": 400.0,
            "liquidity_bucket": "micro",
            "bids": [{"price": 99.5, "qty": 1.0, "notional": 99.5}],
            "asks": [{"price": 100.5, "qty": 1.0, "notional": 100.5}],
        },
        execution_snapshot={"mode": "testnet", "live_enabled": False},
    )

    assert snapshot["scope"]["symbol"] == "BTCUSDT"
    assert snapshot["summary"]["predictions_count"] == 1
    assert snapshot["summary"]["outcomes_count"] == 1
    assert snapshot["summary"]["trades_count"] == 1
    assert snapshot["execution"]["mode"] == "testnet"
    assert snapshot["current_price"] == 111.0
    assert snapshot["latest_prediction_ref"]["log_id"] == "pred_1"
    assert snapshot["latest_outcome_ref"]["log_id"] == "pred_1"
    assert snapshot["latest_outcome_ref"]["gross_return_pct"] == pytest.approx(0.08)
    assert snapshot["latest_outcome_ref"]["net_return_pct"] == pytest.approx(0.077)
    assert snapshot["latest_outcome_ref"]["round_trip_cost_pct"] == pytest.approx(0.003)
    assert snapshot["latest_outcome_ref"]["probability_error"] == pytest.approx(0.28)
    assert snapshot["latest_outcome_ref"]["brier_component"] == pytest.approx(0.0784)
    assert snapshot["latest_outcome_ref"]["confidence_bucket"] == "medium"
    assert snapshot["latest_outcome_ref"]["realized_direction"] == "up"
    assert snapshot["summary"]["has_order_book"] is True
    assert snapshot["order_book"]["best_bid"] == 99.5
    assert snapshot["risk"]["tradeable"] is True
    assert snapshot["risk"]["decision"] == "BUY"
    assert snapshot["risk"]["entry_price"] == 100.0
    assert snapshot["risk"]["target_price"] == 105.0
    assert snapshot["risk"]["stop_price"] is not None
    assert snapshot["summary"]["has_risk"] is True


def test_reconcile_due_predictions_logs_outcome_once(tmp_path, monkeypatch):
    from app.services import crypto_prediction_log as pred_log
    from app.services import crypto_runtime

    log_dir = tmp_path / "crypto"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pred_log, "LOG_FILE", log_dir / "predictions.jsonl")
    monkeypatch.setattr(pred_log, "OUTCOME_FILE", log_dir / "prediction_outcomes.jsonl")
    pred_log.clear_predictions_and_outcomes()

    pred_log.log_prediction(
        {
            "id": "pred_due",
            "symbol": "BTCUSDT",
            "horizon_minutes": 1,
            "decision": "BUY",
            "action_decision": "BUY",
            "current_price": 100.0,
            "predicted_price": 102.0,
            "probability_up": 0.7,
            "engine": "trained",
            "ts": 100,
        }
    )

    first = crypto_runtime.reconcile_due_predictions(price_lookup=lambda _sym: 110.0, limit=10, now_ts=220)
    second = crypto_runtime.reconcile_due_predictions(price_lookup=lambda _sym: 111.0, limit=10, now_ts=280)
    outcomes = pred_log.list_outcomes(limit=10, symbol="BTCUSDT")

    assert first["evaluated"] == 1
    assert first["missing_price"] == 0
    assert second["evaluated"] == 0
    assert len(outcomes) == 1
    assert outcomes[0]["log_id"] == "pred_due"
    assert outcomes[0]["actual_price"] == 110.0
    assert outcomes[0]["trade_evaluable"] is True
    assert outcomes[0]["gross_return_pct"] == pytest.approx(0.1)
    assert outcomes[0]["round_trip_cost_pct"] == pytest.approx(0.003)
    assert outcomes[0]["net_return_pct"] == pytest.approx(0.097)
    assert outcomes[0]["realized_direction"] == "up"
    assert outcomes[0]["realized_up"] is True
    assert outcomes[0]["confidence_bucket"] == "medium"
    assert outcomes[0]["probability_error"] == pytest.approx(0.3)
    assert outcomes[0]["brier_component"] == pytest.approx(0.09)


@pytest.mark.anyio
async def test_crypto_state_stream_emits_snapshot(monkeypatch):
    from app.api import crypto as crypto_api

    calls = {"count": 0}

    def fake_snapshot(**_kwargs):
        calls["count"] += 1
        return {
            "scope": {
                "symbol": "BTCUSDT",
                "engine": "all",
                "horizon_minutes": 15,
                "regime": None,
            },
            "summary": {
                "predictions_count": 1,
                "outcomes_count": 1,
                "trades_count": 1,
                "has_order_book": True,
                "has_price": True,
                "has_prediction": True,
                "has_outcome": True,
                "has_risk": True,
            },
            "current_price": 100.0,
            "execution": {
                "mode": "simulated",
                "requested_mode": "simulated",
                "credentials_present": False,
                "live_trading_enabled": False,
                "testnet_enabled": False,
                "live_enabled": False,
                "simulated": True,
            },
            "latest_prediction": {"id": "pred_1"},
            "latest_prediction_ref": {
                "log_id": "pred_1",
                "symbol": "BTCUSDT",
                "horizon_minutes": 15,
                "ts": 1,
                "source": "history",
                "decision": "BUY",
                "model": "demo",
            },
            "latest_outcome": {"log_id": "pred_1"},
            "latest_outcome_ref": {
                "log_id": "pred_1",
                "symbol": "BTCUSDT",
                "horizon_minutes": 15,
                "ts": 2,
                "source": "history",
                "decision": "BUY",
            },
            "latest_trade": {"id": "trade_1"},
            "latest_trade_ref": {
                "id": "trade_1",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.1,
                "ts": 3,
            },
            "order_book": {
                "best_bid": 99.5,
                "best_ask": 100.5,
                "spread_bps": 100.0,
                "imbalance": 0.55,
                "bid_notional": 500.0,
                "ask_notional": 400.0,
                "liquidity_bucket": "micro",
            },
            "risk": {
                "decision": "BUY",
                "entry_price": 100.0,
                "target_price": 105.0,
                "stop_price": 98.0,
                "risk_reward": 2.5,
                "order_size_pct": 5.0,
                "book_consumption_pct": 10.0,
                "impact_score": 12.0,
                "remaining_liquidity": 350.0,
            },
            "predictions": [],
            "outcomes": [],
            "stats": [],
            "thresholds": {},
            "credibility": {},
            "leaderboard": [],
            "trades": [],
            "pnl": {},
            "generated_at": "2026-04-02T12:00:00Z",
        }

    monkeypatch.setattr(crypto_api, "_crypto_state_snapshot_payload", fake_snapshot)

    class FakeRequest:
        async def is_disconnected(self):
            return False

    response = await crypto_api.crypto_state_stream(
        request=FakeRequest(),
        symbol="BTCUSDT",
        engine="all",
        horizon_minutes=15,
        regime=None,
        execution_mode="simulated",
        limit=20,
        trade_limit=100,
        leaderboard_limit=10,
        interval_seconds=1.0,
    )
    first_chunk = await asyncio.wait_for(response.body_iterator.__anext__(), timeout=2.0)
    collected = first_chunk.decode() if isinstance(first_chunk, (bytes, bytearray)) else str(first_chunk)
    assert "event: crypto_state" in collected
    assert '"symbol":"BTCUSDT"' in collected
    assert calls["count"] >= 1
    await response.body_iterator.aclose()
