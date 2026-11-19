"""The evaluation commands (P8-M4): one command for all, run metadata, the manifest check."""

import json
from pathlib import Path

import pytest

from app import cli
from app.evaluation.manifest import load_manifest


@pytest.fixture
def hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    # No model files and no chat model: the evaluations that need neither run.
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("EASA_LOG_LEVEL", "WARNING")


@pytest.mark.usefixtures("hashing")
def test_evaluate_all_runs_what_it_can_and_explains_what_it_skips(tmp_path: Path) -> None:
    out = tmp_path / "reports"

    assert cli.main(["evaluate-all", "--no-model", "--output-dir", str(out)]) == 0

    summary = next(out.glob("*-all.md")).read_text(encoding="utf-8")
    assert "| Retrieval, SQLite | written |" in summary
    assert "| Access, search only, SQLite | written |" in summary
    assert "| Retrieval, PostgreSQL | skipped: EASA_EVAL_POSTGRES_URL not set |" in summary
    assert "| Answers | skipped: --no-model |" in summary
    assert "| Agent | skipped: --no-model |" in summary
    assert f"Data version {load_manifest().version}" in summary

    retrieval = json.loads(next(out.glob("*-sqlite-default.json")).read_text(encoding="utf-8"))
    run = retrieval["run"]
    assert run["evaluation"] == "retrieval"
    assert run["data_version"] == load_manifest().version
    assert run["embedding_model"].startswith("hashing")
    assert run["settings"] == {"backend": "sqlite", "configs": "default", "top_k": 10}
    access = next(out.glob("*-access-sqlite-search.md")).read_text(encoding="utf-8")
    assert access.splitlines()[0] == "# Access leakage evaluation run"
    assert "Settings: backend=sqlite, surfaces=search." in access


@pytest.mark.usefixtures("hashing")
def test_evaluations_refuse_data_that_does_not_match_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "check_manifest", lambda: ["queries.json: changed (SHA-256 differs)"])

    for command in ("evaluate", "evaluate-agent", "evaluate-all"):
        assert cli.main([command, "--output-dir", str(tmp_path)]) == 1
    assert list(tmp_path.glob("*.md")) == []


def test_the_manifest_command_refuses_an_old_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(version: int) -> None:
        raise ValueError("the new version must be higher than 1")

    monkeypatch.setattr(cli, "write_manifest", refuse)

    assert cli.main(["update-eval-manifest", "--version", "1"]) == 1
