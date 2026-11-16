"""Access leakage evaluation (Phase 6, P6-M5): does restricted text ever get out?

Documents carry a minimum role, and the restricted ones contain canaries:
strings found nowhere else. Every role asks every question (eval/access.json)
through search, grounded answers and the agent. A *leak* is a canary of a
document above the caller's role, or a citation of such a document, in search
results, in anything the model is shown, or in an answer or proposed action.
For questions the role may answer, the run also records whether the expected
fact was found, so a filter that hid too much would show up too.
"""

import json
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.core.identity import Identity
from app.core.roles import ROLE_PERMISSIONS, Role, visible_levels
from app.db.engine import create_db_engine
from app.db.migrate import upgrade_to_head
from app.db.session import create_session_factory
from app.embeddings.base import Embedder
from app.evaluation.dataset import EVAL_ROOT
from app.evaluation.runner import DatabaseFactory
from app.llm.base import ChatMessage, ChatModel, ChatResult
from app.repositories.audit import AuditRepository
from app.retrieval.factory import build_indexes
from app.services.agent import AgentService
from app.services.answers import AnswerService
from app.services.documents import DocumentService
from app.services.search import SearchMode, SearchService
from app.storage.blob_store import LocalBlobStore
from app.tools.executor import ToolExecutor
from app.tools.support import build_tool_registry

SURFACES = ("search", "answers", "agent")
SEARCH_TOP_K = 10
EVAL_TENANT = uuid.UUID("00000000-0000-4000-8000-0000000000f0")
USER_IDS = {
    role: uuid.UUID(f"00000000-0000-4000-8000-0000000000f{i + 1}") for i, role in enumerate(Role)
}


@dataclass(frozen=True)
class AccessDocument:
    path: Path
    min_role: Role
    canaries: tuple[str, ...]


@dataclass(frozen=True)
class AccessQuestion:
    id: str
    level: Role
    question: str
    facts: tuple[str, ...]


@dataclass(frozen=True)
class AccessOutcome:
    surface: str
    role: str
    question_id: str
    permitted: bool  # the role may see the question's document
    status: str  # answered, insufficient_evidence, confirmation_required, failed, hits, error
    leaked: bool
    leak: str | None  # what leaked, e.g. "canary MARTEN-9023 in model input"
    found: bool | None  # expected fact found (only when permitted)
    # The reply (answers and agent; a proposal's arguments), cut to 300 characters,
    # to tell refusals from invented facts when reading the report.
    reply: str | None
    latency_ms: float


@dataclass
class AccessReport:
    backend: str
    model_id: str | None
    outcomes: list[AccessOutcome] = field(default_factory=list)


def load_access_dataset(
    root: Path = EVAL_ROOT,
) -> tuple[list[AccessDocument], list[AccessQuestion]]:
    raw = json.loads((root / "access.json").read_text(encoding="utf-8"))
    documents = [
        AccessDocument(root / d["path"], Role(d["min_role"]), tuple(d["canaries"]))
        for d in raw["documents"]
    ]
    questions = [
        AccessQuestion(q["id"], Role(q["level"]), q["question"], tuple(q["facts"]))
        for q in raw["questions"]
    ]
    return documents, questions


def validate_access_dataset(
    documents: Sequence[AccessDocument], questions: Sequence[AccessQuestion]
) -> list[str]:
    problems = [f"missing document {d.path.name}" for d in documents if not d.path.is_file()]
    for document in documents:
        if document.min_role is not Role.EMPLOYEE and not document.canaries:
            problems.append(f"{document.path.name}: restricted documents need canaries")
        if document.path.is_file():
            text = document.path.read_text(encoding="utf-8").lower()
            problems += [
                f"{document.path.name}: canary {c!r} not in the document"
                for c in document.canaries
                if c.lower() not in text
            ]
    others = {
        d.path: d.path.read_text(encoding="utf-8").lower() for d in documents if d.path.is_file()
    }
    for document in documents:
        for canary in document.canaries:
            if any(
                canary.lower() in text for path, text in others.items() if path != document.path
            ):
                problems.append(f"canary {canary!r} also occurs in another document")
    ids = [q.id for q in questions]
    problems += [f"duplicate question id {i}" for i in set(ids) if ids.count(i) > 1]
    problems += [
        f"{q.id}: a canary appears in the question"
        for q in questions
        for d in documents
        for c in d.canaries
        if c.lower() in q.question.lower()
    ]
    return problems


class RecordingModel:
    """Passes calls through and keeps everything the model was shown."""

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner
        self.model_id = inner.model_id
        self.seen: list[str] = []

    def is_available(self) -> bool:
        return self._inner.is_available()

    def generate(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResult:
        self.seen.extend(m.content for m in messages)
        return self._inner.generate(messages, **kwargs)


def _first_canary(texts: Sequence[str], canaries: Sequence[str]) -> str | None:
    joined = "\n".join(texts).lower()
    return next((c for c in canaries if c.lower() in joined), None)


def _found(texts: Sequence[str], facts: Sequence[str]) -> bool:
    joined = "\n".join(texts).lower()
    return any(f.lower() in joined for f in facts)


def run_access_evaluation(
    documents: Sequence[AccessDocument],
    questions: Sequence[AccessQuestion],
    embedder: Embedder,
    model: ChatModel | None,
    *,
    database: DatabaseFactory,
    backend: str = "sqlite",
    surfaces: Sequence[str] = SURFACES,
    progress: Callable[[str], None] | None = None,
) -> AccessReport:
    if model is None and set(surfaces) - {"search"}:
        raise ValueError("answers and agent surfaces need a chat model")
    report = AccessReport(backend=backend, model_id=model.model_id if model else None)
    with (
        database() as url,
        tempfile.TemporaryDirectory(prefix="easa-access-") as blobs,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        upgrade_to_head(url)
        engine = create_db_engine(url)
        try:
            sessions = create_session_factory(engine)
            levels: dict[uuid.UUID, Role] = {}
            with sessions() as session:
                admin = _identity(Role.ADMINISTRATOR)
                uploads = DocumentService(
                    session,
                    LocalBlobStore(Path(blobs)),
                    max_upload_bytes=10_000_000,
                    embedder=embedder,
                )
                for document in documents:
                    stored = uploads.upload(
                        admin,
                        document.path.name,
                        document.path.read_bytes(),
                        min_role=document.min_role,
                    ).document
                    levels[stored.id] = document.min_role
            executor = ToolExecutor(
                build_tool_registry(embedder), AuditRepository(sessions), sessions, pool=pool
            )
            for role in Role:
                identity = _identity(role)
                visible = set(visible_levels(role.value))
                hidden = [
                    c for d in documents if d.min_role.value not in visible for c in d.canaries
                ]
                for question in questions:
                    permitted = question.level.value in visible
                    for surface in surfaces:
                        with sessions() as session:
                            outcome = _run(
                                surface,
                                session,
                                embedder,
                                model,
                                executor,
                                identity,
                                role,
                                question,
                                permitted,
                                hidden,
                                levels,
                                visible,
                            )
                        report.outcomes.append(outcome)
                        if progress:
                            progress(
                                f"{surface} {role.value} {question.id} {outcome.status} "
                                f"leaked={outcome.leaked} found={outcome.found}"
                            )
        finally:
            engine.dispose()
    return report


def _identity(role: Role) -> Identity:
    return Identity(EVAL_TENANT, USER_IDS[role], ROLE_PERMISSIONS[role], role.value)


def _run(
    surface: str,
    session: Any,
    embedder: Embedder,
    model: ChatModel | None,
    executor: ToolExecutor,
    identity: Identity,
    role: Role,
    question: AccessQuestion,
    permitted: bool,
    hidden: list[str],
    levels: dict[uuid.UUID, Role],
    visible: set[str],
) -> AccessOutcome:
    started = time.perf_counter()
    if model is None and surface != "search":
        raise ValueError(f"the {surface} surface needs a chat model")
    search = SearchService(session, embedder, *build_indexes(session))
    seen: list[str] = []  # everything shown to the model, or returned by search
    outputs: list[str] = []  # what the user receives
    cited: list[uuid.UUID] = []
    try:
        if surface == "search":
            hits = search.search(
                identity, question.question, top_k=SEARCH_TOP_K, mode=SearchMode.HYBRID
            ).hits
            outputs = [h.text for h in hits]
            cited = [h.document_id for h in hits]
            status = "hits"
        elif surface == "answers":
            recorder = RecordingModel(model)
            result = AnswerService(search, recorder, max_output_tokens=256, temperature=0.0).answer(
                identity, question.question
            )
            seen = recorder.seen
            outputs = [result.answer or ""] + [s.text for s in result.sources]
            cited = [s.hit.document_id for s in result.sources]
            status = result.status.value
        else:
            recorder = RecordingModel(model)
            agent = AgentService(session, executor, recorder).run(identity, question.question)
            seen = recorder.seen
            outputs = [agent.answer or ""]
            if agent.pending_action is not None:
                outputs.append(json.dumps(agent.pending_action.arguments))
            status = agent.status.value
    except AppError as error:
        status, seen, outputs, cited = f"error:{error.code}", [], [], []
    leak = None
    hidden_citation = next(
        (d for d in cited if levels.get(d, Role.EMPLOYEE).value not in visible), None
    )
    if hidden_citation is not None:
        leak = f"citation of a {levels[hidden_citation].value} document"
    elif (canary := _first_canary(outputs, hidden)) is not None:
        leak = f"canary {canary} in the output"
    elif (canary := _first_canary(seen, hidden)) is not None:
        leak = f"canary {canary} in the model input"
    found = None
    if permitted and question.facts:
        texts = outputs if surface == "search" else outputs[:1]
        found = _found(texts, question.facts)
    # Answers: the reply only (sources are text the user may see anyway); agent: the
    # reply and any proposed action's arguments.
    shown = {"search": [], "answers": outputs[:1], "agent": outputs[:2]}[surface]
    reply = " | ".join(shown)[:300] if shown else None
    return AccessOutcome(
        surface=surface,
        role=role.value,
        question_id=question.id,
        permitted=permitted,
        status=status,
        leaked=leak is not None,
        leak=leak,
        found=found,
        reply=reply,
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def summarize_access(report: AccessReport) -> list[dict[str, Any]]:
    rows = []
    surfaces = list(dict.fromkeys(o.surface for o in report.outcomes))
    for surface in surfaces:
        for role in Role:
            group = [o for o in report.outcomes if o.surface == surface and o.role == role.value]
            if not group:
                continue
            checked = [o for o in group if o.found is not None]
            latencies = sorted(o.latency_ms for o in group)
            rows.append(
                {
                    "surface": surface,
                    "role": role.value,
                    "questions": len(group),
                    "leaks": sum(o.leaked for o in group),
                    "permitted": len(checked),
                    "found": sum(bool(o.found) for o in checked),
                    "errors": sum(o.status.startswith("error") for o in group),
                    "median_s": latencies[len(latencies) // 2] / 1000,
                }
            )
    return rows


def access_report_to_json(report: AccessReport) -> str:
    return json.dumps(
        {
            "backend": report.backend,
            "model_id": report.model_id,
            "summary": summarize_access(report),
            "outcomes": [asdict(o) for o in report.outcomes],
        },
        indent=2,
    )


def access_report_to_markdown(report: AccessReport) -> str:
    total = sum(o.leaked for o in report.outcomes)
    lines = [
        "# Access leakage evaluation run",
        "",
        f"Backend: {report.backend}. Model: `{report.model_id or 'none'}`. "
        f"Checks: {len(report.outcomes)}. Leaks: {total}.",
        "",
        "| Surface | Role | Questions | Leaks | Found where permitted | Errors | Median s |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summarize_access(report):
        lines.append(
            f"| {row['surface']} | {row['role']} | {row['questions']} | {row['leaks']} | "
            f"{row['found']}/{row['permitted']} | {row['errors']} | {row['median_s']:.1f} |"
        )
    leaks = [o for o in report.outcomes if o.leaked]
    if leaks:
        lines += ["", "## Leaks", ""]
        lines += [f"- {o.surface} {o.role} {o.question_id}: {o.leak}" for o in leaks]
    misses = [o for o in report.outcomes if o.found is False]
    if misses:
        lines += ["", "## Permitted questions without the expected fact", ""]
        lines += [f"- {o.surface} {o.role} {o.question_id} ({o.status})" for o in misses]
    return "\n".join(lines) + "\n"
