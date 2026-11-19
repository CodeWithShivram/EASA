"""Answer evaluation (Phase 4, P4-M5): grounded answers scored against labelled cases.

Cases (eval/answers.json) cover answerable, unanswerable and false-premise
questions, follow-ups and prompt-injection documents (eval/adversarial). For
each configuration the corpus and the adversarial documents are uploaded into
a fresh, migrated database; every case is answered through AnswerService
(follow-ups with the previous turn as history) and scored. The support check
is also scored offline on the same replies, so it costs no extra model calls.
"""

import json
import logging
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.db.engine import create_db_engine
from app.db.migrate import upgrade_to_head
from app.db.session import create_session_factory
from app.embeddings.base import Embedder
from app.evaluation.dataset import EVAL_ROOT, Dataset
from app.evaluation.metrics import format_tokens, mean, median_tokens
from app.evaluation.runner import (
    EVAL_IDENTITY,
    DatabaseFactory,
    EvalConfig,
    _ingest,
)
from app.llm.base import ChatModel
from app.retrieval.factory import build_indexes
from app.services.answers import AnswerResult, AnswerService, AnswerStatus, Turn, check_support
from app.services.chunking import ChunkingStrategy
from app.services.normalization import normalize_text
from app.services.search import SearchService

logger = logging.getLogger(__name__)

KINDS = ("answerable", "unanswerable", "false_premise", "follow_up", "injection")
# Outcomes counted as correct for each kind.
_CORRECT = {
    "answerable": {"correct"},
    "follow_up": {"correct"},
    "unanswerable": {"refused"},
    "false_premise": {"corrected", "refused"},
    "injection": {"correct", "refused"},
}


@dataclass(frozen=True)
class AnswerCase:
    id: str
    kind: str
    turns: tuple[str, ...]  # one question, or several for a follow-up
    document: str | None = None
    facts: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnswerEvalConfig:
    chunking: EvalConfig
    top_k: int

    @property
    def label(self) -> str:
        return f"{self.chunking.label}-top{self.top_k}"


# The application default (3 chunks of 1,200 characters since ADR-027) comes first.
DEFAULT_ANSWER_CONFIG = AnswerEvalConfig(EvalConfig(ChunkingStrategy.STRUCTURED, 1200), 3)
ALL_ANSWER_CONFIGS = (
    DEFAULT_ANSWER_CONFIG,
    AnswerEvalConfig(EvalConfig(ChunkingStrategy.STRUCTURED, 1200), 5),
    AnswerEvalConfig(EvalConfig(ChunkingStrategy.STRUCTURED, 800), 3),
)


@dataclass(frozen=True)
class CaseOutcome:
    config: str
    case_id: str
    kind: str
    document: str | None  # the document a correct answer cites
    status: str  # answered, insufficient_evidence or error
    reason: str | None
    answer: str | None
    cited: tuple[str, ...]  # cited filenames
    outcome: str
    injected: bool  # forbidden (injected) content appeared in the answer
    # The same reply after the support check (scored offline).
    checked_outcome: str
    checked_cited: tuple[str, ...]
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass
class AnswerEvalReport:
    model_id: str
    configs: list[str] = field(default_factory=list)
    outcomes: list[CaseOutcome] = field(default_factory=list)


def load_answer_cases(root: Path = EVAL_ROOT) -> list[AnswerCase]:
    raw = json.loads((root / "answers.json").read_text(encoding="utf-8"))
    cases = []
    for item in raw["cases"]:
        turns = tuple(item["turns"]) if "turns" in item else (item["question"],)
        cases.append(
            AnswerCase(
                id=item["id"],
                kind=item["kind"],
                turns=turns,
                document=item.get("document"),
                facts=tuple(item.get("facts", ())),
                forbidden=tuple(item.get("forbidden", ())),
            )
        )
    return cases


def load_adversarial_documents(root: Path = EVAL_ROOT) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((root / "adversarial").glob("*.txt"))}


def validate_answer_cases(cases: Sequence[AnswerCase], documents: dict[str, bytes]) -> list[str]:
    """Problems that would make the cases unscorable; an empty list means valid."""
    problems: list[str] = []
    texts = {n: normalize_text(d.decode("utf-8")).lower() for n, d in documents.items()}
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            problems.append(f"{case.id}: duplicate id")
        seen.add(case.id)
        if case.kind not in KINDS:
            problems.append(f"{case.id}: unknown kind {case.kind!r}")
        if case.kind == "follow_up" and len(case.turns) < 2:
            problems.append(f"{case.id}: a follow-up needs at least two turns")
        if case.kind == "unanswerable":
            continue
        if case.document not in texts:
            problems.append(f"{case.id}: unknown document {case.document!r}")
            continue
        if not case.facts:
            problems.append(f"{case.id}: no facts")
        if not any(f.lower() in texts[case.document] for f in case.facts):
            problems.append(f"{case.id}: no fact appears in {case.document}")
        if case.kind == "injection" and not case.forbidden:
            problems.append(f"{case.id}: injection case without forbidden content")
    return problems


def score(
    case: AnswerCase, status: str, answer: str | None, cited: Sequence[str]
) -> tuple[str, bool]:
    """(outcome, injected) for one reply.

    Outcomes: refused, correct (fact present and expected document cited),
    wrong_citation (fact present, expected document not cited), wrong (answered
    without the fact), corrected (false premise answered with the true fact),
    accepted (false premise answered without it), answered (an unanswerable
    question was answered), error.
    """
    text = (answer or "").lower()
    injected = any(f.lower() in text for f in case.forbidden)
    if status == "error":
        return "error", injected
    if status != AnswerStatus.ANSWERED.value:
        return "refused", injected
    if case.kind == "unanswerable":
        return "answered", injected
    has_fact = any(f.lower() in text for f in case.facts)
    if case.kind == "false_premise":
        return ("corrected" if has_fact else "accepted"), injected
    if case.kind == "injection" and injected:
        return "injected", injected
    if not has_fact:
        return "wrong", injected
    return ("correct" if case.document in cited else "wrong_citation"), injected


def is_correct(outcome: CaseOutcome, *, checked: bool = False) -> bool:
    value = outcome.checked_outcome if checked else outcome.outcome
    return value in _CORRECT[outcome.kind]


def run_answer_evaluation(
    cases: Sequence[AnswerCase],
    documents: dict[str, bytes],
    embedder: Embedder,
    model: ChatModel,
    *,
    database: DatabaseFactory,
    configs: Sequence[AnswerEvalConfig] = (DEFAULT_ANSWER_CONFIG,),
    max_output_tokens: int = 256,
    progress: Callable[[str], None] | None = None,
    checkpoint: Path | None = None,
) -> AnswerEvalReport:
    """Run the cases; with a checkpoint file, finished cases are saved as they
    complete and skipped when the run is restarted (long CPU runs get interrupted)."""
    report = AnswerEvalReport(model_id=model.model_id)
    corpus = Dataset(documents=documents, queries=())
    done = load_checkpoint(checkpoint, model.model_id)
    for config in configs:
        report.configs.append(config.label)
        report.outcomes.extend(
            done[(config.label, c.id)] for c in cases if (config.label, c.id) in done
        )
        pending = [c for c in cases if (config.label, c.id) not in done]
        if not pending:
            continue
        with database() as url, tempfile.TemporaryDirectory(prefix="easa-answers-") as blobs:
            upgrade_to_head(url)
            engine = create_db_engine(url)
            try:
                with create_session_factory(engine)() as session:
                    _ingest(session, corpus, embedder, config.chunking, Path(blobs))
                    service = AnswerService(
                        SearchService(session, embedder, *build_indexes(session)),
                        model,
                        max_output_tokens=max_output_tokens,
                        temperature=0.0,
                    )
                    for case in pending:
                        outcome = _run_case(service, case, config)
                        report.outcomes.append(outcome)
                        _append_checkpoint(checkpoint, model.model_id, outcome)
                        if progress:
                            progress(f"{config.label} {case.id} {outcome.outcome}")
            finally:
                engine.dispose()
    # Restore case order (checkpointed outcomes were added first).
    order = {c.id: i for i, c in enumerate(cases)}
    configs_order = {label: i for i, label in enumerate(report.configs)}
    report.outcomes.sort(key=lambda o: (configs_order[o.config], order[o.case_id]))
    return report


def load_checkpoint(path: Path | None, model_id: str) -> dict[tuple[str, str], CaseOutcome]:
    """Outcomes saved by an earlier run with the same model (a cut-off last line is ignored)."""
    if path is None or not path.is_file():
        return {}
    done: dict[tuple[str, str], CaseOutcome] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if data.pop("model_id", None) != model_id:
            continue
        data["cited"] = tuple(data["cited"])
        data["checked_cited"] = tuple(data["checked_cited"])
        outcome = CaseOutcome(**data)
        done[(outcome.config, outcome.case_id)] = outcome
    return done


def _append_checkpoint(path: Path | None, model_id: str, outcome: CaseOutcome) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"model_id": model_id, **asdict(outcome)}) + "\n")


def _run_case(service: AnswerService, case: AnswerCase, config: AnswerEvalConfig) -> CaseOutcome:
    history: list[Turn] = []
    result: AnswerResult | None = None
    status, reason, error_code = "error", None, None
    started = time.perf_counter()
    try:
        for question in case.turns:
            result = service.answer(EVAL_IDENTITY, question, top_k=config.top_k, history=history)
            history.append(Turn(question, result.answer))
        if result is not None:  # every case has at least one turn
            status = result.status.value
            reason = result.reason.value if result.reason else None
    except AppError as error:
        error_code = error.code
    latency = (time.perf_counter() - started) * 1000
    answer = result.answer if result and status != "error" else None
    cited = tuple(s.hit.filename for s in result.sources) if result and answer else ()
    outcome, injected = score(case, status, answer, cited)
    # Support check, applied offline to the same reply.
    checked_answer, checked_cited, checked_status = answer, cited, status
    if result and answer:
        checked_answer, kept = check_support(answer, result.sources)
        checked_cited = tuple(s.hit.filename for s in kept)
        if not kept:
            checked_status, checked_answer = AnswerStatus.INSUFFICIENT_EVIDENCE.value, None
    checked_outcome, _ = score(case, checked_status, checked_answer, checked_cited)
    return CaseOutcome(
        config=config.label,
        case_id=case.id,
        kind=case.kind,
        document=case.document,
        status=status,
        reason=reason if status != "error" else error_code,
        answer=answer,
        cited=cited,
        outcome=outcome,
        injected=injected,
        checked_outcome=checked_outcome,
        checked_cited=checked_cited,
        latency_ms=latency,
        prompt_tokens=result.prompt_tokens if result else None,
        completion_tokens=result.completion_tokens if result else None,
    )


def summarize(report: AnswerEvalReport) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in report.configs:
        selected = [o for o in report.outcomes if o.config == config]
        answered = [o for o in selected if o.status == AnswerStatus.ANSWERED.value]
        for kind in ("all", *KINDS):
            group = [o for o in selected if kind in ("all", o.kind)]
            if not group:
                continue
            rows.append(
                {
                    "config": config,
                    "kind": kind,
                    "cases": len(group),
                    "correct": mean([float(is_correct(o)) for o in group]),
                    "correct_with_support_check": mean(
                        [float(is_correct(o, checked=True)) for o in group]
                    ),
                    "outcomes": dict(Counter(o.outcome for o in group)),
                    "injected": sum(o.injected for o in group),
                    "median_ms": _median([o.latency_ms for o in group]),
                    "median_tokens": median_tokens(
                        [(o.prompt_tokens, o.completion_tokens) for o in group]
                    ),
                }
            )
        rows.append(
            {
                "config": config,
                "kind": "citation_precision",
                "cases": len(answered),
                "value": _citation_precision(answered),
                "value_with_support_check": _citation_precision(answered, checked=True),
            }
        )
    return rows


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _citation_precision(outcomes: Sequence[CaseOutcome], *, checked: bool = False) -> float:
    """Share of cited sources that come from the case's expected document."""
    hits = total = 0
    for outcome in outcomes:
        if outcome.document is None:
            continue
        cited = outcome.checked_cited if checked else outcome.cited
        total += len(cited)
        hits += sum(1 for name in cited if name == outcome.document)
    return hits / total if total else 0.0


def answer_report_to_json(report: AnswerEvalReport) -> str:
    return json.dumps(
        {
            "model_id": report.model_id,
            "configs": report.configs,
            "summary": summarize(report),
            "outcomes": [asdict(o) for o in report.outcomes],
        },
        indent=2,
    )


def answer_report_to_markdown(report: AnswerEvalReport) -> str:
    rows = summarize(report)
    lines = [
        "# Answer evaluation run",
        "",
        f"Model: `{report.model_id}`. Cases: {len({o.case_id for o in report.outcomes})}. "
        "Temperature 0.",
        "",
        "| Config | Kind (n) | Correct | Correct with support check | Outcomes "
        "| Injected | Median s | Median tokens |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["kind"] == "citation_precision":
            continue
        outcomes = ", ".join(f"{k} {v}" for k, v in sorted(row["outcomes"].items()))
        lines.append(
            f"| {row['config']} | {row['kind']} ({row['cases']}) | {row['correct']:.2f} | "
            f"{row['correct_with_support_check']:.2f} | {outcomes} | {row['injected']} | "
            f"{row['median_ms'] / 1000:.1f} | {format_tokens(row['median_tokens'])} |"
        )
    lines += [
        "",
        "| Config | Answered | Citation precision | With support check |",
        "|---|---|---|---|",
    ]
    for row in rows:
        if row["kind"] == "citation_precision":
            lines.append(
                f"| {row['config']} | {row['cases']} | {row['value']:.2f} | "
                f"{row['value_with_support_check']:.2f} |"
            )
    lines += [
        "",
        "## Replies",
        "",
        "| Config | Case | Outcome | Support check | Answer | Cited |",
        "|---|---|---|---|---|---|",
    ]
    for o in report.outcomes:
        answer = (o.answer or "").replace("|", "/").replace("\n", " ")[:160]
        lines.append(
            f"| {o.config} | {o.case_id} | {o.outcome} | {o.checked_outcome} | {answer} | "
            f"{', '.join(o.cited)} |"
        )
    return "\n".join(lines) + "\n"
