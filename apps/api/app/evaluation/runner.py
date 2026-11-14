"""Run the labelled queries against freshly ingested copies of the corpus.

For each chunking configuration the corpus is uploaded through the normal
document pipeline (validation, extraction, chunking, embedding) into a new,
migrated database, and every query is run in every search mode through
SearchService, exactly as the API does.
"""

import logging
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.identity import Identity
from app.db.documents import DocumentChunk, DocumentStatus
from app.db.embeddings import ChunkEmbedding
from app.db.engine import create_db_engine
from app.db.migrate import upgrade_to_head
from app.db.session import create_session_factory
from app.embeddings.base import Embedder
from app.evaluation.dataset import CATEGORIES, Dataset
from app.evaluation.metrics import evidence_ranks, mean, recall_at_k, reciprocal_rank
from app.retrieval.factory import build_indexes
from app.services.chunking import ChunkingConfig, ChunkingStrategy
from app.services.documents import DocumentService
from app.services.search import SearchMode, SearchService
from app.storage.blob_store import LocalBlobStore

logger = logging.getLogger(__name__)

K_VALUES = (1, 3, 5, 10)
TOP_K = max(K_VALUES)
# Synthetic identity used only for evaluation databases.
EVAL_IDENTITY = Identity(
    tenant_id=uuid.UUID("00000000-0000-4000-8000-0000000000e1"),
    user_id=uuid.UUID("00000000-0000-4000-8000-0000000000e2"),
)


@dataclass(frozen=True)
class EvalConfig:
    strategy: ChunkingStrategy
    max_chars: int
    overlap_chars: int = 150

    @property
    def label(self) -> str:
        return f"{self.strategy.value}-{self.max_chars}"

    def chunking(self) -> ChunkingConfig:
        return ChunkingConfig(
            strategy=self.strategy, max_chars=self.max_chars, overlap_chars=self.overlap_chars
        )


# The application default (structured, 1,200 characters) comes first.
DEFAULT_CONFIG = EvalConfig(ChunkingStrategy.STRUCTURED, 1200)
ALL_CONFIGS = tuple(
    EvalConfig(strategy, size)
    for strategy in (ChunkingStrategy.STRUCTURED, ChunkingStrategy.FIXED)
    for size in (1200, 800, 400)
)


@dataclass(frozen=True)
class QueryOutcome:
    config: str
    mode: str
    query_id: str
    category: str
    ranks: tuple[int | None, ...]
    latency_ms: float


@dataclass(frozen=True)
class SummaryRow:
    config: str
    mode: str
    category: str  # a category from CATEGORIES, or "all"
    queries: int
    recall: dict[int, float]
    mrr: float
    mean_latency_ms: float


@dataclass(frozen=True)
class ConfigStats:
    config: str
    chunks: int
    mean_chunk_chars: float


@dataclass
class EvaluationReport:
    backend: str
    model_id: str
    top_k: int
    configs: list[ConfigStats] = field(default_factory=list)
    outcomes: list[QueryOutcome] = field(default_factory=list)

    def summary(self) -> list[SummaryRow]:
        rows: list[SummaryRow] = []
        for stats in self.configs:
            for mode in SearchMode:
                selected = [
                    o for o in self.outcomes if o.config == stats.config and o.mode == mode.value
                ]
                for category in ("all", *CATEGORIES):
                    group = [o for o in selected if category in ("all", o.category)]
                    if not group:
                        continue
                    rows.append(
                        SummaryRow(
                            config=stats.config,
                            mode=mode.value,
                            category=category,
                            queries=len(group),
                            recall={
                                k: mean([recall_at_k(o.ranks, k) for o in group]) for k in K_VALUES
                            },
                            mrr=mean([reciprocal_rank(o.ranks, TOP_K) for o in group]),
                            mean_latency_ms=mean([o.latency_ms for o in group]),
                        )
                    )
        return rows


DatabaseFactory = Callable[[], AbstractContextManager[str]]


@contextmanager
def sqlite_database() -> Iterator[str]:
    with tempfile.TemporaryDirectory(prefix="easa-eval-") as directory:
        yield f"sqlite:///{(Path(directory) / 'eval.db').as_posix()}"


def postgres_database(admin_url: str) -> DatabaseFactory:
    """Factory of throwaway PostgreSQL databases (the user must be allowed to create them)."""

    @contextmanager
    def factory() -> Iterator[str]:
        name = f"easa_eval_{uuid.uuid4().hex[:12]}"  # generated, never user input
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
            try:
                yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
            finally:
                with admin.connect() as connection:
                    connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            admin.dispose()

    return factory


def run_evaluation(
    dataset: Dataset,
    embedder: Embedder,
    *,
    backend: str,
    database: DatabaseFactory,
    configs: Sequence[EvalConfig] = (DEFAULT_CONFIG,),
) -> EvaluationReport:
    report = EvaluationReport(backend=backend, model_id=embedder.model_id, top_k=TOP_K)
    for config in configs:
        with database() as url, tempfile.TemporaryDirectory(prefix="easa-eval-blobs-") as blobs:
            upgrade_to_head(url)
            engine = create_db_engine(url)
            try:
                with create_session_factory(engine)() as session:
                    _ingest(session, dataset, embedder, config, Path(blobs))
                    lengths = list(session.scalars(select(func.length(DocumentChunk.text))))
                    report.configs.append(
                        ConfigStats(config.label, len(lengths), mean([float(n) for n in lengths]))
                    )
                    search = SearchService(session, embedder, *build_indexes(session))
                    for query in dataset.queries:
                        for mode in SearchMode:
                            started = time.perf_counter()
                            result = search.search(
                                EVAL_IDENTITY, query.query, top_k=TOP_K, mode=mode
                            )
                            elapsed = (time.perf_counter() - started) * 1000
                            report.outcomes.append(
                                QueryOutcome(
                                    config=config.label,
                                    mode=mode.value,
                                    query_id=query.id,
                                    category=query.category,
                                    ranks=tuple(
                                        evidence_ranks(
                                            [h.text for h in result.hits], query.evidence
                                        )
                                    ),
                                    latency_ms=elapsed,
                                )
                            )
            finally:
                engine.dispose()
        logger.info("evaluation config finished", extra={"config": config.label})
    return report


def _ingest(
    session: Session, dataset: Dataset, embedder: Embedder, config: EvalConfig, blobs: Path
) -> None:
    service = DocumentService(
        session,
        LocalBlobStore(blobs),
        max_upload_bytes=10 * 1024 * 1024,
        chunking=config.chunking(),
        embedder=embedder,
    )
    for name, data in dataset.documents.items():
        document = service.upload(EVAL_IDENTITY, name, data).document
        if document.status is not DocumentStatus.PROCESSED:
            raise RuntimeError(f"evaluation document {name} was not processed")
    # Embedding failures leave documents processed but unembedded, which would
    # silently lower semantic scores; refuse to evaluate in that case.
    chunks = session.scalar(select(func.count()).select_from(DocumentChunk))
    vectors = session.scalar(
        select(func.count())
        .select_from(ChunkEmbedding)
        .where(ChunkEmbedding.model_id == embedder.model_id)
    )
    if not chunks or vectors != chunks:
        raise RuntimeError(f"expected {chunks} vectors for {embedder.model_id}, found {vectors}")
