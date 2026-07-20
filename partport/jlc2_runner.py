"""Run JLC2KiCadLib from the KiCad-managed Python environment."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .models import ResultStatus, RunResult, RunnerOptions

LineCallback = Callable[[str], None]


def summarize_process_failure(lines: list[str], returncode: int) -> str:
    """Return the useful final exception instead of only an exit status."""
    for raw_line in reversed(lines):
        line = raw_line.strip()
        if not line or line == "Traceback (most recent call last):":
            continue
        if line.startswith("File ") or line.startswith("During handling of"):
            continue
        if any(token in line for token in ("Error:", "Exception:", "Failed:", "fatal:")):
            return f"{line} (exit code {returncode})"
    for raw_line in reversed(lines):
        line = raw_line.strip()
        if line:
            return f"{line} (exit code {returncode})"
    return f"JLC2KiCadLib exited with code {returncode}."


def build_command(code: str, project_dir: Path, options: RunnerOptions) -> list[str]:
    output_dir = project_dir / "PartPortLib"
    command = [
        sys.executable,
        "-m",
        "JLC2KiCadLib.JLC2KiCadLib",
        code,
        "-dir",
        str(output_dir),
        "-symbol_lib",
        "partport",
        "-symbol_lib_dir",
        "symbols",
        "-footprint_lib",
        "partport.pretty",
        "-model_dir",
        "packages3d",
        "-model_base_variable",
        "${KIPRJMOD}/PartPortLib/partport.pretty",
    ]
    if not options.import_symbol:
        command.append("--no_symbol")
    if not options.import_footprint:
        command.append("--no_footprint")
    if options.import_footprint:
        command.append("-models")
        command.extend(options.models)
    if options.skip_existing:
        command.append("--skip_existing")
    return command


class JLC2Runner:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    def run(
        self,
        code: str,
        project_dir: Path,
        options: RunnerOptions,
        on_line: LineCallback,
        cancel_event: threading.Event,
    ) -> RunResult:
        command = build_command(code, project_dir, options)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        started = time.monotonic()
        lines: list[str] = []

        try:
            process = subprocess.Popen(
                command,
                cwd=str(project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except Exception as exc:
            return RunResult(
                code,
                ResultStatus.FAILED,
                None,
                time.monotonic() - started,
                command,
                message=str(exc),
            )

        with self._lock:
            self._process = process

        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for raw_line in process.stdout:
                output_queue.put(raw_line.rstrip("\r\n"))
            output_queue.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        stream_done = False
        status = ResultStatus.SUCCESS
        message = ""

        try:
            while process.poll() is None or not stream_done:
                try:
                    item = output_queue.get(timeout=0.1)
                    if item is None:
                        stream_done = True
                    else:
                        lines.append(item)
                        on_line(item)
                except queue.Empty:
                    pass

                if cancel_event.is_set():
                    status = ResultStatus.CANCELLED
                    message = "Cancelled by user."
                    self._stop_process(process)
                elif time.monotonic() - started > options.timeout_seconds:
                    status = ResultStatus.FAILED
                    message = f"Timed out after {options.timeout_seconds} seconds."
                    self._stop_process(process)

            returncode = process.wait()
            if status == ResultStatus.SUCCESS and returncode != 0:
                status = ResultStatus.FAILED
                message = summarize_process_failure(lines, returncode)
            joined = "\n".join(lines).lower()
            if status == ResultStatus.SUCCESS and (
                "failed to get component uuid" in joined or "traceback" in joined
            ):
                status = ResultStatus.FAILED
                message = "JLC2KiCadLib reported a conversion error."
            return RunResult(
                code,
                status,
                returncode,
                time.monotonic() - started,
                command,
                lines,
                message,
            )
        finally:
            with self._lock:
                self._process = None

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
