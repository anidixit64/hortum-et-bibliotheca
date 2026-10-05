import sys
import time
from typing import Protocol


class Reporter(Protocol):
    """Receives progress from a stage. The terminal and the GUI window both implement it."""

    def begin(self, label: str, total: int | None) -> None: ...
    def advance(self, n: int = 1) -> None: ...
    def stat(self, key: str, value: object) -> None: ...
    def log(self, message: str) -> None: ...


class NullReporter:
    def begin(self, label: str, total: int | None) -> None:
        pass

    def advance(self, n: int = 1) -> None:
        pass

    def stat(self, key: str, value: object) -> None:
        pass

    def log(self, message: str) -> None:
        pass


class ConsoleReporter:
    """Prints a progress line at most every couple of seconds."""

    def __init__(self, interval_seconds: float = 2.0) -> None:
        self.interval = interval_seconds
        self.label = ""
        self.total: int | None = None
        self.done = 0
        self.started = 0.0
        self.last_print = 0.0
        self._held: dict[str, object] = {}

    def begin(self, label: str, total: int | None) -> None:
        self.label, self.total, self.done = label, total, 0
        self.started = self.last_print = time.monotonic()
        print(f"  {label}...", file=sys.stderr)

    def advance(self, n: int = 1) -> None:
        self.done += n
        now = time.monotonic()
        if now - self.last_print >= self.interval or (self.total and self.done >= self.total):
            self.last_print = now
            if self.total:
                pct = 100 * self.done / self.total
                line = f"{self.done:,}/{self.total:,} ({pct:.0f}%)"
            else:
                line = f"{self.done:,}"
            held = "".join(f" · {k}: {v}" for k, v in self._held.items())
            print(f"  {self.label}: {line}{held}", file=sys.stderr)
            self._held.clear()

    def stat(self, key: str, value: object) -> None:
        """Mid-stage stats ride along with the next progress line; final ones print now."""
        if self.total is not None and self.done < self.total:
            self._held[key] = value
        else:
            print(f"  {key}: {value}", file=sys.stderr)

    def log(self, message: str) -> None:
        print(f"  {message}", file=sys.stderr)
