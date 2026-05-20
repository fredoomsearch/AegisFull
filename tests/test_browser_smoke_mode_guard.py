from pathlib import Path

from app.scripts import browser_smoke


def test_chat_mode_contract_ready_accepts_real_chat_state():
    assert browser_smoke._chat_mode_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Chat • web auto → local",
        chat_pressed="true",
        crypto_pressed="false",
        send_label="Send",
    )


def test_chat_mode_contract_ready_rejects_crypto_residue():
    assert not browser_smoke._chat_mode_contract_ready(
        body_mode="crypto",
        mode_indicator="Mode: Chat",
        chat_pressed="true",
        crypto_pressed="false",
        send_label="Send",
    )
    assert not browser_smoke._chat_mode_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Chat",
        chat_pressed="true",
        crypto_pressed="true",
        send_label="Send",
    )
    assert not browser_smoke._chat_mode_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Chat",
        chat_pressed="true",
        crypto_pressed="false",
        send_label="Predict",
    )


def test_web_mode_contract_ready_accepts_real_web_state():
    assert browser_smoke._web_mode_contract_ready(
        body_mode="web",
        mode_indicator="Mode: Web",
        web_pressed="true",
    )


def test_web_mode_contract_ready_rejects_chat_or_unpressed_web_state():
    assert not browser_smoke._web_mode_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Web",
        web_pressed="true",
    )
    assert not browser_smoke._web_mode_contract_ready(
        body_mode="web",
        mode_indicator="Mode: Chat",
        web_pressed="true",
    )
    assert not browser_smoke._web_mode_contract_ready(
        body_mode="web",
        mode_indicator="Mode: Web",
        web_pressed="false",
    )


def test_chat_only_web_contract_ready_accepts_chat_only_auto_web_state():
    assert browser_smoke._chat_only_web_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Chat (auto web/local)",
        chat_pressed="true",
    )


def test_chat_only_web_contract_ready_rejects_non_chat_only_state():
    assert not browser_smoke._chat_only_web_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Chat",
        chat_pressed="true",
    )
    assert not browser_smoke._chat_only_web_contract_ready(
        body_mode="web",
        mode_indicator="Mode: Chat (auto web/local)",
        chat_pressed="true",
    )
    assert not browser_smoke._chat_only_web_contract_ready(
        body_mode="chat",
        mode_indicator="Mode: Chat (auto web/local)",
        chat_pressed="false",
    )


def test_new_chat_segment_returns_only_appended_response():
    before = "user: where is russia?\nassistant: Rusia se extiende..."
    after = before + "\nuser: what is the capital of japan?\nassistant: La capital de japan es Tokio."

    segment = browser_smoke._new_chat_segment(before, after)

    assert segment == "user: what is the capital of japan?\nassistant: La capital de japan es Tokio."


def test_new_chat_segment_falls_back_to_full_text_when_prefix_differs():
    after = "assistant: La capital de japan es Tokio."

    segment = browser_smoke._new_chat_segment("different prefix", after)

    assert segment == after


def test_strict_web_proof_ready_accepts_live_web_with_sources():
    assert browser_smoke._strict_web_proof_ready(web_badge="WEB: live", source_cards=3)
    assert browser_smoke._strict_web_proof_ready(web_badge="WEB: vivo", source_cards=1)


def test_strict_web_proof_ready_rejects_cache_and_degraded_states():
    assert not browser_smoke._strict_web_proof_ready(web_badge="WEB: cache", source_cards=3)
    assert not browser_smoke._strict_web_proof_ready(web_badge="WEB: caché", source_cards=3)
    assert not browser_smoke._strict_web_proof_ready(web_badge="WEB: cooldown", source_cards=3)
    assert not browser_smoke._strict_web_proof_ready(web_badge="WEB: unavailable", source_cards=3)
    assert not browser_smoke._strict_web_proof_ready(web_badge="WEB: live", source_cards=0)


def test_browser_smoke_geo_and_memory_proofs_force_chat_mode_before_submit():
    target = Path(__file__).resolve().parents[1] / "app" / "scripts" / "browser_smoke.py"
    src = target.read_text(encoding="utf-8")

    geo_block = src.split('current_stage = "geo-proof"', 1)[1].split('geo_msg.send_keys("where is russia?")', 1)[0]
    memory_block = src.split('current_stage = "memory-speed-proof"', 1)[1].split('cap_msg.send_keys("what is the capital of japan?")', 1)[0]
    web_block = src.split('current_stage = "web-proof"', 1)[1].split('web_msg.send_keys(web_query)', 1)[0]
    web_response_block = src.split('current_stage = "web-proof-response"', 1)[1].split('current_stage = "web-proof-sources"', 1)[0]

    assert "_ensure_chat_mode()" in geo_block
    assert "_ensure_chat_mode()" in memory_block
    assert "_ensure_web_mode()" in web_block
    assert 'web_msg.get_attribute("value")' in src
    assert 'dispatchEvent(new Event("input", { bubbles: true }))' in src
    assert "_wait_for_idle_chat()" in web_response_block
    assert "send_btn.click()" in web_response_block
    assert "_web_submit_started()" in web_response_block
    assert 'web_query = f"web: latest python 3.12 release notes {int(time.time())}"' in src


def test_browser_smoke_idle_wait_checks_send_button_is_enabled():
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "browser_smoke.py").read_text(encoding="utf-8")
    idle_block = src.split("def _wait_for_idle_chat() -> None:", 1)[1].split("def _read_chat_mode_contract()", 1)[0]

    assert 'document.getElementById(\'typing-bubble\')' in idle_block
    assert 'find_element(By.ID, "sendBtn").get_attribute("disabled")' in idle_block