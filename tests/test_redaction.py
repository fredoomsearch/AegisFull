from app.models.llm_utils import build_messages


def test_build_messages_redacts_common_secrets():
    conv_id = "00000000-0000-0000-0000-000000000000"
    token = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
    msgs = build_messages(
        conv_id,
        f"please use {token} in code",
        web_context="",
        max_total_chars=2000,
        history_messages=[{"role": "user", "content": "hi"}],
        summary_override="",
    )
    blob = "\n".join(m.get("content", "") for m in msgs)
    assert token not in blob
    assert "sk-***REDACTED***" in blob

