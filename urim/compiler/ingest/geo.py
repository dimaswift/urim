"""OpenBible.info geocoding for TIPNR places.

OpenBible records list every verse where a place occurs (`extra.osises`). A TIPNR place is
matched to the OpenBible record that shares the most of its references, which is more robust
than names (TIPNR "Carmel_Mount" is OpenBible "Mount Carmel"). Coordinates come from the
record's best-voted identification; its vote score becomes the confidence.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from urim.canon import BOOKS_BY_CODE
from urim.compiler.ingest.tipnr import TipnrRecord, step_ref_to_id
from urim.ir.models import GeoPoint


@dataclass(frozen=True)
class OpenBiblePlace:
    id: str
    name: str
    lat: float
    lon: float
    confidence: float  # 0-1, from community votes on the best identification
    osises: frozenset[str]


def _to_osis(verse_id: str) -> str:
    code, ch, v = verse_id.split(".")
    return f"{BOOKS_BY_CODE[code].osis}.{ch}.{v}"


class OpenBibleIndex:
    def __init__(self, ancient_jsonl: Path):
        self.places: dict[str, OpenBiblePlace] = {}
        self.by_osis: dict[str, list[str]] = defaultdict(list)
        with ancient_jsonl.open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                idents = d.get("identifications") or []
                best = max(
                    idents, key=lambda i: i.get("score", {}).get("time_total", 0), default=None
                )
                lonlat = next(
                    (
                        r.get("lonlat")
                        for r in (best or {}).get("resolutions", [])
                        if r.get("lonlat")
                    ),
                    None,
                )
                if not lonlat:
                    continue
                lon, lat = (float(x) for x in lonlat.split(","))
                osises = frozenset(json.loads(d.get("extra") or "{}").get("osises", []))
                place = OpenBiblePlace(
                    id=d["id"],
                    name=d["friendly_id"],
                    lat=lat,
                    lon=lon,
                    # Votes can net out below zero: a disputed identification, confidence 0.
                    confidence=round(
                        min(max(best.get("score", {}).get("time_total", 0) / 1000, 0.0), 1.0), 3
                    ),
                    osises=osises,
                )
                self.places[place.id] = place
                for o in osises:
                    self.by_osis[o].append(place.id)

    def match(self, rec: TipnrRecord) -> GeoPoint | None:
        refs = {_to_osis(vid) for r in rec.all_refs if (vid := step_ref_to_id(r))}
        overlap = Counter(pid for o in refs for pid in self.by_osis.get(o, ()))
        if not overlap:
            return None
        base = rec.unique_name.split("@")[0].split("|")[-1].replace("_", " ").lower()
        words = set(base.replace("-", " ").split())

        def rank(pid: str) -> tuple[int, int, str]:
            name = self.places[pid].name.lower()
            return (overlap[pid], len(words & set(name.replace("-", " ").split())), pid)

        pid = max(overlap, key=rank)
        place = self.places[pid]
        # Require the match to explain at least half the place's refs, or a shared name word.
        if overlap[pid] * 2 < len(refs) and not rank(pid)[1]:
            return None
        return GeoPoint(
            lat=place.lat,
            lon=place.lon,
            source="openbible",
            source_id=place.id,
            source_name=place.name,
            confidence=place.confidence,
        )
