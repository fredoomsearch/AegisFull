from __future__ import annotations

from typing import Any, List, Tuple


def normalize_prompt_url(raw: str) -> str:
    url = (raw or "").strip() or "http://127.0.0.1:8188/prompt"
    if "/prompt" not in url:
        return url.rstrip("/") + "/prompt"
    return url


def split_prompt_url(prompt_url: str) -> Tuple[str, str]:
    normalized = normalize_prompt_url(prompt_url)
    base = normalized.rsplit("/prompt", 1)[0].rstrip("/")
    return normalized, base


def normalize_checkpoint_values(raw: Any) -> List[str]:
    values = raw
    if isinstance(values, list) and values and isinstance(values[0], list):
        values = values[0]
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for item in values:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def extract_checkpoint_choices(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []

    targets: List[Any] = []
    node = payload.get("CheckpointLoaderSimple")
    if node is not None:
        targets.append(node)
    targets.append(payload)

    for target in targets:
        for path in (
            ("input", "required", "ckpt_name"),
            ("inputs", "required", "ckpt_name"),
            ("required", "ckpt_name"),
            ("ckpt_name",),
        ):
            current: Any = target
            ok = True
            for key in path:
                if isinstance(current, dict) and key in current:
                    current = current.get(key)
                else:
                    ok = False
                    break
            if ok:
                choices = normalize_checkpoint_values(current)
                if choices:
                    return choices

    found: List[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "ckpt_name":
                    for item in normalize_checkpoint_values(value):
                        if item not in found:
                            found.append(item)
                _walk(value)
        elif isinstance(obj, list):
            for value in obj:
                _walk(value)

    _walk(payload)
    return found
