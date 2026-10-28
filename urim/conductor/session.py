"""One headless Claude Code session: `claude -p "/<skill> <scope>"`, watched as it streams.

Sessions run on your Claude subscription, exactly as if you had typed the skill command, with
the same project skills and CLAUDE.md. The run adds a short system note (nobody will answer,
never decide reviews), the tools the skills need, and a wall around the gold.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

UNATTENDED = (
    "You are running unattended inside `urim run`, an autonomous run over a whole book. Nobody "
    "will read questions or answer them during this session: do the whole task the skill "
    "describes, then end with the short report it asks for. Never run `urim approve`, "
    "`urim request-changes` or `urim reopen`: the run applies the critic's report itself. "
    "Never edit the corpus by hand; when a merge fails, fix the fragment and merge again until "
    "it succeeds. Of the shell, only `uv run urim …` runs here, one command at a time: python, "
    "jq, sed, heredocs, pipes and redirections ask for an approval nobody can give, and are "
    "refused. Read files with Read and Grep; write a fragment with Write, in one go even when "
    "it is long, and correct it with Edit."
)
TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "Bash(uv run urim:*)")
GOLD = ("Read(./fixtures/**)", "Read(./runs/demo/**)", "Read(./urim/workbench/gold.py)")
_LIMIT = re.compile(
    r"usage limit|limit reached|hit your (?:usage )?limit|out of (?:extra )?usage|"
    r"rate.?limit|resets? at",
    re.I,
)
_LIMIT_WAIT = timedelta(minutes=30)
_API_ERROR = re.compile(r"API Error\b", re.I)
_OWN_REQUEST = re.compile(r"\b(?:400|413)\b|invalid_request|prompt is too long", re.I)


@dataclass
class SessionResult:
    ok: bool
    summary: str = ""
    error: str | None = None
    limited_until: datetime | None = None
    unavailable: str | None = None
    session_id: str | None = None
    turns: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0


def claude_command(executable: str, prompt: str, model: str) -> list[str]:
    return [
        executable,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--append-system-prompt",
        UNATTENDED,
        "--allowedTools",
        *TOOLS,
        "--disallowedTools",
        *GOLD,
    ]


def limit_reset(text: str, now: datetime) -> datetime | None:
    """When a usage limit lifts, if `text` says one was hit; a guess when it gives no time."""
    if not _LIMIT.search(text):
        return None
    if m := re.search(r"\|(\d{10})\b", text):
        return datetime.fromtimestamp(int(m[1]), UTC)
    if m := re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text, re.I):
        hour = int(m[1]) % 12 + (12 if m[3].lower() == "pm" else 0)
        local = now.astimezone()
        at = local.replace(hour=hour, minute=int(m[2] or 0), second=0, microsecond=0)
        if at <= local:
            at += timedelta(days=1)
        return at.astimezone(UTC)
    return now + _LIMIT_WAIT


def api_failure(text: str) -> str | None:
    """The API's own error line, if `text` reports one that is not about the session's request:
    an account refusal, an outage, an overload. Retrying later helps; the work was not at fault.
    """
    m = _API_ERROR.search(text)
    if m is None or _OWN_REQUEST.search(text):
        return None
    return text[m.start() :].splitlines()[0][:300]


def activity_of(event: dict) -> str | None:
    """A one-line description of what a streamed assistant message is doing."""
    if event.get("type") != "assistant":
        return None
    for block in reversed(event.get("message", {}).get("content", [])):
        if block.get("type") == "tool_use":
            args = block.get("input", {})
            detail = args.get("command") or args.get("file_path") or args.get("pattern") or ""
            return f"{block.get('name')}: {str(detail)[:160]}".rstrip(": ")
        if block.get("type") == "text" and block.get("text", "").strip():
            return block["text"].strip().splitlines()[0][:160]
    return None


class HeadlessSession:
    """Runs one `claude -p` process, keeps its stream as a transcript, reports activity."""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path,
        transcript: Path,
        on_activity: Callable[[str], None] = lambda _: None,
        timeout_s: float = 3600,
    ):
        self.command, self.cwd, self.transcript = command, cwd, transcript
        self.on_activity, self.timeout_s = on_activity, timeout_s
        self._proc: subprocess.Popen | None = None
        self._stopped = self._timed_out = False

    def stop(self) -> None:
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            os.killpg(self._proc.pid, signal.SIGTERM)

    def run(self) -> SessionResult:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE")}
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            self._proc = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as e:
            return SessionResult(ok=False, error=f"could not start {self.command[0]}: {e}")
        stderr: list[str] = []
        reader = threading.Thread(target=lambda: stderr.extend(self._proc.stderr), daemon=True)
        reader.start()
        timer = threading.Timer(self.timeout_s, self._timeout)
        timer.start()
        final: dict | None = None
        try:
            with self.transcript.open("w") as out:
                for line in self._proc.stdout:
                    out.write(line)
                    out.flush()
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "result":
                        final = event
                    elif (what := activity_of(event)) is not None:
                        self.on_activity(what)
            code = self._proc.wait()
        finally:
            timer.cancel()
        reader.join(timeout=5)
        return self._result(final, code, "".join(stderr), time.monotonic() - started)

    def _timeout(self) -> None:
        self._timed_out = True
        self.stop()

    def _result(self, final: dict | None, code: int, stderr: str, elapsed: float) -> SessionResult:
        text = (final or {}).get("result") or ""
        usage = (final or {}).get("usage") or {}
        result = SessionResult(
            ok=final is not None and not final.get("is_error") and code == 0,
            summary=text.strip(),
            session_id=(final or {}).get("session_id"),
            turns=(final or {}).get("num_turns") or 0,
            duration_s=round(elapsed, 1),
            cost_usd=(final or {}).get("total_cost_usd") or 0.0,
            tokens_in=(usage.get("input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0),
            tokens_out=usage.get("output_tokens") or 0,
            cache_read=usage.get("cache_read_input_tokens") or 0,
        )
        if not result.ok:
            if self._timed_out:
                result.error = f"timed out after {self.timeout_s / 60:.0f} min"
            elif self._stopped:
                result.error = "stopped"
            else:
                result.error = (text or stderr or f"exit code {code}").strip()[-2000:]
                said = f"{text}\n{stderr}"
                result.limited_until = limit_reset(said, datetime.now(UTC))
                if result.limited_until is None:
                    result.unavailable = api_failure(said)
        return result
