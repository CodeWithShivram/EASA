from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.base import NAMING_CONVENTION, Base
from app.db.engine import create_db_engine
from app.db.session import SessionFactory, create_session_factory, iter_session, session_scope
from tests.conftest import sqlite_url


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(sqlite_url(tmp_path / "var" / "unit.db"))
    # Test-only scratch table; not part of the application schema.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE scratch (value TEXT NOT NULL)"))
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine: Engine) -> SessionFactory:
    return create_session_factory(engine)


def _count(factory: SessionFactory) -> int:
    with factory() as session:
        return session.execute(text("SELECT COUNT(*) FROM scratch")).scalar_one()


def test_engine_creates_sqlite_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "app.db"
    engine = create_db_engine(sqlite_url(db_path))
    try:
        assert db_path.parent.is_dir()
    finally:
        engine.dispose()


def test_sqlite_foreign_keys_are_enforced(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_session_scope_commits_on_success(factory: SessionFactory) -> None:
    with session_scope(factory) as session:
        session.execute(text("INSERT INTO scratch (value) VALUES ('kept')"))

    assert _count(factory) == 1


def test_session_scope_rolls_back_on_error(factory: SessionFactory) -> None:
    def failing_unit_of_work() -> None:
        with session_scope(factory) as session:
            session.execute(text("INSERT INTO scratch (value) VALUES ('discarded')"))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        failing_unit_of_work()

    assert _count(factory) == 0


def test_iter_session_does_not_commit_implicitly(factory: SessionFactory) -> None:
    sessions = iter_session(factory)
    session = next(sessions)
    session.execute(text("INSERT INTO scratch (value) VALUES ('uncommitted')"))
    sessions.close()  # end of request without an explicit commit

    assert _count(factory) == 0


def test_iter_session_rolls_back_and_closes_on_error(factory: SessionFactory) -> None:
    sessions = iter_session(factory)
    session: Session = next(sessions)
    session.execute(text("INSERT INTO scratch (value) VALUES ('failed')"))

    with pytest.raises(RuntimeError):
        sessions.throw(RuntimeError("request failed"))

    assert not session.in_transaction()
    assert _count(factory) == 0


def test_metadata_has_naming_convention_and_no_tables() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert Base.metadata.tables == {}
