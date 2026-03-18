from __future__ import annotations

from pathlib import Path


def test_ui_clears_manual_root_on_active_project_selection():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function clearManualProjectRoot" in js
    assert "if (state.activeProjectId)" in js
    assert "clearManualProjectRoot({ syncSelect: false });" in js


def test_ui_sync_conversation_state_clears_manual_root_when_remote_project_active():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    marker = "async function syncConversationState"
    idx = js.find(marker)
    assert idx >= 0
    fragment = js[idx : idx + 1200]
    assert "if (remoteProjectId) clearManualProjectRoot({ syncSelect: false });" in fragment


def test_ui_surfaces_planner_stop_reason():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function plannerStopReason" in js
    assert "function plannerLoopMetrics" in js
    assert "using_stale_cache: webMeta?.source === \"stale-cache\"" in js
    assert "stop_reason: String(step?.stop_reason || \"\").trim() || null" in js
    assert "String(data?.stop_reason || \"\").trim()" in js
    assert "`${es ? \"Stop\" : \"Stop\"}: ${stopReason}`" in js
    assert "`${es ? \"Iteraciones\" : \"Iterations\"}: ${loopMetrics.iterationsCompleted}${maxIt}`" in js
    assert "`${es ? \"Tools\" : \"Tools\"}: ${loopMetrics.totalToolCalls}${maxTools}`" in js
