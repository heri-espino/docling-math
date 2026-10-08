"""Headless desktop orchestration tests; no Tk or Docling models are loaded."""

import json
from pathlib import Path

import pytest

from docling_math.desktop import (
    WorkerStep,
    hidden_process_kwargs,
    plan_extract,
    plan_rename,
    plan_upgrade,
    resolve_or_create_library,
    run_worker,
    worker_command,
)


def _library(tmp_path: Path) -> Path:
    project = tmp_path / "library"
    project.mkdir()
    return resolve_or_create_library(project, create=True)


def test_create_and_open_library_from_project_or_bib(tmp_path):
    bib = _library(tmp_path)
    assert (bib / "pdf").is_dir()
    assert (bib / "extracted").is_dir()
    assert (bib / "references").is_dir()
    assert resolve_or_create_library(bib.parent) == bib
    assert resolve_or_create_library(bib) == bib


def test_new_library_creation_is_explicit(tmp_path):
    project = tmp_path / "empty"
    project.mkdir()
    with pytest.raises(FileNotFoundError):
        resolve_or_create_library(project, create=False)
    assert not (project / "bib").exists()


def test_extract_uses_sequential_upgrade_with_vault(tmp_path):
    bib = _library(tmp_path)
    steps = plan_extract(
        bib,
        strategy="smart",
        device="cuda",
        rename_pdfs=True,
        write_pdf_metadata=False,
        create_vault=True,
        obsidian=True,
    )
    assert len(steps) == 2
    assert steps[0].kind == "extract"
    assert "--rename-pdfs" in steps[0].arguments
    assert "--obsidian" in steps[0].arguments
    assert "--write-pdf-metadata" not in steps[0].arguments
    assert steps[1].kind == "upgrade"
    assert "--corpus-dir" in steps[1].arguments
    assert "--no-vault" not in steps[1].arguments


def test_upgrade_opt_out(tmp_path):
    bib = _library(tmp_path)
    step = plan_upgrade(bib, obsidian=False, create_vault=False)
    assert step.kind == "upgrade"
    assert "--no-obsidian" in step.arguments
    assert "--no-vault" in step.arguments


def test_rename_is_previewed_before_apply(tmp_path):
    bib = _library(tmp_path)
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"old.pdf": "new.pdf"}), encoding="utf-8")

    preview = plan_rename(bib, mapping, dry_run=True)
    apply = plan_rename(bib, mapping, dry_run=False)
    assert "--dry-run" in preview.arguments
    assert "--dry-run" not in apply.arguments
    assert preview.kind == apply.kind == "rename"


def test_reject_invalid_plan_values(tmp_path):
    bib = _library(tmp_path)
    with pytest.raises(ValueError):
        plan_extract(bib, device="super-gpu")
    with pytest.raises(ValueError):
        plan_extract(bib, strategy="unsafe")
    with pytest.raises(ValueError):
        plan_upgrade(bib, create_vault=False, vault_path=tmp_path)


def test_hidden_worker_never_inherits_console_stdin(tmp_path):
    kwargs = hidden_process_kwargs(log_path=tmp_path / "job.log")
    assert kwargs["env"]["DOCLING_MATH_LOG_FILE"] == str(tmp_path / "job.log")
    assert kwargs["env"]["DOCLING_MATH_ALLOW_CPU"] == "0"
    assert kwargs["stdin"] is not None
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    consent = hidden_process_kwargs(log_path=tmp_path / "job.log", allow_cpu=True)
    assert consent["env"]["DOCLING_MATH_ALLOW_CPU"] == "1"


def test_worker_unknown_job_fails():
    assert run_worker("unknown", []) == 2


def test_worker_command_is_argument_list(tmp_path):
    step = WorkerStep("upgrade", ("--corpus-dir", "C:\\My papers"), "Upgrade")
    command = worker_command(step, executable="python")
    assert command[0] == "python"
    assert "--docling-math-worker" in command
    assert "C:\\My papers" in command
