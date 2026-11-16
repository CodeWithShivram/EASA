"""Ticket tools and audit records on PostgreSQL."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.identity import Identity
from app.core.roles import ROLE_PERMISSIONS, Role
from app.db.audit import AuditOutcome
from app.main import create_app
from app.repositories.audit import AuditRepository
from app.tools.executor import ToolExecutor
from app.tools.seed import seed_tickets
from tests.conftest import DEV_TENANT_ID, DEV_USER_ID, make_settings


@pytest.fixture
def app(tmp_path: Path, pg_url: str, clean_tables: None) -> Iterator[FastAPI]:
    app = create_app(make_settings(tmp_path, database_url=pg_url))
    with app.state.session_factory() as session:
        seed_tickets(session, DEV_TENANT_ID, DEV_USER_ID)
    with TestClient(app):
        yield app
    app.state.engine.dispose()


def test_ticket_tools_and_audit_on_postgres(app: FastAPI) -> None:
    me = Identity(DEV_TENANT_ID, DEV_USER_ID, ROLE_PERMISSIONS[Role.EMPLOYEE])
    tools: ToolExecutor = app.state.tool_executor

    own = tools.execute(me, "get_ticket", {"number": 1})
    other = tools.execute(me, "get_ticket", {"number": 6})  # another reporter's ticket
    draft = tools.execute(
        me,
        "create_draft_ticket",
        {"title": "Badge not working", "description": "My badge stopped opening doors."},
        confirmed=True,
    )

    assert own.outcome is AuditOutcome.SUCCEEDED
    assert other.detail == "ticket_not_found"
    assert draft.output == {"number": 8, "status": "draft", "title": "Badge not working"}
    outcomes = [
        r.outcome for r in AuditRepository(app.state.session_factory).list_for_tenant(DEV_TENANT_ID)
    ]
    assert sorted(o.value for o in outcomes) == ["failed", "succeeded", "succeeded"]
