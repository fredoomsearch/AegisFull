from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_compact_image_mode_ui_controls_present():
    html = _read("ui/index.html")
    assert 'id="imgBtn"' in html
    assert 'id="attachBtn"' in html
    assert 'id="imageQuickBar"' in html
    assert 'id="imageModeGuide"' in html


def test_legacy_image_panel_removed_from_html():
    html = _read("ui/index.html")
    # Compact image mode should not require a dedicated panel anymore.
    assert 'id="imagePanel"' not in html
    assert 'id="imageGenerateBtn"' not in html
    assert 'id="imageGallery"' not in html


def test_image_command_pipeline_present_in_ui_js():
    js = _read("ui/app.js")
    assert "function parseImageCommand" in js
    assert "function tryHandleImageCommand" in js
    assert "if (await tryHandleImageCommand(raw))" in js
    assert "raw.match(/^\\/img3d\\b\\s*(.*)$/i)" in js
    assert "raw.match(/^\\/(?:img|image)\\b\\s*(.*)$/i)" in js
    assert "appendImageBubble({" in js


def test_image_mode_guide_mentions_img_and_img3d():
    js = _read("ui/app.js")
    assert "/img your prompt" in js
    assert "/img3d robot in neon city" in js


def test_image_mode_supports_plain_draw_prompts_and_stop_button():
    html = _read("ui/index.html")
    js = _read("ui/app.js")
    assert 'id="stopBtn"' in html
    assert 'draw a dragon' in js
    assert 'raw.match(/^(?:generate|create|draw|make)\\s+(?:an?\\s+)?(?:image\\s+(?:of\\s+)?)?(.+)$/i)' in js
    assert 'matched = [raw, raw];' in js


def test_compose_ui_is_mode_aware_and_keeps_crypto_live_available():
    js = _read("ui/app.js")
    assert 'return es ? "Predecir" : "Predict";' in js
    assert 'return es ? "Dibujar" : "Draw";' in js
    assert 'return es ? "Calculando señal…" : "Calculating signal…";' in js
    assert 'es ? "Generando imagen…" : "Generating image…"' in js
    assert 'if (dom.chartLive?.checked && !state.liveTimer) {' in js
    assert 'dom.chartLive.checked = false' not in js


def test_no_legacy_image_panel_hooks_in_ui_js():
    js = _read("ui/app.js")
    assert "document.getElementById(\"imagePanel\")" not in js
    assert "imagePanelExpanded" not in js
    assert "generateImageFromUI" not in js
    assert "loadRecentImages" not in js
    assert "renderImageGallery" not in js
