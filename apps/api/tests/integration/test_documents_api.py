import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.documents import Document, DocumentMediaType
from app.db.models import Base
from app.main import create_app
from app.repositories.documents import DocumentRepository
from tests.conftest import make_settings
from tests.fixtures import DOCX_BYTES, PDF_BYTES, TXT_BYTES

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OTHER_TENANT = uuid.UUID("00000000-0000-4000-8000-0000000000bb")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path, max_upload_bytes=64 * 1024)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    app = create_app(settings)
    # Schema equality with migrations is covered by test_migrations.
    Base.metadata.create_all(app.state.engine)
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def upload(
    client: TestClient, name: str, data: bytes, content_type: str = "text/plain"
) -> httpx2.Response:
    return client.post("/api/v1/documents", files={"file": (name, data, content_type)})


def test_upload_creates_a_document(client: TestClient, settings: Settings) -> None:
    response = upload(client, "leave-policy.txt", TXT_BYTES)

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "leave-policy.txt"
    assert body["media_type"] == "text/plain"
    assert body["size_bytes"] == len(TXT_BYTES)
    assert body["sha256"] == hashlib.sha256(TXT_BYTES).hexdigest()
    assert body["status"] == "uploaded"
    assert response.headers["Location"] == f"/api/v1/documents/{body['id']}"
    # Tenant and owner IDs are not exposed.
    assert "tenant_id" not in body
    assert "owner_id" not in body
    # The bytes are stored under their hash, not their name.
    digest = body["sha256"]
    assert (settings.storage_dir / digest[:2] / digest[2:4] / digest).read_bytes() == TXT_BYTES


@pytest.mark.parametrize(
    ("name", "data", "content_type", "media_type"),
    [
        ("policy.pdf", PDF_BYTES, "application/pdf", "application/pdf"),
        ("handbook.docx", DOCX_BYTES, DOCX_TYPE, DOCX_TYPE),
        # The client-declared content type is ignored; the content decides.
        ("handbook2.docx", DOCX_BYTES + b"", "text/plain", DOCX_TYPE),
    ],
)
def test_upload_accepts_pdf_and_docx(
    client: TestClient, name: str, data: bytes, content_type: str, media_type: str
) -> None:
    response = upload(client, name, data, content_type)

    assert response.status_code in (200, 201)
    assert response.json()["media_type"] == media_type


def test_reupload_of_identical_content_is_idempotent(client: TestClient) -> None:
    first = upload(client, "a.txt", TXT_BYTES)
    second = upload(client, "renamed.txt", TXT_BYTES)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["filename"] == "a.txt"
    assert len(client.get("/api/v1/documents").json()["items"]) == 1


def test_filename_is_sanitized(client: TestClient) -> None:
    response = upload(client, "../../secret<>|.txt", TXT_BYTES)

    assert response.status_code == 201
    assert response.json()["filename"] == "secret.txt"


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("malware.exe", b"MZ fake", 415, "unsupported_file_type"),
        ("fake.pdf", TXT_BYTES, 415, "file_content_mismatch"),
        ("empty.txt", b"", 422, "empty_file"),
        ("latin1.txt", "café".encode("latin-1"), 422, "invalid_text_encoding"),
        (".txt", TXT_BYTES, 400, "invalid_filename"),
    ],
)
def test_invalid_uploads_are_rejected_with_the_error_envelope(
    client: TestClient, name: str, data: bytes, status: int, code: str
) -> None:
    response = upload(client, name, data)

    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]
    assert client.get("/api/v1/documents").json()["items"] == []


def test_file_over_the_limit_is_rejected(client: TestClient) -> None:
    response = upload(client, "big.txt", b"a" * (64 * 1024 + 1))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_missing_file_field_is_a_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/documents", data={"not_file": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_list_and_get(client: TestClient) -> None:
    created = [upload(client, f"doc{i}.txt", f"document {i}".encode()).json() for i in range(3)]

    listing = client.get("/api/v1/documents", params={"limit": 2})
    assert listing.status_code == 200
    assert listing.json()["limit"] == 2
    assert len(listing.json()["items"]) == 2

    one = client.get(f"/api/v1/documents/{created[0]['id']}")
    assert one.status_code == 200
    assert one.json() == created[0]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_list_validates_pagination(client: TestClient, params: dict[str, int]) -> None:
    response = client.get("/api/v1/documents", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_and_malformed_ids(client: TestClient) -> None:
    missing = client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "document_not_found"

    malformed = client.get("/api/v1/documents/not-a-uuid")
    assert malformed.status_code == 422


def test_another_tenants_document_is_invisible(client: TestClient, app: FastAPI) -> None:
    # Insert a document for another tenant directly, then try to read it.
    with app.state.session_factory() as session:
        other = DocumentRepository(session).add(
            Document(
                tenant_id=OTHER_TENANT,
                owner_id=uuid.uuid4(),
                filename="other-tenant.txt",
                media_type=DocumentMediaType.TXT,
                size_bytes=5,
                sha256=hashlib.sha256(b"other").hexdigest(),
            )
        )
        session.commit()
        other_id = other.id

    response = client.get(f"/api/v1/documents/{other_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"
    assert client.get("/api/v1/documents").json()["items"] == []


def test_document_routes_are_not_mounted_in_production(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, environment="production"))

    with TestClient(app) as client:
        assert client.get("/api/v1/documents").status_code == 404
        assert upload(client, "a.txt", TXT_BYTES).status_code == 404
        assert client.get("/api/v1/health").status_code == 200
