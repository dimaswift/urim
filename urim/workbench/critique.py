"""The critic's verdict on one layer of a chapter, and what an autonomous run does with it.

In a session you drive, the critic reports and you decide. In `urim run` nobody is there to
decide, so the critic writes its findings as JSON (`urim schema critic`) and the run applies
them: blocker and should-fix findings send their items back to the agent that owns them,
every other draft the critic reviewed is approved in its name, and on the last round what is
still disputed stays a draft, escalated to you with the critic's note.

A language is a layer too: `ru` holds a chapter's Russian texts and verses (`event.ru:…`,
`verse.ru:…`), reviewed against the English and, for verses, the Hebrew.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from urim.ir.models import ChapterRef, IRModel
from urim.workbench.fragments import Provenance
from urim.workbench.ledger import (
    ChapterLedger,
    ChapterNote,
    ReviewEvent,
    corpus_lock,
    load_ledger,
    now,
    save_ledger,
)

Severity = Literal["blocker", "should_fix", "consider"]

LAYER_KINDS: dict[str, set[str]] = {
    "chronology": {"event", "causal"},
    "ontology": {"entity", "system", "component", "closure", "instance", "edge", "event_links"},
    "philology": {"verse.en"},
}


def is_language(layer: str) -> bool:
    """A translation layer is named by its language code: ru, uk, es."""
    return layer not in LAYER_KINDS and layer != "en" and bool(re.fullmatch(r"[a-z]{2,3}", layer))


def layer_of(item_key: str) -> str | None:
    kind = item_key.split(":", 1)[0]
    _, _, lang = kind.partition(".")
    if lang and lang != "en":
        return lang
    return next((layer for layer, kinds in LAYER_KINDS.items() if kind in kinds), None)


def layer_items(ledger: ChapterLedger, layer: str, status: str | None = None) -> list[str]:
    return [
        k
        for k, item in ledger.items.items()
        if layer_of(k) == layer and (status is None or item.status == status)
    ]


class Finding(IRModel):
    item: str = Field(
        description="Ledger key of the item, as `urim ledger` lists it: event:evt.…, "
        "causal:caus.…, entity:person.…, event_links:evt.…, verse.en:GEN.37.4, and for a "
        "translation event.ru:evt.…, verse.ru:GEN.37.4"
    )
    severity: Severity = Field(
        description="blocker: contradicts the text, misidentifies someone, a date the text "
        "rules out. should_fix: unsupported, missing or misleading, but not contradicted. "
        "consider: a better choice exists. In an autonomous run blocker and should_fix send "
        "the item back; consider is passed on as advice and the item is approved"
    )
    problem: str = Field(description="What is wrong, in one or two sentences")
    evidence: str = Field(
        description='The verse that proves it, with a short quote: GEN.37.4: "they hated him"'
    )
    change_request: str = Field(
        description="A note to the agent that owns the item: what to change, in one or two "
        "sentences. It appears at the top of the agent's next packet"
    )


class CriticReport(IRModel):
    chapter_ref: ChapterRef
    layer: str = Field(
        description="The layer reviewed: chronology, ontology, philology, or a language code "
        "(ru) for that language's translations of the chapter"
    )
    produced_by: Provenance
    reviewed: list[str] = Field(
        description="Ledger key of every item you checked. In an autonomous run each one "
        "without a blocker or should_fix finding is approved in your name; drafts you leave "
        "out stay drafts"
    )
    findings: list[Finding] = []
    sound: str = Field(
        default="",
        description="What holds up well, in a few lines, so the reader knows what was checked",
    )


class CritiqueError(ValueError):
    pass


def load_report(path: Path) -> CriticReport:
    try:
        return CriticReport.model_validate_json(Path(path).read_bytes())
    except (OSError, ValidationError) as e:
        raise CritiqueError(f"{path}: {e}") from e


def report_path(work: Path, chapter: str, layer: str) -> Path:
    return Path(work) / "critic" / f"{chapter}.{layer}.json"


def check_report(report: CriticReport, corpus: Path) -> list[str]:
    """Problems that would make the report apply to the wrong things."""
    led = load_ledger(corpus, report.chapter_ref)
    errors = []
    if report.layer not in LAYER_KINDS and not is_language(report.layer):
        errors.append(f"layer {report.layer!r}: expected {', '.join(LAYER_KINDS)} or a language")
    for k in report.reviewed:
        if k not in led.items:
            errors.append(f"reviewed: no ledger item {k!r} in {report.chapter_ref}")
        elif layer_of(k) != report.layer:
            errors.append(f"reviewed: {k} is not a {report.layer} item")
    for f in report.findings:
        if f.severity != "consider" and f.item not in led.items:
            errors.append(f"finding on {f.item!r}: no such ledger item in {report.chapter_ref}")
    return errors


@dataclass
class Verdict:
    approved: list[str] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)
    escalated: list[str] = field(default_factory=list)
    unreviewed: list[str] = field(default_factory=list)
    noted: int = 0


def critic_name(p: Provenance) -> str:
    return f"{p.skill} · {p.model}"


def _lines(findings: list[Finding]) -> str:
    return " ".join(f"[{f.severity}] {f.change_request} ({f.evidence})" for f in findings)


def apply_critique(corpus: Path, report: CriticReport, *, final: bool) -> Verdict:
    """Decide every draft of the layer the critic reviewed, in the critic's name."""
    by, stamp, verdict = critic_name(report.produced_by), now(), Verdict()
    with corpus_lock(corpus):
        led = load_ledger(corpus, report.chapter_ref)
        drafts = set(layer_items(led, report.layer, "draft"))
        blocking: dict[str, list[Finding]] = defaultdict(list)
        advice: dict[str, list[Finding]] = defaultdict(list)
        elsewhere = []
        for f in report.findings:
            if f.item not in drafts:
                elsewhere.append(f)
            elif f.severity == "consider":
                advice[f.item].append(f)
            else:
                blocking[f.item].append(f)
        reviewed = set(report.reviewed) | set(blocking) | set(advice)
        for k in sorted(drafts):
            item = led.items[k]
            if k not in reviewed:
                verdict.unreviewed.append(k)
                continue
            if k in blocking and final:
                note = f"Escalated: still disputed after the last round. {_lines(blocking[k])}"
                item.history.append(ReviewEvent(status="draft", at=stamp, note=note, by=by))
                verdict.escalated.append(k)
            elif k in blocking:
                item.status = "changes_requested"
                item.history.append(
                    ReviewEvent(
                        status="changes_requested", at=stamp, note=_lines(blocking[k]), by=by
                    )
                )
                verdict.requested.append(k)
            else:
                item.status = "approved"
                note = _lines(advice[k]) if k in advice else None
                item.history.append(ReviewEvent(status="approved", at=stamp, note=note, by=by))
                verdict.approved.append(k)
        # Findings on settled items or on another layer are for you, not for this round.
        led.notes += [
            ChapterNote(
                note=f"[{by}, {f.severity}] {f.item}: {f.problem} ({f.evidence})",
                produced_by=report.produced_by,
                at=stamp,
            )
            for f in elsewhere
        ]
        verdict.noted = len(elsewhere)
        save_ledger(corpus, led)
    return verdict


def back_to_draft(corpus: Path, chapter: str, keys: list[str], *, by: str, note: str) -> None:
    """Return requested items to draft, with a note on why, for the critic to look again."""
    with corpus_lock(corpus):
        led = load_ledger(corpus, chapter)
        for k in keys:
            if (item := led.items.get(k)) is not None:
                item.status = "draft"
                item.history.append(ReviewEvent(status="draft", at=now(), note=note, by=by))
        save_ledger(corpus, led)
