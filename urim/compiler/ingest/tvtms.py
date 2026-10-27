"""STEPBible TVTMS: versification traditions and their mapping to standard (KJV) references.

TAHOT already gives the word-level KJV <-> Hebrew map, so TVTMS is used to cross-check it
(every Hebrew renumbering TVTMS lists must appear in the TAHOT map) and to carry its
versification notes (e.g. "in some Bibles this verse starts on a different word"). The
Latin, Greek and Slavonic traditions it also describes are parsed but not yet used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from urim.canon import BOOKS_BY_CODE, BOOKS_BY_OSIS, BOOKS_BY_STEPBIBLE, Book

_REF = re.compile(r"^([1-3]?[A-Za-z]+)\.(\d+):(\d+)$")


def tvtms_ref_to_id(ref: str) -> str | None:
    """'1Ki.5:1' (or '1Sam.21:1') -> '1KGS.5.1'. None for sub-verses, ranges and titles."""
    m = _REF.match(ref.strip())
    if not m:
        return None
    book: Book | None = (
        BOOKS_BY_STEPBIBLE.get(m[1]) or BOOKS_BY_OSIS.get(m[1]) or BOOKS_BY_CODE.get(m[1].upper())
    )
    return f"{book.code}.{m[2]}.{m[3]}" if book else None


@dataclass(frozen=True)
class TvtmsRow:
    source_type: str  # "Hebrew", "Latin+Greek", "AllBibles", ...
    source_ref: str
    standard_ref: str
    action: str
    reversification_note: str
    versification_note: str

    @property
    def traditions(self) -> set[str]:
        return set(self.source_type.split("+"))


@dataclass
class Tvtms:
    rows: list[TvtmsRow] = field(default_factory=list)
    start_different: set[str] = field(default_factory=set)  # standard verse ids

    def hebrew_renumbers(self) -> dict[str, str]:
        """Hebrew verse id -> standard (KJV) verse id, for whole-verse renumberings."""
        out = {}
        for r in self.rows:
            if "Hebrew" in r.traditions and r.action.startswith("Renumber verse"):
                src, std = tvtms_ref_to_id(r.source_ref), tvtms_ref_to_id(r.standard_ref)
                if src and std:
                    out[src] = std
        return out

    def notes(self) -> dict[str, list[str]]:
        """Standard verse id -> versification notes that hold in every Bible."""
        out: dict[str, list[str]] = {}
        for r in self.rows:
            if r.source_type == "AllBibles" and r.versification_note:
                vid = tvtms_ref_to_id(r.standard_ref)
                note = r.versification_note.replace("%", "").strip()
                if vid and note:
                    out.setdefault(vid, []).append(note)
        return out


def read_tvtms(path: Path) -> Tvtms:
    data = Tvtms()
    section = None
    with path.open(encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if line.startswith("#DataStart("):
                section = line[len("#DataStart(") :].split(")")[0]
                continue
            if line.startswith("#DataEnd("):
                section = None
                continue
            cols = line.split("\t")
            if cols[0] == "StartDifferent":
                data.start_different |= {
                    vid for ref in cols[1].split(";") if (vid := tvtms_ref_to_id(ref))
                }
            elif section == "Expanded" and len(cols) >= 7 and _REF.match(cols[1].strip()):
                data.rows.append(
                    TvtmsRow(
                        source_type=cols[0].strip(),
                        source_ref=cols[1].strip(),
                        standard_ref=cols[2].strip(),
                        action=cols[3].strip(),
                        reversification_note=cols[5].strip(),
                        versification_note=cols[6].strip(),
                    )
                )
    return data
