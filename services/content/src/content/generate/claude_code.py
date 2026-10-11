"""The Claude Code backend: ``claude -p`` with tools off and JSON Schema output, on your
own Claude plan. Personal use only; it needs your local login, so a worker using it runs
on your Mac rather than in Docker."""

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from content.generate import GenerationError, QuotaExceeded, Reply, Request

_LIMIT = re.compile(r"usage limit|rate limit|limit reached|resets? at|overloaded", re.I)


def find_binary(configured: str) -> str:
    """``claude`` on the PATH, or the newest copy bundled with the VS Code extension."""
    if configured:
        return configured
    bundled = sorted(
        Path.home().glob(
            ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"
        ),
        key=lambda p: [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+|\D+", str(p))],
    )
    return str(bundled[-1]) if bundled else "claude"


class ClaudeCode:
    name = "claude_code"

    def __init__(self, model: str, binary: str = "", timeout: float = 300.0) -> None:
        self.model = model
        self.binary = find_binary(binary)
        self.timeout = timeout

    def command(self, request: Request) -> list[str]:
        return [
            self.binary, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(request.schema),
            "--model", self.model,
            "--system-prompt", request.system,
            "--tools", "",
            "--no-session-persistence",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]  # fmt: skip

    def generate(self, request: Request) -> Reply:
        try:
            done = subprocess.run(
                self.command(request),
                input=request.prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=Path.home(),
            )
        except FileNotFoundError as error:
            raise GenerationError(f"claude not found at {self.binary}") from error
        except subprocess.TimeoutExpired as error:
            raise GenerationError("claude timed out") from error
        out = done.stdout.strip()
        try:
            result = json.loads(out)
        except json.JSONDecodeError as error:
            if _LIMIT.search(out + done.stderr):
                raise QuotaExceeded(out[:200], datetime.now(UTC) + timedelta(hours=1)) from error
            raise GenerationError(f"not JSON: {out[:200]!r} {done.stderr[:200]!r}") from error
        if result.get("is_error") or result.get("subtype") != "success":
            message = str(result.get("result") or result.get("subtype"))
            if _LIMIT.search(message):
                raise QuotaExceeded(message[:200], datetime.now(UTC) + timedelta(hours=1))
            raise GenerationError(message[:300])
        data = result.get("structured_output")
        if not isinstance(data, dict):
            raise GenerationError("no structured output")
        usage = result.get("usage", {})
        return Reply(
            data=data,
            backend=self.name,
            model=next(iter(result.get("modelUsage", {})), self.model),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
