import pytest


def test_trade_with_keys_does_not_place_live_order_without_flag(monkeypatch):
    """
    Unit-level safety check: even if keys exist, AEGIS must not place live orders
    unless BINANCE_LIVE_TRADING=1 is explicitly enabled.
    """
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("BINANCE_LIVE_TRADING", "0")

    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 123.45)

    def _boom(*_a, **_kw):  # noqa: ANN001
        raise AssertionError("Should not call Binance signed request when live trading disabled")

    monkeypatch.setattr(crypto_api, "_binance_signed_request", _boom)

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.1, test=False)
    resp = crypto_api.trade(req)
    assert resp.status == "SIMULATED"
    assert "BINANCE_LIVE_TRADING" in (resp.message or "")


def test_normalize_binance_pair_adds_usdt_for_base_symbols():
    import app.api.crypto as crypto_api

    assert crypto_api._normalize_binance_pair("BTC") == "BTCUSDT"
    assert crypto_api._normalize_binance_pair("ETH") == "ETHUSDT"
    assert crypto_api._normalize_binance_pair("bitcoin") == "BTCUSDT"
    assert crypto_api._normalize_binance_pair("bitcoincash") == "BCHUSDT"
    assert crypto_api._normalize_binance_pair("eth/usdt") == "ETHUSDT"
    assert crypto_api._normalize_binance_pair("SOLUSDT") == "SOLUSDT"


def test_symbols_meta_exposes_expanded_pairs_and_aliases():
    import app.api.crypto as crypto_api

    payload = crypto_api.symbols_meta()
    quotes = payload.get("allowed_quote_assets") or []
    pairs = payload.get("popular_pairs") or []
    aliases = payload.get("base_symbol_aliases") or {}

    assert "USDT" in quotes
    assert "BTCUSDT" in pairs
    assert "ETHUSDT" in pairs
    assert "BCHUSDT" in pairs
    assert len(pairs) >= 60
    assert aliases.get("bitcoin") == "BTC"
    assert aliases.get("bitcoincash") == "BCH"


def test_trade_normalizes_base_symbol_to_usdt_pair(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 101.25)
    req = crypto_api.TradeRequest(symbol="btc", side="BUY", quantity=0.01, test=True)
    resp = crypto_api.trade(req)
    assert resp.symbol == "BTCUSDT"


def test_trade_reports_testnet_execution_mode(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("BINANCE_EXECUTION_MODE", "testnet")
    monkeypatch.setenv("BINANCE_LIVE_TRADING", "0")

    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 123.45)

    captured = {}

    def _fake_signed_request(*, method, path, params, api_key, api_secret, base_url=None):  # noqa: ANN001
        captured["method"] = method
        captured["path"] = path
        captured["params"] = dict(params)
        captured["api_key"] = api_key
        captured["api_secret"] = api_secret
        return {}

    monkeypatch.setattr(crypto_api, "_binance_signed_request", _fake_signed_request)

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.1, test=False)
    resp = crypto_api.trade(req)

    assert resp.execution_mode == "testnet"
    assert resp.status == "SENT_TO_EXCHANGE"
    assert captured["path"] == "/api/v3/order"
    assert captured["method"] == "POST"


def test_trade_reports_microstructure_profile_for_simulated_orders(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)
    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.111, test=True, execution_mode="simulated")
    resp = crypto_api.trade(req)

    assert resp.execution_mode == "simulated"
    assert resp.mid_price == 100.0
    assert resp.fill_price is not None
    assert resp.fill_price >= resp.mid_price
    assert resp.spread_bps is not None and resp.spread_bps > 0
    assert resp.slippage_bps is not None and resp.slippage_bps > 0
    assert resp.liquidity_bucket in {"micro", "small", "medium", "large", "whale"}
    assert "spread" in (resp.execution_note or "").lower()
    assert "slippage" in (resp.execution_note or "").lower()


def test_trade_preview_builds_market_style_preview(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)
    monkeypatch.setattr(
        crypto_api,
        "_execution_profile",
        lambda **kwargs: {
            "mid_price": 100.0,
            "fill_price": 100.0,
            "spread_bps": 5.0,
            "slippage_bps": 2.0,
            "impact_bps": 1.0,
            "liquidity_bucket": "micro",
            "notional": 10.0,
            "execution_note": "micro liquidity • STP/ECN-style fill • spread 5.0bps • slippage 2.0bps • impact 1.0bps",
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "_crypto_execution_snapshot",
        lambda requested_mode=None: {
            "mode": "simulated",
            "credentials_present": False,
            "live_trading_enabled": False,
            "testnet_enabled": False,
            "live_enabled": False,
            "simulated": True,
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "build_crypto_state_snapshot",
        lambda **kwargs: {
            "latest_prediction": {
                "id": "pred_1",
                "symbol": "BTCUSDT",
                "horizon_minutes": 15,
                "decision": "BUY",
                "action_decision": "BUY",
                "current_price": 100.0,
                "predicted_price": 105.0,
                "probability_up": 0.72,
            },
            "latest_prediction_ref": {"log_id": "pred_1"},
            "order_book": {
                "bid_notional": 400.0,
                "ask_notional": 600.0,
                "best_bid": 99.5,
                "best_ask": 100.5,
                "spread_bps": 100.0,
                "imbalance": 0.4,
            },
        },
    )

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.111, test=True, execution_mode="simulated")
    preview = crypto_api._build_trade_preview(order=req, horizon_minutes=15, regime="trend")

    assert preview["preview_only"] is True
    assert preview["symbol"] == "BTCUSDT"
    assert preview["side"] == "BUY"
    assert preview["execution_mode"] == "simulated"
    assert preview["requested_mode"] == "simulated"
    assert preview["signal_decision"] == "BUY"
    assert preview["fill_price"] == 100.0
    assert preview["entry_price"] == 100.0
    assert preview["predicted_price"] == 105.0
    assert preview["expected_gain_quote"] is not None and preview["expected_gain_quote"] > 0
    assert preview["expected_loss_quote"] is not None and preview["expected_loss_quote"] > 0
    assert preview["order_size_pct"] is not None and preview["order_size_pct"] > 0
    assert preview["book_consumption_pct"] is not None and preview["book_consumption_pct"] > 0
    assert preview["participation_pct"] is not None and preview["participation_pct"] > 0
    assert preview["others_pct"] is not None and preview["others_pct"] >= 0
    assert preview["remaining_liquidity"] is not None and preview["remaining_liquidity"] >= 0
    assert preview["pre_trade_price"] == 100.0
    assert preview["post_trade_estimate"] == 100.0
    assert preview["impact_score"] is not None and preview["impact_score"] >= 0
    assert preview["risk_gate"]["allowed"] is True
    assert preview["risk_gate"]["reason"] in {"ok", "signal_aligned"}
    assert preview["risk"]["tradeable"] is True
    assert preview["risk"]["decision"] == "BUY"
    assert "stp/ecn" in (preview["execution_note"] or "").lower()


def test_trade_rejects_when_risk_gate_blocks_large_notional(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setenv("AEGIS_CRYPTO_MAX_ORDER_NOTIONAL", "5")
    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)

    def _boom(*_a, **_kw):  # noqa: ANN001
        raise AssertionError("Should not call Binance signed request when risk gate blocks the order")

    monkeypatch.setattr(crypto_api, "_binance_signed_request", _boom)

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.1, test=False, execution_mode="simulated")
    resp = crypto_api.trade(req)

    assert resp.status == "REJECTED"
    assert resp.risk_gate is not None
    assert resp.risk_gate["allowed"] is False
    assert "risk gate" in (resp.message or "").lower()


def test_trade_preview_blocks_when_calibration_guidance_abstains(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)
    monkeypatch.setattr(
        crypto_api,
        "_execution_profile",
        lambda **kwargs: {
            "mid_price": 100.0,
            "fill_price": 100.0,
            "spread_bps": 5.0,
            "slippage_bps": 2.0,
            "impact_bps": 1.0,
            "liquidity_bucket": "micro",
            "notional": 10.0,
            "execution_note": "preview fill",
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "_crypto_execution_snapshot",
        lambda requested_mode=None: {
            "mode": "simulated",
            "credentials_present": False,
            "live_trading_enabled": False,
            "testnet_enabled": False,
            "live_enabled": False,
            "simulated": True,
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "build_crypto_state_snapshot",
        lambda **kwargs: {
            "latest_prediction": {
                "id": "pred_1",
                "symbol": "BTCUSDT",
                "horizon_minutes": 15,
                "decision": "BUY",
                "action_decision": "BUY",
                "current_price": 100.0,
                "predicted_price": 105.0,
                "probability_up": 0.78,
                "operator_guidance": {
                    "status": "abstain",
                    "action": "hold_out_until_recalibrated",
                    "reasons": ["high_confidence_bucket_miscalibrated"],
                },
            },
            "latest_prediction_ref": {"log_id": "pred_1"},
            "order_book": {"bid_notional": 500.0, "ask_notional": 500.0, "spread_bps": 10.0, "imbalance": 0.5},
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "_risk_snapshot",
        lambda **kwargs: {
            "decision": "BUY",
            "tradeable": True,
            "entry_price": 100.0,
            "predicted_price": 105.0,
            "target_price": 105.0,
            "stop_price": 98.0,
            "expected_pnl_pct": 0.03,
            "risk_reward": 1.5,
            "projected_move_pct": 0.05,
            "execution_drag_pct": 0.001,
            "confidence": 0.78,
            "confidence_bucket": "medium",
            "order_notional": 10.0,
            "visible_liquidity_notional": 1000.0,
            "side_liquidity_notional": 500.0,
            "order_size_pct": 1.0,
            "book_consumption_pct": 2.0,
            "participation_pct": 1.0,
            "others_pct": 99.0,
            "remaining_liquidity": 490.0,
            "pre_trade_price": 100.0,
            "post_trade_estimate": 100.0,
            "impact_score": 3.0,
            "net_expected_profit_after_costs_pct": 0.029,
            "net_expected_profit_after_costs_quote": 0.29,
            "spread_bps": 10.0,
        },
    )

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.1, test=True, execution_mode="simulated")
    preview = crypto_api._build_trade_preview(order=req, horizon_minutes=15, regime="trend", use_order_book=False)

    assert preview["risk_gate"]["allowed"] is False
    assert preview["risk_gate"]["reason"] == "calibration_abstain"
    assert preview["risk_gate"]["checks"]["operator_guidance"]["value"] == "abstain"
    assert preview["risk_gate"]["checks"]["operator_guidance"]["action"] == "hold_out_until_recalibrated"
    assert preview["risk_gate"]["operator_guidance"]["status"] == "abstain"


def test_trade_preview_exposes_calibration_downgrade_size_controls(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)
    monkeypatch.setattr(
        crypto_api,
        "_execution_profile",
        lambda **kwargs: {
            "mid_price": 100.0,
            "fill_price": 100.0,
            "spread_bps": 5.0,
            "slippage_bps": 2.0,
            "impact_bps": 1.0,
            "liquidity_bucket": "micro",
            "notional": 10.0,
            "execution_note": "preview fill",
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "_crypto_execution_snapshot",
        lambda requested_mode=None: {
            "mode": "simulated",
            "credentials_present": False,
            "live_trading_enabled": False,
            "testnet_enabled": False,
            "live_enabled": False,
            "simulated": True,
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "build_crypto_state_snapshot",
        lambda **kwargs: {
            "latest_prediction": {
                "id": "pred_1",
                "symbol": "BTCUSDT",
                "horizon_minutes": 15,
                "decision": "BUY",
                "action_decision": "BUY",
                "current_price": 100.0,
                "predicted_price": 104.0,
                "probability_up": 0.74,
                "operator_guidance": {
                    "status": "downgrade",
                    "action": "raise_thresholds_or_reduce_size",
                    "reasons": ["overall_brier_elevated"],
                },
            },
            "latest_prediction_ref": {"log_id": "pred_1"},
            "order_book": {
                "bid_notional": 50.0,
                "ask_notional": 50.0,
                "best_bid": 99.5,
                "best_ask": 100.5,
                "spread_bps": 100.0,
                "imbalance": 0.5,
            },
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "_risk_snapshot",
        lambda **kwargs: {
            "decision": "BUY",
            "tradeable": True,
            "entry_price": 100.0,
            "predicted_price": 104.0,
            "target_price": 104.0,
            "stop_price": 98.0,
            "expected_pnl_pct": 0.02,
            "risk_reward": 1.4,
            "projected_move_pct": 0.04,
            "execution_drag_pct": 0.001,
            "confidence": 0.74,
            "confidence_bucket": "medium",
            "order_notional": 10.0,
            "visible_liquidity_notional": 50.0,
            "side_liquidity_notional": 50.0,
            "order_size_pct": 20.0,
            "book_consumption_pct": 20.0,
            "participation_pct": 16.6667,
            "others_pct": 83.3333,
            "remaining_liquidity": 40.0,
            "pre_trade_price": 100.0,
            "post_trade_estimate": 100.0,
            "impact_score": 5.0,
            "net_expected_profit_after_costs_pct": 0.019,
            "net_expected_profit_after_costs_quote": 0.19,
            "spread_bps": 5.0,
        },
    )

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.1, test=True, execution_mode="simulated")
    preview = crypto_api._build_trade_preview(order=req, horizon_minutes=15, regime="trend", use_order_book=False)

    assert preview["preview_only"] is True
    assert preview["risk_gate"]["allowed"] is False
    assert preview["risk_gate"]["reason"] == "calibration_size_reduction_required"
    assert preview["risk_gate"]["checks"]["operator_guidance"]["value"] == "downgrade"
    assert preview["risk_gate"]["checks"]["operator_guidance"]["action"] == "raise_thresholds_or_reduce_size"
    assert preview["risk_gate"]["operator_guidance"]["status"] == "downgrade"
    assert preview["risk_gate"]["calibration_controls"]["max_order_size_pct"] == 15.0
    assert preview["risk_gate"]["calibration_controls"]["max_order_notional"] == pytest.approx(7.5)
    assert preview["risk_gate"]["calibration_controls"]["max_quantity"] == pytest.approx(0.075)
    assert preview["risk_gate"]["calibration_controls"]["recommended_reduction_pct"] == pytest.approx(0.25)
    assert preview["risk_gate"]["calibration_controls"]["sizing_basis"] == "visible_liquidity_notional"
    assert preview["risk_gate"]["blocked_checks"][0] == "calibration_order_notional"
    assert "calibration_quantity" in preview["risk_gate"]["blocked_checks"]


def test_trade_rejects_when_calibration_downgrade_requires_smaller_order(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)
    monkeypatch.setattr(
        crypto_api,
        "_execution_profile",
        lambda **kwargs: {
            "mid_price": 100.0,
            "fill_price": 100.0,
            "spread_bps": 5.0,
            "slippage_bps": 2.0,
            "impact_bps": 1.0,
            "liquidity_bucket": "micro",
            "notional": 10.0,
            "execution_note": "preview fill",
        },
    )
    monkeypatch.setattr(
        crypto_api,
        "list_predictions",
        lambda **kwargs: [
            {
                "id": "pred_1",
                "symbol": "BTCUSDT",
                "decision": "BUY",
                "action_decision": "BUY",
                "current_price": 100.0,
                "predicted_price": 104.0,
                "probability_up": 0.74,
                "operator_guidance": {
                    "status": "downgrade",
                    "action": "raise_thresholds_or_reduce_size",
                    "reasons": ["overall_brier_elevated"],
                },
            }
        ],
    )
    monkeypatch.setattr(crypto_api, "list_trades", lambda **kwargs: [])
    monkeypatch.setattr(crypto_api, "compute_pnl", lambda *args, **kwargs: {"per_symbol": {}})
    monkeypatch.setattr(
        crypto_api,
        "_risk_snapshot",
        lambda **kwargs: {
            "decision": "BUY",
            "tradeable": True,
            "entry_price": 100.0,
            "predicted_price": 104.0,
            "target_price": 104.0,
            "stop_price": 98.0,
            "expected_pnl_pct": 0.02,
            "risk_reward": 1.4,
            "projected_move_pct": 0.04,
            "execution_drag_pct": 0.001,
            "confidence": 0.74,
            "confidence_bucket": "medium",
            "order_notional": 10.0,
            "visible_liquidity_notional": 50.0,
            "side_liquidity_notional": 50.0,
            "order_size_pct": 20.0,
            "book_consumption_pct": 20.0,
            "participation_pct": 16.6667,
            "others_pct": 83.3333,
            "remaining_liquidity": 40.0,
            "pre_trade_price": 100.0,
            "post_trade_estimate": 100.0,
            "impact_score": 5.0,
            "net_expected_profit_after_costs_pct": 0.019,
            "net_expected_profit_after_costs_quote": 0.19,
            "spread_bps": 5.0,
        },
    )

    req = crypto_api.TradeRequest(symbol="BTCUSDT", side="BUY", quantity=0.1, test=True, execution_mode="simulated")
    resp = crypto_api.trade(req)

    assert resp.status == "REJECTED"
    assert resp.risk_gate is not None
    assert resp.risk_gate["reason"] == "calibration_size_reduction_required"
    assert resp.risk_gate["checks"]["operator_guidance"]["value"] == "downgrade"
    assert resp.risk_gate["calibration_controls"]["max_order_size_pct"] == 15.0
    assert resp.risk_gate["calibration_controls"]["max_order_notional"] == pytest.approx(7.5)
    assert resp.risk_gate["calibration_controls"]["max_quantity"] == pytest.approx(0.075)
    assert resp.risk_gate["calibration_controls"]["recommended_reduction_pct"] == pytest.approx(0.25)
    assert resp.risk_gate["calibration_controls"]["sizing_basis"] == "visible_liquidity_notional"
    assert resp.risk_gate["blocked_checks"][0] == "calibration_order_notional"
    assert "calibration_quantity" in resp.risk_gate["blocked_checks"]


def test_crypto_state_reflects_requested_execution_mode(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)

    payload = crypto_api.crypto_state(symbol="BTCUSDT", horizon_minutes=15, execution_mode="live")

    assert payload["execution"]["requested_mode"] == "live"
    assert payload["execution"]["mode"] == "live"
    assert payload["execution"]["simulated"] is False


def test_crypto_state_includes_order_book_snapshot(monkeypatch):
    import app.api.crypto as crypto_api

    monkeypatch.setattr(crypto_api, "_binance_spot_price", lambda _sym: 100.0)
    monkeypatch.setattr(
        crypto_api,
        "_binance_order_book",
        lambda symbol, limit=10: {
            "symbol": symbol,
            "source": "binance",
            "levels": limit,
            "mid_price": 100.0,
            "best_bid": 99.5,
            "best_ask": 100.5,
            "spread": 1.0,
            "spread_bps": 100.0,
            "imbalance": 0.62,
            "bid_qty": 10.0,
            "ask_qty": 8.0,
            "bid_notional": 995.0,
            "ask_notional": 804.0,
            "liquidity_bucket": "medium",
            "bids": [{"price": 99.5, "qty": 1.0, "notional": 99.5}],
            "asks": [{"price": 100.5, "qty": 1.0, "notional": 100.5}],
            "note": "binance order book • spread 100.0bps • imbalance 62.0% bid side",
        },
    )

    payload = crypto_api.crypto_state(symbol="BTCUSDT", horizon_minutes=15, execution_mode="simulated")

    assert payload["summary"]["has_order_book"] is True
    assert payload["order_book"]["source"] == "binance"
    assert payload["order_book"]["best_bid"] == 99.5


def test_ohlcv_normalizes_base_symbol_for_binance_request(monkeypatch):
    import app.api.crypto as crypto_api

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                [0, "1", "2", "0.5", "1.5", "10", 60],
                [60, "1.5", "2.5", "1.0", "2.0", "11", 120],
            ]

    def _fake_get(url, params=None, timeout=0):  # noqa: ANN001
        captured["url"] = url
        captured["params"] = dict(params or {})
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(crypto_api.requests, "get", _fake_get)
    series = crypto_api.get_ohlcv(symbol="btc", interval="1m", limit=2)
    assert captured.get("params", {}).get("symbol") == "BTCUSDT"
    assert len(series) == 2
