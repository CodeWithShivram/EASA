"""The retrieval evaluation dataset: a synthetic corpus and labelled queries.

Relevance is defined by evidence phrases rather than chunk IDs, so the same
labels work for every chunking configuration: a retrieved chunk is relevant
to a phrase when its text contains the phrase.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config import API_ROOT
from app.services.normalization import normalize_text

EVAL_ROOT = API_ROOT / "eval"
CATEGORIES = ("paraphrase", "exact", "keyword")


@dataclass(frozen=True)
class EvalQuery:
    id: str
    category: str
    query: str
    document: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Dataset:
    # File name -> raw bytes, uploaded through the normal document pipeline.
    documents: dict[str, bytes]
    queries: tuple[EvalQuery, ...]


def load_dataset(root: Path = EVAL_ROOT) -> Dataset:
    documents = {path.name: path.read_bytes() for path in sorted((root / "corpus").glob("*.txt"))}
    raw = json.loads((root / "queries.json").read_text(encoding="utf-8"))
    queries = tuple(
        EvalQuery(
            id=item["id"],
            category=item["category"],
            query=item["query"],
            document=item["document"],
            evidence=tuple(item["evidence"]),
        )
        for item in raw["queries"]
    )
    return Dataset(documents=documents, queries=queries)


def validate_dataset(dataset: Dataset) -> list[str]:
    """Problems that would make the labels ambiguous; an empty list means valid."""
    problems: list[str] = []
    texts = {name: normalize_text(data.decode("utf-8")) for name, data in dataset.documents.items()}
    seen: set[str] = set()
    for query in dataset.queries:
        if query.id in seen:
            problems.append(f"{query.id}: duplicate id")
        seen.add(query.id)
        if query.category not in CATEGORIES:
            problems.append(f"{query.id}: unknown category {query.category!r}")
        if query.document not in texts:
            problems.append(f"{query.id}: unknown document {query.document!r}")
            continue
        if not query.evidence:
            problems.append(f"{query.id}: no evidence")
        for phrase in query.evidence:
            if normalize_text(phrase) != phrase or "\n" in phrase:
                problems.append(f"{query.id}: evidence is not a normalized single line")
            count = texts[query.document].count(phrase)
            if count != 1:
                problems.append(f"{query.id}: evidence found {count} times in {query.document}")
            others = [
                name for name, text in texts.items() if name != query.document and phrase in text
            ]
            if others:
                problems.append(f"{query.id}: evidence also found in {', '.join(others)}")
    return problems
