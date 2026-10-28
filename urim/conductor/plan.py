"""What an autonomous run does next, read from the corpus itself.

The corpus and its ledger are the run's memory. A layer with nothing written gets written, a
layer with change requests gets revised, a layer with drafts gets critiqued, and a layer whose
items are all approved, or settled with the leftovers escalated to you, is done. A run that
stops (a crash, Ctrl-C, a usage limit) resumes by planning again. The run state adds only what
the corpus cannot say: how many rounds the critic has had, which layers are settled, failures.

Chapters of a book build on each other, so chronology goes one chapter at a time; ontology
follows the settled chronology of its chapter and its own previous chapter; philology windows
run side by side once a chapter's events are settled.

A language (`ru`) is one more layer: a chapter's texts once its English chronology and ontology
are settled, its verses in windows once their philology is, then the critic. A language also
has work outside the chapters, its interface messages (one step per namespace) and its bundle
labels; those have no critique.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from urim.canon import parse_ref
from urim.config import Paths
from urim.i18n.messages import english
from urim.ir.load import inputs_root, load_sources
from urim.workbench.critique import is_language, layer_items, layer_of
from urim.workbench.ledger import USER, LedgerItem, load_ledger
from urim.workbench.localize import bundle_states, message_states, text_states, verse_states
from urim.workbench.merge import CorpusFiles, chapter_of
from urim.workbench.packets import PHILOLOGY_WINDOW

LAYERS = ("chronology", "ontology", "philology")
SKILLS = {
    "chronology": "urim-chronologist",
    "ontology": "urim-ontologist",
    "philology": "urim-philologist",
    "localization": "urim-localizer",
    "critic": "urim-critic",
}
MAX_FAILURES = 3
_VERSE = re.compile(r"^[1-3]?[A-Z]+\.\d+\.\d+$")
Action = Literal["write", "revise", "critique"]


class LayerState(BaseModel):
    rounds: int = 0  # critiques applied in the current cycle
    settled: bool = False  # the last round ran: what is left is yours
    failures: int = 0  # sessions in a row that changed nothing


@dataclass(frozen=True)
class Step:
    action: Action
    layer: str
    chapter: str
    scope: str
    round: int = 0
    final: bool = False
    fresh: bool = False  # a revision you asked for: the critic's rounds start over

    @property
    def id(self) -> str:
        tail = f".r{self.round}" if self.action == "critique" else ""
        return f"{self.action}.{self.layer}.{self.scope}{tail}"

    @property
    def agent(self) -> str:
        if self.action == "critique":
            return "critic"
        return "localization" if is_language(self.layer) else self.layer

    @property
    def command(self) -> str:
        if self.action == "critique":
            return f"/{SKILLS['critic']} {self.chapter} {self.layer}"
        if is_language(self.layer):
            return f"/{SKILLS['localization']} {self.layer} {self.scope}"
        return f"/{SKILLS[self.layer]} {self.scope}"

    @property
    def outside_chapters(self) -> bool:
        """Interface messages and bundle labels: a language's work that has no chapter."""
        return self.chapter.startswith("ui.") or self.chapter == "bundle"


def is_escalated(item: LedgerItem) -> bool:
    last = item.history[-1] if item.history else None
    return (
        item.status == "draft"
        and last is not None
        and last.status == "draft"
        and (last.note or "").startswith("Escalated")
    )


@dataclass
class LayerView:
    """One layer of one chapter, as the corpus shows it."""

    chapter: str
    layer: str
    approved: int = 0
    drafts: int = 0
    requested: list[str] = field(default_factory=list)
    escalated: int = 0
    # Verses (philology), the chapter (chronology, ontology), or for a language the keys of
    # texts and the verses still to translate, stale ones included.
    unwritten: list[str] = field(default_factory=list)
    by_user: bool = False  # some request is yours

    @property
    def items(self) -> int:
        return self.approved + self.drafts + len(self.requested)

    def phase(self, state: LayerState) -> str:
        if state.failures >= MAX_FAILURES:
            return "failed"
        if self.unwritten:
            return "partial" if self.items else "unwritten"
        if self.requested:
            return "requested"
        if self.drafts > self.escalated or (self.drafts and not state.settled):
            return "drafts"
        return "done"


def chapter_verses(paths: Paths, chapters: list[str]) -> dict[str, list[str]]:
    wanted = set(chapters)
    out: dict[str, list[str]] = {c: [] for c in chapters}
    for book in load_sources(inputs_root(paths.corpus, paths.inputs)):
        for v in book.verses:
            if (c := chapter_of(v.verse_id)) in wanted:
                out[c].append(v.verse_id)
    return out


def layer_views(
    paths: Paths, verses: dict[str, list[str]], langs: tuple[str, ...] = ()
) -> dict[tuple[str, str], LayerView]:
    files = CorpusFiles(paths.corpus)
    views = {}
    for ch, chapter_verse_ids in verses.items():
        led = load_ledger(paths.corpus, ch)
        events = files.core(ch).events
        written = {
            "chronology": [] if events else [ch],
            "ontology": [] if layer_items(led, "ontology") else [ch],
            "philology": sorted(
                set(chapter_verse_ids) - {v.verse_id for v in files.i18n("en", ch).verses},
                key=_verse_no,
            ),
        }
        for lang in langs:
            texts = [s.key for s in text_states(files, led, lang, ch) if s.todo]
            lines = [s.item_id for s in verse_states(files, led, lang, ch) if s.todo]
            written[lang] = texts + sorted(lines, key=_verse_no)
        for layer in (*LAYERS, *langs):
            view = LayerView(ch, layer, unwritten=written[layer])
            for k, item in led.items.items():
                if layer_of(k) != layer:
                    continue
                if item.status == "approved":
                    view.approved += 1
                elif item.status == "changes_requested":
                    view.requested.append(k)
                    last = item.history[-1] if item.history else None
                    view.by_user |= last is not None and last.by == USER
                else:
                    view.drafts += 1
                    view.escalated += is_escalated(item)
            views[ch, layer] = view
    return views


def _verse_no(verse_id: str) -> int:
    return parse_ref(verse_id)[1].verse


def is_verse(ref: str) -> bool:
    return bool(_VERSE.match(ref))


def windows(verse_ids: list[str]) -> list[str]:
    """Verses grouped into philology scopes of at most PHILOLOGY_WINDOW verses each."""
    nos = sorted({_verse_no(v) for v in verse_ids})
    if not nos:
        return []
    chapter = chapter_of(verse_ids[0])
    out, start = [], nos[0]
    prev = start
    for n in nos[1:]:
        if n - start >= PHILOLOGY_WINDOW:
            out.append((start, prev))
            start = n
        prev = n
    out.append((start, prev))
    return [f"{chapter}.{a}-{b}" for a, b in out]


@dataclass
class Plan:
    views: dict[tuple[str, str], LayerView]
    steps: list[Step]  # runnable now, most urgent first

    def phase(self, chapter: str, layer: str, states: dict[str, LayerState]) -> str:
        return self.views[chapter, layer].phase(states.get(f"{chapter}:{layer}", LayerState()))


def plan(
    paths: Paths,
    verses: dict[str, list[str]],
    states: dict[str, LayerState],
    *,
    layers: tuple[str, ...] = LAYERS,
    max_rounds: int = 2,
    running: tuple[Step, ...] = (),
) -> Plan:
    """Every step that may start now, given the steps already running."""
    langs = tuple(layer for layer in layers if is_language(layer))
    views = layer_views(paths, verses, langs)
    chapters = list(verses)

    def state(ch: str, layer: str) -> LayerState:
        return states.get(f"{ch}:{layer}", LayerState())

    def done(ch: str | None, layer: str) -> bool:
        if ch is None or layer not in layers:
            return True
        return views[ch, layer].phase(state(ch, layer)) == "done"

    def settled(ch: str, layer: str) -> bool:
        """English a translation may follow: done in this run, or settled before it."""
        if layer in layers:
            return done(ch, layer)
        return views[ch, layer].phase(LayerState(settled=True)) == "done"

    steps = []
    for lang in langs:
        steps += _outside_chapters(paths, lang, states)
    for i, ch in enumerate(chapters):
        prev = chapters[i - 1] if i and _same_book(chapters[i - 1], ch) else None
        texts_ready = settled(ch, "chronology") and settled(ch, "ontology")
        ready = {
            "chronology": done(prev, "chronology"),
            "ontology": done(ch, "chronology") and done(prev, "ontology"),
            "philology": done(ch, "chronology"),
        } | {lang: texts_ready or settled(ch, "philology") for lang in langs}
        for layer in layers:
            view, st = views[ch, layer], state(ch, layer)
            phase = view.phase(st)
            if phase in ("done", "failed") or not ready[layer]:
                continue
            if phase in ("unwritten", "partial"):
                if is_language(layer):
                    scopes = _language_scopes(ch, view.unwritten)
                    scopes = [
                        s for s in scopes if (texts_ready if s == ch else settled(ch, "philology"))
                    ]
                else:
                    scopes = windows(view.unwritten) if layer == "philology" else [ch]
                steps += [Step("write", layer, ch, s) for s in scopes]
            elif phase == "requested":
                refs = [k.split(":", 1)[1] for k in view.requested]
                if layer == "philology":
                    scopes = windows(refs)
                elif is_language(layer):
                    scopes = _language_scopes(ch, view.requested)
                else:
                    scopes = [ch]
                steps += [Step("revise", layer, ch, s, fresh=view.by_user) for s in scopes]
            elif phase == "drafts":
                steps.append(
                    Step(
                        "critique",
                        layer,
                        ch,
                        ch,
                        round=st.rounds + 1,
                        final=st.rounds >= max_rounds,
                    )
                )
    steps = [s for s in steps if not any(clashes(s, r) for r in running)]
    order = {layer: n for n, layer in enumerate((*LAYERS, *langs))}

    def urgency(s: Step) -> tuple:
        where = -1 if s.outside_chapters else chapters.index(s.chapter)
        return (order[s.layer], where, s.scope)

    steps.sort(key=urgency)
    return Plan(views, steps)


def _language_scopes(chapter: str, pending: list[str]) -> list[str]:
    """The chapter's texts as one scope, its verses in windows."""
    refs = [k.split(":", 1)[-1] for k in pending]
    lines = [r for r in refs if is_verse(r)]
    return ([chapter] if len(lines) < len(refs) else []) + windows(lines)


# Shared words (statuses, kinds, units, the shell) come first, so every screen can use them.
SHARED_UI = ("ui.common", "ui.shell")


def _outside_chapters(paths: Paths, lang: str, states: dict[str, LayerState]) -> list[Step]:
    """Interface namespaces and the bundle with something to translate."""
    namespace = {k: s.namespace for k, s in english().items()}
    pending = {f"ui.{namespace[s.item_id]}" for s in message_states(paths.corpus, lang) if s.todo}
    shared = pending & set(SHARED_UI)
    if any(states.get(f"{scope}:{lang}", LayerState()).failures < MAX_FAILURES for scope in shared):
        pending = shared
    if any(s.todo for s in bundle_states(paths.corpus, lang)):
        pending.add("bundle")
    return [
        Step("write", lang, scope, scope)
        for scope in sorted(pending)
        if states.get(f"{scope}:{lang}", LayerState()).failures < MAX_FAILURES
    ]


def outside_pending(paths: Paths, step: Step) -> set[str]:
    """What a step outside the chapters still has to translate."""
    if step.chapter == "bundle":
        return {s.key for s in bundle_states(paths.corpus, step.layer) if s.todo}
    ns = step.chapter.removeprefix("ui.")
    namespace = {k: s.namespace for k, s in english().items()}
    return {
        s.key
        for s in message_states(paths.corpus, step.layer)
        if s.todo and namespace[s.item_id] == ns
    }


def clashes(step: Step, running: Step) -> bool:
    """One session per chapter layer at a time, except windows (philology, a language's texts
    and verse windows), which never overlap."""
    if (step.layer, step.chapter) != (running.layer, running.chapter):
        return False
    windowed = step.layer == "philology" or is_language(step.layer)
    windows_only = windowed and "critique" not in (step.action, running.action)
    return not windows_only or step.scope == running.scope


def _same_book(a: str, b: str) -> bool:
    return a.split(".")[0] == b.split(".")[0]
