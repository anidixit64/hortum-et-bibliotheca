"""Keeps a Mac from idle-sleeping during long runs (a sleeping Mac pauses every request)."""

import os
import shutil
import subprocess
import sys


class KeepAwake:
    """Holds a ``caffeinate`` assertion tied to this process; a no-op off macOS.

    ``caffeinate -i -w <pid>`` blocks idle sleep and exits on its own when this process
    does, so a crash can't leave the Mac unable to sleep. The display may still turn off,
    and closing the lid still sleeps the Mac.
    """

    def __init__(self) -> None:
        self._binary = shutil.which("caffeinate") if sys.platform == "darwin" else None
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def available(self) -> bool:
        return self._binary is not None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def hold(self) -> None:
        if self._binary and not self.active:
            self._proc = subprocess.Popen(
                [self._binary, "-i", "-w", str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def release(self) -> None:
        if self.active and self._proc is not None:
            self._proc.terminate()
        self._proc = None

    def __enter__(self) -> "KeepAwake":
        self.hold()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
