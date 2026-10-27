"""`urim travel`: how long a journey takes, so a session picks the route and mode, not the sums.

Distance is great-circle between the places' coordinates (corpus override, else the registry),
stretched by a detour factor for roads that follow valleys and passes. Speeds are rough figures
for the ancient Near East: each mode has a moving speed and the hours a day it can be kept up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from urim.ir.load import inputs_root, load_registry
from urim.workbench.merge import CorpusFiles

DETOUR = 1.25


@dataclass(frozen=True)
class Mode:
    kmh: float
    hours_per_day: float
    note: str


MODES: dict[str, Mode] = {
    "walk": Mode(4.0, 7, "on foot, about 28 km a day"),
    "hurry": Mode(5.0, 10, "flight or an urgent errand on foot, about 50 km a day"),
    "run": Mode(10.0, 3, "a trained runner; a few hours at most"),
    "donkey": Mode(4.0, 8, "a rider or laden donkey, about 32 km a day"),
    "army": Mode(3.0, 6, "an army with baggage, about 18 km a day"),
    "chariot": Mode(12.0, 5, "a chariot on a road; horses tire after a few hours"),
}


class TravelError(ValueError):
    pass


@dataclass
class Place:
    entity_id: str
    name: str
    lat: float
    lon: float


@dataclass
class Leg:
    mode: str
    straight_km: float
    route_km: float
    moving_hours: float
    elapsed_hours: float

    @property
    def ir_duration(self) -> dict:
        """The elapsed time as an IR duration, rounded to half units."""
        if self.elapsed_hours < 24:
            return {"value": max(round(self.elapsed_hours * 2) / 2, 0.5), "unit": "hours"}
        return {"value": round(self.elapsed_hours / 24 * 2) / 2, "unit": "days"}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def find_place(query: str, corpus: Path, inputs: Path) -> Place:
    """An entity id (loc.carmel), a TIPNR id or an English name."""
    registry = load_registry(inputs_root(corpus, inputs))
    seeds = [s for s in (registry.entities if registry else []) if s.geo]
    by_tipnr = {s.tipnr_id: s for s in seeds}
    files = CorpusFiles(corpus)
    for ch in files.chapters():
        for e in files.core(ch).entities:
            if e.entity_id != query:
                continue
            if e.geo_lat is not None and e.geo_lon is not None:
                return Place(e.entity_id, e.entity_id, e.geo_lat, e.geo_lon)
            if seed := by_tipnr.get(e.tipnr_id):
                return Place(e.entity_id, seed.names[0], seed.geo.lat, seed.geo.lon)
            raise TravelError(f"{query} has no coordinates")
    q = query.casefold()
    hits = [s for s in seeds if query in (s.proposed_entity_id, s.tipnr_id)]
    hits = hits or [s for s in seeds if q in (n.casefold() for n in s.names)]
    hits = hits or [s for s in seeds if any(q in n.casefold().split() for n in s.names)]
    if not hits:
        raise TravelError(f"no place with coordinates matches {query!r}")
    if len(hits) > 1:
        options = ", ".join(f"{s.proposed_entity_id} ({s.tipnr_id})" for s in hits)
        raise TravelError(f"{query!r} is ambiguous: {options}")
    s = hits[0]
    return Place(s.proposed_entity_id or s.tipnr_id, s.names[0], s.geo.lat, s.geo.lon)


def journey(places: list[Place], mode: str, detour: float = DETOUR) -> Leg:
    if mode not in MODES:
        raise TravelError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
    straight = sum(
        distance_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(places, places[1:], strict=False)
    )
    m = MODES[mode]
    route = straight * detour
    moving = route / m.kmh
    # Full travel days, each followed by a night's rest, then what is left of the road.
    nights = max(math.ceil(moving / m.hours_per_day) - 1, 0)
    elapsed = nights * 24 + (moving - nights * m.hours_per_day)
    return Leg(mode, straight, route, moving, elapsed)
