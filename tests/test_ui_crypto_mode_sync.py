from pathlib import Path


def test_ui_crypto_chat_shorthand_syncs_panel_scope_and_refreshes_panel():
    js = Path("ui/app.js").read_text(encoding="utf-8")

    assert "function syncCryptoPanelScopeFromText" in js
    assert "const explicitSymbol = extractCryptoSymbolFromText(raw);" in js
    assert "const explicitHorizon = extractCryptoHorizonFromText(raw);" in js

    crypto_block = js.split('if (effectiveMode === "crypto") {', 1)[1].split("\n  }\n\n  return { context, sources, data };", 1)[0]
    assert "syncCryptoPanelScopeFromText(text);" in crypto_block
    assert "loadChartData(state.chartSymbol);" in crypto_block
    assert "loadCryptoPrediction({ force: true });" in crypto_block
    assert "loadCryptoState({ force: true });" in crypto_block
    assert "loadPredictionComparison(state.chartSymbol, { force: true });" in crypto_block