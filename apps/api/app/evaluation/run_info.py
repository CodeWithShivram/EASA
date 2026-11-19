"""What every evaluation report records about its run (P8-M4, ADR-038).

The data version and manifest SHA-256, the models, the settings that shape
the result, the code version (Git commit, marked "-dirty" with uncommitted
changes) and the timing. Added to a report's JSON as "run" and to its
Markdown as a short block under the title.
"""

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.dataset import EVAL_ROOT
from app.evaluation.manifest import load_manifest, manifest_sha256


@dataclass(frozen=True)
class RunInfo:
    evaluation: str
    started_at: str
    finished_at: str
    duration_s: float
    data_version: int
    manifest_sha256: str
    git_commit: str | None
    python: str
    embedding_model: str | None = None
    chat_model: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)


def git_commit(cwd: Path = EVAL_ROOT) -> str | None:
    """The checked-out commit, with "-dirty" for uncommitted changes; None without Git."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        # Fixed arguments, no shell, the resolved git executable.
        head = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=10
        )
        status = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except OSError, subprocess.SubprocessError:
        return None
    if head.returncode != 0:
        return None
    return head.stdout.strip() + ("-dirty" if status.stdout.strip() else "")


def run_info(
    evaluation: str,
    started: datetime,
    *,
    embedding_model: str | None = None,
    chat_model: str | None = None,
    settings: dict[str, Any] | None = None,
    root: Path = EVAL_ROOT,
) -> RunInfo:
    finished = datetime.now(UTC)
    return RunInfo(
        evaluation=evaluation,
        started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"),
        duration_s=round((finished - started).total_seconds(), 1),
        data_version=load_manifest(root).version,
        manifest_sha256=manifest_sha256(root),
        git_commit=git_commit(root),
        python=sys.version.split()[0],
        embedding_model=embedding_model,
        chat_model=chat_model,
        settings=settings or {},
    )


def with_run_info(files: dict[str, str], run: RunInfo) -> dict[str, str]:
    """The report files with the run added: JSON gets "run" first, Markdown a block
    under its title."""
    result = dict(files)
    if "json" in files:
        data = json.loads(files["json"])
        body = data if isinstance(data, dict) else {"report": data}
        result["json"] = json.dumps({"run": asdict(run), **body}, indent=2)
    if "md" in files:
        lines = files["md"].split("\n")
        settings = ", ".join(f"{k}={v}" for k, v in run.settings.items()) or "-"
        block = [
            "",
            f"Run: {run.started_at} to {run.finished_at} ({run.duration_s:.0f} s). "
            f"Data version {run.data_version} (manifest SHA-256 `{run.manifest_sha256[:12]}`). "
            f"Code: `{run.git_commit or 'unknown'}`. Python {run.python}.",
            f"Models: embedding `{run.embedding_model or '-'}`, chat `{run.chat_model or '-'}`. "
            f"Settings: {settings}.",
        ]
        result["md"] = "\n".join(lines[:1] + block + lines[1:])
    return result
