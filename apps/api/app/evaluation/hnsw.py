"""Exact versus HNSW vector search on PostgreSQL with synthetic vectors (P3-M5).

Measures how an approximate pgvector HNSW index would behave for EASA's query
shape (top-k filtered by tenant, model and document status) before deciding
whether to adopt one. Vectors are generated from a seed in a throwaway
database; nothing is added to the application schema.

Synthetic data: real sentence embeddings have a low intrinsic dimension, so
vectors are points of a ``latent_dims``-dimensional Gaussian projected into 384
dimensions plus a little isotropic noise. Queries are fresh points of the same
distribution, not copies of stored vectors. (Clustered data with many
near-identical neighbours was tried first and rejected: its exact top 10 is
dominated by near-ties, so "recall" there measures tie-breaking.)
"""

import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from pgvector.psycopg import register_vector
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.documents import Document, DocumentMediaType, DocumentStatus
from app.db.engine import create_db_engine
from app.db.migrate import upgrade_to_head
from app.db.session import create_session_factory
from app.evaluation.runner import DatabaseFactory
from app.retrieval.pgvector_index import PgvectorIndex

DIMENSIONS = 384
MODEL_ID = "hnsw-benchmark"
TOP_K = 10
INDEX_NAME = "ix_hnsw_benchmark"
# Constant SQL: the model literal must appear in the query text so the planner
# can match the partial index predicate.
CREATE_INDEX_SQL = text(
    "CREATE INDEX ix_hnsw_benchmark ON chunk_embeddings "
    "USING hnsw ((vector::vector(384)) vector_cosine_ops) "
    "WHERE model_id = 'hnsw-benchmark'"
)
HNSW_SEARCH_SQL = text(
    "SELECT e.chunk_id FROM chunk_embeddings e "
    "JOIN document_chunks dc ON dc.id = e.chunk_id "
    "JOIN documents d ON d.id = dc.document_id "
    "WHERE e.model_id = 'hnsw-benchmark' AND e.tenant_id = :tenant "
    "AND d.tenant_id = :tenant AND d.status = 'processed' "
    "ORDER BY (e.vector::vector(384)) <=> CAST(:query AS vector(384)) "
    "LIMIT 10"
)
SETTINGS = ((40, "off"), (40, "relaxed_order"), (100, "off"), (100, "relaxed_order"))


@dataclass(frozen=True)
class SettingResult:
    ef_search: int
    iterative_scan: str
    index_used: bool
    recall_at_10: float
    median_ms: float
    p95_ms: float


@dataclass
class HnswReport:
    vectors: int
    tenants: int
    queries: int
    latent_dims: int
    noise: float
    seed: int
    build_seconds: float = 0.0
    exact_median_ms: float = 0.0
    exact_p95_ms: float = 0.0
    settings: list[SettingResult] = field(default_factory=list)


def _p95(values: list[float]) -> float:
    return float(np.percentile(values, 95))


def _vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vector) + "]"


def _generate(
    rng: np.random.Generator, projection: np.ndarray, count: int, noise: float
) -> np.ndarray:
    """Unit vectors with a low intrinsic dimension (see the module docstring).

    More noise makes the data more isotropic, which is harder for HNSW.
    """
    latent = rng.normal(size=(count, projection.shape[0]))
    vectors = latent @ projection + noise * rng.normal(size=(count, DIMENSIONS))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors.astype(np.float32)


def _load(engine: Engine, vectors: np.ndarray, tenants: list[uuid.UUID]) -> None:
    with create_session_factory(engine)() as session:
        documents = []
        for tenant in tenants:
            document = Document(
                tenant_id=tenant,
                owner_id=uuid.uuid4(),
                filename="synthetic.txt",
                media_type=DocumentMediaType.TXT,
                size_bytes=1,
                sha256=uuid.uuid4().hex * 2,
                status=DocumentStatus.PROCESSED,
            )
            session.add(document)
            documents.append(document)
        session.commit()
        document_ids = [d.id for d in documents]

    now = datetime.now(UTC)
    raw = engine.raw_connection()
    try:
        connection = raw.driver_connection
        register_vector(connection)  # type: ignore[arg-type]
        with connection.cursor() as cursor:  # type: ignore[union-attr]
            chunk_ids = [uuid.uuid4() for _ in range(len(vectors))]
            with cursor.copy(
                "COPY document_chunks (id, document_id, tenant_id, chunk_index, text, "
                "char_start, char_end, created_at) FROM STDIN"
            ) as copy:
                for i, chunk_id in enumerate(chunk_ids):
                    t = i % len(tenants)
                    copy.write_row(
                        (chunk_id, document_ids[t], tenants[t], i, "synthetic", 0, 9, now)
                    )
            with cursor.copy(
                "COPY chunk_embeddings (chunk_id, model_id, tenant_id, dimensions, vector, "
                "created_at) FROM STDIN"
            ) as copy:
                for i, chunk_id in enumerate(chunk_ids):
                    copy.write_row(
                        (chunk_id, MODEL_ID, tenants[i % len(tenants)], DIMENSIONS, vectors[i], now)
                    )
        connection.commit()  # type: ignore[union-attr]
    finally:
        raw.close()
    with engine.begin() as connection:
        connection.execute(text("ANALYZE document_chunks"))
        connection.execute(text("ANALYZE chunk_embeddings"))
        connection.execute(text("ANALYZE documents"))


def _hnsw_search(session: Session, tenant: uuid.UUID, query: np.ndarray) -> list[uuid.UUID]:
    rows = session.execute(HNSW_SEARCH_SQL, {"tenant": tenant, "query": _vector_literal(query)})
    return [row.chunk_id for row in rows]


def run_hnsw_benchmark(
    database: DatabaseFactory,
    *,
    vectors: int = 50_000,
    tenants: int = 10,
    queries: int = 100,
    latent_dims: int = 32,
    noise: float = 0.1,
    seed: int = 7,
) -> HnswReport:
    if vectors < tenants * TOP_K or queries < 1:
        raise ValueError("need at least top_k vectors per tenant and one query")
    report = HnswReport(vectors, tenants, queries, latent_dims, noise, seed)
    rng = np.random.default_rng(seed)
    projection = rng.normal(size=(latent_dims, DIMENSIONS)) / np.sqrt(latent_dims)
    data = _generate(rng, projection, vectors, noise)
    query_vectors = _generate(rng, projection, queries, noise)
    tenant_ids = [uuid.UUID(int=i + 1) for i in range(tenants)]
    query_tenants = [tenant_ids[i] for i in rng.integers(0, tenants, size=queries)]

    with database() as url:
        upgrade_to_head(url)
        engine = create_db_engine(url)
        try:
            _load(engine, data, tenant_ids)
            with create_session_factory(engine)() as session:
                index = PgvectorIndex(session)
                index.search(query_tenants[0], MODEL_ID, query_vectors[0], TOP_K)  # warm-up
                exact, timings = [], []
                for tenant, query in zip(query_tenants, query_vectors, strict=True):
                    started = time.perf_counter()
                    hits = index.search(tenant, MODEL_ID, query, TOP_K)
                    timings.append((time.perf_counter() - started) * 1000)
                    exact.append({h.chunk_id for h in hits})
                report.exact_median_ms = statistics.median(timings)
                report.exact_p95_ms = _p95(timings)

                session.execute(text("SET maintenance_work_mem = '256MB'"))
                # Docker's small /dev/shm cannot hold parallel build workers' memory.
                session.execute(text("SET max_parallel_maintenance_workers = 0"))
                started = time.perf_counter()
                session.execute(CREATE_INDEX_SQL)
                session.commit()
                report.build_seconds = time.perf_counter() - started
                session.execute(text("ANALYZE chunk_embeddings"))

                for ef_search, iterative in SETTINGS:
                    session.execute(
                        text("SELECT set_config('hnsw.ef_search', :value, false)"),
                        {"value": str(ef_search)},
                    )
                    session.execute(
                        text("SELECT set_config('hnsw.iterative_scan', :value, false)"),
                        {"value": iterative},
                    )
                    plan = session.execute(
                        text("EXPLAIN " + HNSW_SEARCH_SQL.text),
                        {"tenant": query_tenants[0], "query": _vector_literal(query_vectors[0])},
                    ).scalars()
                    index_used = INDEX_NAME in "\n".join(plan)
                    _hnsw_search(session, query_tenants[0], query_vectors[0])  # warm-up
                    recalls, timings = [], []
                    for tenant, query, expected in zip(
                        query_tenants, query_vectors, exact, strict=True
                    ):
                        started = time.perf_counter()
                        found = _hnsw_search(session, tenant, query)
                        timings.append((time.perf_counter() - started) * 1000)
                        recalls.append(len(expected.intersection(found)) / len(expected))
                    report.settings.append(
                        SettingResult(
                            ef_search=ef_search,
                            iterative_scan=iterative,
                            index_used=index_used,
                            recall_at_10=float(np.mean(recalls)),
                            median_ms=statistics.median(timings),
                            p95_ms=_p95(timings),
                        )
                    )
        finally:
            engine.dispose()
    return report


def hnsw_report_to_markdown(report: HnswReport) -> str:
    lines = [
        "# HNSW benchmark run",
        "",
        f"{report.vectors} synthetic vectors ({DIMENSIONS} dimensions, intrinsic dimension "
        f"{report.latent_dims}, noise {report.noise}, seed {report.seed}) across "
        f"{report.tenants} tenants; {report.queries} queries, top {TOP_K}, "
        "each filtered to one tenant.",
        "",
        f"Exact search (pgvector, no index): median {report.exact_median_ms:.1f} ms, "
        f"p95 {report.exact_p95_ms:.1f} ms. HNSW build (m=16, ef_construction=64): "
        f"{report.build_seconds:.1f} s.",
        "",
        "| ef_search | iterative_scan | Index used | Recall@10 vs exact | Median ms | p95 ms |",
        "|---|---|---|---|---|---|",
        *(
            f"| {s.ef_search} | {s.iterative_scan} | {'yes' if s.index_used else 'no'} | "
            f"{s.recall_at_10:.3f} | {s.median_ms:.1f} | {s.p95_ms:.1f} |"
            for s in report.settings
        ),
    ]
    return "\n".join(lines) + "\n"
