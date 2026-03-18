from __future__ import annotations

import threading
import time

from app import llm_client_offload as offload


def _msg() -> list[dict[str, str]]:
    return [{"role": "user", "content": "hello"}]


def test_generate_response_waits_for_queue_slot(monkeypatch):
    sem = threading.Semaphore(1)
    assert sem.acquire(blocking=False) is True

    monkeypatch.setattr(offload, "_llm_semaphore", sem)
    monkeypatch.setattr(offload, "LLM_QUEUE_WAIT_SECONDS", 0.4)
    monkeypatch.setattr(offload, "_get_llama_class", lambda: object())
    monkeypatch.setattr(
        offload,
        "_call_llama_chat_with_timeout",
        lambda **_: "queued-ok",
    )

    result: dict[str, float | str] = {}

    def _worker() -> None:
        started = time.perf_counter()
        result["text"] = offload.generate_response(_msg(), max_new_tokens=32)
        result["elapsed"] = time.perf_counter() - started

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    time.sleep(0.12)
    sem.release()
    t.join(timeout=2.0)

    assert not t.is_alive()
    assert result["text"] == "queued-ok"
    assert float(result["elapsed"]) >= 0.1


def test_generate_response_returns_busy_after_timeout(monkeypatch):
    sem = threading.Semaphore(1)
    assert sem.acquire(blocking=False) is True

    monkeypatch.setattr(offload, "_llm_semaphore", sem)
    monkeypatch.setattr(offload, "LLM_QUEUE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(offload, "_get_llama_class", lambda: object())
    monkeypatch.setattr(
        offload,
        "_call_llama_chat_with_timeout",
        lambda **_: "should-not-run",
    )

    started = time.perf_counter()
    text = offload.generate_response(_msg(), max_new_tokens=32)
    elapsed = time.perf_counter() - started

    assert "local model is busy" in text.lower()
    assert elapsed >= 0.05


def test_generate_response_returns_busy_when_active_generation_is_stale(monkeypatch):
    sem = threading.Semaphore(1)
    assert sem.acquire(blocking=False) is True

    monkeypatch.setattr(offload, "_llm_semaphore", sem)
    monkeypatch.setattr(offload, "LLM_QUEUE_WAIT_SECONDS", 5.0)
    monkeypatch.setattr(offload, "LLM_STALL_BUSY_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(offload, "_get_llama_class", lambda: object())
    monkeypatch.setattr(offload, "_active_generations", {999: time.perf_counter() - 1.0})
    monkeypatch.setattr(
        offload,
        "_call_llama_chat_with_timeout",
        lambda **_: "should-not-run",
    )

    started = time.perf_counter()
    text = offload.generate_response(_msg(), max_new_tokens=32)
    elapsed = time.perf_counter() - started

    assert "long-running request" in text.lower()
    assert elapsed < 0.5
