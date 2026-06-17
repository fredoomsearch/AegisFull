from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from app.services.progress_tracker import update_phase_percentage, snapshot_progress

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "data"
STATE_FILE = STATE_DIR / "phase_progress_state.json"

# Phase definitions: map phase heading -> list of stage fragments to match
PHASE_DEFINITIONS: Dict[str, List[str]] = {
    "Fase 1 — Context Aggregator": ["context"],
    "Fase 2 — Validation Layer (Anti-hallucination)": ["validation", "validate"],
    "Fase 3 — Project Knowledge Graph": ["project", "introspect", "entrypoint"],
    "Fase 4 — Unified Memory Layer": ["memory", "durable"],
    "Fase 5 — Hybrid Model Reasoning": ["hybrid", "reason"],
    "Fase 6 — Tool Result Persistence / Cache": ["tool", "cache", "persist"],
}


def _read_state(state_path: Path | None = None) -> Dict[str, int]:
    target = Path(state_path) if state_path else STATE_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8") or "{}")
    except Exception:
        pass
    return {"stages": {}}


def _write_state(state: Dict, state_path: Path | None = None) -> None:
    target = Path(state_path) if state_path else STATE_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def set_stage_progress(
    stage_name: str,
    percent: int,
    note: str | None = None,
    state_path: Path | None = None,
    progress_md: Path | None = None,
    emit_snapshot: bool = True,
) -> bool:
    """Set a stage progress (0-100) and update mapped phase percentages.

    Behavior:
    - Records `stage_name` -> percent in a small JSON state file.
    - For each phase that has matching stage fragments, computes the average
      percent across matched stages and writes that percent to `PROGRESO_FASES.md`.
    - If no phase matches the stage fragments, does nothing further.
    """
    if percent is None:
        return False
    try:
        pct = int(percent)
    except Exception:
        return False
    pct = max(0, min(100, pct))

    state = _read_state(state_path)
    stages: Dict[str, int] = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    stages[str(stage_name)] = pct
    state["stages"] = stages
    _write_state(state, state_path)

    try:
        sync_phase_percentages(state_path=state_path, progress_md=progress_md)
    except Exception:
        pass

    if emit_snapshot:
        try:
            from app.services.progress_snapshot_service import emit_progress_snapshot

            emit_progress_snapshot(state_path=state_path, progress_md=progress_md)
        except Exception:
            pass

    return True


def snapshot_stage_state(state_path: Path | None = None) -> Dict[str, int]:
    st = _read_state(state_path)
    return dict(st.get("stages") or {})


def sync_phase_percentages(state_path: Path | None = None, progress_md: Path | None = None) -> bool:
    """Sync computed phase percentages from a state file into the progress markdown.

    - `state_path`: optional Path to a JSON file with structure {"stages": {"name": percent}}
      If not provided the function reads the default STATE_FILE via `_read_state()`.
    - `progress_md`: optional Path to the `PROGRESO_FASES.md` file to update. If not
      provided the default file used by `progress_tracker` is used.

    The function computes averages for each `PHASE_DEFINITIONS` entry and calls
    `update_phase_percentage()` for each phase, passing `progress_md` when given so
    test harnesses can operate on temporary files.
    """
    # Load stage state
    stages: Dict[str, int] = {}
    if state_path:
        try:
            if state_path.exists():
                raw = state_path.read_text(encoding="utf-8") or "{}"
                st = json.loads(raw)
                stages = dict(st.get("stages") or {})
        except Exception:
            return False
    else:
        st = _read_state()
        stages = dict(st.get("stages") or {})

    # For each phase compute average from matching stages and update markdown
    any_updated = False
    for phase_heading, fragments in PHASE_DEFINITIONS.items():
        matched_percents: List[int] = []
        for sname, sval in stages.items():
            sl = sname.lower()
            if any(frag in sl for frag in fragments):
                try:
                    matched_percents.append(int(sval))
                except Exception:
                    pass
        if matched_percents:
            avg = int(round(sum(matched_percents) / len(matched_percents)))
            try:
                update_phase_percentage(phase_heading, avg, path=progress_md)
                any_updated = True
            except Exception:
                pass

    return any_updated


__all__ = [
    "set_stage_progress",
    "snapshot_stage_state",
    "sync_phase_percentages",
    "PHASE_DEFINITIONS",
]
