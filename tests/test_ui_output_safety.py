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


def test_ui_display_query_is_sanitized():
    js = Path("ui/app.js").read_text(encoding="utf-8")
    assert "function formatDisplayQuery" in js
    assert "stripInlinePromptBlob(raw).text" in js
    assert "stripInlineTraceBlob(withoutPromptBlob).text" in js
    assert "displayQuery = formatDisplayQuery(query || context?.web_query || \"\")" in js
