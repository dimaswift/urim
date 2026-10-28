"""The review ledger: who produced each item, and where your review of it stands.

One file per chapter under `corpus/ledger/`. Item keys are `kind:id` (see fragments.key):

    event, causal                      chronology
    entity, system, component, closure,
    instance, edge, event_links        ontology (event_links = an event's participants + place)
    verse.en                           philology
    event.ru, entity.ru, verse.ru, …   localization: one language's text of an item

A translation remembers the English it was made from (`source`, a hash): when the English
changes, the translation is stale, and its approval no longer locks it. Interface messages and
bundle labels are not chapter items; their provenance is in `corpus/ledger/lang/<lang>.json`.

Approved items are locked: merges may not change or drop them until they are reopened.
Decisions are yours, except in an autonomous run (`urim run`), where the critic decides and
signs its decisions; you can reopen any of them.
"""

from __future__ import annotations

import fcntl
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from urim.workbench.fragments import Provenance

Status = Literal["draft", "changes_requested", "approved"]
USER = "user"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ReviewEvent(BaseModel):
    status: Status
    at: str
    note: str | None = None
    by: str = USER  # or the critic of an autonomous run: "urim-critic@2 · claude-opus-5-5"


class LedgerItem(BaseModel):
    status: Status = "draft"
    produced_by: Provenance
    produced_at: str
    agent_notes: list[str] = []
    history: list[ReviewEvent] = []
    source: str | None = None  # translations: hash of the English they were made from

    @property
    def last_note(self) -> str | None:
        return next((h.note for h in reversed(self.history) if h.note), None)

    def review_note(self) -> str | None:
        """Your latest note with where it stands, so an old request does not read as open."""
        event = next((h for h in reversed(self.history) if h.note), None)
        if event is None:
            return None
        who = "" if event.by == USER else f" by {event.by}"
        if event.status != "changes_requested":
            return f"[{event.status}{who} {_minute(event.at)}] {event.note}"
        if self.status == "changes_requested":
            return f"[open request{who}] {event.note}"
        steps = [f"requested{who} {_minute(event.at)}"]
        if self.produced_at >= event.at:
            steps.append(f"revised {_minute(self.produced_at)}")
        if self.status == "approved":
            steps.append("approved")
        return f"[{', '.join(steps)}] {event.note}"


def _minute(at: str) -> str:
    return at[:16].replace("T", " ")


class ChapterNote(BaseModel):
    note: str
    produced_by: Provenance
    at: str


class ChapterLedger(BaseModel):
    chapter_ref: str
    items: dict[str, LedgerItem] = {}
    notes: list[ChapterNote] = []

    def status(self, item_key: str) -> Status | None:
        item = self.items.get(item_key)
        return item.status if item else None

    def locked(self, item_key: str) -> bool:
        return self.status(item_key) == "approved"


def write_atomic(path: Path, text: str) -> None:
    """Replace a file whole: a run plans from these files while its sessions merge into them."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def ledger_path(corpus: Path, chapter_ref: str) -> Path:
    return Path(corpus) / "ledger" / f"{chapter_ref}.json"


def load_ledger(corpus: Path, chapter_ref: str) -> ChapterLedger:
    path = ledger_path(corpus, chapter_ref)
    if path.exists():
        return ChapterLedger.model_validate_json(path.read_bytes())
    return ChapterLedger(chapter_ref=chapter_ref)


def save_ledger(corpus: Path, ledger: ChapterLedger) -> None:
    path = ledger_path(corpus, ledger.chapter_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger.items = dict(sorted(ledger.items.items()))
    write_atomic(path, ledger.model_dump_json(indent=1, exclude_defaults=False) + "\n")


def all_ledgers(corpus: Path) -> list[ChapterLedger]:
    return [
        ChapterLedger.model_validate_json(p.read_bytes())
        for p in sorted((Path(corpus) / "ledger").glob("*.json"))
    ]


class Record(BaseModel):
    """Who translated one interface message or bundle label, and from which English."""

    produced_by: Provenance
    produced_at: str
    source: str


class LanguageRecords(BaseModel):
    """Provenance of a language's interface messages (`ui:<key>`) and bundle labels
    (`book:GEN`, `vocab:<kind>.<code>`, `anchor:<id>`)."""

    lang: str
    items: dict[str, Record] = {}
    notes: list[ChapterNote] = []


def records_path(corpus: Path, lang: str) -> Path:
    return Path(corpus) / "ledger" / "lang" / f"{lang}.json"


def load_records(corpus: Path, lang: str) -> LanguageRecords:
    path = records_path(corpus, lang)
    if path.exists():
        return LanguageRecords.model_validate_json(path.read_bytes())
    return LanguageRecords(lang=lang)


def save_records(corpus: Path, records: LanguageRecords) -> None:
    path = records_path(corpus, records.lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    records.items = dict(sorted(records.items.items()))
    write_atomic(path, records.model_dump_json(indent=1) + "\n")


class LedgerError(ValueError):
    pass


@contextmanager
def corpus_lock(corpus: Path) -> Iterator[None]:
    """One writer at a time: parallel sessions merge, and you review, into the same corpus."""
    path = Path(corpus) / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def set_status(
    corpus: Path, keys: list[str], status: Status, note: str | None = None, by: str = USER
) -> list[tuple[str, str]]:
    """Record a review decision for each key; returns (chapter, key) pairs that changed."""
    if status == "changes_requested" and not note:
        raise LedgerError("say what should change: a note is required")
    with corpus_lock(corpus):
        return _set_status(corpus, keys, status, note, by)


def _set_status(
    corpus: Path, keys: list[str], status: Status, note: str | None, by: str
) -> list[tuple[str, str]]:
    ledgers = {led.chapter_ref: led for led in all_ledgers(corpus)}
    changed = []
    for item_key in keys:
        owner = next((led for led in ledgers.values() if item_key in led.items), None)
        if owner is None:
            raise LedgerError(f"no ledger item {item_key!r}")
        item = owner.items[item_key]
        if item.status != status or note:
            item.status = status
            item.history.append(ReviewEvent(status=status, at=now(), note=note, by=by))
            changed.append((owner.chapter_ref, item_key))
    for chapter in {c for c, _ in changed}:
        save_ledger(corpus, ledgers[chapter])
    return changed
