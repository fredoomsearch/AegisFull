from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.phase_progress_manager import (
    PHASE_DEFINITIONS,
    snapshot_stage_state,
    sync_phase_percentages,
)
from app.services.progress_tracker import snapshot_progress, update_snapshot_block


def _format_stage_lines(stages: Dict[str, int]) -> list[str]:
    if not stages:
        return ["- Ninguna etapa registrada."]
    return [f"- {name}: {int(percent)}%" for name, percent in sorted(stages.items())]


def _phase_progress_average(phase_progress: Dict[str, int]) -> int | None:
    if not phase_progress:
        return None
    return int(round(sum(phase_progress.values()) / len(phase_progress)))


def _format_job_meta(job_meta: Dict[str, Any] | None) -> list[str]:
    if not isinstance(job_meta, dict):
        return []
    lines: list[str] = []
    job_id = str(job_meta.get("id") or "").strip()
    if job_id:
        lines.append(f"- Job ID: {job_id}")
    stages = job_meta.get("stages")
    if isinstance(stages, list) and stages:
        lines.append("- Job stages:")
        for stage in stages:
            name = str(stage.get("name") or "").strip()
            status = str(stage.get("status") or "unknown").strip()
            detail = str(stage.get("detail") or "").strip()
            line = f"  - {name}: {status}"
            if detail:
                line += f" ({detail})"
            lines.append(line)
    return lines


def _format_session_state(session_state: Dict[str, Any] | None) -> list[str]:
    if not isinstance(session_state, dict):
        return []
    lines: list[str] = []
    current_task = str(session_state.get("current_task") or "").strip()
    if current_task:
        lines.append(f"- Tarea actual: {current_task}")
    pending = session_state.get("pending_approval")
    if isinstance(pending, dict):
        tool = str(pending.get("tool") or "").strip()
        expires_ms = pending.get("expires_ms")
        if tool:
            lines.append(f"- Aprobación pendiente: {tool}")
        if expires_ms is not None:
            lines.append(f"- Expira en: {int(expires_ms)} ms")
    return lines


def _ordered_phase_lines(phase_progress: Dict[str, int]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()

    for heading in PHASE_DEFINITIONS.keys():
        if heading in phase_progress:
            lines.append(f"  - {heading}: {phase_progress[heading]}%")
            seen.add(heading)

    extra_headings = [heading for heading in phase_progress.keys() if heading not in seen]
    for heading in sorted(extra_headings):
        lines.append(f"  - {heading}: {phase_progress[heading]}%")

    return lines


def build_progress_snapshot_block(
    session_state: Dict[str, Any] | None = None,
    job_meta: Dict[str, Any] | None = None,
    stage_state: Dict[str, int] | None = None,
    progress_md: Path | None = None,
) -> str:
    if stage_state is None:
        stage_state = snapshot_stage_state()

    phase_progress = snapshot_progress(path=progress_md)
    lines: list[str] = ["### Estado de progreso automático"]
    average = _phase_progress_average(phase_progress)
    if average is not None:
        lines.append(f"- **Avance global de fases:** {average}%")
    else:
        lines.append("- **Avance global de fases:** no disponible.")

    if phase_progress:
        lines.append("- **Porcentaje por fase:**")
        lines.extend(_ordered_phase_lines(phase_progress))
    else:
        lines.append("- **Porcentaje por fase:** no disponible.")

    lines.append("- **Estado de etapas:**")
    lines.extend(_format_stage_lines(stage_state))

    job_lines = _format_job_meta(job_meta)
    if job_lines:
        lines.append("- **Detalle de job:**")
        lines.extend(job_lines)

    session_lines = _format_session_state(session_state)
    if session_lines:
        lines.append("- **Estado de sesión:**")
        lines.extend(session_lines)

    return "\n".join(lines)


def emit_progress_snapshot(
    session_state: Dict[str, Any] | None = None,
    job_meta: Dict[str, Any] | None = None,
    progress_md: Path | None = None,
    state_path: Path | None = None,
) -> bool:
    try:
        sync_phase_percentages(state_path=state_path, progress_md=progress_md)
    except Exception:
        pass

    snapshot_block = build_progress_snapshot_block(
        session_state=session_state,
        job_meta=job_meta,
        stage_state=snapshot_stage_state(state_path=state_path),
        progress_md=progress_md,
    )
    return update_snapshot_block(snapshot_block, path=progress_md)


__all__ = [
    "build_progress_snapshot_block",
    "emit_progress_snapshot",
]
