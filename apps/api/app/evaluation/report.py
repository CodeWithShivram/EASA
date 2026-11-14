"""JSON and Markdown output for evaluation runs."""

import json
from dataclasses import asdict
from typing import Any

from app.evaluation.runner import K_VALUES, EvaluationReport, SummaryRow


def report_to_json(report: EvaluationReport) -> str:
    data: dict[str, Any] = {
        "backend": report.backend,
        "model_id": report.model_id,
        "top_k": report.top_k,
        "configs": [asdict(stats) for stats in report.configs],
        "summary": [asdict(row) for row in report.summary()],
        "outcomes": [asdict(outcome) for outcome in report.outcomes],
    }
    return json.dumps(data, indent=2)


def _row(row: SummaryRow, *, first: str) -> str:
    recalls = " | ".join(f"{row.recall[k]:.3f}" for k in K_VALUES)
    return f"| {first} | {row.mode} | {recalls} | {row.mrr:.3f} | {row.mean_latency_ms:.1f} |"


def report_to_markdown(report: EvaluationReport) -> str:
    rows = report.summary()
    queries = len({o.query_id for o in report.outcomes})
    header_k = " | ".join(f"R@{k}" for k in K_VALUES)
    divider = "|---" * (len(K_VALUES) + 4) + "|"
    lines = [
        "# Retrieval evaluation run",
        "",
        f"Backend: {report.backend}. Embedding model: `{report.model_id}`. "
        f"Queries: {queries}. Results per query: top {report.top_k}.",
        "",
        "## Chunking configurations",
        "",
        "| Config | Chunks | Mean chunk length (chars) |",
        "|---|---|---|",
        *(f"| {s.config} | {s.chunks} | {s.mean_chunk_chars:.0f} |" for s in report.configs),
        "",
        "## All queries",
        "",
        f"| Config | Mode | {header_k} | MRR@{report.top_k} | Mean ms |",
        divider,
        *(_row(r, first=r.config) for r in rows if r.category == "all"),
    ]
    for stats in report.configs:
        lines += [
            "",
            f"## By category: {stats.config}",
            "",
            f"| Category (n) | Mode | {header_k} | MRR@{report.top_k} | Mean ms |",
            divider,
            *(
                _row(r, first=f"{r.category} ({r.queries})")
                for r in rows
                if r.config == stats.config and r.category != "all"
            ),
        ]
    return "\n".join(lines) + "\n"
