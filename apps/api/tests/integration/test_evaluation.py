import json
from pathlib import Path

import numpy as np
import pytest

from app import cli
from app.embeddings.hashing import HashingEmbedder
from app.evaluation.dataset import load_dataset
from app.evaluation.report import report_to_json, report_to_markdown
from app.evaluation.runner import DEFAULT_CONFIG, EvalConfig, run_evaluation, sqlite_database
from app.services.chunking import ChunkingStrategy


class FailingEmbedder(HashingEmbedder):
    """Test double: embedding fails, so documents end up processed but unembedded."""

    def embed(self, texts: list[str]) -> np.ndarray:  # type: ignore[override]
        raise RuntimeError("simulated embedding failure")


def test_evaluation_runs_every_query_in_every_mode() -> None:
    dataset = load_dataset()

    report = run_evaluation(
        dataset,
        HashingEmbedder(),
        backend="sqlite",
        database=sqlite_database,
        configs=(DEFAULT_CONFIG, EvalConfig(ChunkingStrategy.FIXED, 400)),
    )

    assert [s.config for s in report.configs] == ["structured-1200", "fixed-400"]
    assert report.configs[1].chunks > report.configs[0].chunks
    assert len(report.outcomes) == 2 * 3 * len(dataset.queries)
    rows = report.summary()
    assert len(rows) == 2 * 3 * 4  # configs x modes x (all + 3 categories)
    for row in rows:
        assert all(0.0 <= value <= 1.0 for value in row.recall.values())
        assert row.recall[1] <= row.recall[3] <= row.recall[5] <= row.recall[10]
        assert 0.0 <= row.mrr <= 1.0
    # Keyword search does not depend on the embedder: exact codes and names rank first.
    exact_keyword = next(
        r for r in rows if (r.config, r.mode, r.category) == ("structured-1200", "keyword", "exact")
    )
    assert exact_keyword.recall[1] == 1.0


def test_reports_render_json_and_markdown() -> None:
    report = run_evaluation(
        load_dataset(), HashingEmbedder(), backend="sqlite", database=sqlite_database
    )

    data = json.loads(report_to_json(report))
    markdown = report_to_markdown(report)

    assert data["model_id"] == "hashing-v1-384"
    assert len(data["outcomes"]) == 180
    assert "| structured-1200 | hybrid |" in markdown
    assert "## By category: structured-1200" in markdown


def test_evaluation_refuses_missing_vectors() -> None:
    with pytest.raises(RuntimeError, match="vectors"):
        run_evaluation(
            load_dataset(), FailingEmbedder(), backend="sqlite", database=sqlite_database
        )


def test_evaluate_command_writes_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("EASA_DATABASE_URL", f"sqlite:///{(tmp_path / 'unused.db').as_posix()}")

    assert cli.main(["evaluate", "--output-dir", str(tmp_path / "out")]) == 0

    written = sorted(p.suffix for p in (tmp_path / "out").iterdir())
    assert written == [".json", ".md"]


def test_postgres_evaluation_needs_a_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASA_EMBEDDING_PROVIDER", "hashing")

    assert cli.main(["evaluate", "--backend", "postgres", "--output-dir", str(tmp_path)]) == 1
    assert cli.main(["evaluate-hnsw", "--output-dir", str(tmp_path)]) == 1
    assert not list(tmp_path.iterdir())
