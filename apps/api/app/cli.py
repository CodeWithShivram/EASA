"""Server-side maintenance commands.

Run from apps/api:
    uv run python -m app.cli download-embedding-model
    uv run python -m app.cli download-chat-model
    uv run python -m app.cli embed-missing [--limit N]
    uv run python -m app.cli rebuild-keyword-index
    uv run python -m app.cli evaluate [--backend sqlite|postgres] [--configs default|all]
    uv run python -m app.cli evaluate-hnsw [--vectors N] [--tenants N] [--queries N]
    uv run python -m app.cli evaluate-answers [--configs default|all] [--limit N]

The evaluation commands use the PostgreSQL URL in EASA_EVAL_POSTGRES_URL (a
user that may create databases); they create and drop throwaway databases.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import API_ROOT, load_settings
from app.core.logging import configure_logging
from app.db.engine import create_db_engine
from app.db.fts import rebuild_keyword_index
from app.db.session import create_session_factory
from app.embeddings.factory import build_embedder, download_model
from app.embeddings.registry import DEFAULT_MODEL
from app.evaluation.answers_eval import (
    ALL_ANSWER_CONFIGS,
    DEFAULT_ANSWER_CONFIG,
    answer_report_to_json,
    answer_report_to_markdown,
    load_adversarial_documents,
    load_answer_cases,
    run_answer_evaluation,
    validate_answer_cases,
)
from app.evaluation.dataset import load_dataset, validate_dataset
from app.evaluation.hnsw import hnsw_report_to_markdown, run_hnsw_benchmark
from app.evaluation.report import report_to_json, report_to_markdown
from app.evaluation.runner import (
    ALL_CONFIGS,
    DEFAULT_CONFIG,
    DatabaseFactory,
    postgres_database,
    run_evaluation,
    sqlite_database,
)
from app.llm.factory import build_chat_model
from app.llm.registry import DEFAULT_CHAT_MODEL, ModelFileError, download_chat_model
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger("app.cli")

EVAL_OUTPUT_DIR = API_ROOT / "var" / "eval"


def _postgres_factory() -> DatabaseFactory | None:
    url = os.environ.get("EASA_EVAL_POSTGRES_URL")
    if not url:
        logger.error("set EASA_EVAL_POSTGRES_URL to a PostgreSQL URL that may create databases")
        return None
    return postgres_database(url)


def _write(output_dir: Path, stem: str, files: dict[str, str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for suffix, content in files.items():
        path = output_dir / f"{stem}.{suffix}"
        path.write_text(content, encoding="utf-8")
        logger.info("evaluation output written", extra={"path": str(path)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "download-embedding-model",
        help=f"download {DEFAULT_MODEL.model_id} ({DEFAULT_MODEL.repo_id}, network access)",
    )
    commands.add_parser(
        "download-chat-model",
        help=f"download {DEFAULT_CHAT_MODEL.name} ({DEFAULT_CHAT_MODEL.repo_id}, "
        f"{DEFAULT_CHAT_MODEL.size_bytes / 1e9:.2f} GB, network access) and verify its SHA-256",
    )
    backfill = commands.add_parser(
        "embed-missing", help="embed chunks of processed documents that have no vector yet"
    )
    backfill.add_argument("--limit", type=int, default=10_000, help="maximum chunks to embed")
    commands.add_parser(
        "rebuild-keyword-index",
        help="rebuild the SQLite FTS5 keyword index from document_chunks (e.g. after VACUUM)",
    )
    evaluate = commands.add_parser(
        "evaluate", help="measure retrieval quality on the labelled synthetic dataset (eval/)"
    )
    evaluate.add_argument("--backend", choices=("sqlite", "postgres"), default="sqlite")
    evaluate.add_argument(
        "--configs",
        choices=("default", "all"),
        default="default",
        help="default: the application chunking setting; all: 6 chunking settings",
    )
    evaluate.add_argument("--output-dir", type=Path, default=EVAL_OUTPUT_DIR)
    hnsw = commands.add_parser(
        "evaluate-hnsw", help="compare exact and HNSW vector search on PostgreSQL"
    )
    hnsw.add_argument("--vectors", type=int, default=50_000)
    hnsw.add_argument("--tenants", type=int, default=10)
    hnsw.add_argument("--queries", type=int, default=100)
    hnsw.add_argument(
        "--noise", type=float, default=0.1, help="isotropic noise; higher is harder for HNSW"
    )
    hnsw.add_argument("--output-dir", type=Path, default=EVAL_OUTPUT_DIR)
    answers = commands.add_parser(
        "evaluate-answers",
        help="evaluate grounded answers with the configured chat model (eval/answers.json)",
    )
    answers.add_argument("--configs", choices=("default", "all"), default="default")
    answers.add_argument("--limit", type=int, default=0, help="only the first N cases (0 = all)")
    answers.add_argument("--output-dir", type=Path, default=EVAL_OUTPUT_DIR)
    answers.add_argument(
        "--fresh",
        action="store_true",
        help="ignore finished cases saved by an interrupted earlier run",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level)

    if args.command == "download-embedding-model":
        path = download_model(DEFAULT_MODEL, settings.embedding_model_dir)
        logger.info(
            "embedding model downloaded",
            extra={"model_id": DEFAULT_MODEL.model_id, "path": str(path)},
        )
        return 0

    if args.command == "download-chat-model":
        try:
            path = download_chat_model(DEFAULT_CHAT_MODEL, settings.chat_model_dir)
        except ModelFileError as error:
            logger.error("chat model verification failed", extra={"error": str(error)})
            return 1
        logger.info(
            "chat model downloaded and verified",
            extra={"model": DEFAULT_CHAT_MODEL.name, "path": str(path)},
        )
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if args.command == "evaluate-hnsw":
        factory = _postgres_factory()
        if factory is None:
            return 1
        hnsw_report = run_hnsw_benchmark(
            factory,
            vectors=args.vectors,
            tenants=args.tenants,
            queries=args.queries,
            noise=args.noise,
        )
        _write(
            args.output_dir,
            f"{stamp}-hnsw-{args.tenants}t-noise{args.noise}",
            {"md": hnsw_report_to_markdown(hnsw_report)},
        )
        return 0

    if args.command == "evaluate-answers":
        cases = load_answer_cases()
        documents = {**load_dataset().documents, **load_adversarial_documents()}
        problems = validate_answer_cases(cases, documents)
        if problems:
            logger.error("answer evaluation cases are invalid", extra={"problems": problems})
            return 1
        embedder = build_embedder(settings)
        # A slow CPU model needs more time than a normal request allows.
        model = build_chat_model(
            settings.model_copy(
                update={"model_timeout_seconds": max(settings.model_timeout_seconds, 300.0)}
            )
        )
        if model is None or not model.is_available() or not embedder.is_available():
            logger.error("a configured, available chat model and embedding model are required")
            return 1
        selected = cases[: args.limit] if args.limit > 0 else cases
        answer_report = run_answer_evaluation(
            selected,
            documents,
            embedder,
            model,
            database=sqlite_database,
            configs=ALL_ANSWER_CONFIGS if args.configs == "all" else (DEFAULT_ANSWER_CONFIG,),
            progress=lambda line: logger.info("answer case done", extra={"case": line}),
            # Resumable: finished cases are kept here and skipped on the next run.
            checkpoint=args.output_dir
            / (
                f"{stamp}-answers.checkpoint.jsonl"
                if args.fresh
                else f"answers-{args.configs}.checkpoint.jsonl"
            ),
        )
        _write(
            args.output_dir,
            f"{stamp}-answers-{args.configs}",
            {
                "json": answer_report_to_json(answer_report),
                "md": answer_report_to_markdown(answer_report),
            },
        )
        return 0

    if args.command == "evaluate":
        dataset = load_dataset()
        problems = validate_dataset(dataset)
        if problems:
            logger.error("evaluation dataset is invalid", extra={"problems": problems})
            return 1
        embedder = build_embedder(settings)
        if not embedder.is_available():
            logger.error("embedding model not available; run download-embedding-model first")
            return 1
        factory = sqlite_database if args.backend == "sqlite" else _postgres_factory()
        if factory is None:
            return 1
        configs = ALL_CONFIGS if args.configs == "all" else (DEFAULT_CONFIG,)
        report = run_evaluation(
            dataset, embedder, backend=args.backend, database=factory, configs=configs
        )
        _write(
            args.output_dir,
            f"{stamp}-{args.backend}-{args.configs}",
            {"json": report_to_json(report), "md": report_to_markdown(report)},
        )
        return 0

    if args.command == "rebuild-keyword-index":
        engine = create_db_engine(settings.database_url.get_secret_value())
        try:
            with engine.begin() as connection:
                rebuild_keyword_index(connection)
        finally:
            engine.dispose()
        logger.info("keyword index rebuilt")
        return 0

    embedder = build_embedder(settings)
    if not embedder.is_available():
        logger.error(
            "embedding model not available; run download-embedding-model first",
            extra={"model_id": embedder.model_id},
        )
        return 1
    engine = create_db_engine(settings.database_url.get_secret_value())
    try:
        with create_session_factory(engine)() as session:
            EmbeddingService(
                session, embedder, batch_size=settings.embedding_batch_size
            ).embed_missing(limit=args.limit)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
