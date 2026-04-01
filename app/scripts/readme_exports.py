#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ENV = ROOT / ".env.strict.full.local.example"
DEFAULT_ENV_OUT = ROOT / ".env.strict.full.local"
_CONTRACT_MODES = {"full", "strict", "none"}


def _parse_env_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            pairs.append((key, value))
    return pairs


def _load_example_pairs() -> list[tuple[str, str]]:
    if EXAMPLE_ENV.exists():
        return _parse_env_pairs(EXAMPLE_ENV.read_text(encoding="utf-8"))
    return [
        ("AEGIS_RUNTIME_PROFILE", "strict"),
        ("AEGIS_PRODUCT_TRACK", "full"),
        ("AEGIS_AUTH_MODE", "on"),
        ("AEGIS_API_KEY", '"aegis-demo-key-2026-strong"'),
        ("FILES_API_KEY", '"aegis-demo-key-2026-strong"'),
        ("ADMIN_API_KEY", '"set-a-different-strong-key"'),
        ("DATABASE_URL", '"postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/aegis"'),
        ("AEGIS_IMAGE_ENDPOINT", '"http://127.0.0.1:8188/prompt"'),
        ("AEGIS_IMAGE_CKPT", '"DreamShaper_8_pruned.safetensors"'),
        ("AEGIS_IMAGE_TIMEOUT", "90"),
        ("AEGIS_BROWSER_BINARY", '"/usr/bin/google-chrome-stable"'),
        ("AEGIS_CORS_ORIGINS", '"http://127.0.0.1:8000"'),
        ("FILES_AV_FAIL_OPEN", "0"),
        ("AEGIS_HSTS_SECONDS", "31536000"),
        ("TOKENIZERS_PARALLELISM", "false"),
    ]


def _with_contract_mode(pairs: list[tuple[str, str]], contract_mode: str) -> list[tuple[str, str]]:
    normalized = contract_mode.strip().lower()
    if normalized not in _CONTRACT_MODES:
        normalized = "full"
    out: list[tuple[str, str]] = []
    seen = False
    for key, value in pairs:
        if key == "AEGIS_START_CONTRACT_MODE":
            out.append((key, normalized))
            seen = True
            continue
        out.append((key, value))
    if not seen:
        out.append(("AEGIS_START_CONTRACT_MODE", normalized))
    return out


def render_env(contract_mode: str = "full") -> str:
    pairs = _with_contract_mode(_load_example_pairs(), contract_mode)
    return "\n".join(f"{key}={value}" for key, value in pairs) + "\n"


def render_shell(contract_mode: str = "full") -> str:
    pairs = _with_contract_mode(_load_example_pairs(), contract_mode)
    return "\n".join(f"export {key}={value}" for key, value in pairs) + "\n"


def write_env_file(path: Path, *, contract_mode: str = "full", overwrite: bool = False) -> Path:
    target = path.resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_env(contract_mode), encoding="utf-8")
    return target


def copy_to_clipboard(text: str) -> bool:
    commands = (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["pbcopy"],
    )
    for cmd in commands:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True, check=True)
                return True
            except Exception:
                continue
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the local strict/full export block documented in README.MD."
    )
    parser.add_argument("--format", choices=["shell", "env"], default="shell")
    parser.add_argument("--contract-mode", choices=["full", "strict", "none"], default="full")
    parser.add_argument(
        "--write-env-file",
        nargs="?",
        const=str(DEFAULT_ENV_OUT),
        default="",
        help="Write .env-style output to the given file. Defaults to .env.strict.full.local when no path is provided.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--copy", action="store_true", help="Copy the rendered output to the system clipboard when possible.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rendered = render_shell(args.contract_mode) if args.format == "shell" else render_env(args.contract_mode)

    if args.write_env_file:
        target = write_env_file(Path(args.write_env_file), contract_mode=args.contract_mode, overwrite=args.overwrite)
        print(f"[ok] wrote {target}", file=sys.stderr)

    if args.copy:
        if copy_to_clipboard(rendered):
            print("[ok] copied exports to clipboard", file=sys.stderr)
        else:
            print("[warn] clipboard tool not available; printed exports to stdout instead", file=sys.stderr)

    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
