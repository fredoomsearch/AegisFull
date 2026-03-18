from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PROFILE = {
    "skills": [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "Angular",
        "Django",
        "chatbot",
    ]
}


def load_profile(path: str | None = None) -> dict[str, Any]:
    if not path:
        return dict(DEFAULT_PROFILE)
    target = Path(path)
    if not target.exists():
        return dict(DEFAULT_PROFILE)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_PROFILE)
    if not isinstance(data, dict):
        return dict(DEFAULT_PROFILE)
    return data


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.-]+", (text or "").lower())


def _normalized_skill(skill: str) -> str:
    raw = str(skill or "").strip()
    return raw.lower()


def compute_match(profile: dict[str, Any], job_text: str, role: str) -> tuple[float, list[str], list[str], list[str]]:
    skills = [str(item).strip() for item in (profile.get("skills") or DEFAULT_PROFILE["skills"]) if str(item).strip()]
    haystack = " ".join([job_text or "", role or ""]).lower()
    matched_skills = [skill for skill in skills if _normalized_skill(skill) in haystack]

    term_candidates = {"chatbot", "fastapi", "postgresql", "docker", "angular", "django", "python"}
    matched_terms = sorted(term for term in term_candidates if term in haystack)
    gaps = [skill for skill in skills if skill not in matched_skills and _normalized_skill(skill) not in matched_terms]

    score = 0.0
    if skills:
        score += len(matched_skills) / len(skills)
    if matched_terms:
        score += min(0.5, len(matched_terms) * 0.1)
    return round(score, 4), matched_skills, matched_terms, gaps


def _slugify(parts: Iterable[str]) -> str:
    raw = "-".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
    cleaned = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return cleaned or "application-bundle"


def _job_text_from_args(args) -> str:
    if getattr(args, "job_text", None):
        return str(args.job_text)
    job_file = getattr(args, "job_file", None)
    if job_file:
        target = Path(job_file)
        if target.exists():
            return target.read_text(encoding="utf-8")
    return ""


def prepare_bundle(args) -> int:
    profile = load_profile(getattr(args, "profile", None))
    company = str(getattr(args, "company", "") or "Company").strip()
    role = str(getattr(args, "role", "") or "Role").strip()
    platform = str(getattr(args, "platform", "") or "unknown").strip()
    lang = str(getattr(args, "lang", "en") or "en").strip().lower()
    output_dir = Path(str(getattr(args, "output_dir", ".") or ".")).resolve()
    bundle_dir = output_dir / _slugify([company, role])
    bundle_dir.mkdir(parents=True, exist_ok=True)

    job_text = _job_text_from_args(args)
    score, matched_skills, matched_terms, gaps = compute_match(profile, job_text, role)
    payload = {
        "company": company,
        "role": role,
        "platform": platform,
        "lang": lang,
        "score": score,
        "matched_skills": matched_skills,
        "matched_terms": matched_terms,
        "gaps": gaps,
        "job_text": job_text,
    }
    (bundle_dir / "application_bundle.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        f"# {company} - {role}",
        "",
        f"- Platform: {platform}",
        f"- Language: {lang}",
        f"- Match score: {score}",
        f"- Matched skills: {', '.join(matched_skills) or 'n/a'}",
        f"- Matched terms: {', '.join(matched_terms) or 'n/a'}",
        f"- Gaps: {', '.join(gaps) or 'n/a'}",
    ]
    (bundle_dir / "application_bundle.md").write_text("\n".join(md), encoding="utf-8")
    return 0


def batch_prepare(args) -> int:
    csv_path = Path(str(getattr(args, "csv", "") or ""))
    output_dir = Path(str(getattr(args, "output_dir", ".") or ".")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = load_profile(getattr(args, "profile", None))
    rows_out: list[dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row_ns = type("Args", (), {
                "company": row.get("company") or "",
                "role": row.get("role") or "",
                "platform": row.get("platform") or "",
                "job_file": str((csv_path.parent / (row.get("job_file") or "")).resolve()) if row.get("job_file") else None,
                "job_text": row.get("job_text") or "",
                "lang": row.get("lang") or "en",
                "profile": None,
                "output_dir": str(output_dir),
            })()
            prepare_bundle(row_ns)
            score, matched_skills, matched_terms, gaps = compute_match(
                profile,
                _job_text_from_args(row_ns),
                row.get("role") or "",
            )
            rows_out.append(
                {
                    "company": row.get("company") or "",
                    "role": row.get("role") or "",
                    "platform": row.get("platform") or "",
                    "score": score,
                    "matched_skills": ",".join(matched_skills),
                    "matched_terms": ",".join(matched_terms),
                    "gaps": ",".join(gaps),
                }
            )

    summary_path = output_dir / "batch_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["company", "role", "platform", "score", "matched_skills", "matched_terms", "gaps"],
        )
        writer.writeheader()
        writer.writerows(rows_out)
    return 0
