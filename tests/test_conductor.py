"""Autonomous runs: planning from the corpus, the critic's verdicts, revisions, escalation,
usage limits, API failures, retries and the headless session wrapper, with fake sessions that
merge the gold."""

import json
import shutil
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from urim.conductor.plan import Step, windows
from urim.conductor.run import Conductor, RunError, load_state
from urim.conductor.session import (
    HeadlessSession,
    SessionResult,
    activity_of,
    api_failure,
    claude_command,
    limit_reset,
)
from urim.config import load_paths
from urim.i18n.messages import english, plural_categories
from urim.ir.models import VerseText
from urim.workbench import gold
from urim.workbench.critique import (
    CriticReport,
    Finding,
    apply_critique,
    is_language,
    layer_items,
)
from urim.workbench.fragments import (
    BundleTexts,
    InterfaceMessage,
    LocalizationFragment,
    Provenance,
)
from urim.workbench.ledger import corpus_lock, load_ledger, set_status
from urim.workbench.localize import TEXT_SECTIONS, message_states
from urim.workbench.merge import merge_fragment

from .conftest import FIXTURE_IR

REPO = Path(__file__).resolve().parent.parent
CRITIC = Provenance(model="claude-opus-5-5", skill="urim-critic@2")
LOCALIZER = Provenance(model="claude-sonnet-5-5", skill="urim-localizer@1")
REFUSAL = "API Error: Your account can't receive replies from Claude right now."


@pytest.fixture
def paths(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(REPO / "corpus", corpus, ignore=shutil.ignore_patterns("core", "ledger"))
    shutil.copy(FIXTURE_IR / "chronology.json", corpus / "chronology.json")
    for p in (corpus / "i18n").glob("*/*.json"):
        if p.name != "_bundle.json":
            p.unlink()
    return replace(
        load_paths(),
        corpus=corpus,
        inputs=FIXTURE_IR,
        work=tmp_path / "work",
        bundles=tmp_path / "bundles",
    )


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 28, 12, tzinfo=UTC)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeSession:
    """Does what a session would: merge the gold for writes, write a report for critiques."""

    def __init__(self, world, step, model, transcript, on_activity):
        self.world, self.step, self.model = world, step, model
        self.on_activity = on_activity

    def stop(self):
        pass

    def run(self) -> SessionResult:
        w, step = self.world, self.step
        w.calls.append(step)
        self.on_activity(f"Bash: uv run urim task {step.layer} {step.scope}")
        if w.limit_once and step.action == "write":
            w.limit_once = False
            return SessionResult(
                ok=False, error="limit", limited_until=w.clock() + timedelta(minutes=20)
            )
        if w.refuse and step.action == "write":
            w.refuse -= 1
            return SessionResult(ok=False, error=REFUSAL, unavailable=REFUSAL)
        if w.idle and step.action == "write":
            w.idle -= 1
            return SessionResult(ok=True, summary="I wrote a script nobody could run")
        if step.action == "critique":
            return self.critique()
        if is_language(step.layer):
            return self.localize()
        if w.lazy and step.action == "revise":
            return SessionResult(ok=True, summary="kept as it was")
        frag = getattr(gold, step.layer)(step.chapter)
        if step.layer == "philology":
            frag = self.philology(frag)
        if step.action == "revise" and step.layer == "chronology":
            led = load_ledger(w.paths.corpus, step.chapter)
            asked = {k for k, i in led.items.items() if i.status == "changes_requested"}
            texts = [
                t.model_copy(update={"title": t.title + " (revised)"})
                if f"event:{t.event_id}" in asked
                else t
                for t in frag.event_texts
            ]
            frag = frag.model_copy(update={"event_texts": texts})
        with corpus_lock(w.paths.corpus):  # as `urim ir merge` does
            result = merge_fragment(frag, w.paths.corpus, w.paths.inputs)
        assert result.ok, result.errors
        return SessionResult(ok=True, summary="merged", turns=4, cost_usd=0.25, tokens_in=1000)

    def philology(self, frag):
        lo, hi = (int(n) for n in self.step.scope.rsplit(".", 1)[1].split("-"))
        ids = [f"{self.step.chapter}.{n}" for n in range(lo, hi + 1)]
        verses = [
            VerseText(
                verse_id=vid,
                translation_literal="literal",
                translation_dramatic="dramatic",
                directors_commentary="commentary",
            )
            for vid in ids
            if vid in self.world.verse_ids
        ]
        return frag.model_copy(update={"verses": verses})

    def localize(self) -> SessionResult:
        """Translate by copying the English, which the merge accepts like any translation."""
        step, corpus = self.step, self.world.paths.corpus
        base = {"agent": "localization", "lang": step.layer, "scope": step.scope}
        if step.scope.startswith("ui."):
            cats = plural_categories(step.layer)
            msgs = [
                InterfaceMessage(key=k, text=s.text)
                if s.text is not None
                else InterfaceMessage(
                    key=k, forms={c: s.forms.get(c, s.forms["other"]) for c in cats}
                )
                for k, s in english().items()
                if f"ui.{s.namespace}" == step.scope
            ]
            frag = LocalizationFragment(**base, produced_by=LOCALIZER, messages=msgs)
        elif step.scope == "bundle":
            en = json.loads((corpus / "i18n" / "en" / "_bundle.json").read_text())
            frag = LocalizationFragment(
                **base,
                produced_by=LOCALIZER,
                bundle=BundleTexts.model_validate(
                    {k: en[k] for k in ("books", "vocab", "anchors")}
                ),
            )
        else:
            from urim.workbench.merge import CorpusFiles

            en = CorpusFiles(corpus).i18n("en", step.chapter)
            if step.scope == step.chapter:
                frag = LocalizationFragment(
                    **base,
                    produced_by=LOCALIZER,
                    **{section: getattr(en, section) for _, section, _ in TEXT_SECTIONS},
                )
            else:
                lo, hi = (int(n) for n in step.scope.rsplit(".", 1)[1].split("-"))
                verses = [v for v in en.verses if lo <= int(v.verse_id.rsplit(".", 1)[1]) <= hi]
                frag = LocalizationFragment(**base, produced_by=LOCALIZER, verses=verses)
        with corpus_lock(corpus):
            result = merge_fragment(frag, corpus, self.world.paths.inputs)
        assert result.ok, result.errors
        return SessionResult(ok=True, summary="translated", turns=3, cost_usd=0.1)

    def critique(self) -> SessionResult:
        w, step = self.world, self.step
        led = load_ledger(w.paths.corpus, step.chapter)
        drafts = layer_items(led, step.layer, "draft")
        events = sorted(k for k in drafts if k.startswith("event:"))
        findings = []
        if events and (w.stubborn or step.round == 1):
            findings.append(
                Finding(
                    item=events[0],
                    severity="should_fix",
                    problem="the title adds a motive",
                    evidence='1KGS.17.1: "As the LORD God of Israel liveth"',
                    change_request="Say only what the verse says.",
                )
            )
        report = CriticReport(
            chapter_ref=step.chapter,
            layer=step.layer,
            produced_by=CRITIC,
            reviewed=drafts,
            findings=findings,
        )
        path = w.paths.work / "critic" / f"{step.chapter}.{step.layer}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json())
        return SessionResult(ok=True, summary=f"{len(findings)} findings", turns=6, cost_usd=1.0)


class World:
    def __init__(self, paths, *, stubborn=False, lazy=False, limit_once=False, refuse=0, idle=0):
        self.paths, self.stubborn, self.lazy, self.limit_once = paths, stubborn, lazy, limit_once
        self.refuse, self.idle = refuse, idle
        self.calls: list[Step] = []
        self.clock = Clock()
        self.verse_ids = {
            v["verse_id"]
            for v in json.loads((FIXTURE_IR / "source" / "1KGS.json").read_text())["verses"]
        }

    def conductor(self, scope="1KGS.17-19", **kw) -> Conductor:
        kw.setdefault("layers", ("chronology", "ontology"))
        return Conductor(
            self.paths,
            scope,
            sessions=lambda *a: FakeSession(self, *a),
            echo=lambda _: None,
            sleep=self.clock.sleep,
            clock=self.clock,
            **kw,
        )


def test_a_run_writes_critiques_revises_and_approves_a_book(paths):
    world = World(paths)
    state = world.conductor(parallel=2).run()
    assert state.status == "finished"
    phases = {(c.chapter, layer): r.phase for c in state.chapters for layer, r in c.layers.items()}
    assert set(phases.values()) == {"done"}, phases

    # Chronology goes chapter by chapter, and each chapter waits for the last to settle.
    chrono = [s for s in world.calls if s.layer == "chronology"]
    assert [s.action for s in chrono if s.chapter == "1KGS.17"] == [
        "write",
        "critique",
        "revise",
        "critique",
    ]
    first_18 = next(i for i, s in enumerate(world.calls) if s.chapter == "1KGS.18")
    settled_17 = max(
        i for i, s in enumerate(world.calls) if s.chapter == "1KGS.17" and s.layer == "chronology"
    )
    assert first_18 > settled_17

    led = load_ledger(paths.corpus, "1KGS.17")
    assert {i.status for i in led.items.values()} == {"approved"}
    revised = next(i for k, i in led.items.items() if k.startswith("event:") and len(i.history) > 1)
    assert [h.status for h in revised.history] == ["changes_requested", "approved"]
    assert all(h.by == "urim-critic@2 · claude-opus-5-5" for h in revised.history)

    saved = load_state(paths, "1KGS.17-19")
    assert saved.status == "finished" and saved.pid is None
    assert len(saved.steps) == len(world.calls) and all(s.status == "done" for s in saved.steps)
    assert (paths.work / "run" / "1KGS.17-19" / "report.md").exists()


def test_what_the_critic_cannot_settle_is_escalated_to_you(paths):
    world = World(paths, stubborn=True)
    state = world.conductor("1KGS.17", layers=("chronology",), max_rounds=1).run()
    row = state.chapters[0].layers["chronology"]
    assert row.phase == "done" and row.escalated == 1 and row.requested == 0
    critiques = [s for s in world.calls if s.action == "critique"]
    assert [(s.round, s.final) for s in critiques] == [(1, False), (2, True)]
    led = load_ledger(paths.corpus, "1KGS.17")
    escalated = [i for i in led.items.values() if i.status == "draft"]
    assert len(escalated) == 1 and escalated[0].history[-1].note.startswith("Escalated")


def test_an_agent_that_keeps_an_item_sends_it_back_to_the_critic(paths):
    world = World(paths, lazy=True, stubborn=True)
    state = world.conductor("1KGS.17", layers=("chronology",)).run()
    row = state.chapters[0].layers["chronology"]
    assert row.phase == "done" and row.escalated == 1
    actions = [(s.action, s.round) for s in world.calls]
    assert actions == [
        ("write", 0),
        ("critique", 1),
        ("revise", 0),
        ("critique", 2),
        ("revise", 0),
        ("critique", 3),
    ]
    led = load_ledger(paths.corpus, "1KGS.17")
    item = next(i for i in led.items.values() if i.status == "draft")
    assert [h.by for h in item.history].count("urim run") == 2
    assert item.history[-1].note.startswith("Escalated")


def test_your_requests_come_first_and_restart_the_rounds(paths):
    world = World(paths)
    world.conductor("1KGS.17", layers=("chronology",)).run()
    led = load_ledger(paths.corpus, "1KGS.17")
    event = next(k for k in led.items if k.startswith("event:"))
    set_status(paths.corpus, [event], "changes_requested", "Name the brook.")
    conductor = world.conductor("1KGS.17", layers=("chronology",))
    first = conductor.plan().steps[0]
    assert (first.action, first.fresh) == ("revise", True)
    world.calls.clear()
    conductor.run()
    assert [s.action for s in world.calls] == ["revise", "critique", "revise", "critique"]
    assert load_ledger(paths.corpus, "1KGS.17").items[event].status == "approved"


def test_usage_limits_pause_the_run_until_they_lift(paths):
    world = World(paths, limit_once=True)
    state = world.conductor("1KGS.17", layers=("chronology",)).run()
    assert state.status == "finished"
    assert [s.status for s in state.steps][:2] == ["limited", "done"]
    assert world.clock.now >= datetime(2026, 10, 28, 12, 20, tzinfo=UTC)


def test_api_failures_pause_the_run_and_count_against_nothing(paths):
    world = World(paths, refuse=4)  # one more than a layer may fail
    alerts = []
    state = world.conductor("1KGS.17", layers=("chronology",), alert=alerts.append).run()
    assert state.status == "finished" and state.chapters[0].layers["chronology"].phase == "done"
    assert [s.status for s in state.steps][:5] == ["unavailable"] * 4 + ["done"]
    # Waits of 10, 20, 40 and 80 minutes, and one alert for the whole outage.
    assert world.clock.now >= datetime(2026, 10, 28, 14, 30, tzinfo=UTC)
    assert alerts == [f"Run 1KGS.17 paused: {REFUSAL}"]
    assert state.waiting_until is None and state.waiting_for is None


def test_running_again_retries_layers_that_failed(paths):
    world = World(paths, idle=3)
    first = world.conductor("1KGS.17", layers=("chronology",)).run()
    assert first.chapters[0].layers["chronology"].phase == "failed"
    assert [s.error for s in first.steps] == ["the session merged nothing"] * 3
    second = world.conductor("1KGS.17", layers=("chronology",)).run()
    assert second.chapters[0].layers["chronology"].phase == "done"
    assert any(line.endswith("retrying what failed: 1KGS.17 chronology") for line in second.log)


def test_api_failures_are_told_apart_from_the_sessions_own():
    assert api_failure(f"{REFUSAL} You can find the next step…\nmore") == (
        f"{REFUSAL} You can find the next step…"
    )
    assert api_failure("API Error: 529 Overloaded") == "API Error: 529 Overloaded"
    assert api_failure("API Error: 400 prompt is too long: 210000 tokens > 200000") is None
    assert api_failure("the session merged nothing") is None


def test_a_language_follows_the_settled_english_and_its_interface_comes_first(paths):
    world = World(paths)
    layers = ("chronology", "ontology", "philology", "ru")
    state = world.conductor("1KGS.17", layers=layers, parallel=3).run()
    assert state.status == "finished"
    assert {r.phase for c in state.chapters for r in c.layers.values()} == {"done"}
    ru = [s for s in world.calls if s.layer == "ru"]
    first_ru = world.calls.index(ru[0])
    english_done = max(i for i, s in enumerate(world.calls) if s.layer != "ru")
    chapter_steps = [s for s in ru if s.chapter == "1KGS.17"]
    assert all(world.calls.index(s) > english_done for s in chapter_steps)
    assert ru[0].scope.startswith(("ui.", "bundle")) and first_ru < world.calls.index(
        chapter_steps[0]
    )
    assert {s.command.split()[0] for s in ru if s.action != "critique"} == {"/urim-localizer"}
    assert [s.action for s in chapter_steps][-1] == "critique"
    led = load_ledger(paths.corpus, "1KGS.17")
    translated = [i for k, i in led.items.items() if ".ru:" in k]
    assert translated and {i.status for i in translated} == {"approved"}
    assert not any(s.todo for s in message_states(paths.corpus, "ru"))


def test_philology_runs_in_windows(paths):
    world = World(paths)
    state = world.conductor("1KGS.17-18", layers=("chronology", "philology"), parallel=3).run()
    assert {c.layers["philology"].phase for c in state.chapters} == {"done"}
    writes = [
        s.scope
        for s in world.calls
        if s.layer == "philology" and s.action == "write" and s.chapter == "1KGS.18"
    ]
    assert sorted(writes) == ["1KGS.18.1-12", "1KGS.18.13-24", "1KGS.18.25-36", "1KGS.18.37-46"]


def test_windows_group_verses_twelve_at_a_time():
    assert windows([f"GEN.37.{n}" for n in (1, 2, 3, 12, 13, 30)]) == [
        "GEN.37.1-12",
        "GEN.37.13-13",
        "GEN.37.30-30",
    ]


def test_runs_refuse_chapters_that_are_not_ingested(paths):
    with pytest.raises(RunError, match="not ingested"):
        World(paths).conductor("1KGS.20")


def test_critique_decisions_are_signed_and_findings_elsewhere_become_notes(paths):
    for chapter in ("1KGS.17", "1KGS.18"):
        merge_fragment(gold.chronology(chapter), paths.corpus, paths.inputs)
    led = load_ledger(paths.corpus, "1KGS.18")
    drafts = layer_items(led, "chronology", "draft")
    report = CriticReport(
        chapter_ref="1KGS.18",
        layer="chronology",
        produced_by=CRITIC,
        reviewed=drafts[1:],
        findings=[
            Finding(
                item="entity:person.elijah",
                severity="blocker",
                problem="wrong",
                evidence="1KGS.18.1",
                change_request="fix",
            )
        ],
    )
    verdict = apply_critique(paths.corpus, report, final=False)
    assert verdict.unreviewed == drafts[:1] and len(verdict.approved) == len(drafts) - 1
    assert verdict.noted == 1
    led = load_ledger(paths.corpus, "1KGS.18")
    assert led.items[drafts[0]].status == "draft"
    assert "person.elijah" in led.notes[-1].note
    assert led.items[drafts[1]].status == "approved"
    assert led.items[drafts[1]].history[-1].by == "urim-critic@2 · claude-opus-5-5"


def test_limit_messages_say_when_to_resume():
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    assert limit_reset("Claude AI usage limit reached|1761660000", now) == datetime.fromtimestamp(
        1761660000, UTC
    )
    assert limit_reset("some other error", now) is None
    later = limit_reset("You've hit your limit · resets 3pm", now)
    assert later > now and later.astimezone().hour == 15
    assert limit_reset("usage limit reached", now) == now + timedelta(minutes=30)


def test_headless_sessions_stream_activity_and_usage(tmp_path):
    fake = tmp_path / "claude"
    lines = [
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "uv run urim task"}}
                ]
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "merged 9 events",
            "session_id": "s1",
            "num_turns": 7,
            "total_cost_usd": 0.42,
            "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30},
        },
    ]
    script = "import json, sys\n" + "".join(f"print(json.dumps({line!r}))\n" for line in lines)
    fake.write_text(f"#!{sys.executable}\n{script}")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    seen = []
    session = HeadlessSession(
        claude_command(str(fake), "/urim-chronologist GEN.38", "claude-sonnet-5-5"),
        cwd=tmp_path,
        transcript=tmp_path / "t.jsonl",
        on_activity=seen.append,
    )
    result = session.run()
    assert result.ok and result.summary == "merged 9 events" and result.turns == 7
    assert (result.tokens_in, result.tokens_out, result.cache_read) == (10, 20, 30)
    assert seen == ["Bash: uv run urim task"]
    assert len((tmp_path / "t.jsonl").read_text().splitlines()) == 3

    message = "Claude AI usage limit reached|1761660000"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.exit({message!r})\n")
    limited = HeadlessSession(
        claude_command(str(fake), "/x", "m"), cwd=tmp_path, transcript=tmp_path / "u.jsonl"
    ).run()
    assert not limited.ok and limited.limited_until == datetime.fromtimestamp(1761660000, UTC)

    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.exit({REFUSAL!r})\n")
    refused = HeadlessSession(
        claude_command(str(fake), "/x", "m"), cwd=tmp_path, transcript=tmp_path / "v.jsonl"
    ).run()
    assert refused.unavailable == REFUSAL and refused.limited_until is None


def test_sessions_are_told_they_run_alone_and_kept_from_the_gold():
    cmd = claude_command("claude", "/urim-critic GEN.38 chronology", "claude-opus-5-5")
    assert cmd[:3] == ["claude", "-p", "/urim-critic GEN.38 chronology"]
    assert "Read(./fixtures/**)" in cmd and "Bash(uv run urim:*)" in cmd
    note = cmd[cmd.index("--append-system-prompt") + 1]
    assert "unattended" in note and "only `uv run urim …` runs" in note
    assert activity_of({"type": "user"}) is None


def test_a_second_conductor_will_not_start_on_a_live_run(paths):
    world = World(paths)
    conductor = world.conductor("1KGS.17", layers=("chronology",))
    conductor.state.pid = 1  # launchd: always alive
    conductor.state.status = "running"
    conductor.save()
    with pytest.raises(RunError, match="already going"):
        world.conductor("1KGS.17", layers=("chronology",))
