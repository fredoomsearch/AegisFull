from __future__ import annotations

from pathlib import Path


def test_handle_web_publishes_prefetched_context_before_backend_chat():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    handle_web_block = js.split("async function handleWeb(query) {", 1)[1].split("async function webSearch(query) {", 1)[0]

    assert "state.lastChatContext = ctx;" in handle_web_block
    assert "updateModeIndicator();" in handle_web_block
    assert "renderSourceOriginBar(state.lastChatContext);" in handle_web_block
    assert "renderResponseSources(query, results, ctx, null);" in handle_web_block


def test_handle_web_merges_prefetched_web_context_when_chat_loses_it():
    js = Path("ui/app.js").read_text(encoding="utf-8")

    assert "function mergePrefetchedWebContext" in js
    assert 'const chatResult = await handleChat(query, { mode: "web" });' in js
    assert "const mergedContext = mergePrefetchedWebContext(ctx, chatResult?.context, results, chatResult?.sources || []);" in js
    assert "state.lastChatContext = mergedContext;" in js
    assert "renderResponseSources(query, results, mergedContext, null);" in js


def test_non_chat_only_ui_exposes_web_mode_button():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    html = Path("ui/index.html").read_text(encoding="utf-8")

    assert "const CHAT_ONLY_EXPERIENCE = false;" in js
    assert 'id="webBtn"' in html
    assert 'dom.webBtn?.addEventListener("click", () => setMode(MODES.WEB));' in js