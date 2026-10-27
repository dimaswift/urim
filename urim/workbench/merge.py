"""`urim ir merge`: check a session's fragment and fold it into the corpus.

A fragment is authoritative for what its agent owns in its chapter: items it leaves out are
dropped, unless you approved them (approved items are locked and kept). Philology is the
exception: it touches only the verses it carries, so it can work in windows. Nothing is
written until the merged corpus links cleanly in a scratch copy.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from urim.bundles import core_path
from urim.canon import parse_ref
from urim.compiler.link import LinkError, link_all
from urim.ir.load import inputs_root, load_sources, read_model, write_model
from urim.ir.models import CoreChapterIR, I18nChapterIR, Participant
from urim.workbench.fragments import (
    ChronologyFragment,
    OntologyFragment,
    PhilologyFragment,
    key,
    key_for_note,
)
from urim.workbench.ledger import (
    ChapterLedger,
    ChapterNote,
    LedgerItem,
    load_ledger,
    now,
    save_ledger,
)
from urim.workbench.timeline import CauseRow, TimeRow, chapter_timeline

Fragment = ChronologyFragment | OntologyFragment | PhilologyFragment


@dataclass
class MergeResult:
    agent: str
    chapter_ref: str
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kept_locked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    timeline: list[TimeRow] = field(default_factory=list)
    causes: list[CauseRow] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def chapter_of(verse_id: str) -> str:
    _, ref = parse_ref(verse_id)
    return f"{ref.book.code}.{ref.chapter}"


def _ordinal(verse_id: str) -> int:
    return parse_ref(verse_id)[1].ordinal


def _dump(model: BaseModel | None, **exclude: Any) -> str:
    if model is None:
        return ""
    return json.dumps(model.model_dump(mode="json", exclude=set(exclude) or None), sort_keys=True)


class CorpusFiles:
    """Lazily loaded corpus chapter files, with change tracking."""

    def __init__(self, corpus: Path):
        self.corpus = Path(corpus)
        self._core: dict[str, CoreChapterIR] = {}
        self._i18n: dict[tuple[str, str], I18nChapterIR] = {}
        self.dirty: set[tuple[str, ...]] = set()

    def core(self, chapter: str) -> CoreChapterIR:
        if chapter not in self._core:
            path = self.corpus / "core" / f"{chapter}.json"
            self._core[chapter] = (
                read_model(path, CoreChapterIR)
                if path.exists()
                else CoreChapterIR(chapter_ref=chapter)
            )
        return self._core[chapter]

    def i18n(self, lang: str, chapter: str) -> I18nChapterIR:
        if (lang, chapter) not in self._i18n:
            path = self.corpus / "i18n" / lang / f"{chapter}.json"
            self._i18n[(lang, chapter)] = (
                read_model(path, I18nChapterIR)
                if path.exists()
                else I18nChapterIR(chapter_ref=chapter)
            )
        return self._i18n[(lang, chapter)]

    def chapters(self) -> list[str]:
        return sorted(p.stem for p in (self.corpus / "core").glob("*.json"))

    def home(self, section: str, id_attr: str, item_id: str) -> str | None:
        """Chapter whose core file defines the item, if any."""
        for chapter in self.chapters():
            if any(getattr(x, id_attr) == item_id for x in getattr(self.core(chapter), section)):
                return chapter
        return None

    def touch_core(self, chapter: str) -> None:
        self.dirty.add(("core", chapter))

    def touch_i18n(self, lang: str, chapter: str) -> None:
        self.dirty.add(("i18n", lang, chapter))

    def write(self, root: Path) -> list[Path]:
        written = []
        for entry in sorted(self.dirty):
            if entry[0] == "core":
                path = Path(root) / "core" / f"{entry[1]}.json"
                write_model(path, self.core(entry[1]))
            else:
                path = Path(root) / "i18n" / entry[1] / f"{entry[2]}.json"
                write_model(path, self.i18n(entry[1], entry[2]))
            written.append(path)
        return written


def _decide(
    kind: str,
    cur: dict[str, str],
    inc: dict[str, str],
    ledger: ChapterLedger,
    result: MergeResult,
) -> dict[str, str]:
    """Per id: keep the 'old' item or take the 'new' one; ids missing from the result go.

    `cur` and `inc` map ids to a comparable serialization of everything the key covers.
    """
    decision = {}
    for item_id in sorted(set(cur) | set(inc)):
        k = key(kind, item_id)
        if ledger.locked(k) and item_id in cur:
            if item_id in inc and inc[item_id] != cur[item_id]:
                result.errors.append(
                    f"{k} is approved and locked: leave it out or reproduce it exactly "
                    "(reopen it to change it)"
                )
            decision[item_id] = "old"
            result.kept_locked.append(k)
        elif item_id in inc:
            decision[item_id] = "new"
            if item_id not in cur:
                result.added.append(k)
            elif inc[item_id] == cur[item_id]:
                result.unchanged.append(k)
            else:
                result.changed.append(k)
        else:
            result.removed.append(k)
    return decision


def _section(
    kind: str,
    cur_items: list,
    cur_texts: list,
    inc_items: list,
    inc_texts: list,
    id_attr: str,
    ledger: ChapterLedger,
    result: MergeResult,
    sort_key: Callable[[Any], Any],
    *,
    ignore: tuple[str, ...] = (),
    carry: Callable[[Any, Any], Any] | None = None,
) -> tuple[list, list]:
    """Merge a core section and its English text section, both keyed `kind:id`."""

    def index(items, texts):
        items_by = {getattr(x, id_attr): x for x in items}
        texts_by = {getattr(t, id_attr): t for t in texts}
        return (
            items_by,
            texts_by,
            {
                i: _dump(items_by.get(i), **dict.fromkeys(ignore)) + "|" + _dump(texts_by.get(i))
                for i in set(items_by) | set(texts_by)
            },
        )

    cur_by, cur_text_by, cur_cmp = index(cur_items, cur_texts)
    inc_by, inc_text_by, inc_cmp = index(inc_items, inc_texts)
    decision = _decide(kind, cur_cmp, inc_cmp, ledger, result)
    items, texts = [], []
    for item_id, which in decision.items():
        if which == "old":
            item, text = cur_by.get(item_id), cur_text_by.get(item_id)
        else:
            item, text = inc_by.get(item_id), inc_text_by.get(item_id)
            if carry and item is not None and item_id in cur_by:
                item = carry(cur_by[item_id], item)
        if item is not None:
            items.append(item)
        if text is not None:
            texts.append(text)
    items.sort(key=sort_key)
    order = {getattr(x, id_attr): i for i, x in enumerate(items)}
    texts.sort(key=lambda t: order.get(getattr(t, id_attr), len(order)))
    return items, texts


def _require_texts(kind: str, items: list, texts: list, id_attr: str, result: MergeResult) -> None:
    have = {getattr(t, id_attr) for t in texts}
    for item in items:
        if getattr(item, id_attr) not in have:
            result.errors.append(f"{key(kind, getattr(item, id_attr))}: English text is missing")
    ids = {getattr(i, id_attr) for i in items}
    for t in texts:
        if getattr(t, id_attr) not in ids:
            result.errors.append(f"text for {getattr(t, id_attr)} has no matching {kind}")


# --- per agent --------------------------------------------------------------------------------


def _merge_chronology(
    f: ChronologyFragment, files: CorpusFiles, led: ChapterLedger, result: MergeResult
) -> None:
    ch = f.chapter_ref
    for e in f.events:
        if chapter_of(e.verse_start) != ch:
            result.errors.append(f"{e.event_id} starts at {e.verse_start}, outside {ch}")
    _require_texts("event", f.events, f.event_texts, "event_id", result)
    _require_texts("causal", f.causal_edges, f.causal_texts, "causal_id", result)
    core, en = files.core(ch), files.i18n("en", ch)
    chapter_events = {e.event_id for e in f.events} | {e.event_id for e in core.events}
    for c in f.causal_edges:
        if c.effect_event_id not in chapter_events:
            result.errors.append(
                f"{c.causal_id}: its effect {c.effect_event_id} is not an event of {ch}; "
                "causal links live in the chapter of their effect"
            )

    def keep_links(old, new):
        return new.model_copy(
            update={"participants": old.participants, "location_entity_id": old.location_entity_id}
        )

    core.events, en.events = _section(
        "event",
        core.events,
        en.events,
        f.events,
        f.event_texts,
        "event_id",
        led,
        result,
        lambda e: (_ordinal(e.verse_start), _ordinal(e.verse_end), e.event_id),
        ignore=("participants", "location_entity_id"),
        carry=keep_links,
    )
    core.causal_edges, en.causal_edges = _section(
        "causal",
        core.causal_edges,
        en.causal_edges,
        f.causal_edges,
        f.causal_texts,
        "causal_id",
        led,
        result,
        lambda c: c.causal_id,
    )
    for k in result.removed:
        if k.startswith("event:"):
            led.items.pop(key("event_links", k.split(":", 1)[1]), None)
    files.touch_core(ch)
    files.touch_i18n("en", ch)


def _merge_ontology(
    f: OntologyFragment,
    files: CorpusFiles,
    led: ChapterLedger,
    result: MergeResult,
    ledgers: dict[str, ChapterLedger],
) -> None:
    ch = f.chapter_ref
    core, en = files.core(ch), files.i18n("en", ch)

    for e in f.entities:
        if chapter_of(e.first_mention_verse) != ch:
            result.errors.append(
                f"{e.entity_id}: first mentioned at {e.first_mention_verse}; "
                "define entities in the chapter of their first mention"
            )
        home = files.home("entities", "entity_id", e.entity_id)
        if home and home != ch:
            result.errors.append(f"{e.entity_id} is already defined in {home}")
    for s in f.systems:
        home = files.home("systems", "system_id", s.system_id)
        if home and home != ch:
            result.errors.append(f"{s.system_id} is already defined in {home}")
    for c in f.components:
        if chapter_of(c.acquired_at_verse) != ch:
            result.errors.append(
                f"{c.component_id}: acquired at {c.acquired_at_verse}, not in {ch}"
            )
    own_components = {c.component_id for c in f.components}
    for c in f.component_closures:
        if c.component_id in own_components:
            result.errors.append(
                f"{c.component_id}: set expired_at_verse on the component itself; "
                "closures are for states opened in earlier chapters"
            )
        if chapter_of(c.expired_at_verse) != ch:
            result.errors.append(f"closing {c.component_id} at {c.expired_at_verse}, not in {ch}")
    for i in f.system_instances:
        if chapter_of(i.verse_start) != ch:
            result.errors.append(f"{i.instance_id} starts at {i.verse_start}, outside {ch}")
    for e in f.edges:
        if chapter_of(e.verse_id) != ch:
            result.errors.append(f"{e.edge_id} is at {e.verse_id}, outside {ch}")

    new_entities = {e.entity_id for e in f.entities}
    new_systems = {s.system_id for s in f.systems}
    own_entity_texts = [t for t in f.entity_texts if t.entity_id in new_entities]
    own_system_texts = [t for t in f.system_texts if t.system_id in new_systems]
    _require_texts("entity", f.entities, own_entity_texts, "entity_id", result)
    _require_texts("system", f.systems, own_system_texts, "system_id", result)
    _require_texts("component", f.components, f.component_texts, "component_id", result)
    _require_texts("instance", f.system_instances, f.instance_texts, "instance_id", result)
    _require_texts("edge", f.edges, f.edge_texts, "edge_id", result)

    core.entities, en.entities = _section(
        "entity",
        core.entities,
        en.entities,
        f.entities,
        own_entity_texts,
        "entity_id",
        led,
        result,
        lambda e: e.entity_id,
    )
    core.systems, en.systems = _section(
        "system",
        core.systems,
        en.systems,
        f.systems,
        own_system_texts,
        "system_id",
        led,
        result,
        lambda s: s.system_id,
    )
    core.components, en.components = _section(
        "component",
        core.components,
        en.components,
        f.components,
        f.component_texts,
        "component_id",
        led,
        result,
        lambda c: c.component_id,
    )
    core.component_closures, _ = _section(
        "closure",
        core.component_closures,
        [],
        f.component_closures,
        [],
        "component_id",
        led,
        result,
        lambda c: c.component_id,
    )
    core.system_instances, en.system_instances = _section(
        "instance",
        core.system_instances,
        en.system_instances,
        f.system_instances,
        f.instance_texts,
        "instance_id",
        led,
        result,
        lambda i: i.instance_id,
    )
    core.edges, en.edges = _section(
        "edge",
        core.edges,
        en.edges,
        f.edges,
        f.edge_texts,
        "edge_id",
        led,
        result,
        lambda e: e.edge_id,
    )

    # Event links: participants and location of this chapter's events.
    events = {e.event_id: e for e in core.events}
    rows: dict[str, list] = defaultdict(list)
    places: dict[str, str] = {}
    for p in f.participants:
        rows[p.event_id].append(p)
    for loc in f.event_locations:
        places[loc.event_id] = loc.location_entity_id
    for event_id in sorted(set(rows) | set(places)):
        if event_id not in events:
            result.errors.append(
                f"{event_id} is not an event of {ch}; run the chronology task "
                "first, or check the id"
            )

    def links(participants, location) -> str:
        return json.dumps([sorted((p.entity_id, p.role) for p in participants), location])

    cur = {
        i: links(e.participants, e.location_entity_id)
        for i, e in events.items()
        if e.participants or e.location_entity_id
    }
    inc = {i: links(rows.get(i, []), places.get(i)) for i in set(rows) | set(places) if i in events}
    for event_id, which in _decide("event_links", cur, inc, led, result).items():
        if which == "new":
            ev = events[event_id]
            cast = sorted(rows.get(event_id, []), key=lambda p: p.entity_id)
            events[event_id] = ev.model_copy(
                update={
                    "participants": [Participant(entity_id=p.entity_id, role=p.role) for p in cast],
                    "location_entity_id": places.get(event_id),
                }
            )
    for k in result.removed:
        if k.startswith("event_links:"):
            event_id = k.split(":", 1)[1]
            events[event_id] = events[event_id].model_copy(
                update={"participants": [], "location_entity_id": None}
            )
    core.events = [events[e.event_id] for e in core.events]
    files.touch_core(ch)
    files.touch_i18n("en", ch)

    # Text updates for entities and systems defined in earlier chapters.
    for texts, section, id_attr, kind in (
        (
            [t for t in f.entity_texts if t.entity_id not in new_entities],
            "entities",
            "entity_id",
            "entity",
        ),
        (
            [t for t in f.system_texts if t.system_id not in new_systems],
            "systems",
            "system_id",
            "system",
        ),
    ):
        for t in texts:
            item_id = getattr(t, id_attr)
            home = files.home(section, id_attr, item_id)
            if home is None:
                result.errors.append(f"text for {item_id}, which is not defined anywhere")
                continue
            home_ledger = ledgers.setdefault(home, load_ledger(files.corpus, home))
            home_en = files.i18n("en", home)
            current = getattr(home_en, section)
            old = next((x for x in current if getattr(x, id_attr) == item_id), None)
            k = key(kind, item_id)
            if _dump(old) == _dump(t):
                result.unchanged.append(k)
                continue
            if home_ledger.locked(k):
                result.errors.append(f"{k} (defined in {home}) is approved and locked")
                continue
            setattr(
                home_en,
                section,
                [t if getattr(x, id_attr) == item_id else x for x in current]
                if old
                else [*current, t],
            )
            files.touch_i18n("en", home)
            result.changed.append(k)


def _merge_philology(
    f: PhilologyFragment,
    files: CorpusFiles,
    led: ChapterLedger,
    result: MergeResult,
    token_counts: dict[str, int],
) -> None:
    ch = f.chapter_ref
    for v in f.verses:
        if chapter_of(v.verse_id) != ch:
            result.errors.append(f"{v.verse_id} is outside {ch}")
        n = token_counts.get(v.verse_id)
        if n is None:
            result.errors.append(f"{v.verse_id} is not in the ingested source text")
        elif v.token_glosses and len(v.token_glosses) != n:
            result.warnings.append(f"{v.verse_id}: {len(v.token_glosses)} glosses for {n} words")
    en = files.i18n("en", ch)
    current = {v.verse_id: v for v in en.verses}
    incoming = {v.verse_id: v for v in f.verses}
    decision = _decide(
        "verse.en",
        {i: _dump(current[i]) for i in incoming if i in current},
        {i: _dump(v) for i, v in incoming.items()},
        led,
        result,
    )
    merged = dict(current)
    for verse_id, which in decision.items():
        merged[verse_id] = current[verse_id] if which == "old" else incoming[verse_id]
    en.verses = sorted(merged.values(), key=lambda v: _ordinal(v.verse_id))
    files.touch_i18n("en", ch)


# --- entry point ------------------------------------------------------------------------------


def merge_fragment(
    fragment: Fragment, corpus: Path, inputs: Path, *, dry_run: bool = False
) -> MergeResult:
    corpus, inputs = Path(corpus), Path(inputs)
    result = MergeResult(agent=fragment.agent, chapter_ref=fragment.chapter_ref)
    sources = load_sources(inputs_root(corpus, inputs))
    token_counts = {v.verse_id: len(v.tokens) for b in sources for v in b.verses}
    if not any(chapter_of(v) == fragment.chapter_ref for v in token_counts):
        result.errors.append(f"{fragment.chapter_ref} is not ingested yet: run `urim ingest` first")
        return result

    files = CorpusFiles(corpus)
    led = load_ledger(corpus, fragment.chapter_ref)
    ledgers = {fragment.chapter_ref: led}
    match fragment:
        case ChronologyFragment():
            _merge_chronology(fragment, files, led, result)
        case OntologyFragment():
            _merge_ontology(fragment, files, led, result, ledgers)
        case PhilologyFragment():
            _merge_philology(fragment, files, led, result, token_counts)
    if result.errors:
        return result

    # Link the merged corpus in a scratch copy before touching the real one.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "corpus"
        if corpus.exists():
            shutil.copytree(corpus, scratch)
        files.write(scratch)
        try:
            reports = link_all(scratch, Path(tmp) / "bundles", inputs_dir=inputs)
        except LinkError as e:
            result.errors += e.report.errors
            result.warnings += e.report.warnings
            return result
        for name, report in reports.items():
            result.warnings += [f"{name}: {w}" for w in report.warnings]
        if isinstance(fragment, ChronologyFragment):
            result.timeline, result.causes = chapter_timeline(
                core_path(Path(tmp) / "bundles"), fragment.chapter_ref
            )
    if dry_run:
        return result

    result.written = files.write(corpus)
    _record(fragment, ledgers, result)
    for ledger in ledgers.values():
        save_ledger(corpus, ledger)
    return result


def _record(fragment: Fragment, ledgers: dict[str, ChapterLedger], result: MergeResult) -> None:
    """Provenance and agent notes into the ledger; removed items leave it."""
    lang = "en"
    notes: dict[str, list[str]] = defaultdict(list)
    chapter_notes = []
    for n in fragment.reviewer_notes:
        k = key_for_note(n.item, fragment.agent, lang) if n.item else None
        (notes[k].append(n.note) if k else chapter_notes.append(n.note))
    stamp = now()
    led = ledgers[fragment.chapter_ref]
    touched = set(result.added) | set(result.changed) | set(result.unchanged)
    for k in sorted(touched):
        owner = next((x for x in ledgers.values() if k in x.items), led)
        old = owner.items.get(k)
        if k in result.unchanged and old is not None:
            if notes.get(k):
                old.agent_notes = notes[k]
            continue
        owner.items[k] = LedgerItem(
            status="draft",
            produced_by=fragment.produced_by,
            produced_at=stamp,
            agent_notes=notes.get(k, []),
            history=old.history if old else [],
        )
    for k in result.removed:
        led.items.pop(k, None)
    for k, texts in notes.items():
        if k not in touched:
            chapter_notes += [f"[{k}] {t}" for t in texts]
    led.notes += [
        ChapterNote(note=t, produced_by=fragment.produced_by, at=stamp) for t in chapter_notes
    ]
