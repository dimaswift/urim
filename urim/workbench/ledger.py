"""The review ledger: who produced each item, and where your review of it stands.

One file per chapter under `corpus/ledger/`. Item keys are `kind:id` (see fragments.key):

    event, causal                      chronology
    entity, system, component, closure,
    instance, edge, event_links        ontology (event_links = an event's participants + place)
    verse.en                           philology

Approved items are locked: merges may not change or drop them until they are reopened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from urim.workbench.fragments import Provenance

Status = Literal["draft", "changes_requested", "approved"]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ReviewEvent(BaseModel):
    status: Status
    at: str
    note: str | None = None


class LedgerItem(BaseModel):
    status: Status = "draft"
    produced_by: Provenance
    produced_at: str
    agent_notes: list[str] = []
    history: list[ReviewEvent] = []

    @property
    def last_note(self) -> str | None:
        return next((h.note for h in reversed(self.history) if h.note), None)

    def review_note(self) -> str | None:
        """Your latest note with where it stands, so an old request does not read as open."""
        event = next((h for h in reversed(self.history) if h.note), None)
        if event is None:
            return None
        if event.status != "changes_requested":
            return f"[{event.status} {_minute(event.at)}] {event.note}"
        if self.status == "changes_requested":
            return f"[open request] {event.note}"
        steps = [f"requested {_minute(event.at)}"]
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
    path.write_text(ledger.model_dump_json(indent=1, exclude_defaults=False) + "\n")


def all_ledgers(corpus: Path) -> list[ChapterLedger]:
    return [
        ChapterLedger.model_validate_json(p.read_bytes())
        for p in sorted((Path(corpus) / "ledger").glob("*.json"))
    ]


class LedgerError(ValueError):
    pass


def set_status(
    corpus: Path, keys: list[str], status: Status, note: str | None = None
) -> list[tuple[str, str]]:
    """Record a review decision for each key; returns (chapter, key) pairs that changed."""
    if status == "changes_requested" and not note:
        raise LedgerError("say what should change: a note is required")
    ledgers = {led.chapter_ref: led for led in all_ledgers(corpus)}
    changed = []
    for item_key in keys:
        owner = next((led for led in ledgers.values() if item_key in led.items), None)
        if owner is None:
            raise LedgerError(f"no ledger item {item_key!r}")
        item = owner.items[item_key]
        if item.status != status or note:
            item.status = status
            item.history.append(ReviewEvent(status=status, at=now(), note=note))
            changed.append((owner.chapter_ref, item_key))
    for chapter in {c for c, _ in changed}:
        save_ledger(corpus, ledgers[chapter])
    return changed
