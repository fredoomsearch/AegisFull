from __future__ import annotations

from app.services import runtime_metrics


def test_runtime_metrics_route_confidence_buckets_and_rates(monkeypatch):
    monkeypatch.setattr(runtime_metrics, "_persist_locked", lambda: None)
    with runtime_metrics._lock:  # type: ignore[attr-defined]
        runtime_metrics._counters.clear()  # type: ignore[attr-defined]
        runtime_metrics._events.clear()  # type: ignore[attr-defined]

    runtime_metrics.record_route_decision("local_only", routing_confidence=0.91, ambiguous_route=False)
    runtime_metrics.record_route_decision("local_only", routing_confidence=0.41, ambiguous_route=True)
    runtime_metrics.record_route_decision("web_only", routing_confidence=None, ambiguous_route=False)

    snap = runtime_metrics.snapshot(window_seconds=3600)
    dist = dict(snap.get("route_confidence_distribution_window") or {})
    rates = dict(snap.get("rates") or {})
    assert dist.get("high") == 1
    assert dist.get("low") == 1
    assert dist.get("unknown") == 1
    assert rates.get("ambiguous_route_rate") == 1.0 / 3.0
    assert rates.get("low_confidence_route_rate") == 1.0 / 3.0

