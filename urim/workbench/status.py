"""`urim status`: where each chapter stands, and what to do next."""

from __future__ import annotations

from dataclasses import dataclass

from urim.canon import parse_ref
from urim.config import Paths
from urim.ir.load import inputs_root, load_sources
from urim.workbench.ledger import load_ledger
from urim.workbench.merge import CorpusFiles, chapter_of
from urim.workbench.packets import PHILOLOGY_WINDOW


@dataclass
class ChapterRow:
    chapter: str
    verses: list[str]
    events: int = 0
    linked_events: int = 0
    ontology_items: int = 0
    philology: int = 0
    approved: int = 0
    drafts: int = 0
    requests: int = 0
    notes: int = 0

    @property
    def missing_philology(self) -> list[str]:
        return [v for v in self.verses if v not in self._done]

    _done: frozenset[str] = frozenset()


def corpus_status(paths: Paths) -> list[ChapterRow]:
    sources = load_sources(inputs_root(paths.corpus, paths.inputs))
    chapters: dict[str, list[str]] = {}
    for book in sources:
        for v in book.verses:
            chapters.setdefault(chapter_of(v.verse_id), []).append(v.verse_id)
    files = CorpusFiles(paths.corpus)
    rows = []
    for ch in sorted(chapters, key=lambda c: parse_ref(f"{c}.1")[1].ordinal):
        core, en = files.core(ch), files.i18n("en", ch)
        led = load_ledger(paths.corpus, ch)
        done = {v.verse_id for v in en.verses}
        row = ChapterRow(
            chapter=ch,
            verses=chapters[ch],
            events=len(core.events),
            linked_events=sum(bool(e.participants or e.location_entity_id) for e in core.events),
            ontology_items=len(core.entities)
            + len(core.components)
            + len(core.system_instances)
            + len(core.edges)
            + len(core.systems)
            + len(core.component_closures),
            philology=len(done),
            approved=sum(i.status == "approved" for i in led.items.values()),
            drafts=sum(i.status == "draft" for i in led.items.values()),
            requests=sum(i.status == "changes_requested" for i in led.items.values()),
            notes=len(led.notes),
        )
        row._done = frozenset(done)
        rows.append(row)
    return rows


def next_steps(rows: list[ChapterRow], limit: int = 6) -> list[str]:
    steps = []
    chronology_next = ontology_next = False  # both build on earlier chapters: one at a time
    for row in rows:
        ch = row.chapter
        if row.requests:
            steps.append(
                f"{ch}: {row.requests} change request(s) waiting; rerun the skill that "
                "owns them (the packet lists them first)"
            )
        if row.events == 0:
            if not chronology_next:
                steps.append(f"/urim-chronologist {ch}")
            chronology_next = True
        elif row.linked_events == 0 and row.ontology_items == 0:
            if not ontology_next:
                steps.append(f"/urim-ontologist {ch}")
            ontology_next = True
        missing = row.missing_philology
        if missing and row.events:
            first = parse_ref(missing[0])[1].verse
            window = [v for v in missing if parse_ref(v)[1].verse < first + PHILOLOGY_WINDOW]
            last = parse_ref(window[-1])[1].verse
            steps.append(f"/urim-philologist {ch}.{first}-{last}")
        if row.drafts:
            steps.append(f"{ch}: review {row.drafts} draft item(s)")
        if len(steps) >= limit:
            break
    return steps[:limit]
