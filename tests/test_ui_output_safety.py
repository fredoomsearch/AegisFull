from __future__ import annotations

from pathlib import Path


def test_ui_has_assistant_output_sanitizer():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function sanitizeAssistantAnswerText" in js
    assert "INTERNAL_LEAK_LINE_PATTERNS" in js
    assert "INTERNAL_LEAK_ANYWHERE_PATTERNS" in js
    assert "INTERNAL_TRACE_PREFIX" in js
    assert "function stripInlinePromptBlob" in js
    assert "function stripInlineTraceBlob" in js


def test_ui_applies_sanitizer_to_backend_answers():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "const answer = sanitizeAssistantAnswerText(data?.response || \"\");" in js
    assert "const answer = sanitizeAssistantAnswerText(data?.response ?? data?.answer ?? data?.text ?? data?.message ?? \"\");" in js
    assert "if (role === \"bot\") {" in js
    assert "content = sanitizeAssistantAnswerText(content);" in js


def test_web_sources_info_bubble_is_debug_only():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "Found ${results.length} sources. Now answering with context." in js
    assert "if (state.debugTraceEnabled)" in js


def test_response_context_trace_chips_are_debug_only():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "if (debugMode && context.source_plan)" in js
    assert "if (debugMode && origins.length)" in js
    assert "if (debugMode && list.childNodes.length)" in js


def test_ui_shows_crypto_prediction_reference_from_response_context():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function formatCryptoPredictionRef" in js
    assert "context.crypto_prediction_ref" in js
    assert "Prediction used" in js


def test_ui_display_query_is_sanitized():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function formatDisplayQuery" in js
    assert "stripInlinePromptBlob(raw).text" in js
    assert "stripInlineTraceBlob(withoutPromptBlob).text" in js
    assert "displayQuery = formatDisplayQuery(query || context?.web_query || \"\")" in js


def test_ui_removes_untrusted_innerhtml_sinks():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "dom.predictionCompareTooltip.innerHTML = body.join(\"\");" not in js
    assert "li.innerHTML = `" not in js
    assert "row.innerHTML =" not in js
    assert 'a.appendChild(document.createTextNode(r.title ? String(r.title) : String(r.url)));' in js


def test_ui_uses_session_storage_for_secrets():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function writeSecretItem" in js
    assert 'sessionStorage.setItem(k, String(value));' in js
    assert 'localStorage.setItem("aegis_api_key"' not in js
    assert 'localStorage.setItem("aegis_files_api_key"' not in js
    assert 'writeSecretItem("aegis_access_token"' not in js
    assert 'writeSecretItem("aegis_refresh_token"' not in js
    assert 'writeSecretItem("aegis_token_exp"' not in js


def test_ui_prefers_cookie_based_auth_session():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "cookieAuth" in js
    assert "aegis_cookie_auth" in js
    assert 'credentials: "include"' in js
