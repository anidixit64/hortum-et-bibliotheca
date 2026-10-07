import contextlib
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from hortum_pipeline.power import KeepAwake
from hortum_pipeline.progress import Reporter

Job = Callable[[Reporter], int]

_POLL_MS = 250  # redraw at most four times a second, however many events arrive
_BAR_HEIGHT = 14


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


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}h {rest // 60:02d}m" if hours else f"{rest // 60}m {rest % 60:02d}s"


class ProgressBar(tk.Canvas):
    """A plain drawn bar. The native macOS bar animates constantly, which costs real CPU."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, height=_BAR_HEIGHT, highlightthickness=0, background="#e5e5e5")
        self._fill = self.create_rectangle(0, 0, 0, _BAR_HEIGHT, fill="#3b82f6", width=0)
        self._fraction: float | None = 0.0
        self._sweep = 0
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, fraction: float | None) -> None:
        """A fraction from 0 to 1, or None for "busy, total unknown"."""
        if fraction is None:
            self._sweep = (self._sweep + 1) % 20
        elif fraction == self._fraction:
            return
        self._fraction = fraction
        self._draw()

    def _draw(self) -> None:
        width = self.winfo_width()
        if self._fraction is None:  # a slow sliding block, moved once per redraw
            block = width // 5
            left = (width - block) * self._sweep // 19
            self.coords(self._fill, left, 0, left + block, _BAR_HEIGHT)
        else:
            self.coords(self._fill, 0, 0, width * self._fraction, _BAR_HEIGHT)


class ProgressWindow:
    def __init__(self, root: tk.Tk, title: str, on_review: Callable[[], None] | None) -> None:
        self.root = root
        self.on_review = on_review
        root.title(title)
        root.minsize(560, 420)

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)

        self.stage_var = tk.StringVar(value="Starting…")
        ttk.Label(frame, textvariable=self.stage_var, font=("TkDefaultFont", 14, "bold")).pack(
            anchor="w"
        )
        self.bar = ProgressBar(frame)
        self.bar.pack(fill="x", pady=(10, 4))
        self.count_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.count_var).pack(anchor="w")
        self.elapsed_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.elapsed_var, foreground="#6b7280").pack(anchor="w")

        self.stats = ttk.Frame(frame)
        self.stats.pack(fill="x", pady=(12, 6))
        self._stat_vars: dict[str, tk.StringVar] = {}

        self.log = tk.Listbox(frame, height=9, activestyle="none")
        self.log.pack(fill="both", expand=True)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        self.review_button = ttk.Button(
            buttons, text="Review low-confidence answers", command=self._review, state="disabled"
        )
        if on_review is not None:
            self.review_button.pack(side="left")
        self.close_button = ttk.Button(buttons, text="Close", command=self._close)
        self.close_button.pack(side="right")

        self.awake = KeepAwake()
        self.awake_var = tk.BooleanVar(value=self.awake.available)
        if self.awake.available:
            ttk.Checkbutton(
                buttons,
                text="Keep this Mac awake until finished",
                variable=self.awake_var,
                command=self._toggle_awake,
            ).pack(side="right", padx=(0, 12))
        root.protocol("WM_DELETE_WINDOW", self._close)

        self.total: int | None = None
        self.done = 0
        self.stage_started = self.run_started = time.monotonic()
        self.stage_name = ""
        self.running = False
        self.exit_code = 1
        self._pending_stats: dict[str, str] = {}
        self._pending_logs: list[tuple[str, str | None]] = []

    def run(self, job: Job) -> int:
        reporter = GuiReporter()

        def work() -> None:
            try:
                code = job(reporter)
            except Exception as exc:  # shown in the window instead of a silent thread death
                reporter.events.put(("error", repr(exc), None))
            else:
                reporter.events.put(("finished", code, None))

        self.running = True
        self._toggle_awake()
        threading.Thread(target=work, daemon=True).start()
        self._poll(reporter)
        self.root.mainloop()
        self.awake.release()
        return self.exit_code

    # -- event handling: update state for every event, draw once per poll -------------------

    def _poll(self, reporter: GuiReporter) -> None:
        with contextlib.suppress(queue.Empty):
            while True:
                kind, a, b = reporter.events.get_nowait()
                self._handle(kind, a, b)
        self._render()
        with contextlib.suppress(tk.TclError):  # the window was closed
            self.root.after(_POLL_MS, self._poll, reporter)

    def _handle(self, kind: str, a: object, b: object) -> None:
        now = time.monotonic()
        if kind == "begin":
            if self.stage_name:
                self._pending_logs.append(
                    (f"   {self.stage_name} took {_clock(now - self.stage_started)}", None)
                )
            self.stage_name = str(a)
            self.total = b if isinstance(b, int) else None
            self.done = 0
            self.stage_started = now
        elif kind == "advance":
            self.done += int(a)  # type: ignore[call-overload]
        elif kind == "stat":
            self._pending_stats[str(a)] = str(b)
        elif kind == "log":
            self._pending_logs.append((str(a), None))
        elif kind in ("finished", "error"):
            self.running = False
            self.awake.release()
            if self.stage_name:
                self._pending_logs.append(
                    (f"   {self.stage_name} took {_clock(now - self.stage_started)}", None)
                )
            if kind == "finished":
                self.exit_code = int(a)  # type: ignore[call-overload]
                self.stage_name = "Finished" if self.exit_code == 0 else "Stopped"
                self.total, self.done = 1, 1
                if self.exit_code == 0:
                    self.review_button.configure(state="normal")
            else:
                self.stage_name = "Failed"
                self._pending_logs.append((f"ERROR: {a}", "red"))

    def _render(self) -> None:
        self.stage_var.set(self.stage_name or "Starting…")
        if self.total:
            fraction = min(1.0, self.done / self.total)
            self.bar.set(fraction)
            eta = ""
            elapsed = time.monotonic() - self.stage_started
            if self.running and 0.02 < fraction < 1:
                eta = f" · about {_clock(elapsed / fraction - elapsed)} left"
            self.count_var.set(f"{self.done:,} / {self.total:,} ({fraction:.0%}){eta}")
        else:
            self.bar.set(None if self.running else 0.0)
            self.count_var.set(f"{self.done:,} processed" if self.done else "Working…")
        if self.running:
            self.elapsed_var.set(f"Running for {_clock(time.monotonic() - self.run_started)}")
        for key, value in self._pending_stats.items():
            self._set_stat(key, value)
        self._pending_stats.clear()
        for message, color in self._pending_logs:
            self.log.insert("end", message)
            if color:
                self.log.itemconfigure("end", foreground=color)
        if self._pending_logs:
            self.log.see("end")
            self._pending_logs.clear()

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

    # -- buttons --------------------------------------------------------------------------

    def _toggle_awake(self) -> None:
        if self.running and self.awake_var.get():
            self.awake.hold()
        else:
            self.awake.release()

    def _review(self) -> None:
        if self.on_review is not None:
            self.on_review()

    def _close(self) -> None:
        self.awake.release()
        self.root.destroy()
