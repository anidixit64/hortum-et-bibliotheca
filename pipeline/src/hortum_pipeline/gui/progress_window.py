import contextlib
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from hortum_pipeline.progress import Reporter

Job = Callable[[Reporter], int]


class GuiReporter:
    """Thread-safe reporter: the worker thread queues events, the Tk thread draws them."""

    def __init__(self) -> None:
        self.events: queue.Queue[tuple[str, object, object]] = queue.Queue()

    def begin(self, label: str, total: int | None) -> None:
        self.events.put(("begin", label, total))

    def advance(self, n: int = 1) -> None:
        self.events.put(("advance", n, None))

    def stat(self, key: str, value: object) -> None:
        self.events.put(("stat", key, value))

    def log(self, message: str) -> None:
        self.events.put(("log", message, None))


class ProgressWindow:
    def __init__(self, root: tk.Tk, title: str, on_review: Callable[[], None] | None) -> None:
        self.root = root
        self.on_review = on_review
        root.title(title)
        root.minsize(520, 360)

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)

        self.stage_var = tk.StringVar(value="Starting…")
        ttk.Label(frame, textvariable=self.stage_var, font=("TkDefaultFont", 14, "bold")).pack(
            anchor="w"
        )
        self.bar = ttk.Progressbar(frame, mode="determinate", maximum=1)
        self.bar.pack(fill="x", pady=(10, 4))
        self.count_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.count_var).pack(anchor="w")

        self.stats = ttk.Frame(frame)
        self.stats.pack(fill="x", pady=(12, 6))
        self._stat_vars: dict[str, tk.StringVar] = {}

        self.log = tk.Listbox(frame, height=8, activestyle="none")
        self.log.pack(fill="both", expand=True)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        self.review_button = ttk.Button(
            buttons, text="Review low-confidence answers", command=self._review, state="disabled"
        )
        if on_review is not None:
            self.review_button.pack(side="left")
        self.close_button = ttk.Button(buttons, text="Close", command=root.destroy)
        self.close_button.pack(side="right")

        self.total: int | None = None
        self.done = 0
        self.started = time.monotonic()
        self.exit_code = 1

    def run(self, job: Job) -> int:
        reporter = GuiReporter()

        def work() -> None:
            try:
                code = job(reporter)
            except Exception as exc:  # shown in the window instead of a silent thread death
                reporter.events.put(("error", repr(exc), None))
            else:
                reporter.events.put(("finished", code, None))

        threading.Thread(target=work, daemon=True).start()
        self._poll(reporter)
        self.root.mainloop()
        return self.exit_code

    def _poll(self, reporter: GuiReporter) -> None:
        try:
            while True:
                kind, a, b = reporter.events.get_nowait()
                self._handle(kind, a, b)
        except queue.Empty:
            pass
        with contextlib.suppress(tk.TclError):  # the window was closed
            self.root.after(100, self._poll, reporter)

    def _handle(self, kind: str, a: object, b: object) -> None:
        if kind == "begin":
            self.stage_var.set(str(a))
            self.total = b if isinstance(b, int) else None
            self.done = 0
            self.started = time.monotonic()
            self.bar.configure(mode="determinate" if self.total else "indeterminate")
            self.bar.configure(maximum=self.total or 100, value=0)
            if not self.total:
                self.bar.start(15)
            self._update_count()
        elif kind == "advance":
            self.done += int(a)  # type: ignore[call-overload]
            if self.total:
                self.bar.configure(value=self.done)
            self._update_count()
        elif kind == "stat":
            self._set_stat(str(a), str(b))
        elif kind == "log":
            self.log.insert("end", str(a))
            self.log.see("end")
        elif kind == "finished":
            self.exit_code = int(a)  # type: ignore[call-overload]
            self.bar.stop()
            self.stage_var.set("Finished" if self.exit_code == 0 else "Stopped")
            if self.exit_code == 0:
                self.review_button.configure(state="normal")
        elif kind == "error":
            self.bar.stop()
            self.stage_var.set("Failed")
            self.log.insert("end", f"ERROR: {a}")
            self.log.itemconfigure("end", foreground="red")
            self.log.see("end")

    def _update_count(self) -> None:
        if not self.total:
            self.count_var.set(f"{self.done:,} processed")
            return
        pct = self.done / self.total
        elapsed = time.monotonic() - self.started
        eta = ""
        if 0.02 < pct < 1:
            remaining = elapsed / pct - elapsed
            eta = f" · about {int(remaining // 60)}m {int(remaining % 60)}s left"
        self.count_var.set(f"{self.done:,} / {self.total:,} ({pct:.0%}){eta}")

    def _set_stat(self, key: str, value: str) -> None:
        var = self._stat_vars.get(key)
        if var is None:
            var = tk.StringVar()
            row = len(self._stat_vars)
            ttk.Label(self.stats, text=f"{key}:").grid(row=row, column=0, sticky="w")
            ttk.Label(self.stats, textvariable=var, font=("TkDefaultFont", 12, "bold")).grid(
                row=row, column=1, sticky="w", padx=(8, 0)
            )
            self._stat_vars[key] = var
        var.set(value)

    def _review(self) -> None:
        if self.on_review is not None:
            self.on_review()
