"""Merge validated converter output into user-selected global KiCad libraries."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

from .jlc2_runner import JLC2Runner
from .library_catalog import LibraryEntry
from .library_tables import child_form_spans, form_spans, is_balanced_s_expression
from .models import ResultStatus, RunResult, RunnerOptions
from .validation import OutputSnapshot, validate_import


class GlobalImportError(RuntimeError):
    pass


def _atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=path.parent
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".partport.bak"))


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _symbol_name(form: str) -> str:
    match = re.match(r'\(symbol\s+"((?:\\.|[^"\\])*)"', form)
    return match.group(1) if match else ""


def _rewrite_symbol_footprint(form: str, footprint_nickname: str) -> str:
    pattern = re.compile(r'(\(property\s+"Footprint"\s+")partport:')
    return pattern.sub(lambda match: match.group(1) + footprint_nickname + ":", form)


def merge_symbol_library(
    staged: Path,
    target: Path,
    footprint_nickname: str,
    *,
    skip_existing: bool,
) -> tuple[int, int]:
    target_text = target.read_text(encoding="utf-8", errors="replace")
    staged_text = staged.read_text(encoding="utf-8", errors="replace")
    if not is_balanced_s_expression(target_text) or not target_text.lstrip().startswith(
        "(kicad_symbol_lib"
    ):
        raise GlobalImportError(f"Invalid target symbol library: {target}")
    incoming = [
        _rewrite_symbol_footprint(staged_text[start:end], footprint_nickname)
        for start, end in child_form_spans(staged_text, "kicad_symbol_lib", "symbol")
    ]
    if not incoming:
        raise GlobalImportError("The staging symbol library contains no symbols.")

    existing_spans = child_form_spans(target_text, "kicad_symbol_lib", "symbol")
    existing = {_symbol_name(target_text[start:end]): (start, end) for start, end in existing_spans}
    skipped = 0
    accepted: list[str] = []
    replace_names: set[str] = set()
    for form in incoming:
        name = _symbol_name(form)
        if not name:
            raise GlobalImportError("A generated symbol has no valid name.")
        if name in existing and skip_existing:
            skipped += 1
            continue
        if name in existing:
            replace_names.add(name)
        accepted.append(form)

    for name in replace_names:
        start, end = existing[name]
        target_text = target_text[:start] + target_text[end:]
        shift = end - start
        existing = {
            other: ((s - shift if s > start else s), (e - shift if e > start else e))
            for other, (s, e) in existing.items()
            if other != name
        }

    if not accepted:
        return 0, skipped
    roots = form_spans(target_text, "kicad_symbol_lib")
    if len(roots) != 1:
        raise GlobalImportError(f"Ambiguous target symbol library root: {target}")
    close_index = roots[0][1] - 1
    newline = "\r\n" if "\r\n" in target_text else "\n"
    block = newline.join(form.rstrip("\r\n") for form in accepted) + newline
    updated = target_text[:close_index].rstrip("\r\n") + newline + block + target_text[close_index:]
    if not is_balanced_s_expression(updated):
        raise GlobalImportError("Merging symbols produced an invalid library.")
    _backup(target)
    _atomic_write(target, updated)
    return len(accepted), skipped


def merge_footprint_library(
    staged: Path,
    target: Path,
    target_uri: str,
    *,
    skip_existing: bool,
) -> tuple[int, int]:
    written = 0
    skipped = 0
    model_base = target_uri.rstrip("/\\") + "/packages3d"
    old_model_base = "${KIPRJMOD}/PartPortLib/partport.pretty/packages3d"
    for source in sorted(staged.glob("*.kicad_mod")):
        destination = target / source.name
        if destination.exists() and skip_existing:
            skipped += 1
            continue
        text = source.read_text(encoding="utf-8", errors="replace").replace(
            old_model_base, model_base.replace("\\", "/")
        )
        if not is_balanced_s_expression(text):
            raise GlobalImportError(f"Invalid generated footprint: {source.name}")
        _backup(destination)
        _atomic_write(destination, text)
        written += 1

    staged_models = staged / "packages3d"
    if staged_models.is_dir():
        for source in sorted(path for path in staged_models.iterdir() if path.is_file()):
            destination = target / "packages3d" / source.name
            if destination.exists() and skip_existing:
                continue
            _backup(destination)
            _atomic_copy(source, destination)
    return written, skipped


class GlobalLibraryImporter:
    def __init__(self, runner: JLC2Runner) -> None:
        self.runner = runner

    def import_code(
        self,
        code: str,
        options: RunnerOptions,
        symbol_library: LibraryEntry,
        footprint_library: LibraryEntry,
        on_line,
        cancel_event: threading.Event,
    ) -> RunResult:
        if not symbol_library.writable or not symbol_library.path:
            return RunResult(code, ResultStatus.FAILED, None, 0, message="Symbol library is not writable.")
        if not footprint_library.writable or not footprint_library.path:
            return RunResult(code, ResultStatus.FAILED, None, 0, message="Footprint library is not writable.")

        with tempfile.TemporaryDirectory(prefix="partport-global-stage-") as directory:
            staging_project = Path(directory)
            stage_options = replace(options, skip_existing=False)
            before = OutputSnapshot.capture(staging_project)
            result = self.runner.run(
                code, staging_project, stage_options, on_line, cancel_event
            )
            if result.status != ResultStatus.SUCCESS:
                return result
            report = validate_import(staging_project, stage_options, before, result.output)
            for warning in report.warnings:
                on_line("Validation warning: " + warning)
            if report.status == ResultStatus.FAILED:
                result.status = ResultStatus.FAILED
                result.message = " ".join(report.errors)
                return result

            try:
                written = 0
                skipped = 0
                base = staging_project / "PartPortLib"
                if options.import_footprint:
                    count, ignored = merge_footprint_library(
                        base / "partport.pretty",
                        footprint_library.path,
                        footprint_library.uri,
                        skip_existing=options.skip_existing,
                    )
                    written += count
                    skipped += ignored
                if options.import_symbol:
                    count, ignored = merge_symbol_library(
                        base / "symbols" / "partport.kicad_sym",
                        symbol_library.path,
                        footprint_library.nickname,
                        skip_existing=options.skip_existing,
                    )
                    written += count
                    skipped += ignored
            except (OSError, GlobalImportError) as exc:
                result.status = ResultStatus.FAILED
                result.message = str(exc)
                return result

            on_line(
                f"Merged into global libraries: {written} item(s), {skipped} skipped."
            )
            if written == 0 and skipped:
                result.status = ResultStatus.SKIPPED
            elif report.status == ResultStatus.PARTIAL:
                result.status = ResultStatus.PARTIAL
            return result
