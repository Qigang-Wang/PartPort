import queue
import shutil
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def default_exe_path() -> str:
    found = shutil.which("JLC2KiCadLib.exe")
    if found:
        return found
    candidate = Path.home() / "AppData" / "Roaming" / "Python" / "Python313" / "Scripts" / "JLC2KiCadLib.exe"
    return str(candidate)


def parse_codes(text: str) -> list[str]:
    raw = text.replace(",", "\n").replace(";", "\n")
    codes = [line.strip() for line in raw.splitlines() if line.strip()]
    return list(dict.fromkeys(codes))


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("JLC2KiCadLib GUI")
        self.root.geometry("900x650")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.exe_var = tk.StringVar(value=default_exe_path())
        self.base_dir_var = tk.StringVar(value="JLCLib")
        self.symbol_lib_var = tk.StringVar(value="jlc_lib")
        self.footprint_lib_var = tk.StringVar(value="jlc_footprint_lib.pretty")

        self.build_ui()
        self.poll_log_queue()

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        self.path_row(main, "JLC2KiCadLib.exe", self.exe_var, is_file=True)
        self.path_row(main, "Base dir (-dir)", self.base_dir_var, is_file=False)
        self.simple_row(main, "symbol_lib", self.symbol_lib_var)
        self.simple_row(main, "footprint_lib", self.footprint_lib_var)

        ttk.Label(main, text="LCSC Codes (one per line, or comma/semicolon separated)").pack(
            anchor="w", pady=(10, 2)
        )

        self.code_text = tk.Text(main, height=8)
        self.code_text.pack(fill=tk.X)
        self.code_text.insert("1.0", "C393941")

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(10, 6))

        self.run_btn = ttk.Button(btn_row, text="Download", command=self.start_download)
        self.run_btn.pack(side=tk.LEFT)

        ttk.Button(btn_row, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(main, text="Log").pack(anchor="w", pady=(4, 2))
        self.log_text = tk.Text(main, height=18, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def path_row(self, parent: ttk.Frame, label: str, var: tk.StringVar, is_file: bool) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label, width=20).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

        if is_file:
            ttk.Button(row, text="Browse", command=lambda: self.choose_file(var)).pack(side=tk.LEFT)
        else:
            ttk.Button(row, text="Browse", command=lambda: self.choose_dir(var)).pack(side=tk.LEFT)

    def simple_row(self, parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label, width=20).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

    def choose_file(self, var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            title="Select JLC2KiCadLib.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            var.set(path)

    def choose_dir(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory(title="Select directory")
        if path:
            var.set(path)

    def clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)

    def append_log(self, line: str) -> None:
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)

    def poll_log_queue(self) -> None:
        try:
            while True:
                self.append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def start_download(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Running", "A download task is already running.")
            return

        exe = Path(self.exe_var.get().strip())
        base_dir = self.base_dir_var.get().strip()
        symbol_lib = self.symbol_lib_var.get().strip()
        footprint_lib = self.footprint_lib_var.get().strip()
        codes = parse_codes(self.code_text.get("1.0", tk.END))

        if not codes:
            messagebox.showerror("Input error", "Please input at least one LCSC code.")
            return
        if not exe.exists():
            messagebox.showerror("Path error", f"Executable not found:\n{exe}")
            return
        if not base_dir:
            messagebox.showerror("Input error", "Base dir cannot be empty.")
            return
        if not symbol_lib:
            messagebox.showerror("Input error", "symbol_lib cannot be empty.")
            return
        if not footprint_lib:
            messagebox.showerror("Input error", "footprint_lib cannot be empty.")
            return

        Path(base_dir).mkdir(parents=True, exist_ok=True)
        self.run_btn.config(state=tk.DISABLED)

        self.worker = threading.Thread(
            target=self.run_download,
            args=(str(exe), base_dir, symbol_lib, footprint_lib, codes),
            daemon=True,
        )
        self.worker.start()

    def run_download(
        self,
        exe: str,
        base_dir: str,
        symbol_lib: str,
        footprint_lib: str,
        codes: list[str],
    ) -> None:
        self.log_queue.put(f"Start: {len(codes)} code(s)")
        self.log_queue.put(f"Exe: {exe}")
        self.log_queue.put(f"Dir: {base_dir}")

        all_ok = True
        for idx, code in enumerate(codes, start=1):
            cmd = [
                exe,
                code,
                "-dir",
                base_dir,
                "-symbol_lib",
                symbol_lib,
                "-footprint_lib",
                footprint_lib,
            ]
            self.log_queue.put("")
            self.log_queue.put(f"[{idx}/{len(codes)}] Running: {' '.join(cmd)}")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            except Exception as exc:
                all_ok = False
                self.log_queue.put(f"ERROR: {exc}")
                continue

            if result.stdout.strip():
                self.log_queue.put(result.stdout.strip())
            if result.stderr.strip():
                self.log_queue.put("stderr:")
                self.log_queue.put(result.stderr.strip())

            if result.returncode == 0:
                self.log_queue.put("Result: OK")
            else:
                all_ok = False
                self.log_queue.put(f"Result: FAILED (exit code {result.returncode})")

        self.log_queue.put("")
        if all_ok:
            self.log_queue.put("All tasks finished successfully.")
        else:
            self.log_queue.put("Finished with errors. Check log above.")

        self.root.after(0, lambda: self.run_btn.config(state=tk.NORMAL))


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
