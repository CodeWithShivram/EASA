from pathlib import Path
from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.main import create_app
from tests.conftest import make_settings


def test_request_scoped_session_uses_configured_database(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    # Test-only route exercising the session dependency.
    @app.get("/test/db")
    def db_probe(session: Annotated[Session, Depends(get_db_session)]) -> dict[str, int]:
        return {"value": session.execute(text("SELECT 1")).scalar_one()}

    with TestClient(app) as client:
        response = client.get("/test/db")

    assert response.status_code == 200
    assert response.json() == {"value": 1}
    assert (tmp_path / "var" / "test.db").exists()
