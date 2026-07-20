"""Safely register PartPort's project-local KiCad libraries."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path


class LibraryTableError(RuntimeError):
    pass


def is_balanced_s_expression(text: str) -> bool:
    depth = 0
    quoted = False
    escaped = False
    comment = False
    for char in text:
        if comment:
            if char == "\n":
                comment = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == ";":
            comment = True
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted


def _scanned_forms(text: str) -> list[tuple[int, int, int, str]]:
    """Return ``(start, end, depth, head)`` for all complete forms."""
    stack: list[int] = []
    spans: list[tuple[int, int, int, str]] = []
    quoted = False
    escaped = False
    comment = False
    for index, char in enumerate(text):
        if comment:
            if char == "\n":
                comment = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == ";":
            comment = True
        elif char == '"':
            quoted = True
        elif char == "(":
            stack.append(index)
        elif char == ")" and stack:
            start = stack.pop()
            atom = re.match(r"\s*([^\s()]+)", text[start + 1 : index])
            if atom:
                spans.append((start, index + 1, len(stack) + 1, atom.group(1)))
    return sorted(spans)


def form_spans(text: str, head: str) -> list[tuple[int, int]]:
    """Return matching S-expression spans, ignoring strings and comments."""
    return [(start, end) for start, end, _depth, atom in _scanned_forms(text) if atom == head]


def child_form_spans(text: str, root_head: str, child_head: str) -> list[tuple[int, int]]:
    """Return forms that are direct children of the single root expression."""
    roots = [item for item in _scanned_forms(text) if item[3] == root_head and item[2] == 1]
    if len(roots) != 1:
        return []
    root_start, root_end, _depth, _head = roots[0]
    return [
        (start, end)
        for start, end, depth, atom in _scanned_forms(text)
        if atom == child_head and depth == 2 and root_start < start < end < root_end
    ]


def _lib_entries(text: str) -> list[str]:
    roots = [item for item in _scanned_forms(text) if item[2] == 1]
    if len(roots) != 1:
        return []
    root_start, root_end, _depth, _head = roots[0]
    return [
        text[start:end]
        for start, end, depth, atom in _scanned_forms(text)
        if atom == "lib" and depth == 2 and root_start < start < end < root_end
    ]


def _root_close_index(text: str, root_name: str) -> int | None:
    spans = [
        (start, end)
        for start, end, depth, atom in _scanned_forms(text)
        if atom == root_name and depth == 1
    ]
    if len(spans) != 1:
        return None
    start, end = spans[0]
    if text[:start].strip():
        return None
    return end - 1


def _field(entry: str, name: str) -> str | None:
    match = re.search(rf'\({re.escape(name)}\s+"((?:\\.|[^"\\])*)"\)', entry)
    return match.group(1) if match else None


def update_table(path: Path, root_name: str, nickname: str, uri: str, description: str) -> bool:
    """Add a library entry, returning True when the file changed."""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if not is_balanced_s_expression(text) or not text.lstrip().startswith(f"({root_name}"):
            raise LibraryTableError(f"Invalid KiCad library table: {path}")
    else:
        text = f"({root_name}\n)\n"

    for entry in _lib_entries(text):
        if _field(entry, "name") == nickname:
            existing_uri = _field(entry, "uri")
            if existing_uri == uri:
                return False
            raise LibraryTableError(
                f"Library nickname '{nickname}' already points to '{existing_uri}'."
            )

    close_index = _root_close_index(text, root_name)
    if close_index is None:
        raise LibraryTableError(f"Missing or ambiguous root expression in {path}")
    newline = "\r\n" if "\r\n" in text else "\n"
    entry = (
        f'  (lib (name "{nickname}")(type "KiCad")(uri "{uri}")'
        f'(options "")(descr "{description}")){newline}'
    )
    updated = text[:close_index].rstrip("\r\n") + newline + entry + text[close_index:]
    if not is_balanced_s_expression(updated):
        raise LibraryTableError(f"Generated invalid library table: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".partport.bak"))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=path.parent
    ) as handle:
        handle.write(updated)
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True


def register_project_libraries(
    project_dir: Path, *, symbol: bool = True, footprint: bool = True
) -> bool:
    symbol_changed = False
    footprint_changed = False
    if symbol:
        symbol_changed = update_table(
            project_dir / "sym-lib-table",
            "sym_lib_table",
            "partport",
            "${KIPRJMOD}/PartPortLib/symbols/partport.kicad_sym",
            "PartPort imported symbols",
        )
    if footprint:
        footprint_changed = update_table(
            project_dir / "fp-lib-table",
            "fp_lib_table",
            "partport",
            "${KIPRJMOD}/PartPortLib/partport.pretty",
            "PartPort imported footprints",
        )
    return symbol_changed or footprint_changed
