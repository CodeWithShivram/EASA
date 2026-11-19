"""Server-side maintenance commands.

Run from apps/api:
    uv run python -m app.cli download-embedding-model
    uv run python -m app.cli download-chat-model
    uv run python -m app.cli embed-missing [--limit N]
    uv run python -m app.cli rebuild-keyword-index
    uv run python -m app.cli create-user --tenant T --username U --role R [--password-stdin]
    uv run python -m app.cli seed-tickets --username NAME
    uv run python -m app.cli upload-documents --username NAME [--min-role R] FILE...
    uv run python -m app.cli evaluate [--backend sqlite|postgres] [--configs default|all]
    uv run python -m app.cli evaluate-hnsw [--vectors N] [--tenants N] [--queries N]
    uv run python -m app.cli evaluate-answers [--configs default|all] [--limit N]
    uv run python -m app.cli evaluate-agent [--limit N]
    uv run python -m app.cli evaluate-access [--backend sqlite|postgres] [--surfaces all|search]
    uv run python -m app.cli evaluate-all [--no-model]
    uv run python -m app.cli update-eval-manifest --version N

The evaluation commands use the PostgreSQL URL in EASA_EVAL_POSTGRES_URL (a
user that may create databases); they create and drop throwaway databases.
They refuse to run when the data under eval/ does not match eval/manifest.json,
and every report records the data version, models, settings and code version
(P8-M4, ADR-038).
"""

import argparse
import getpass
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.api.dependencies import session_policy
from app.core.config import API_ROOT, Settings, load_settings
from app.core.errors import AppError
from app.core.identity import Identity
from app.core.logging import configure_logging
from app.core.roles import ROLE_PERMISSIONS, Role
from app.db.audit import AuditOutcome
from app.db.engine import create_db_engine
from app.db.fts import rebuild_keyword_index
from app.db.session import create_session_factory
from app.embeddings.factory import build_embedder, download_model
from app.embeddings.registry import DEFAULT_MODEL
from app.evaluation.access_eval import (
    SURFACES,
    access_report_to_json,
    access_report_to_markdown,
    load_access_dataset,
    run_access_evaluation,
    validate_access_dataset,
)
from app.evaluation.agent_eval import (
    agent_report_to_json,
    agent_report_to_markdown,
    load_agent_cases,
    run_agent_evaluation,
    validate_agent_cases,
)
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
from app.evaluation.manifest import check_manifest, write_manifest
from app.evaluation.report import report_to_json, report_to_markdown
from app.evaluation.run_info import RunInfo, run_info, with_run_info
from app.evaluation.runner import (
    ALL_CONFIGS,
    DEFAULT_CONFIG,
    TOP_K,
    DatabaseFactory,
    postgres_database,
    run_evaluation,
    sqlite_database,
)
from app.llm.factory import build_chat_model
from app.llm.registry import DEFAULT_CHAT_MODEL, ModelFileError, download_chat_model
from app.repositories.accounts import AccountRepository
from app.repositories.audit import AuditRepository
from app.services.auth import AuthService
from app.services.chunking import ChunkingConfig, ChunkingStrategy
from app.services.documents import DocumentService
from app.services.embedding_service import EmbeddingService
from app.storage.blob_store import LocalBlobStore
from app.tools.seed import seed_tickets

logger = logging.getLogger("app.cli")

EVAL_OUTPUT_DIR = API_ROOT / "var" / "eval"


def _postgres_factory() -> DatabaseFactory | None:
    url = os.environ.get("EASA_EVAL_POSTGRES_URL")
    if not url:
        logger.error("set EASA_EVAL_POSTGRES_URL to a PostgreSQL URL that may create databases")
        return None
    return postgres_database(url)


def _evaluate_all(settings: Settings, output_dir: Path, stamp: str, *, use_model: bool) -> int:
    """Run each evaluation as its own command; skip those whose prerequisites are missing.

    The retrieval and search-only access evaluations always run; PostgreSQL
    variants need EASA_EVAL_POSTGRES_URL; the answer, agent and full access
    evaluations need an available chat model. The HNSW benchmark (synthetic
    vectors, slow) stays a separate command. Writes ``<stamp>-all.md``.
    """
    out = ["--output-dir", str(output_dir)]
    model = build_chat_model(settings) if use_model else None
    model_reason = None
    if not use_model:
        model_reason = "--no-model"
    elif model is None or not model.is_available():
        model_reason = "no available chat model (EASA_MODEL_PROVIDER)"
    postgres_reason = (
        None if os.environ.get("EASA_EVAL_POSTGRES_URL") else "EASA_EVAL_POSTGRES_URL not set"
    )
    steps: list[tuple[str, list[str], str | None]] = [
        ("Retrieval, SQLite", ["evaluate", *out], None),
        ("Retrieval, PostgreSQL", ["evaluate", "--backend", "postgres", *out], postgres_reason),
        ("Access, search only, SQLite", ["evaluate-access", "--surfaces", "search", *out], None),
        (
            "Access, search only, PostgreSQL",
            ["evaluate-access", "--surfaces", "search", "--backend", "postgres", *out],
            postgres_reason,
        ),
        ("Answers", ["evaluate-answers", "--fresh", *out], model_reason),
        ("Agent", ["evaluate-agent", *out], model_reason),
        ("Access, all surfaces, SQLite", ["evaluate-access", *out], model_reason),
    ]
    rows = []
    failed = False
    for name, argv, skip in steps:
        if skip is not None:
            rows.append(f"| {name} | skipped: {skip} | - | - |")
            continue
        logger.info("evaluation started", extra={"evaluation": name})
        before = set(output_dir.glob("*")) if output_dir.exists() else set()
        began = datetime.now(UTC)
        code = main(argv)
        seconds = (datetime.now(UTC) - began).total_seconds()
        written = sorted(p.name for p in set(output_dir.glob("*")) - before if p.suffix == ".md")
        failed = failed or code != 0
        result = "written" if code == 0 else f"failed (exit code {code})"
        rows.append(f"| {name} | {result} | {seconds:.0f} | {', '.join(written) or '-'} |")
    _write(
        output_dir,
        f"{stamp}-all",
        {
            "md": "\n".join(
                [
                    "# All evaluations",
                    "",
                    "| Evaluation | Result | Seconds | Report |",
                    "|---|---|---|---|",
                    *rows,
                ]
            )
            + "\n"
        },
        run_info(
            "all",
            datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
            chat_model=model.model_id if model is not None and model_reason is None else None,
            settings={"model": model_reason is None, "postgres": postgres_reason is None},
        ),
    )
    return 1 if failed else 0


def _upload_documents(settings: Settings, username: str, min_role: Role, files: list[Path]) -> int:
    """Upload files as the user, with the same checks and audit record as the API (P8-M5)."""
    embedder = build_embedder(settings)
    if not embedder.is_available():
        logger.error("embedding model not available; run download-embedding-model first")
        return 1
    engine = create_db_engine(settings.database_url.get_secret_value())
    failed = 0
    try:
        sessions = create_session_factory(engine)
        audit = AuditRepository(sessions)
        with sessions() as session:
            user = AccountRepository(session).get_user_by_username(username.lower())
            if user is None or not user.is_active:
                logger.error("no such active user", extra={"username": username})
                return 1
            identity = Identity(
                user.tenant_id, user.id, ROLE_PERMISSIONS[user.role], user.role.value
            )
            if not identity.can("documents:upload"):
                logger.error("this user may not upload documents", extra={"role": user.role.value})
                return 1
            service = DocumentService(
                session,
                LocalBlobStore(settings.storage_dir),
                max_upload_bytes=settings.max_upload_bytes,
                max_pdf_pages=settings.max_pdf_pages,
                chunking=ChunkingConfig(
                    strategy=ChunkingStrategy(settings.chunk_strategy),
                    max_chars=settings.chunk_max_chars,
                    overlap_chars=settings.chunk_overlap_chars,
                ),
                embedder=embedder,
                embedding_batch_size=settings.embedding_batch_size,
            )
            for path in files:
                try:
                    result = service.upload(
                        identity, path.name, path.read_bytes(), min_role=min_role
                    )
                except (AppError, OSError) as error:
                    failed += 1
                    code = error.code if isinstance(error, AppError) else type(error).__name__
                    logger.error("document not uploaded", extra={"file": path.name, "code": code})
                    continue
                audit.record(
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    action="document.upload",
                    target=f"document:{result.document.id}",
                    outcome=AuditOutcome.SUCCEEDED,
                    detail=f"min_role={result.document.min_role} "
                    f"created={str(result.created).lower()} cli",
                )
                logger.info(
                    "document uploaded",
                    extra={
                        "file": path.name,
                        "document_id": str(result.document.id),
                        "status": result.document.status.value,
                        "new_document": result.created,
                    },
                )
    finally:
        engine.dispose()
    return 1 if failed else 0


EVALUATION_COMMANDS = frozenset(
    {
        "evaluate",
        "evaluate-hnsw",
        "evaluate-answers",
        "evaluate-access",
        "evaluate-agent",
        "evaluate-all",
    }
)
# What the model evaluations pass to the chat model (answers_eval, access_eval, agent_eval).
GROUNDED_SETTINGS = {"max_output_tokens": 256, "temperature": 0.0}


def _write(output_dir: Path, stem: str, files: dict[str, str], run: RunInfo | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if run is not None:
        files = with_run_info(files, run)
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
    create_user = commands.add_parser(
        "create-user", help="create a user (and its tenant if new); asks for the password"
    )
    create_user.add_argument("--tenant", required=True, help="tenant name, created if new")
    create_user.add_argument("--username", required=True)
    create_user.add_argument("--role", required=True, choices=[role.value for role in Role])
    create_user.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from the first line of standard input instead of a prompt",
    )
    upload = commands.add_parser(
        "upload-documents",
        help="upload files as a user (who may upload), like the documents page; audited",
    )
    upload.add_argument("--username", required=True)
    upload.add_argument(
        "--min-role",
        choices=[role.value for role in Role],
        default=Role.EMPLOYEE.value,
        help="lowest role that may see the documents (at most the user's own)",
    )
    upload.add_argument("files", nargs="+", type=Path)
    seed = commands.add_parser(
        "seed-tickets", help="create synthetic support tickets for a user's tenant (once)"
    )
    seed.add_argument("--username", required=True, help="the user who reports the own tickets")
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
    agent = commands.add_parser(
        "evaluate-agent",
        help="evaluate the agent with the configured chat model (eval/agent.json); "
        "nothing is confirmed",
    )
    agent.add_argument("--limit", type=int, default=0, help="only the first N tasks (0 = all)")
    agent.add_argument("--output-dir", type=Path, default=EVAL_OUTPUT_DIR)
    access = commands.add_parser(
        "evaluate-access",
        help="check that restricted documents never leak to lower roles (eval/access.json)",
    )
    access.add_argument("--backend", choices=("sqlite", "postgres"), default="sqlite")
    access.add_argument(
        "--surfaces",
        choices=("all", "search"),
        default="all",
        help="all: search, answers and the agent (needs a chat model); search: no model",
    )
    access.add_argument("--output-dir", type=Path, default=EVAL_OUTPUT_DIR)
    every = commands.add_parser(
        "evaluate-all",
        help="run every evaluation whose prerequisites are present and write a summary",
    )
    every.add_argument(
        "--no-model", action="store_true", help="skip the evaluations that need a chat model"
    )
    every.add_argument("--output-dir", type=Path, default=EVAL_OUTPUT_DIR)
    manifest = commands.add_parser(
        "update-eval-manifest",
        help="record the SHA-256 of every file under eval/ in eval/manifest.json",
    )
    manifest.add_argument(
        "--version", type=int, required=True, help="the new data version (higher than before)"
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

    started = datetime.now(UTC)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    if args.command in EVALUATION_COMMANDS:
        problems = check_manifest()
        if problems:
            logger.error(
                "the evaluation data does not match eval/manifest.json; update it with "
                "update-eval-manifest after reviewing the changes",
                extra={"problems": problems},
            )
            return 1

    if args.command == "update-eval-manifest":
        try:
            manifest = write_manifest(args.version)
        except ValueError as error:
            logger.error("manifest not updated", extra={"error": str(error)})
            return 1
        logger.info(
            "evaluation manifest written",
            extra={"version": manifest.version, "files": len(manifest.files)},
        )
        return 0

    if args.command == "evaluate-all":
        return _evaluate_all(settings, args.output_dir, stamp, use_model=not args.no_model)

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
            run_info(
                "hnsw",
                started,
                settings={
                    "vectors": args.vectors,
                    "tenants": args.tenants,
                    "queries": args.queries,
                    "noise": args.noise,
                },
            ),
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
            run_info(
                "answers",
                started,
                embedding_model=embedder.model_id,
                chat_model=model.model_id,
                settings={"configs": args.configs, "cases": len(selected), **GROUNDED_SETTINGS},
            ),
        )
        return 0

    if args.command == "evaluate-access":
        access_documents, access_questions = load_access_dataset()
        problems = validate_access_dataset(access_documents, access_questions)
        if problems:
            logger.error("access evaluation data is invalid", extra={"problems": problems})
            return 1
        database: DatabaseFactory | None = sqlite_database
        if args.backend == "postgres":
            database = _postgres_factory()
            if database is None:
                return 1
        embedder = build_embedder(settings)
        chat_model = None
        if args.surfaces == "all":
            chat_model = build_chat_model(
                settings.model_copy(
                    update={"model_timeout_seconds": max(settings.model_timeout_seconds, 300.0)}
                )
            )
            if chat_model is None or not chat_model.is_available():
                logger.error("--surfaces all needs a configured, available chat model")
                return 1
        if not embedder.is_available():
            logger.error("the embedding model is not available")
            return 1
        access_report = run_access_evaluation(
            access_documents,
            access_questions,
            embedder,
            chat_model,
            database=database,
            backend=args.backend,
            surfaces=SURFACES if args.surfaces == "all" else ("search",),
            progress=lambda line: logger.info("access check done", extra={"check": line}),
        )
        _write(
            args.output_dir,
            f"{stamp}-access-{args.backend}-{args.surfaces}",
            {
                "json": access_report_to_json(access_report),
                "md": access_report_to_markdown(access_report),
            },
            run_info(
                "access",
                started,
                embedding_model=embedder.model_id,
                chat_model=chat_model.model_id if chat_model else None,
                settings={
                    "backend": args.backend,
                    "surfaces": args.surfaces,
                    **(GROUNDED_SETTINGS if chat_model else {}),
                },
            ),
        )
        return 0

    if args.command == "evaluate-agent":
        agent_cases, agent_documents = load_agent_cases()
        problems = validate_agent_cases(agent_cases, agent_documents)
        if problems:
            logger.error("agent evaluation tasks are invalid", extra={"problems": problems})
            return 1
        embedder = build_embedder(settings)
        model = build_chat_model(
            settings.model_copy(
                update={"model_timeout_seconds": max(settings.model_timeout_seconds, 300.0)}
            )
        )
        if model is None or not model.is_available() or not embedder.is_available():
            logger.error("a configured, available chat model and embedding model are required")
            return 1
        agent_report = run_agent_evaluation(
            agent_cases[: args.limit] if args.limit > 0 else agent_cases,
            agent_documents,
            embedder,
            model,
            database=sqlite_database,
            progress=lambda line: logger.info("agent task done", extra={"task": line}),
        )
        _write(
            args.output_dir,
            f"{stamp}-agent",
            {
                "json": agent_report_to_json(agent_report),
                "md": agent_report_to_markdown(agent_report),
            },
            run_info(
                "agent",
                started,
                embedding_model=embedder.model_id,
                chat_model=model.model_id,
                settings={
                    "tasks": args.limit if args.limit > 0 else len(agent_cases),
                    "agent_temperature": 0.0,
                    **GROUNDED_SETTINGS,
                },
            ),
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
            run_info(
                "retrieval",
                started,
                embedding_model=embedder.model_id,
                settings={"backend": args.backend, "configs": args.configs, "top_k": TOP_K},
            ),
        )
        return 0

    if args.command == "create-user":
        if args.password_stdin:
            # Windows PowerShell may put a byte order mark in front of piped text.
            password = sys.stdin.readline().removeprefix("\ufeff").rstrip("\r\n")
        else:
            password = getpass.getpass("Password: ")
            if getpass.getpass("Repeat password: ") != password:
                logger.error("the passwords do not match")
                return 1
        engine = create_db_engine(settings.database_url.get_secret_value())
        try:
            with create_session_factory(engine)() as session:
                audit = AuditRepository(create_session_factory(engine))
                service = AuthService(session, session_policy(settings), ROLE_PERMISSIONS, audit)
                user = service.create_user(args.tenant, args.username, password, Role(args.role))
                tenant_id, user_id = user.tenant_id, user.id
        except AppError as error:
            logger.error("user not created", extra={"code": error.code, "reason": error.message})
            return 1
        finally:
            engine.dispose()
        logger.info(
            "user created",
            extra={"tenant_id": str(tenant_id), "user_id": str(user_id), "role": args.role},
        )
        return 0

    if args.command == "upload-documents":
        return _upload_documents(settings, args.username, Role(args.min_role), args.files)

    if args.command == "seed-tickets":
        engine = create_db_engine(settings.database_url.get_secret_value())
        try:
            with create_session_factory(engine)() as session:
                user = AccountRepository(session).get_user_by_username(args.username.lower())
                if user is None:
                    logger.error("no such user", extra={"username": args.username})
                    return 1
                created = seed_tickets(session, user.tenant_id, user.id)
        finally:
            engine.dispose()
        logger.info("synthetic tickets seeded", extra={"tickets_created": created})
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
