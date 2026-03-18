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
