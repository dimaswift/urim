"""`urim timeline`: a chapter's events as the linker dated them, for checking a chronology.

Reads a linked core bundle, so the times are exactly what the engine will serve: anchors
resolved, `time_of_day` snapped, margins summed along the chain.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from urim import utime
from urim.bundles import sqlite_uri
from urim.runtime.engine import format_utes


@dataclass
class TimeRow:
    event_id: str
    parent_event_id: str | None
    verses: str
    start: str
    end: str
    duration_seconds: int
    margin_seconds: int  # relative to the anchor
    absolute_margin_seconds: int  # root anchor plus the whole chain
    precision_tier: str
    anchor: str


@dataclass
class CauseRow:
    causal_id: str
    causal_type: str
    elapsed_seconds: int


def span(seconds: float) -> str:
    """'2.5 h', '40 d', '2.6 y': a compact duration for tables."""
    for unit, size in (("y", utime.NOMINAL_YEAR), ("d", utime.DAY), ("h", utime.HOUR)):
        if abs(seconds) >= size:
            return f"{seconds / size:.3g} {unit}"
    return f"{seconds / utime.MINUTE:.3g} min"


def _short(verse_id: str) -> str:
    _, c, v = verse_id.split(".")
    return f"{c}:{v}"


def chapter_timeline(core_db: Path, chapter: str) -> tuple[list[TimeRow], list[CauseRow]]:
    conn = sqlite3.connect(sqlite_uri(core_db), uri=True)
    try:
        events = conn.execute(
            "SELECT event_id, parent_event_id, verse_start, verse_end, utes_start, utes_end,"
            " relative_margin_seconds, utes_margin_seconds, precision_tier, anchor_event_id,"
            " anchor_chronology_id, anchor_point, relative_offset_seconds, time_of_day"
            " FROM core_events"
            " WHERE verse_start LIKE ? ORDER BY utes_start, utes_end DESC, event_id",
            (f"{chapter}.%",),
        ).fetchall()
        ids = [e[0] for e in events]
        causes = conn.execute(
            "SELECT causal_id, causal_type, elapsed_seconds FROM core_causal_edges"
            f" WHERE effect_event_id IN ({','.join('?' * len(ids))}) ORDER BY causal_id",
            ids,
        ).fetchall()
    finally:
        conn.close()
    rows = []
    for (
        e_id,
        parent,
        v0,
        v1,
        start,
        end,
        rel,
        margin,
        tier,
        a_evt,
        a_chr,
        point,
        off,
        tod,
    ) in events:
        # The stored offset is effective: it already includes the snap to time_of_day.
        anchor = f"{a_evt or a_chr} {point.lower()}"
        if tod:
            anchor += f" → {tod}"
        if off:
            anchor += f", {span(off)} later"
        verses = _short(v0) if v0 == v1 else f"{_short(v0)}–{_short(v1)}"
        rows.append(
            TimeRow(
                e_id,
                parent,
                verses,
                format_utes(start, "DIURNAL_HOUR"),
                format_utes(end, "DIURNAL_HOUR"),
                end - start,
                rel,
                margin,
                tier,
                anchor,
            )
        )
    return rows, [CauseRow(*c) for c in causes]
