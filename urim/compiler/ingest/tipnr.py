"""STEPBible TIPNR: one record per individual person, place or named thing.

A record is a header line (`UniqueName=uStrong` plus category-specific columns), sub-record
lines starting with "–" (each name form with its disambiguated Strong's and references), and
`@Brief=` / `@Short=` descriptions. TAHOT tags each proper noun with a dStrong, which
identifies exactly one record; that join is what turns a word into an entity mention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from urim.canon import BOOKS_BY_STEPBIBLE

_HEADER = re.compile(r"^(?P<name>[^\t=]+@[^\t=]+)=(?P<ustrong>[GH]\d+[A-Za-z]?)$")
_SECTION = re.compile(r"^\$=+\s*(PERSON|PLACE|OTHER)")
_GOOGLE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_STEP_REF = re.compile(r"^(?:LXX\s*)?([1-3]?[A-Z][a-z]{1,3})\.(\d+)\.(\d+)[a-z]?$")


@dataclass
class TipnrName:
    significance: str  # "Named", "Greek", "Spelled", "Group", ...
    unique_name: str
    dstrong: str
    source_form: str  # Hebrew/Greek
    english: str
    refs: list[str]  # STEPBible refs in standard (KJV) numbering


@dataclass
class TipnrRecord:
    unique_name: str
    ustrong: str
    category: str  # PERSON | PLACE | OTHER
    description: str
    type: str | None
    parents: list[str] = field(default_factory=list)
    siblings: list[str] = field(default_factory=list)
    partners: list[str] = field(default_factory=list)
    offspring: list[str] = field(default_factory=list)
    tribe: str | None = None
    openbible_name: str | None = None
    google_latlon: tuple[float, float] | None = None
    names: list[TipnrName] = field(default_factory=list)
    brief: str | None = None
    short: str | None = None

    @property
    def dstrongs(self) -> list[str]:
        seen = dict.fromkeys([self.ustrong, *(n.dstrong for n in self.names)])
        return list(seen)

    @property
    def all_refs(self) -> list[str]:
        return list(dict.fromkeys(r for n in self.names for r in n.refs))


def step_ref_to_id(ref: str) -> str | None:
    """'1Ki.17.23a' -> '1KGS.17.23' (standard numbering)."""
    m = _STEP_REF.match(ref.strip())
    if not m or m[1] not in BOOKS_BY_STEPBIBLE:
        return None
    return f"{BOOKS_BY_STEPBIBLE[m[1]].code}.{m[2]}.{m[3]}"


def _split_names(cell: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,+]", cell) if "@" in p]


def _parse_header(cols: list[str], category: str, rec: TipnrRecord) -> None:
    summary = next((i for i, c in enumerate(cols) if c.startswith("#")), len(cols))
    after = [c.strip() for c in cols[summary + 1 :] if c.strip()]
    rec.type = after[0] if after else ("Place" if category == "PLACE" else None)
    if category == "PERSON":
        pad = cols + [""] * 7
        rec.parents = _split_names(pad[2])
        rec.siblings = _split_names(pad[3])
        rec.partners = _split_names(pad[4])
        rec.offspring = _split_names(pad[5])
        rec.tribe = pad[6].strip() or None
    elif category == "PLACE":
        rec.openbible_name = (cols[1].strip() or None) if len(cols) > 1 else None
        for c in cols[2:summary]:
            if m := _GOOGLE.search(c):
                rec.google_latlon = (float(m[1]), float(m[2]))
                break


def read_tipnr(path: Path) -> list[TipnrRecord]:
    records: list[TipnrRecord] = []
    category = None
    current: TipnrRecord | None = None
    with path.open(encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if m := _SECTION.match(line):
                category = m[1]
                current = None
                continue
            cols = line.split("\t")
            if category and (h := _HEADER.match(cols[0])):
                current = TipnrRecord(
                    unique_name=h["name"],
                    ustrong=h["ustrong"],
                    category=category,
                    description=cols[1].strip() if len(cols) > 1 else "",
                    type=None,
                )
                _parse_header(cols, category, current)
                records.append(current)
            elif current is None:
                continue
            elif cols[0].startswith("–") and len(cols) >= 4 and "«" in cols[2]:
                significance = cols[0].lstrip("–").strip()
                if significance == "Total":
                    continue
                dstrong, _, form = cols[2].partition("«")
                refs = next((c for c in reversed(cols) if _STEP_REF.match(c.split(";")[0])), "")
                current.names.append(
                    TipnrName(
                        significance=significance,
                        unique_name=cols[1].strip(),
                        dstrong=dstrong.strip(),
                        source_form=form.partition("=")[2].strip(),
                        english=cols[3].strip(),
                        refs=[r.strip() for r in refs.split(";") if r.strip()],
                    )
                )
            elif line.startswith("@Brief="):
                current.brief = line[len("@Brief=") :].split("\t")[0].strip() or None
            elif line.startswith("@Short="):
                current.short = line[len("@Short=") :].split("\t")[0].strip() or None
    return records


class TipnrIndex:
    def __init__(self, records: list[TipnrRecord]):
        self.records = records
        self.by_dstrong: dict[str, TipnrRecord] = {}
        self.by_name: dict[str, TipnrRecord] = {}
        for rec in records:
            for d in rec.dstrongs:
                self.by_dstrong.setdefault(d, rec)
            for n in [rec.unique_name, *(x.unique_name for x in rec.names)]:
                for variant in n.split("|"):
                    self.by_name.setdefault(variant, rec)

    def lookup(self, dstrong: str | None, name_ref: str | None) -> TipnrRecord | None:
        if dstrong and (rec := self.by_dstrong.get(dstrong)):
            return rec
        if name_ref:
            return self.by_name.get(name_ref)
        return None
