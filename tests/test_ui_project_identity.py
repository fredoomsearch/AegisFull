from __future__ import annotations

from pathlib import Path


def test_ui_clears_manual_root_on_active_project_selection():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function clearManualProjectRoot" in js
    assert "if (state.activeProjectId)" in js
    assert "clearManualProjectRoot({ syncSelect: false });" in js
    assert "function resolveProjectSelectionState" in js


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


def test_ui_ingest_uses_visible_project_selection_and_helpful_error():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "const selection = resolveProjectSelectionState();" in js
    assert "const effectiveProjectId = selection.projectId || \"\";" in js
    assert "Select an active project, or upload/register a valid root first." in js
    assert "Could not start ingest (" in js


def test_ui_syncs_auto_ingest_jobs_from_project_onboarding():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function syncAutoIngestJob" in js
    assert "Project indexing in background" in js
    assert "Indexando proyecto en background" in js
    assert "data?.auto_ingest || data" in js


def test_ui_has_backend_stop_button_and_shutdown_wiring():
    html = Path("ui/index.html").read_text(encoding="utf-8")
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert 'id="backendStopBtn"' in html
    assert 'id="backendProcessBadge"' in html
    assert "This will attempt to stop the AEGIS backend on this machine." in js
    assert "await cancelAllRequests(true);" in js
    assert "await shutdownServer(true);" in js
    assert "Backend process" in js
    assert "const process = data?.process || readyz?.process || {};" in js
    assert "pid:" in js
    assert "dom.backendProcessBadge" in js
    assert "Stop current backend" in js


def test_ui_restores_conversation_transcript_on_reload():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "conversationBundle: (id) => `/chat/${id}/bundle`" in js
    assert "function restoreConversationTranscript" in js
    assert "function clearChatTranscript" in js
    assert "clearChatTranscript();" in js
    assert "localStorage.setItem(\"aegis_last_transcript_conv\", targetConvId)" in js
    assert "void restoreConversationTranscript(state.conversationId, { force: true });" in js
