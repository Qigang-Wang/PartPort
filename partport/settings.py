"""Persistent PartPort configuration."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from . import PLUGIN_IDENTIFIER


@dataclass(frozen=True)
class PartPortSettings:
    destination: str = "project"
    global_symbol_library: str = ""
    global_footprint_library: str = ""
    language: str = "zh_CN"
    project_directory: str = ""
    data_sources: tuple[str, ...] = ("lcsc", "szlcsc")


def settings_directory() -> Path:
    override = os.environ.get("PARTPORT_SETTINGS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    try:
        from kipy import KiCad

        path = KiCad(client_name="PartPort settings", timeout_ms=1200).get_plugin_settings_path(
            PLUGIN_IDENTIFIER
        )
        if path:
            return Path(path)
    except Exception:
        pass
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "PartPort"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PartPort"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "partport"


def settings_path() -> Path:
    return settings_directory() / "settings.json"


def load_settings(path: Path | None = None) -> PartPortSettings:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        destination = data.get("destination", "project")
        if destination not in {"project", "global"}:
            destination = "project"
        raw_sources = data.get("data_sources", ["lcsc", "szlcsc"])
        sources = tuple(
            source
            for source in ("lcsc", "szlcsc")
            if isinstance(raw_sources, (list, tuple)) and source in raw_sources
        )
        if not sources:
            sources = ("lcsc", "szlcsc")
        return PartPortSettings(
            destination=destination,
            global_symbol_library=str(data.get("global_symbol_library", "")),
            global_footprint_library=str(data.get("global_footprint_library", "")),
            language=(
                str(data.get("language", "zh_CN"))
                if data.get("language", "zh_CN") in {"zh_CN", "en"}
                else "zh_CN"
            ),
            project_directory=str(data.get("project_directory", "")),
            data_sources=sources,
        )
    except (OSError, ValueError, TypeError):
        return PartPortSettings()


def save_settings(settings: PartPortSettings, path: Path | None = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        json.dump({"version": 2, **asdict(settings)}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path
