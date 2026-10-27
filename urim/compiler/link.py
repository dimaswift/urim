"""Linker: validated IR -> SQLite bundles.

This is the deterministic back half of the compiler and the code half of the Sanhedrin Critic.
It resolves references, materializes UTES timestamps from anchor chains, derives every computed
column (elapsed times, component intervals, verse primary events), and refuses to write a
bundle while any error remains. The same IR always produces the same core file, byte for byte.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import sqlite3
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from urim import __version__, utime
from urim.bundles import core_path, lang_bundle_path, sqlite_uri
from urim.canon import BOOKS, BOOKS_BY_CODE, TRANSLATION_SCHEMES, parse_ref
from urim.embeddings import Vectorizer, load_sqlite_vec
from urim.ir.load import (
    CoreCorpus,
    available_langs,
    inputs_root,
    load_core_corpus,
    load_i18n,
    load_sources,
)
from urim.ir.models import ChronologyAnchorIR, ComponentIR, EventIR

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
SCHEMA_VERSION = "1.1"

Table = tuple[tuple[str, ...], list[tuple[Any, ...]]]


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


class LinkError(Exception):
    def __init__(self, report: Report):
        self.report = report
        lines = "\n".join(f"  - {e}" for e in report.errors)
        super().__init__(f"{len(report.errors)} link error(s):\n{lines}")


@dataclass(frozen=True)
class ResolvedTime:
    start: int
    end: int
    margin: int  # absolute: root anchor margin + every relative margin on the chain
    relative_margin: int
    offset: int  # start - anchor point


# =============================================================================================
# Core
# =============================================================================================


def _unique(items, key: str, kind: str, report: Report) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items:
        k = getattr(item, key)
        if k in out:
            report.error(f"duplicate {kind} id {k}")
        else:
            out[k] = item
    return out


def _resolve_times(
    events: dict[str, EventIR], anchors: dict[str, ChronologyAnchorIR], report: Report
) -> dict[str, ResolvedTime]:
    children: dict[str, list[str]] = defaultdict(list)
    roots = []
    for eid, ev in events.items():
        if ev.time.anchor.startswith("evt."):
            children[ev.time.anchor].append(eid)
        else:
            roots.append(eid)

    resolved: dict[str, ResolvedTime] = {}
    queue = deque(sorted(roots))
    while queue:
        eid = queue.popleft()
        t = events[eid].time
        if t.anchor.startswith("anchor."):
            root = anchors[t.anchor]
            base, base_margin = root.date.utes, root.margin.seconds
        else:
            parent = resolved[t.anchor]
            base = parent.start if t.anchor_point == "START" else parent.end
            base_margin = parent.margin
        start = base + (t.offset.seconds if t.offset else 0)
        if t.time_of_day:
            start = utime.next_time_of_day(start, t.time_of_day)
        rel = t.margin.seconds
        resolved[eid] = ResolvedTime(
            start, start + t.duration.seconds, base_margin + rel, rel, start - base
        )
        queue.extend(sorted(children[eid]))

    if unresolved := sorted(set(events) - set(resolved)):
        report.error(f"anchor cycle among events: {', '.join(unresolved)}")
    return resolved


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    for start in sorted(graph):
        if color[start] != WHITE:
            continue
        stack = [(start, iter(graph[start]))]
        path = [start]
        color[start] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                path.pop()
            elif color[nxt] == GREY:
                return path[path.index(nxt) :] + [nxt]
            elif color[nxt] == WHITE:
                color[nxt] = GREY
                stack.append((nxt, iter(graph.get(nxt, []))))
                path.append(nxt)
    return None


def build_core(corpus: CoreCorpus, scheme: str, report: Report) -> dict[str, Table]:
    """Validate the corpus and produce every core table. Returns {} if any error was reported."""
    # --- verses -----------------------------------------------------------------------------
    verses: dict[str, tuple[Any, Any, str]] = {}
    ordinal: dict[str, int] = {}
    for book in corpus.sources:
        if book.book_code not in BOOKS_BY_CODE:
            report.error(f"source/{book.book_code}: unknown book code")
            continue
        for v in book.verses:
            _, ref = parse_ref(v.verse_id)
            if ref.book.code != book.book_code:
                report.error(f"source/{book.book_code}: verse {v.verse_id} belongs to another book")
            elif v.verse_id in verses:
                report.error(f"duplicate verse {v.verse_id}")
            if [t.pos for t in v.tokens] != list(range(1, len(v.tokens) + 1)):
                report.error(f"{v.verse_id}: token positions must run 1..{len(v.tokens)}")
            for gloss_lang, glosses in v.glosses.items():
                if len(glosses) != len(v.tokens):
                    report.error(
                        f"{v.verse_id}: {len(glosses)} {gloss_lang} glosses for "
                        f"{len(v.tokens)} tokens"
                    )
            verses[v.verse_id] = (v, ref, book.source_language)
            ordinal[v.verse_id] = ref.ordinal
    verse_map = [row for book in corpus.sources for row in book.verse_map]
    for row in verse_map:
        if row.verse_id not in verses:
            report.error(f"verse_map {row.scheme}:{row.scheme_ref}: unknown verse {row.verse_id}")

    # --- merge chapter documents ------------------------------------------------------------
    chs = corpus.chapters
    entities = _unique((x for c in chs for x in c.entities), "entity_id", "entity", report)
    systems = _unique((x for c in chs for x in c.systems), "system_id", "system", report)
    events = _unique((x for c in chs for x in c.events), "event_id", "event", report)
    causal = _unique((x for c in chs for x in c.causal_edges), "causal_id", "causal edge", report)
    components: dict[str, ComponentIR] = _unique(
        (x for c in chs for x in c.components), "component_id", "component", report
    )
    instances = _unique(
        (x for c in chs for x in c.system_instances), "instance_id", "system instance", report
    )
    edges = _unique((x for c in chs for x in c.edges), "edge_id", "edge", report)

    # Registry: TIPNR identity, first mentions and coordinates. Agents never write coordinates;
    # explicit IR geo is an override.
    seeds = {s.tipnr_id: s for s in corpus.registry.entities} if corpus.registry else {}
    tipnr_owner: dict[str, str] = {}
    for e in entities.values():
        if e.tipnr_id is None:
            continue
        if other := tipnr_owner.get(e.tipnr_id):
            report.error(f"{e.entity_id}: tipnr_id {e.tipnr_id} already used by {other}")
        tipnr_owner[e.tipnr_id] = e.entity_id
        seed = seeds.get(e.tipnr_id)
        if corpus.registry and seed is None:
            report.warn(f"{e.entity_id}: tipnr_id {e.tipnr_id} is not in the registry")
        elif seed and e.first_mention_verse in ordinal:
            seen = [m.verse_id for m in seed.mentions if m.verse_id in ordinal]
            earliest = min(seen, key=ordinal.__getitem__, default=None)
            if earliest and ordinal[earliest] < ordinal[e.first_mention_verse]:
                report.warn(
                    f"{e.entity_id}: mentioned at {earliest}, before its "
                    f"first_mention_verse {e.first_mention_verse}"
                )

    def geo_of(e) -> tuple[float | None, float | None, float | None, str | None, float | None]:
        if e.geo_lat is not None and e.geo_lon is not None:
            return e.geo_lat, e.geo_lon, e.geo_elevation_m, "ir", None
        point = seeds[e.tipnr_id].geo if e.tipnr_id in seeds else None
        if point is None:
            return None, None, None, None, None
        source = f"{point.source}:{point.source_name}" if point.source_name else point.source
        return point.lat, point.lon, None, source, point.confidence

    if scheme not in corpus.chronology.schemes:
        report.error(f"unknown chronology scheme {scheme}")
        return {}
    anchors = {a.anchor_id: a for a in corpus.chronology.schemes[scheme]}

    # --- reference checks -------------------------------------------------------------------
    def need(kind: str, known, value: str | None, where: str) -> None:
        if value is not None and value not in known:
            report.error(f"{where}: unknown {kind} {value}")

    def verse_range(start: str, end: str, where: str) -> None:
        need("verse", verses, start, where)
        need("verse", verses, end, where)
        if start in ordinal and end in ordinal and ordinal[start] > ordinal[end]:
            report.error(f"{where}: verse range {start}..{end} is reversed")

    def within(verse: str, event_id: str, where: str) -> None:
        ev = events.get(event_id)
        if not (ev and verse in ordinal and ev.verse_start in ordinal and ev.verse_end in ordinal):
            return
        if not ordinal[ev.verse_start] <= ordinal[verse] <= ordinal[ev.verse_end]:
            report.warn(f"{where}: verse {verse} lies outside event {event_id}")

    for e in entities.values():
        need("verse", verses, e.first_mention_verse, e.entity_id)
    for ev in events.values():
        verse_range(ev.verse_start, ev.verse_end, ev.event_id)
        need("entity", entities, ev.location_entity_id, ev.event_id)
        need("event", events, ev.parent_event_id, ev.event_id)
        if ev.time.anchor.startswith("evt."):
            need("event", events, ev.time.anchor, f"{ev.event_id} time.anchor")
        else:
            need(
                f"{scheme} chronology anchor", anchors, ev.time.anchor, f"{ev.event_id} time.anchor"
            )
        seen = set()
        for p in ev.participants:
            need("entity", entities, p.entity_id, f"{ev.event_id} participant")
            if p.entity_id in seen:
                report.error(f"{ev.event_id}: participant {p.entity_id} listed twice")
            seen.add(p.entity_id)
    for c in causal.values():
        need("event", events, c.cause_event_id, c.causal_id)
        need("event", events, c.effect_event_id, c.causal_id)
        if c.cause_event_id == c.effect_event_id:
            report.error(f"{c.causal_id}: an event cannot cause itself")
    for comp in components.values():
        need("entity", entities, comp.entity_id, comp.component_id)
        need("entity", entities, comp.target_entity_id, comp.component_id)
        need("component", components, comp.supersedes_component_id, comp.component_id)
        need("verse", verses, comp.acquired_at_verse, comp.component_id)
        need("verse", verses, comp.expired_at_verse, comp.component_id)
        need("event", events, comp.acquired_in_event, comp.component_id)
        need("event", events, comp.expired_in_event, comp.component_id)
        within(comp.acquired_at_verse, comp.acquired_in_event, comp.component_id)
        if comp.expired_at_verse and comp.expired_in_event:
            within(comp.expired_at_verse, comp.expired_in_event, comp.component_id)
    for closure in (x for c in chs for x in c.component_closures):
        comp = components.get(closure.component_id)
        if comp is None:
            report.error(f"closure: unknown component {closure.component_id}")
        elif comp.expired_at_verse is not None:
            report.error(f"closure: component {closure.component_id} is already closed")
        else:
            need("verse", verses, closure.expired_at_verse, f"closure {closure.component_id}")
            need("event", events, closure.expired_in_event, f"closure {closure.component_id}")
            components[closure.component_id] = comp.model_copy(
                update={
                    "expired_at_verse": closure.expired_at_verse,
                    "expired_in_event": closure.expired_in_event,
                }
            )
    for inst in instances.values():
        need("system", systems, inst.system_id, inst.instance_id)
        need("event", events, inst.event_id, inst.instance_id)
        verse_range(inst.verse_start, inst.verse_end, inst.instance_id)
        for eid in [
            inst.initiator_entity_id,
            *inst.target_entity_ids,
            *inst.artifact_entity_ids,
            inst.location_entity_id,
        ]:
            need("entity", entities, eid, inst.instance_id)
        within(inst.verse_start, inst.event_id, inst.instance_id)
        within(inst.verse_end, inst.event_id, inst.instance_id)
    for edge in edges.values():
        need("entity", entities, edge.source_entity_id, edge.edge_id)
        need("entity", entities, edge.target_entity_id, edge.edge_id)
        need("verse", verses, edge.verse_id, edge.edge_id)
        need("event", events, edge.event_id, edge.edge_id)
        within(edge.verse_id, edge.event_id, edge.edge_id)
    if report.errors:
        return {}

    # --- time -------------------------------------------------------------------------------
    times = _resolve_times(events, anchors, report)
    if report.errors:
        return {}
    for ev in events.values():
        if ev.parent_event_id:
            t, p = times[ev.event_id], times[ev.parent_event_id]
            if t.start < p.start or t.end > p.end:
                report.warn(f"{ev.event_id}: time span leaves parent {ev.parent_event_id}")

    causal_graph: dict[str, list[str]] = defaultdict(list)
    for c in causal.values():
        cause, effect = times[c.cause_event_id], times[c.effect_event_id]
        if effect.start < cause.start:
            report.error(f"{c.causal_id}: effect starts before its cause")
        causal_graph[c.cause_event_id].append(c.effect_event_id)
    if cycle := _find_cycle(causal_graph):
        report.error(f"causal cycle: {' -> '.join(cycle)}")

    by_slot: dict[tuple[str, str], list[ComponentIR]] = defaultdict(list)
    for comp in components.values():
        by_slot[(comp.entity_id, comp.component_key)].append(comp)
        if comp.expired_at_verse:
            if ordinal[comp.expired_at_verse] < ordinal[comp.acquired_at_verse]:
                report.error(f"{comp.component_id}: expires before it is acquired")
            elif times[comp.expired_in_event].start < times[comp.acquired_in_event].start:
                report.error(f"{comp.component_id}: expiry event precedes acquisition event")
    for (entity_id, key), comps in by_slot.items():
        comps.sort(key=lambda c: ordinal[c.acquired_at_verse])
        for a, b in zip(comps, comps[1:], strict=False):
            if (
                a.expired_at_verse is None
                or ordinal[a.expired_at_verse] > ordinal[b.acquired_at_verse]
            ):
                report.error(f"{entity_id}.{key}: {a.component_id} overlaps {b.component_id}")
    if report.errors:
        return {}

    # --- derived columns --------------------------------------------------------------------
    sorted_verses = sorted(verses, key=ordinal.__getitem__)
    sorted_ordinals = [ordinal[v] for v in sorted_verses]
    primary: dict[str, tuple[int, int, str]] = {}  # verse -> (span, start, event_id)
    for ev in events.values():
        lo, hi = ordinal[ev.verse_start], ordinal[ev.verse_end]
        candidate = (hi - lo, times[ev.event_id].start, ev.event_id)
        for i in range(
            bisect.bisect_left(sorted_ordinals, lo), bisect.bisect_right(sorted_ordinals, hi)
        ):
            vid = sorted_verses[i]
            if vid not in primary or candidate < primary[vid]:
                primary[vid] = candidate

    def location_of(event_id: str | None) -> str | None:
        while event_id:
            ev = events[event_id]
            if ev.location_entity_id:
                return ev.location_entity_id
            event_id = ev.parent_event_id
        return None

    first_occurrence: dict[str, str] = {}
    for inst in instances.values():
        cur = first_occurrence.get(inst.system_id)
        if cur is None or ordinal[inst.verse_start] < ordinal[cur]:
            first_occurrence[inst.system_id] = inst.verse_start
    for sid in systems:
        if sid not in first_occurrence:
            report.warn(f"{sid}: system has no instances")

    # --- rows -------------------------------------------------------------------------------
    j = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    tables: dict[str, Table] = {}
    tables["core_books"] = (
        ("book_id", "book_code", "osis_code", "testament"),
        [(b.book_id, b.code, b.osis, b.testament) for b in BOOKS],
    )
    rows = []
    for vid in sorted_verses:
        v, ref, lang = verses[vid]
        ev_id = primary.get(vid, (0, 0, None))[2]
        tokens = [t.model_dump(exclude_none=True) for t in v.tokens]
        rows.append(
            (
                vid,
                ref.book.book_id,
                ref.chapter,
                ref.verse,
                ref.ordinal,
                lang,
                v.source_text,
                j(tokens),
                ev_id,
                location_of(ev_id),
            )
        )
    tables["core_verses"] = (
        (
            "verse_id",
            "book_id",
            "chapter",
            "verse",
            "ordinal",
            "source_language",
            "source_text",
            "tokens_json",
            "primary_event_id",
            "location_entity_id",
        ),
        rows,
    )
    tables["core_verse_map"] = (
        ("scheme", "scheme_ref", "verse_id", "coverage"),
        sorted((r.scheme, r.scheme_ref, r.verse_id, r.coverage) for r in verse_map),
    )
    tables["core_chronology_anchors"] = (
        ("anchor_id", "utes", "margin_seconds", "precision_tier", "basis"),
        [
            (a.anchor_id, a.date.utes, a.margin.seconds, a.precision_tier, a.basis)
            for a in sorted(anchors.values(), key=lambda a: a.anchor_id)
        ],
    )
    rows = []
    for eid in sorted(events):
        ev, t = events[eid], times[eid]
        from_event = ev.time.anchor.startswith("evt.")
        rows.append(
            (
                eid,
                ev.parent_event_id,
                ev.verse_start,
                ev.verse_end,
                t.start,
                t.end,
                t.margin,
                t.relative_margin,
                ev.time.precision_tier,
                ev.time.anchor if from_event else None,
                None if from_event else ev.time.anchor,
                ev.time.anchor_point,
                t.offset,
                ev.time.time_of_day,
                ev.location_entity_id,
            )
        )
    tables["core_events"] = (
        (
            "event_id",
            "parent_event_id",
            "verse_start",
            "verse_end",
            "utes_start",
            "utes_end",
            "utes_margin_seconds",
            "relative_margin_seconds",
            "precision_tier",
            "anchor_event_id",
            "anchor_chronology_id",
            "anchor_point",
            "relative_offset_seconds",
            "time_of_day",
            "location_entity_id",
        ),
        rows,
    )
    tables["core_event_participants"] = (
        ("event_id", "entity_id", "role"),
        sorted((eid, p.entity_id, p.role) for eid, ev in events.items() for p in ev.participants),
    )
    tables["core_causal_edges"] = (
        (
            "causal_id",
            "cause_event_id",
            "effect_event_id",
            "causal_type",
            "elapsed_seconds",
            "confidence",
        ),
        [
            (
                c.causal_id,
                c.cause_event_id,
                c.effect_event_id,
                c.causal_type,
                times[c.effect_event_id].start - times[c.cause_event_id].end,
                c.confidence,
            )
            for c in sorted(causal.values(), key=lambda c: c.causal_id)
        ],
    )
    tables["core_entities"] = (
        (
            "entity_id",
            "tipnr_id",
            "entity_type",
            "source_script_name",
            "transliterated_name",
            "first_mention_verse",
            "created_at_utes",
            "destroyed_at_utes",
            "geo_lat",
            "geo_lon",
            "geo_elevation_m",
            "geo_source",
            "geo_confidence",
        ),
        [
            (
                e.entity_id,
                e.tipnr_id,
                e.entity_type,
                e.source_script_name,
                e.transliterated_name,
                e.first_mention_verse,
                None,
                None,
                *geo_of(e),
            )
            for e in sorted(entities.values(), key=lambda e: e.entity_id)
        ],
    )
    tables["core_components"] = (
        (
            "component_id",
            "entity_id",
            "category",
            "component_key",
            "value_code",
            "target_entity_id",
            "supersedes_component_id",
            "acquired_at_verse",
            "expired_at_verse",
            "acquired_in_event_id",
            "expired_in_event_id",
            "utes_start",
            "utes_end",
        ),
        [
            (
                c.component_id,
                c.entity_id,
                c.category,
                c.component_key,
                c.value_code,
                c.target_entity_id,
                c.supersedes_component_id,
                c.acquired_at_verse,
                c.expired_at_verse,
                c.acquired_in_event,
                c.expired_in_event,
                times[c.acquired_in_event].start,
                times[c.expired_in_event].start if c.expired_in_event else None,
            )
            for c in sorted(components.values(), key=lambda c: c.component_id)
        ],
    )
    tables["core_systems"] = (
        ("system_id", "category", "first_occurrence_verse"),
        [
            (s.system_id, s.category, first_occurrence.get(s.system_id))
            for s in sorted(systems.values(), key=lambda s: s.system_id)
        ],
    )
    tables["core_system_instances"] = (
        (
            "instance_id",
            "system_id",
            "event_id",
            "verse_start",
            "verse_end",
            "utes_timestamp",
            "initiator_entity_id",
            "target_entity_ids_json",
            "artifact_entity_ids_json",
            "location_entity_id",
            "tags_json",
        ),
        [
            (
                i.instance_id,
                i.system_id,
                i.event_id,
                i.verse_start,
                i.verse_end,
                times[i.event_id].start,
                i.initiator_entity_id,
                j(i.target_entity_ids),
                j(i.artifact_entity_ids),
                i.location_entity_id,
                j(i.tags),
            )
            for i in sorted(instances.values(), key=lambda i: i.instance_id)
        ],
    )
    tables["core_edges"] = (
        (
            "edge_id",
            "source_entity_id",
            "target_entity_id",
            "interaction_type",
            "verse_id",
            "event_id",
            "utes_timestamp",
        ),
        [
            (
                e.edge_id,
                e.source_entity_id,
                e.target_entity_id,
                e.interaction_type,
                e.verse_id,
                e.event_id,
                times[e.event_id].start,
            )
            for e in sorted(edges.values(), key=lambda e: e.edge_id)
        ],
    )

    surface = hashlib.sha256()
    for name in (
        "core_verses",
        "core_chronology_anchors",
        "core_events",
        "core_causal_edges",
        "core_entities",
        "core_components",
        "core_systems",
        "core_system_instances",
        "core_edges",
    ):
        for row in tables[name][1]:
            surface.update(f"{name}\t{row[0]}\n".encode())
    content = hashlib.sha256(j({k: v[1] for k, v in tables.items()}).encode())
    attribution = sorted({a for book in corpus.sources for a in book.attribution})
    tables["core_meta"] = (
        ("key", "value"),
        sorted(
            [
                ("schema_version", SCHEMA_VERSION),
                ("core_version", __version__),
                ("chronology_scheme", scheme),
                ("versification", "SOURCE"),
                ("id_surface_hash", surface.hexdigest()),
                ("content_hash", content.hexdigest()),
                ("attribution_json", j(attribution)),
            ]
        ),
    )
    return tables


# =============================================================================================
# Language bundles
# =============================================================================================

_I18N_KINDS = (
    # (IR attribute, id attribute, core table, i18n table, columns after the id)
    (
        "events",
        "event_id",
        "core_events",
        "i18n_events",
        (
            "title",
            "narrative_summary",
            "temporal_reasoning_note",
            "ancient_year_marker",
            "ancient_season_marker",
            "ancient_diurnal_marker",
        ),
    ),
    (
        "causal_edges",
        "causal_id",
        "core_causal_edges",
        "i18n_causal_edges",
        ("causal_explanation",),
    ),
    (
        "entities",
        "entity_id",
        "core_entities",
        "i18n_entities",
        ("canonical_name", "phonetic_name", "aliases", "etymology_meaning", "summary_bio"),
    ),
    (
        "components",
        "component_id",
        "core_components",
        "i18n_components",
        ("label_key", "label_value", "evidence_explanation"),
    ),
    (
        "systems",
        "system_id",
        "core_systems",
        "i18n_systems",
        ("name", "ancient_near_east_context", "rules_and_mechanics"),
    ),
    (
        "system_instances",
        "instance_id",
        "core_system_instances",
        "i18n_system_instances",
        ("outcome_summary", "significance_note"),
    ),
    ("edges", "edge_id", "core_edges", "i18n_edges", ("interaction_label", "description")),
)
_JSON_COLUMNS = {"aliases": "aliases_json", "rules_and_mechanics": "rules_and_mechanics_json"}


def build_lang(
    ir_dir: Path,
    lang: str,
    core: sqlite3.Connection,
    report: Report,
    inputs_dir: Path | None = None,
) -> tuple[dict[str, Table], dict[str, Any]]:
    bundle, chapters = load_i18n(ir_dir, lang)
    j = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    meta = dict(core.execute("SELECT key, value FROM core_meta").fetchall())
    tables: dict[str, Table] = {}
    search_rows: list[tuple[str, str, str, str]] = []

    # --- entity-like kinds ------------------------------------------------------------------
    for attr, id_attr, core_table, i18n_table, cols in _I18N_KINDS:
        core_ids = {r[0] for r in core.execute(f"SELECT {id_attr} FROM {core_table}")}
        items = _unique(
            (x for c in chapters for x in getattr(c, attr)), id_attr, f"{lang} {attr}", report
        )
        for orphan in sorted(set(items) - core_ids):
            report.error(f"{lang}: {attr} text for unknown core id {orphan}")
        if missing := sorted(core_ids - set(items)):
            report.warn(f"{lang}: {len(missing)} {attr} without text (e.g. {missing[0]})")
        rows = []
        for key in sorted(set(items) & core_ids):
            item = items[key]
            rows.append(
                (
                    key,
                    *(
                        j(getattr(item, c)) if c in _JSON_COLUMNS else getattr(item, c)
                        for c in cols
                    ),
                )
            )
        tables[i18n_table] = ((id_attr, *(_JSON_COLUMNS.get(c, c) for c in cols)), rows)

        if attr == "entities":
            search_rows += [
                ("entity", r[0], r[1], " ".join([r[2], *json.loads(r[3]), r[4], r[5]]))
                for r in rows
            ]
        elif attr == "systems":
            search_rows += [("system", r[0], r[1], f"{r[2]} {r[3]}") for r in rows]
        elif attr == "events":
            search_rows += [("event", r[0], r[1], f"{r[2]} {r[3]}") for r in rows]

    # --- verses -----------------------------------------------------------------------------
    core_verses = {
        r[0]: (r[1], len(json.loads(r[2])))
        for r in core.execute("SELECT verse_id, ordinal, tokens_json FROM core_verses")
    }
    texts = _unique((x for c in chapters for x in c.verses), "verse_id", f"{lang} verse", report)
    for vid, vt in texts.items():
        if vid not in core_verses:
            report.error(f"{lang}: verse text for unknown verse {vid}")
            continue
        n_tokens = core_verses[vid][1]
        for g in vt.token_glosses:
            if g.pos > n_tokens:
                report.error(f"{lang} {vid}: gloss for token {g.pos}, verse has {n_tokens}")

    translation = bundle.baseline_translation
    scheme = TRANSLATION_SCHEMES.get(translation)
    baseline_texts: dict[str, str] = {}
    source_glosses: dict[str, list[str]] = {}  # reference glosses (e.g. STEPBible) per verse
    for src in load_sources(inputs_root(ir_dir, inputs_dir)):
        baseline_texts.update(src.baselines.get(translation, {}))
        source_glosses |= {v.verse_id: v.glosses[lang] for v in src.verses if lang in v.glosses}
    if not baseline_texts:
        report.error(f"{lang}: no {translation} baseline text in source IR")
    mapped: dict[str, list[str]] = defaultdict(list)
    if scheme:
        for scheme_ref, vid in core.execute(
            "SELECT scheme_ref, verse_id FROM core_verse_map WHERE scheme = ?", (scheme,)
        ):
            mapped[vid].append(scheme_ref)

    rows = []
    for vid in sorted(core_verses, key=lambda v: core_verses[v][0]):
        refs = sorted(mapped.get(vid, [vid]), key=lambda r: parse_ref(r)[1].ordinal)
        baseline = " ".join(baseline_texts[r] for r in refs if r in baseline_texts)
        vt = texts.get(vid)
        if vt and vt.token_glosses:
            glosses = [g.model_dump() for g in vt.token_glosses]
        else:
            glosses = [
                {"pos": i, "gloss": g}
                for i, g in enumerate(source_glosses.get(vid, []), start=1)
                if g
            ]
        if not baseline and not vt and not glosses:
            continue
        if not baseline:
            report.warn(f"{lang} {vid}: has layers but no {translation} baseline")
        rows.append(
            (
                vid,
                baseline,
                vt.translation_literal if vt else None,
                vt.translation_dramatic if vt else None,
                vt.directors_commentary if vt else None,
                j([n.model_dump(exclude_none=True) for n in vt.philological_notes]) if vt else None,
                j(glosses) if glosses else None,
            )
        )
        body = " ".join(x for x in (baseline, *(rows[-1][2:5])) if x)
        search_rows.append(("verse", vid, vid, body))
    tables["i18n_verses"] = (
        (
            "verse_id",
            "traditional_baseline",
            "translation_literal",
            "translation_dramatic",
            "directors_commentary",
            "philological_notes_json",
            "token_glosses_json",
        ),
        rows,
    )

    # --- bundle-level -----------------------------------------------------------------------
    book_rows = []
    for b in bundle.books:
        if b.book_code not in BOOKS_BY_CODE:
            report.error(f"{lang}: unknown book code {b.book_code}")
        else:
            book_rows.append((BOOKS_BY_CODE[b.book_code].book_id, b.name, b.abbreviation))
    tables["i18n_books"] = (("book_id", "name", "abbreviation"), sorted(book_rows))
    tables["i18n_vocab"] = (
        ("kind", "code", "label"),
        sorted({(v.kind, v.code, v.label) for v in bundle.vocab}),
    )
    core_anchors = {r[0] for r in core.execute("SELECT anchor_id FROM core_chronology_anchors")}
    tables["i18n_chronology_anchors"] = (
        ("anchor_id", "label", "note"),
        sorted(
            (a.anchor_id, a.label, a.note) for a in bundle.anchors if a.anchor_id in core_anchors
        ),
    )
    tables["i18n_search"] = (("doc_kind", "doc_id", "title", "body"), search_rows)

    manifest = {
        "lang_code": lang,
        "lang_name": bundle.lang_name,
        "urim_core_version": meta["core_version"],
        "core_id_surface_hash": meta["id_surface_hash"],
        "baseline_translation": translation,
        "source_translations": bundle.source_translations,
        "embedding_model": None,
        "compiled_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    tables["bundle_manifest"] = (
        (
            "lang_code",
            "lang_name",
            "urim_core_version",
            "core_id_surface_hash",
            "baseline_translation",
            "source_translations_json",
            "embedding_model",
            "compiled_at",
        ),
        [
            (
                lang,
                bundle.lang_name,
                manifest["urim_core_version"],
                manifest["core_id_surface_hash"],
                translation,
                j(bundle.source_translations),
                None,
                manifest["compiled_at"],
            )
        ],
    )
    return tables, manifest


# =============================================================================================
# Writing
# =============================================================================================


def _write_db(
    path: Path,
    schema_file: str,
    tables: dict[str, Table],
    post: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    """Write a bundle to a temporary file and move it into place, so readers never see half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript((SCHEMA_DIR / schema_file).read_text())
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            for name, (cols, rows) in tables.items():
                if rows:
                    placeholders = ", ".join("?" * len(cols))
                    conn.executemany(
                        f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({placeholders})", rows
                    )
        if problems := conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError(f"{path.name}: foreign key violations {problems[:5]}")
        if post is not None:
            post(conn)
    finally:
        conn.close()
    os.replace(tmp, path)


def validate(ir_dir: Path, scheme: str | None = None, *, inputs_dir: Path | None = None) -> Report:
    corpus = load_core_corpus(ir_dir, inputs_dir)
    report = Report()
    build_core(corpus, scheme or corpus.chronology.default_scheme, report)
    return report


def link_core(
    ir_dir: Path, bundles_dir: Path, scheme: str | None = None, *, inputs_dir: Path | None = None
) -> Report:
    corpus = load_core_corpus(ir_dir, inputs_dir)
    report = Report()
    tables = build_core(corpus, scheme or corpus.chronology.default_scheme, report)
    if not report.ok:
        raise LinkError(report)
    _write_db(core_path(bundles_dir), "core.sql", tables)
    return report


def _vector_table(docs: list[tuple], vectors: Vectorizer) -> Callable[[sqlite3.Connection], None]:
    """Embed the search documents and store them in a sqlite-vec table inside the bundle."""
    # A verse's id says nothing; other documents lead with their name or title.
    texts = [body if kind == "verse" else f"{title}. {body}" for kind, _, title, body in docs]
    blobs = vectors(texts)

    def write(conn: sqlite3.Connection) -> None:
        if not load_sqlite_vec(conn):
            raise RuntimeError("sqlite-vec is not installed: `uv sync --extra search`")
        conn.execute(
            "CREATE VIRTUAL TABLE i18n_vectors USING vec0(doc_kind text,"
            f" embedding float[{vectors.dims}] distance_metric=cosine, +doc_id text)"
        )
        with conn:
            conn.executemany(
                "INSERT INTO i18n_vectors (doc_kind, embedding, doc_id) VALUES (?, ?, ?)",
                [
                    (kind, blob, doc_id)
                    for (kind, doc_id, _, _), blob in zip(docs, blobs, strict=True)
                ],
            )

    return write


def link_lang(
    ir_dir: Path,
    lang: str,
    bundles_dir: Path,
    *,
    inputs_dir: Path | None = None,
    vectors: Vectorizer | None = None,
) -> Report:
    """Build one language bundle against an existing core. Opens the core read-only.

    With `vectors`, every search document is also embedded into the bundle's `i18n_vectors`.
    """
    core_file = core_path(bundles_dir)
    if not core_file.exists():
        raise FileNotFoundError(f"{core_file} not found; run link core first")
    report = Report()
    core = sqlite3.connect(sqlite_uri(core_file), uri=True)
    try:
        tables, manifest = build_lang(Path(ir_dir), lang, core, report, inputs_dir)
    finally:
        core.close()
    if not report.ok:
        raise LinkError(report)
    out = lang_bundle_path(bundles_dir, lang)
    post = None
    if vectors is not None:
        post = _vector_table(tables["i18n_search"][1], vectors)
        manifest["embedding_model"] = vectors.model_id
        cols, rows = tables["bundle_manifest"]
        i = cols.index("embedding_model")
        tables["bundle_manifest"] = (cols, [(*r[:i], vectors.model_id, *r[i + 1 :]) for r in rows])
    _write_db(out, "i18n.sql", tables, post)
    (out.parent / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return report


def link_all(
    ir_dir: Path,
    bundles_dir: Path,
    scheme: str | None = None,
    *,
    inputs_dir: Path | None = None,
    vectors: Vectorizer | None = None,
) -> dict[str, Report]:
    reports = {"core": link_core(ir_dir, bundles_dir, scheme, inputs_dir=inputs_dir)}
    for lang in available_langs(ir_dir):
        reports[lang] = link_lang(ir_dir, lang, bundles_dir, inputs_dir=inputs_dir, vectors=vectors)
    return reports
