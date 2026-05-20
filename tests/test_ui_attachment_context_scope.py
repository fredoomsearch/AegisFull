from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_attachment_context_only_applies_to_attachment_targeted_messages():
    js = _read("ui/app.js")
    block = js.split('function buildMessageWithAttachment(message, mode = "general") {', 1)[1].split("function updateImageQuickBar() {", 1)[0]

    assert "function messageTargetsAttachmentContext(text)" in js
    assert "if (!messageTargetsAttachmentContext(base)) return base;" in block


def test_attachment_context_helper_explicitly_blocks_social_and_project_turns():
    js = _read("ui/app.js")
    helper = js.split("function messageTargetsAttachmentContext(text) {", 1)[1].split('function buildMessageWithAttachment(message, mode = "general") {', 1)[0]

    assert "if (looksLocalSocialMessage(lower)) return false;" in helper
    assert "if (looksProjectScopedMessage(lower) || looksExplicitLocalOnlyMessage(lower)) return false;" in helper
    assert '"what does it say"' in helper
    assert '"que dice"' in helper


def test_attachment_local_routing_uses_same_scope_guard():
    js = _read("ui/app.js")
    block = js.split('function attachmentKeepsLocalRouting(text, mode = "general") {', 1)[1].split('function projectKeepsLocalRouting(text, mode = "general") {', 1)[0]

    assert "if (!messageTargetsAttachmentContext(text)) return false;" in block
    assert "if (messageNeedsFreshWeb(text)) return false;" in block
    assert "return true;" in block