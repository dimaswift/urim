"""`urim run <book>`: write, critique and revise a whole book with headless sessions.

The conductor is code, not a model, so a run of hundreds of sessions keeps no context to fill
and resumes where it stopped. It plans from the corpus (plan.py), starts up to `parallel`
sessions, applies each critic report in the critic's name, waits out usage limits and API
outages, and keeps its state in `work/run/<name>.json`, which the War Room's Campaign view
reads. Session transcripts go next to it, in `work/run/<name>/`, with the final report.
Running it again is the go-ahead to retry: layers that failed get fresh attempts.
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from urim.compiler.ingest.build import parse_scope
from urim.conductor.plan import (
    LAYERS,
    MAX_FAILURES,
    LayerState,
    LayerView,
    Plan,
    Step,
    chapter_verses,
    clashes,
    is_verse,
    layer_views,
    outside_pending,
    plan,
)
from urim.conductor.session import HeadlessSession, SessionResult, claude_command
from urim.config import Paths
from urim.workbench.critique import (
    CritiqueError,
    apply_critique,
    back_to_draft,
    check_report,
    is_language,
    load_report,
    report_path,
)

DEFAULT_MODELS = {
    "chronology": "claude-sonnet-5-5",
    "ontology": "claude-sonnet-5-5",
    "philology": "claude-sonnet-5-5",
    "localization": "claude-sonnet-5-5",
    "critic": "claude-opus-5-5",
}
RUN_BY = "urim run"
LOG_LINES = 200
API_WAIT = timedelta(minutes=10)
API_WAIT_MAX = timedelta(hours=2)


class StepRecord(BaseModel):
    id: str
    action: str
    layer: str
    chapter: str
    scope: str
    round: int = 0
    final: bool = False
    model: str
    status: Literal["running", "done", "failed", "limited", "unavailable", "stopped"] = "running"
    started: str
    ended: str | None = None
    activity: str | None = None
    summary: str = ""
    error: str | None = None
    verdict: dict[str, int] | None = None
    transcript: str = ""
    turns: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0


class LayerRow(BaseModel):
    phase: str
    approved: int
    drafts: int
    requested: int
    escalated: int
    unwritten: int
    rounds: int


class ChapterRow(BaseModel):
    chapter: str
    verses: int
    layers: dict[str, LayerRow]


class RunState(BaseModel):
    name: str
    scope: str
    layers: list[str]
    models: dict[str, str]
    parallel: int
    max_rounds: int
    status: Literal["running", "waiting", "finished", "stopped"] = "running"
    started: str
    updated: str
    finished: str | None = None
    waiting_until: str | None = None
    waiting_for: str | None = None
    pid: int | None = None
    layer_state: dict[str, LayerState] = {}
    chapters: list[ChapterRow] = []
    steps: list[StepRecord] = []
    log: list[str] = []

    @property
    def totals(self) -> dict[str, float]:
        return {
            "sessions": len(self.steps),
            "cost_usd": round(sum(s.cost_usd for s in self.steps), 2),
            "tokens": sum(s.tokens_in + s.tokens_out + s.cache_read for s in self.steps),
        }


class Session(Protocol):
    def run(self) -> SessionResult: ...
    def stop(self) -> None: ...


SessionFactory = Callable[[Step, str, Path, Callable[[str], None]], Session]


def iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


def state_path(paths: Paths, name: str) -> Path:
    return Path(paths.work) / "run" / f"{name}.json"


def load_state(paths: Paths, name: str) -> RunState | None:
    path = state_path(paths, name)
    return RunState.model_validate_json(path.read_bytes()) if path.exists() else None


def list_runs(paths: Paths) -> list[RunState]:
    runs = [
        RunState.model_validate_json(p.read_bytes())
        for p in (Path(paths.work) / "run").glob("*.json")
    ]
    return sorted(runs, key=lambda r: r.updated, reverse=True)


def scope_chapters(scope: str) -> list[str]:
    book, chapters = parse_scope(scope)
    return [f"{book.code}.{n}" for n in sorted(chapters or range(1, book.chapters + 1))]


def alive(pid: int | None) -> bool:
    if not pid or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RunError(RuntimeError):
    pass


class Conductor:
    def __init__(
        self,
        paths: Paths,
        scope: str,
        *,
        name: str | None = None,
        parallel: int = 3,
        max_rounds: int = 2,
        models: dict[str, str] | None = None,
        layers: tuple[str, ...] = LAYERS,
        sessions: SessionFactory | None = None,
        claude: str = "claude",
        timeout_min: float = 60,
        root: Path | None = None,
        echo: Callable[[str], None] = print,
        alert: Callable[[str], None] = lambda _: None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.paths, self.echo, self.alert = paths, echo, alert
        self.sleep, self.clock = sleep, clock
        self.name = name or scope
        self.verses = chapter_verses(paths, scope_chapters(scope))
        missing = [c for c, v in self.verses.items() if not v]
        if missing:
            raise RunError(f"not ingested: {', '.join(missing)} (run `urim ingest {scope}`)")
        self.layers = tuple(layer for layer in LAYERS if layer in layers) + tuple(
            layer for layer in layers if is_language(layer)
        )
        for lang in self.layers[len(LAYERS) :]:
            if not (Path(paths.corpus) / "i18n" / lang / "_bundle.json").exists():
                raise RunError(f"no language {lang!r}: corpus/i18n/{lang}/_bundle.json")
        root = root or Path.cwd()
        self.sessions = sessions or (
            lambda step, model, transcript, on_activity: HeadlessSession(
                claude_command(claude, step.command, model),
                cwd=root,
                transcript=transcript,
                on_activity=on_activity,
                timeout_s=timeout_min * 60,
            )
        )
        now = iso(clock())
        prior = load_state(paths, self.name)
        if prior and prior.status in ("running", "waiting") and alive(prior.pid):
            raise RunError(f"run {self.name!r} is already going (pid {prior.pid})")
        self._retrying = []
        if prior:
            # Running again is the go-ahead: failed layers start over, a pause is tried at once.
            self._retrying = [
                key.replace(":", " ")
                for key, st in prior.layer_state.items()
                if st.failures >= MAX_FAILURES
            ]
            for st in prior.layer_state.values():
                st.failures = 0
            prior.waiting_until = prior.waiting_for = None
        self.state = prior or RunState(
            name=self.name,
            scope=scope,
            layers=list(self.layers),
            models={},
            parallel=parallel,
            max_rounds=max_rounds,
            started=now,
            updated=now,
        )
        self.state.models = DEFAULT_MODELS | (models or {})
        self.state.parallel, self.state.max_rounds = parallel, max_rounds
        self.state.layers = list(self.layers)
        self._lock = threading.RLock()
        self._dirty = True
        self._before: dict[str, set[str]] = {}
        self._outages = 0

    # --- state ---------------------------------------------------------------------------------

    def layer_state(self, chapter: str, layer: str) -> LayerState:
        return self.state.layer_state.setdefault(f"{chapter}:{layer}", LayerState())

    def log(self, line: str) -> None:
        stamp = self.clock().astimezone().strftime("%H:%M")
        with self._lock:
            self.state.log = [*self.state.log, f"{stamp} {line}"][-LOG_LINES:]
            self._dirty = True
        self.echo(f"[{stamp}] {line}")

    def save(self) -> None:
        with self._lock:
            self.state.updated = iso(self.clock())
            path = state_path(self.paths, self.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(self.state.model_dump_json(indent=1))
            tmp.replace(path)
            self._dirty = False

    def plan(self, running: tuple[Step, ...] = ()) -> Plan:
        p = plan(
            self.paths,
            self.verses,
            self.state.layer_state,
            layers=self.layers,
            max_rounds=self.state.max_rounds,
            running=running,
        )
        with self._lock:
            self.state.chapters = [
                ChapterRow(
                    chapter=ch,
                    verses=len(verses),
                    layers={
                        layer: self._row(p.views[ch, layer], self.layer_state(ch, layer))
                        for layer in self.layers
                    },
                )
                for ch, verses in self.verses.items()
            ]
            self._dirty = True
        return p

    @staticmethod
    def _row(view: LayerView, st: LayerState) -> LayerRow:
        return LayerRow(
            phase=view.phase(st),
            approved=view.approved,
            drafts=view.drafts,
            requested=len(view.requested),
            escalated=view.escalated,
            unwritten=len(view.unwritten),
            rounds=st.rounds,
        )

    # --- the loop ------------------------------------------------------------------------------

    def run(self) -> RunState:
        self.state.status, self.state.pid, self.state.finished = "running", os.getpid(), None
        self.log(
            f"run {self.name}: {len(self.verses)} chapters, layers {', '.join(self.layers)}, "
            f"{self.state.parallel} at a time"
        )
        if self._retrying:
            self.log(f"retrying what failed: {', '.join(self._retrying)}")
        running: dict[Future, tuple[Step, Session, StepRecord]] = {}
        steps: list[Step] = []
        replan = True
        pool = ThreadPoolExecutor(max_workers=self.state.parallel)
        try:
            while True:
                for future in [f for f in running if f.done()]:
                    self._finish(*running.pop(future), future.result())
                    replan = True
                if self._waiting():
                    if not running:
                        self.save()
                        self.sleep(min(60.0, self._wait_left()))
                        continue
                elif replan:
                    steps = self.plan(tuple(s for s, _, _ in running.values())).steps
                    replan = False
                    for step in steps:
                        if len(running) >= self.state.parallel:
                            break
                        live = [s for s, _, _ in running.values()]
                        if any(step.id == s.id or clashes(step, s) for s in live):
                            continue
                        session, record = self._start(step)
                        running[pool.submit(session.run)] = (step, session, record)
                    if not running:
                        break
                if self._dirty:
                    self.save()
                wait(list(running), timeout=5, return_when=FIRST_COMPLETED)
        except KeyboardInterrupt:
            for _, session, record in running.values():
                session.stop()
                record.status, record.ended = "stopped", iso(self.clock())
            self.state.status = "stopped"
            self.log("stopped; `urim run` again resumes")
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        if self.state.status != "stopped":
            self.state.status, self.state.finished = "finished", iso(self.clock())
            self.plan()
            self.log(self.summary())
        self.state.pid = None
        self.save()
        self.write_report()
        return self.state

    def _waiting(self) -> bool:
        if self.state.waiting_until and self._wait_left() <= 0:
            self.log(f"resuming after the pause ({self.state.waiting_for})")
            self.state.status = "running"
            self.state.waiting_until = self.state.waiting_for = None
        return self.state.waiting_until is not None

    def _pause(self, until: datetime, reason: str) -> None:
        self.state.status, self.state.waiting_until = "waiting", iso(until)
        self.state.waiting_for = reason

    def _wait_left(self) -> float:
        until = datetime.fromisoformat(self.state.waiting_until)
        return (until - self.clock()).total_seconds()

    def _start(self, step: Step) -> tuple[Session, StepRecord]:
        model = self.state.models[step.agent]
        transcript = Path(self.paths.work) / "run" / self.name / f"{step.id}.jsonl"
        record = StepRecord(
            id=step.id,
            action=step.action,
            layer=step.layer,
            chapter=step.chapter,
            scope=step.scope,
            round=step.round,
            final=step.final,
            model=model,
            started=iso(self.clock()),
            transcript=str(transcript),
        )
        # What the session should change, to tell afterwards whether it did.
        if step.outside_chapters:
            self._before[step.id] = outside_pending(self.paths, step)
        else:
            view = self._view(step)
            pending = view.requested if step.action == "revise" else view.unwritten
            self._before[step.id] = {k for k in pending if _in_scope(k, step)}

        def on_activity(what: str) -> None:
            with self._lock:
                record.activity = what
                self._dirty = True

        with self._lock:
            self.state.steps.append(record)
        tail = f" round {step.round}{' (last)' if step.final else ''}" if step.round else ""
        self.log(f"start {step.action} {step.layer} {step.scope}{tail} · {model}")
        return self.sessions(step, model, transcript, on_activity), record

    def _finish(self, step: Step, _: Session, record: StepRecord, result: SessionResult) -> None:
        with self._lock:
            record.ended = iso(self.clock())
            record.summary = result.summary[-3000:]
            for field in ("turns", "duration_s", "cost_usd", "tokens_in", "tokens_out"):
                setattr(record, field, getattr(result, field))
            record.cache_read = result.cache_read
            record.activity = None
        if result.limited_until is not None:
            record.status, record.error = "limited", result.error
            self._pause(result.limited_until, "usage limit")
            local = result.limited_until.astimezone().strftime("%a %H:%M")
            self.log(f"usage limit in {step.id}; waiting until {local}")
            return
        if result.unavailable is not None:
            # Not the work's fault: wait, longer each time in a row, and do not count a failure.
            record.status, record.error = "unavailable", result.error
            if self.state.waiting_until is None:
                until = self.clock() + min(API_WAIT * 2**self._outages, API_WAIT_MAX)
                self._outages += 1
                self._pause(until, result.unavailable)
                local = until.astimezone().strftime("%a %H:%M")
                self.log(f"the API failed in {step.id}: {result.unavailable}; again at {local}")
                if self._outages == 1:
                    self.alert(f"Run {self.name} paused: {result.unavailable}")
            return
        st = self.layer_state(step.chapter, step.layer)
        try:
            outcome = (
                self._critique(step, record, st)
                if step.action == "critique"
                else self._written(step, record, st, result)
            )
        except (CritiqueError, OSError) as e:
            outcome = str(e)
        if outcome is None:
            st.failures = self._outages = 0
            record.status = "done"
            self.log(f"done  {step.action} {step.layer} {step.scope}{self._verdict(record)}")
        else:
            st.failures += 1
            record.status, record.error = "failed", result.error or outcome
            self.log(f"FAIL  {step.action} {step.layer} {step.scope}: {outcome}")

    def _critique(self, step: Step, record: StepRecord, st: LayerState) -> str | None:
        path = report_path(self.paths.work, step.chapter, step.layer)
        started = datetime.fromisoformat(record.started).timestamp()
        if not path.exists() or path.stat().st_mtime < started - 1:
            return f"the critic wrote no report to {path}"
        report = load_report(path)
        if report.chapter_ref != step.chapter or report.layer != step.layer:
            return f"{path} is about {report.layer} {report.chapter_ref}"
        if errors := check_report(report, self.paths.corpus):
            return "; ".join(errors)
        verdict = apply_critique(self.paths.corpus, report, final=step.final)
        record.verdict = {
            "approved": len(verdict.approved),
            "requested": len(verdict.requested),
            "escalated": len(verdict.escalated),
            "unreviewed": len(verdict.unreviewed),
            "noted": verdict.noted,
            "findings": len(report.findings),
        }
        st.rounds += 1
        st.settled = st.settled or step.final
        return None

    def _view(self, step: Step) -> LayerView:
        langs = (step.layer,) if is_language(step.layer) else ()
        views = layer_views(self.paths, {step.chapter: self.verses[step.chapter]}, langs)
        return views[step.chapter, step.layer]

    def _written(
        self, step: Step, record: StepRecord, st: LayerState, result: SessionResult
    ) -> str | None:
        if step.outside_chapters:
            before = self._before.pop(step.id, set())
            if before and before <= outside_pending(self.paths, step):
                return "the session merged nothing"
            return None
        view, before = self._view(step), self._before.pop(step.id, set())
        if step.action == "write":
            if before and before <= set(view.unwritten):
                return "the session merged nothing"
            return None
        still = sorted(before & set(view.requested))
        if still and len(still) == len(before) and not result.ok:
            return "the session ended before revising anything"
        # A session that finished but kept an item as it was disagrees with the request: the
        # critic looks again, with the agent's notes, and the last round still ends with you.
        if still:
            back_to_draft(
                self.paths.corpus,
                step.chapter,
                still,
                by=RUN_BY,
                note="The agent kept it unchanged after the request; back to the critic.",
            )
            record.verdict = {"kept": len(still)}
        st.settled = False
        if step.fresh:
            st.rounds = 0
        return None

    @staticmethod
    def _verdict(record: StepRecord) -> str:
        v = record.verdict or {}
        keys = ("approved", "requested", "escalated", "kept")
        parts = [f"{v[k]} {k}" for k in keys if v.get(k)]
        cost = f" · {record.turns} turns · ${record.cost_usd:.2f}" if record.turns else ""
        return (f": {', '.join(parts)}" if parts else "") + cost

    # --- reporting -----------------------------------------------------------------------------

    def summary(self) -> str:
        phases = [row.phase for ch in self.state.chapters for row in ch.layers.values()]
        escalated = sum(r.escalated for ch in self.state.chapters for r in ch.layers.values())
        t = self.state.totals
        return (
            f"finished: {phases.count('done')}/{len(phases)} chapter layers done, "
            f"{escalated} item(s) escalated to you, {phases.count('failed')} failed; "
            f"{t['sessions']} sessions, ${t['cost_usd']:.2f}"
        )

    def write_report(self) -> Path:
        s, t = self.state, self.state.totals
        lines = [
            f"# Run {s.name} · {s.status}",
            "",
            f"Scope {s.scope}; started {s.started}, updated {s.updated}. {t['sessions']} "
            f"sessions, {t['tokens']:,} tokens, ${t['cost_usd']:.2f} (as the CLI reports it).",
            "",
            "| chapter | " + " | ".join(s.layers) + " |",
            "|---|" + "---|" * len(s.layers),
        ]
        for ch in s.chapters:
            cells = [
                f"{r.phase}: {r.approved}✓ {r.drafts} draft {r.requested} asked "
                f"{r.escalated} escalated"
                for r in ch.layers.values()
            ]
            lines.append(f"| {ch.chapter} | " + " | ".join(cells) + " |")
        failed = [st for st in s.steps if st.status == "failed"]
        if failed:
            lines += ["", "## Failed sessions", ""]
            lines += [f"- `{st.id}` ({st.model}): {(st.error or '')[:300]}" for st in failed]
        lines += ["", "## Log", "", "```", *s.log[-60:], "```", ""]
        path = Path(self.paths.work) / "run" / s.name / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines))
        return path


def _in_scope(key_or_verse: str, step: Step) -> bool:
    """Whether a ledger key or verse id falls inside a step's scope."""
    ref = key_or_verse.split(":", 1)[-1]
    if is_language(step.layer) and step.scope == step.chapter:
        return not is_verse(ref)  # a language's texts step: everything but its verses
    if not (step.layer == "philology" or is_language(step.layer)) or step.scope == step.chapter:
        return True
    lo, hi = (int(n) for n in step.scope.rsplit(".", 1)[1].split("-"))
    head, _, verse = ref.rpartition(".")
    return head == step.chapter and verse.isdigit() and lo <= int(verse) <= hi


def notify(title: str, message: str) -> None:
    """A desktop notification where the platform has one; silently nothing elsewhere."""
    if platform.system() != "Darwin":
        return
    script = f"display notification {message!r} with title {title!r}".replace("'", '"')
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
