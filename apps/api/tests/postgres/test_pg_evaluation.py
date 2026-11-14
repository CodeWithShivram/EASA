import pytest

from app.embeddings.hashing import HashingEmbedder
from app.evaluation.dataset import load_dataset
from app.evaluation.hnsw import run_hnsw_benchmark
from app.evaluation.runner import (
    EvaluationReport,
    SummaryRow,
    postgres_database,
    run_evaluation,
    sqlite_database,
)
from tests.postgres.conftest import require_admin_url


def test_semantic_results_match_sqlite() -> None:
    database = postgres_database(require_admin_url())
    dataset = load_dataset()

    on_postgres = run_evaluation(dataset, HashingEmbedder(), backend="postgres", database=database)
    on_sqlite = run_evaluation(
        dataset, HashingEmbedder(), backend="sqlite", database=sqlite_database
    )

    def semantic(report: EvaluationReport) -> SummaryRow:
        return next(r for r in report.summary() if (r.mode, r.category) == ("semantic", "all"))

    # Same vectors and exact search; only the order of exactly tied scores may differ.
    assert semantic(on_postgres).recall == pytest.approx(semantic(on_sqlite).recall, abs=0.05)
    assert semantic(on_postgres).mrr == pytest.approx(semantic(on_sqlite).mrr, abs=0.05)
    assert len(on_postgres.outcomes) == len(on_sqlite.outcomes)


def test_hnsw_benchmark_runs() -> None:
    report = run_hnsw_benchmark(
        postgres_database(require_admin_url()), vectors=2_000, tenants=2, queries=10
    )

    assert report.build_seconds > 0
    assert len(report.settings) == 4
    assert all(0.0 <= s.recall_at_10 <= 1.0 for s in report.settings)
    # At this size the planner may prefer an exact scan; then results must be exact.
    assert all(s.recall_at_10 == 1.0 for s in report.settings if not s.index_used)
