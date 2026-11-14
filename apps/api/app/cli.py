"""Server-side maintenance commands.

Run from apps/api:
    uv run python -m app.cli download-embedding-model
    uv run python -m app.cli embed-missing [--limit N]
"""

import argparse
import logging
import sys

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.embeddings.factory import build_embedder, download_model
from app.embeddings.registry import DEFAULT_MODEL
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger("app.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "download-embedding-model",
        help=f"download {DEFAULT_MODEL.model_id} ({DEFAULT_MODEL.repo_id}, network access)",
    )
    backfill = commands.add_parser(
        "embed-missing", help="embed chunks of processed documents that have no vector yet"
    )
    backfill.add_argument("--limit", type=int, default=10_000, help="maximum chunks to embed")
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
