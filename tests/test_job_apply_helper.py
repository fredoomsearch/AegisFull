from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "scripts" / "job_apply_helper.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("job_apply_helper", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compute_match_uses_experience_keywords_for_gaps():
    module = load_module()
    profile = module.load_profile()
    score, matched_skills, matched_terms, gaps = module.compute_match(
        profile,
        "Remote Python role building chatbots with FastAPI and PostgreSQL for startup clients.",
        "Python Developer",
    )

    assert score > 0
    assert "Python" in matched_skills
    assert "chatbot" in matched_terms
    assert "chatbot" not in gaps


def test_prepare_bundle_writes_expected_files(tmp_path):
    module = load_module()
    job_file = tmp_path / "job.txt"
    job_file.write_text(
        (
            "Need a full stack engineer with Angular, Docker, Django, and PostgreSQL "
            "experience for a remote product team."
        ),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        company="Braintrust Client",
        role="Full Stack Developer",
        platform="braintrust",
        job_file=str(job_file),
        lang="en",
        profile=None,
        output_dir=str(tmp_path),
        track=False,
    )

    exit_code = module.prepare_bundle(args)

    assert exit_code == 0
    bundle_dir = tmp_path / "braintrust-client-full-stack-developer"
    assert (bundle_dir / "application_bundle.json").exists()
    assert (bundle_dir / "application_bundle.md").exists()


def test_batch_prepare_writes_summary(tmp_path):
    module = load_module()
    job_file = tmp_path / "mercor.txt"
    job_file.write_text(
        "Remote Python and FastAPI role with Docker and PostgreSQL.",
        encoding="utf-8",
    )
    csv_file = tmp_path / "jobs.csv"
    csv_file.write_text(
        (
            "company,role,platform,job_file,job_text,lang\n"
            f"Mercor,Python Developer,mercor,{job_file.name},,\n"
            "Indeed Client,Full Stack Developer,indeed,,Need Angular Django and SQL,EN\n"
        ),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        csv=str(csv_file),
        profile=None,
        output_dir=str(tmp_path / "out"),
        track=False,
    )

    exit_code = module.batch_prepare(args)

    assert exit_code == 0
    assert (tmp_path / "out" / "batch_summary.csv").exists()
