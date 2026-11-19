"""The evaluation data manifest and run metadata (P8-M4)."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.evaluation import run_info as run_info_module
from app.evaluation.manifest import (
    MANIFEST_NAME,
    check_manifest,
    file_digests,
    load_manifest,
    manifest_sha256,
    write_manifest,
)
from app.evaluation.metrics import format_tokens, median_tokens
from app.evaluation.run_info import RunInfo, git_commit, run_info, with_run_info


def test_the_committed_manifest_matches_the_evaluation_data() -> None:
    # Fails when a file under eval/ changes without update-eval-manifest.
    assert check_manifest() == []
    manifest = load_manifest()
    assert manifest.version >= 1
    assert len(manifest.files) == 23
    assert "agent.json" in manifest.files
    assert MANIFEST_NAME not in manifest.files


def data(tmp_path: Path) -> Path:
    root = tmp_path / "eval"
    (root / "corpus").mkdir(parents=True)
    (root / "queries.json").write_text("{}", encoding="utf-8")
    (root / "corpus" / "a.txt").write_text("Leave is 25 days.", encoding="utf-8")
    return root


def test_check_manifest_reports_every_difference(tmp_path: Path) -> None:
    root = data(tmp_path)
    assert check_manifest(root) == ["manifest.json is missing"]
    write_manifest(1, root)
    assert check_manifest(root) == []
    assert set(file_digests(root)) == {"queries.json", "corpus/a.txt"}

    (root / "corpus" / "a.txt").write_text("Leave is 26 days.", encoding="utf-8")
    (root / "queries.json").unlink()
    (root / "corpus" / "b.txt").write_text("New.", encoding="utf-8")

    assert sorted(check_manifest(root)) == [
        "corpus/a.txt: changed (SHA-256 differs)",
        "corpus/b.txt: not in the manifest",
        "queries.json: listed but missing",
    ]


def test_an_invalid_manifest_is_reported(tmp_path: Path) -> None:
    root = data(tmp_path)
    (root / MANIFEST_NAME).write_text('{"files": {}}', encoding="utf-8")

    assert check_manifest(root) == ["manifest.json is invalid: KeyError"]


def test_a_new_manifest_needs_a_higher_version(tmp_path: Path) -> None:
    root = data(tmp_path)
    write_manifest(1, root)
    first = manifest_sha256(root)

    with pytest.raises(ValueError, match="higher than 1"):
        write_manifest(1, root)
    (root / "corpus" / "a.txt").write_text("Changed.", encoding="utf-8")
    write_manifest(2, root)

    assert load_manifest(root).version == 2
    assert manifest_sha256(root) != first
    assert (root / MANIFEST_NAME).read_bytes().endswith(b"}\n")


def test_run_info_names_the_data_models_and_settings(tmp_path: Path) -> None:
    root = data(tmp_path)
    write_manifest(3, root)
    started = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)

    run = run_info(
        "agent",
        started,
        embedding_model="hash",
        chat_model="fake-chat-v1",
        settings={"tasks": 26},
        root=root,
    )

    assert (run.evaluation, run.data_version, run.manifest_sha256) == (
        "agent",
        3,
        manifest_sha256(root),
    )
    assert (run.embedding_model, run.chat_model, run.settings) == (
        "hash",
        "fake-chat-v1",
        {"tasks": 26},
    )
    assert run.started_at == "2026-11-19T10:00:00+00:00"
    assert run.duration_s > 0


def test_git_commit_is_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("git"):
        assert git_commit(tmp_path) is None  # not a repository
    monkeypatch.setattr(run_info_module.shutil, "which", lambda _name: None)
    assert git_commit(tmp_path) is None


RUN = RunInfo(
    evaluation="agent",
    started_at="2026-11-19T10:00:00+00:00",
    finished_at="2026-11-19T10:10:00+00:00",
    duration_s=600.0,
    data_version=2,
    manifest_sha256="ab" * 32,
    git_commit="abc123",
    python="3.14.0",
    embedding_model="bge",
    chat_model="qwen",
    settings={"tasks": 26, "temperature": 0.0},
)


def test_reports_get_the_run_first() -> None:
    files = with_run_info({"json": '{"model_id": "qwen"}', "md": "# Title\n\nBody\n"}, RUN)

    report = json.loads(files["json"])
    assert list(report) == ["run", "model_id"]
    assert report["run"]["data_version"] == 2
    lines = files["md"].split("\n")
    assert lines[0] == "# Title"
    assert "Data version 2 (manifest SHA-256 `abababababab`)" in lines[2]
    assert "Code: `abc123`" in lines[2]
    assert "Settings: tasks=26, temperature=0.0." in lines[3]
    assert lines[-2] == "Body"


def test_reports_that_are_lists_are_wrapped() -> None:
    files = with_run_info({"json": "[1, 2]"}, RUN)

    assert json.loads(files["json"])["report"] == [1, 2]


def test_median_tokens_ignores_calls_without_counts() -> None:
    assert median_tokens([(100, 20), (None, None), (50, 10), (30, None)]) == 60
    assert median_tokens([(None, None)]) is None
    assert (format_tokens(None), format_tokens(59.6)) == ("-", "60")
