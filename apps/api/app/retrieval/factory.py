"""Choose retrieval implementations for the session's database backend."""

from sqlalchemy.orm import Session

from app.retrieval.base import KeywordIndex, VectorIndex
from app.retrieval.brute_force import BruteForceVectorIndex
from app.retrieval.keyword import PostgresKeywordIndex, SqliteKeywordIndex
from app.retrieval.pgvector_index import PgvectorIndex


def build_indexes(session: Session) -> tuple[VectorIndex, KeywordIndex]:
    if session.get_bind().dialect.name == "postgresql":
        return PgvectorIndex(session), PostgresKeywordIndex(session)
    return BruteForceVectorIndex(session), SqliteKeywordIndex(session)
