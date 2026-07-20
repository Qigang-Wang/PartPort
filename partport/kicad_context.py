"""Discover the project associated with the KiCad action invocation."""

from __future__ import annotations

from pathlib import Path

from .models import ProjectContext


def find_project_file(directory: Path, preferred_stem: str = "") -> Path | None:
    directory = directory.expanduser().resolve()
    if preferred_stem:
        preferred = directory / f"{preferred_stem}.kicad_pro"
        if preferred.is_file():
            return preferred
    projects = sorted(directory.glob("*.kicad_pro")) if directory.is_dir() else []
    return projects[0] if len(projects) == 1 else None


def _context_from_project_path(raw_path: str, raw_name: str = "") -> ProjectContext | None:
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if path.suffix.lower() == ".kicad_pro":
        project_file = path.resolve()
        return ProjectContext(project_file.parent, project_file)
    directory = path.resolve()
    if not directory.is_dir():
        return None
    project_file = find_project_file(directory, Path(raw_name).stem)
    return ProjectContext(directory, project_file)


def discover_project_context() -> ProjectContext:
    """Try KiCad IPC, returning a manual-selection warning when it is ambiguous.

    KiCad 10 may omit project information for schematic documents, so failure to
    auto-detect is an expected condition rather than a startup error.
    """
    try:
        from kipy import KiCad
        from kipy.proto.common.types import DocumentType

        client = KiCad(client_name="PartPort project discovery", timeout_ms=2500)
        try:
            documents = client.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
            contexts: list[ProjectContext] = []
            for document in documents:
                if document.HasField("project"):
                    context = _context_from_project_path(
                        document.project.path, document.project.name
                    )
                    if context:
                        contexts.append(context)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        unique: dict[Path, ProjectContext] = {
            context.project_dir: context
            for context in contexts
            if context.project_dir is not None
        }
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            return ProjectContext(
                warning="Multiple KiCad projects are open. Select the target project folder.",
                candidates=tuple(unique),
            )
        return ProjectContext(
            warning=(
                "KiCad 10 did not expose the schematic project path. "
                "Select the project folder once before importing."
            )
        )
    except Exception as exc:
        return ProjectContext(
            warning=f"Could not detect the KiCad project ({exc}). Select it manually."
        )
