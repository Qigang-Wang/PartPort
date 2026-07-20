"""Read writable KiCad libraries from the global library tables."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .library_tables import child_form_spans, is_balanced_s_expression


@dataclass(frozen=True)
class LibraryEntry:
    nickname: str
    library_type: str
    uri: str
    path: Path | None
    writable: bool
    reason: str = ""


@dataclass(frozen=True)
class GlobalLibraryCatalog:
    config_dir: Path
    symbols: tuple[LibraryEntry, ...]
    footprints: tuple[LibraryEntry, ...]


def kicad_config_directory() -> Path:
    override = os.environ.get("PARTPORT_KICAD_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "kicad" / "10.0"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "kicad" / "10.0"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kicad" / "10.0"


def _field(entry: str, name: str) -> str:
    match = re.search(rf'\({re.escape(name)}\s+"((?:\\.|[^"\\])*)"\)', entry)
    if not match:
        return ""
    return match.group(1).replace(r'\"', '"').replace(r"\\", "\\")


def _resolve_uri(uri: str, table_dir: Path) -> tuple[Path | None, str]:
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        value = os.environ.get(name)
        if value is None:
            unresolved.append(name)
            return match.group(0)
        return value

    expanded = re.sub(r"\$\{([^}]+)\}|\$\(([^)]+)\)", replace, uri)
    if unresolved:
        return None, "Unresolved variable: " + ", ".join(unresolved)
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = table_dir / path
    return path.resolve(), ""


def _is_under_program_files(path: Path) -> bool:
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            try:
                path.relative_to(Path(root).resolve())
                return True
            except ValueError:
                pass
    return False


def _read_table(path: Path, root_head: str, expected: str) -> tuple[LibraryEntry, ...]:
    if not path.is_file():
        return ()
    text = path.read_text(encoding="utf-8", errors="replace")
    if not is_balanced_s_expression(text):
        return ()
    entries: list[LibraryEntry] = []
    for start, end in child_form_spans(text, root_head, "lib"):
        form = text[start:end]
        nickname = _field(form, "name")
        library_type = _field(form, "type")
        uri = _field(form, "uri")
        resolved, reason = _resolve_uri(uri, path.parent)
        writable = False
        if library_type != "KiCad":
            reason = "Only KiCad file libraries are supported"
        elif resolved is None:
            pass
        elif _is_under_program_files(resolved):
            reason = "KiCad installation libraries are read-only"
        elif expected == "symbol" and not resolved.is_file():
            reason = "Symbol library file does not exist"
        elif expected == "footprint" and not resolved.is_dir():
            reason = "Footprint library directory does not exist"
        else:
            target = resolved if expected == "footprint" else resolved.parent
            writable = os.access(target, os.W_OK)
            if not writable:
                reason = "Library is not writable"
        entries.append(LibraryEntry(nickname, library_type, uri, resolved, writable, reason))
    return tuple(entries)


def load_global_library_catalog(config_dir: Path | None = None) -> GlobalLibraryCatalog:
    config_dir = (config_dir or kicad_config_directory()).resolve()
    return GlobalLibraryCatalog(
        config_dir,
        _read_table(config_dir / "sym-lib-table", "sym_lib_table", "symbol"),
        _read_table(config_dir / "fp-lib-table", "fp_lib_table", "footprint"),
    )
