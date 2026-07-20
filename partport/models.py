"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProjectContext:
    project_dir: Path | None = None
    project_file: Path | None = None
    warning: str = ""
    candidates: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RunnerOptions:
    import_symbol: bool = True
    import_footprint: bool = True
    models: tuple[str, ...] = ("STEP",)
    skip_existing: bool = True
    timeout_seconds: int = 180


@dataclass
class RunResult:
    code: str
    status: ResultStatus
    returncode: int | None
    elapsed_seconds: float
    command: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    message: str = ""
