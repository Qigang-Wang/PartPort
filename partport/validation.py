"""Validate files produced by JLC2KiCadLib before registering them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .library_tables import is_balanced_s_expression
from .models import ResultStatus, RunnerOptions


@dataclass(frozen=True)
class FileStamp:
    size: int
    modified_ns: int


@dataclass(frozen=True)
class OutputSnapshot:
    files: dict[Path, FileStamp]

    @classmethod
    def capture(cls, project_dir: Path) -> "OutputSnapshot":
        root = project_dir / "PartPortLib"
        files: dict[Path, FileStamp] = {}
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    stat = path.stat()
                    files[path.relative_to(root)] = FileStamp(stat.st_size, stat.st_mtime_ns)
        return cls(files)


@dataclass
class ValidationReport:
    status: ResultStatus
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _changed_files(
    before: OutputSnapshot, after: OutputSnapshot, suffixes: tuple[str, ...]
) -> list[Path]:
    return sorted(
        path
        for path, stamp in after.files.items()
        if path.suffix.lower() in suffixes and before.files.get(path) != stamp
    )


def _is_explicit_skip(output: list[str]) -> bool:
    joined = "\n".join(output).lower()
    return "skip" in joined and ("exist" in joined or "already" in joined)


def validate_import(
    project_dir: Path,
    options: RunnerOptions,
    before: OutputSnapshot,
    output: list[str],
) -> ValidationReport:
    after = OutputSnapshot.capture(project_dir)
    errors: list[str] = []
    warnings: list[str] = []
    skipped = _is_explicit_skip(output)
    produced_primary_output = False

    if options.import_symbol:
        relative = Path("symbols") / "partport.kicad_sym"
        symbol_path = project_dir / "PartPortLib" / relative
        changed = before.files.get(relative) != after.files.get(relative)
        produced_primary_output |= changed
        if not symbol_path.is_file():
            errors.append("Symbol library was not created.")
        elif changed:
            text = symbol_path.read_text(encoding="utf-8", errors="replace")
            if "(kicad_symbol_lib" not in text or not is_balanced_s_expression(text):
                errors.append("Generated symbol library is malformed.")
        elif not skipped:
            errors.append("Symbol library did not change and no existing-part skip was reported.")

    if options.import_footprint:
        changed_footprints = _changed_files(before, after, (".kicad_mod",))
        produced_primary_output |= bool(changed_footprints)
        if not changed_footprints and not skipped:
            errors.append("No footprint was created or updated.")
        for relative in changed_footprints:
            path = project_dir / "PartPortLib" / relative
            text = path.read_text(encoding="utf-8", errors="replace")
            if (
                "(footprint " not in text
                and "(module " not in text
                or not is_balanced_s_expression(text)
            ):
                errors.append(f"Generated footprint is malformed: {relative}")

        if options.models:
            changed_models = _changed_files(before, after, (".step", ".stp", ".wrl"))
            if not changed_models and not skipped:
                warnings.append("No requested 3D model was created; the source may not provide one.")

    if errors:
        status = ResultStatus.FAILED
    elif skipped and not produced_primary_output:
        status = ResultStatus.SKIPPED
    elif warnings:
        status = ResultStatus.PARTIAL
    else:
        status = ResultStatus.SUCCESS
    return ValidationReport(status, errors, warnings)
