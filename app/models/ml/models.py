from __future__ import annotations

"""
Crypto model catalog helpers.

Why this module exists:
- Provide typed metadata objects for `/crypto/models`.
- Discover locally available trained model artifacts without importing heavy ML stacks.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from pydantic import BaseModel, Field

_SUPPORTED_EXTS = {".joblib", ".pkl", ".pickle", ".onnx", ".pt", ".pth"}
_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH")
_PAIR_RE = re.compile(r"\b([A-Z0-9]{2,12})(USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH)\b")
_HORIZON_RE = re.compile(r"\b(\d{1,4})\s*(m|min|h|d)\b", flags=re.IGNORECASE)
_MODEL_TYPES = ("ensemble", "rf", "xgb", "cat", "dl", "seta")
_CANONICAL_FILENAMES = {
    "rf_model",
    "xgb_model",
    "cat_model",
    "lstm_model",
    "calibrated_stacking_model",
    "calibrated_model",
    "ensemble_model",
}
_CANONICAL_MODEL_TYPE_MAP = {
    "rf_model": "rf",
    "xgb_model": "xgb",
    "cat_model": "cat",
    "lstm_model": "dl",
    "calibrated_stacking_model": "seta",
    "calibrated_model": "seta",
    "ensemble_model": "ensemble",
}
_BASE_HINTS = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "DOT",
    "TRX",
    "LTC",
    "BCH",
    "LINK",
    "ATOM",
    "MATIC",
}


class TrainedModel(BaseModel):
    symbol: str
    horizon_minutes: int = Field(default=15, ge=1)
    model_type: str = "ensemble"
    artifact_path: Optional[str] = None
    interval_minutes: Optional[int] = None
    dataset_hash: Optional[str] = None
    trained_at: Optional[str] = None
    validation_mode: Optional[str] = None
    provenance_path: Optional[str] = None


class ModelRegistryEntry(BaseModel):
    symbol: str
    horizon_minutes: int = Field(default=15, ge=1)
    interval_minutes: Optional[int] = None
    available_model_types: List[str]
    dataset_hash: Optional[str] = None
    trained_at: Optional[str] = None
    validation_mode: Optional[str] = None


class ModelCatalog(BaseModel):
    available: List[str]
    default: str
    trained: List[TrainedModel]
    supported: List[str] = Field(default_factory=list)
    installed: List[str] = Field(default_factory=list)


def _iter_artifact_versions(root: Path) -> Iterator[Path]:
    """Yield pointed artifact version dirs (`latest.txt`, `previous.txt`) when present."""
    for pointer_name in ("latest.txt", "previous.txt"):
        pointer = root / pointer_name
        if not pointer.exists():
            continue
        try:
            version = pointer.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not version:
            continue
        version_dir = root / version
        if version_dir.exists() and version_dir.is_dir():
            yield version_dir


def _looks_like_crypto_artifact(path: Path) -> bool:
    stem_lower = path.stem.lower()
    stem_upper = path.stem.upper()
    parent_tokens = {p.lower() for p in path.parts}

    if stem_lower in _CANONICAL_FILENAMES:
        return True
    if _PAIR_RE.search(stem_upper):
        return True
    if "crypto" in stem_lower or "crypto" in parent_tokens:
        return True
    if any(model_type in stem_lower for model_type in _MODEL_TYPES):
        if any(base in stem_upper for base in _BASE_HINTS):
            return True
    return False


def _iter_candidate_files() -> Iterable[Path]:
    """Scan bounded paths for likely crypto model artifacts."""
    env_dir = (os.getenv("CRYPTO_MODELS_DIR") or "").strip()
    model_dir = (os.getenv("MODEL_DIR") or "").strip()
    artifacts_dir = (os.getenv("CRYPTO_ARTIFACTS_DIR") or "artifacts/crypto_models").strip()
    candidates: List[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))
    if model_dir:
        candidates.append(Path(model_dir))
    if artifacts_dir:
        artifacts_root = Path(artifacts_dir)
        candidates.append(artifacts_root)
        candidates.extend(_iter_artifact_versions(artifacts_root))
    candidates.extend([Path("models/crypto"), Path("models/ml"), Path("models")])

    seen: set[Path] = set()
    for root in candidates:
        root = root.resolve()
        if root in seen or not root.exists():
            continue
        seen.add(root)
        if root.is_file():
            if root.suffix.lower() in _SUPPORTED_EXTS and _looks_like_crypto_artifact(root):
                yield root
            continue
        # Bounded depth and skip heavy unrelated folders.
        for entry in root.iterdir():
            name = entry.name.lower()
            if name in {"comfyui", "embeddings", "__pycache__"}:
                continue
            if entry.is_file() and entry.suffix.lower() in _SUPPORTED_EXTS and _looks_like_crypto_artifact(entry):
                yield entry
            elif entry.is_dir():
                for child in entry.glob("*"):
                    if child.is_file() and child.suffix.lower() in _SUPPORTED_EXTS and _looks_like_crypto_artifact(child):
                        yield child


def _normalize_pair_from_name(name_upper: str) -> str:
    match = _PAIR_RE.search(name_upper)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    # Fallback to base symbol hints; default to USDT pair.
    base_match = re.search(r"\b(BTC|ETH|BNB|SOL|XRP|ADA|DOGE|AVAX|DOT|TRX|LTC|BCH|LINK|ATOM|MATIC)\b", name_upper)
    if base_match:
        return f"{base_match.group(1)}USDT"
    return "BTCUSDT"


def _extract_horizon_minutes(name_lower: str) -> int:
    match = _HORIZON_RE.search(name_lower)
    if not match:
        return 15
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit in {"m", "min"}:
        return max(1, value)
    if unit == "h":
        return max(1, value) * 60
    if unit == "d":
        return max(1, value) * 1440
    return 15


def _extract_model_type(name_lower: str) -> str:
    canonical = _CANONICAL_MODEL_TYPE_MAP.get(name_lower)
    if canonical:
        return canonical
    for model_type in _MODEL_TYPES:
        if model_type in name_lower:
            return model_type
    return "ensemble"


def _load_artifact_meta(artifact: Path) -> Optional[dict]:
    candidates = [
        artifact.with_suffix(f"{artifact.suffix}.meta.json"),
        artifact.parent / "calibrated_stacking_model.joblib.meta.json",
        artifact.parent / "training_provenance.json",
    ]
    seen: set[Path] = set()
    for cand in candidates:
        if cand in seen or not cand.exists():
            continue
        seen.add(cand)
        try:
            return json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _normalize_supported_symbols(meta: Optional[dict], fallback_pair: str) -> List[str]:
    if not isinstance(meta, dict):
        return [fallback_pair]
    supported = meta.get("supported_symbols")
    if isinstance(supported, list):
        out = []
        for item in supported:
            text = str(item or "").strip().upper()
            if text:
                out.append(text)
        if out:
            return sorted(set(out))
    return [fallback_pair]


def discover_trained_models() -> List[TrainedModel]:
    """
    Discover trained-model artifact metadata from local filesystem.
    Returns a deduplicated sorted list by (symbol, horizon, model_type).
    """
    rows: Dict[tuple[str, int, str], tuple[TrainedModel, float]] = {}
    for artifact in _iter_candidate_files():
        stem_lower = artifact.stem.lower()
        stem_upper = artifact.stem.upper()
        pair = _normalize_pair_from_name(stem_upper)
        meta = _load_artifact_meta(artifact)
        horizon_minutes = int(
            ((meta or {}).get("training") or {}).get("horizon_minutes")
            or (meta or {}).get("horizon_minutes")
            or _extract_horizon_minutes(stem_lower)
        )
        interval_minutes = ((meta or {}).get("time") or {}).get("interval_minutes")
        model_type = _extract_model_type(stem_lower)
        try:
            mtime = float(artifact.stat().st_mtime)
        except Exception:
            mtime = 0.0
        for symbol in _normalize_supported_symbols(meta, pair):
            key = (symbol, horizon_minutes, model_type)
            model = TrainedModel(
                symbol=symbol,
                horizon_minutes=horizon_minutes,
                model_type=model_type,
                artifact_path=str(artifact),
                interval_minutes=int(interval_minutes) if isinstance(interval_minutes, (int, float)) else None,
                dataset_hash=str((meta or {}).get("dataset_hash") or "") or None,
                trained_at=str((meta or {}).get("trained_at") or "") or None,
                validation_mode=str((meta or {}).get("validation_mode") or "") or None,
                provenance_path=(
                    str(artifact.parent / "calibrated_stacking_model.joblib.meta.json")
                    if (artifact.parent / "calibrated_stacking_model.joblib.meta.json").exists()
                    else None
                ),
            )
            current = rows.get(key)
            if current is None or mtime >= current[1]:
                rows[key] = (model, mtime)

    models = [row[0] for row in rows.values()]
    models.sort(key=lambda item: (item.symbol, item.horizon_minutes, item.model_type))
    return models


def build_model_registry(models: Optional[List[TrainedModel]] = None) -> List[ModelRegistryEntry]:
    grouped: Dict[tuple[str, int, Optional[int]], List[TrainedModel]] = {}
    for item in models or discover_trained_models():
        key = (item.symbol, item.horizon_minutes, item.interval_minutes)
        grouped.setdefault(key, []).append(item)

    entries: List[ModelRegistryEntry] = []
    for (symbol, horizon_minutes, interval_minutes), rows in sorted(grouped.items()):
        sorted_rows = sorted(
            rows,
            key=lambda row: (
                str(row.trained_at or ""),
                str(row.dataset_hash or ""),
                str(row.artifact_path or ""),
            ),
            reverse=True,
        )
        latest = sorted_rows[0]
        entries.append(
            ModelRegistryEntry(
                symbol=symbol,
                horizon_minutes=horizon_minutes,
                interval_minutes=interval_minutes,
                available_model_types=sorted(
                    {str(row.model_type or "ensemble") for row in rows} | {"ensemble"}
                ),
                dataset_hash=latest.dataset_hash,
                trained_at=latest.trained_at,
                validation_mode=latest.validation_mode,
            )
        )
    return entries
