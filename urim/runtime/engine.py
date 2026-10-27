"""UrimEngine: the read-only query layer behind the SDK, REST API and MCP server.

The core bundle is opened read-only and immutable, so serving can never modify it. The
requested language bundle is ATTACHed as `lang_active` and English as `lang_en`; any text
missing from the active bundle falls back to English. Connections are cached per thread and
per language.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import deque
from collections.abc import Iterable
from itertools import batched
from pathlib import Path
from typing import Any, Literal

from urim import utime
from urim.bundles import core_path, discover_langs, sqlite_uri
from urim.canon import parse_ref
from urim.runtime.models import (
    CausalGraph,
    CausalLink,
    ChapterStream,
    Coded,
    ComponentView,
    EdgeView,
    EntityDossier,
    EntityRef,
    EventView,
    Geo,
    LanguageInfo,
    SearchHit,
    SystemCodex,
    SystemInstanceView,
    Timeline,
    TimelineEntry,
    TokenView,
    VerseEcs,
    VerseMatrix,
)


class UrimError(Exception):
    pass


class NotFoundError(UrimError):
    pass


class LanguageNotAvailable(UrimError):
    pass


class BundleMismatch(UrimError):
    pass


_LABEL_PRECISION = {
    "MACRO_ERA": "year",
    "REGNAL_YEAR": "year",
    "SEASONAL_MONTH": "month",
    "DAY_SEQUENCE": "day",
    "DIURNAL_HOUR": "minute",
}

_SEARCH_KINDS = {
    "verses": ("verse",),
    "entities": ("entity",),
    "systems": ("system",),
    "events": ("event",),
    "all": ("verse", "entity", "system", "event"),
}

_EVENT_SELECT = (
    "SELECT e.*, COALESCE(e.anchor_event_id, e.anchor_chronology_id) AS anchor_id "
    "FROM core_events e"
)
_COVERING_EVENTS = (
    _EVENT_SELECT + " JOIN core_verses vs ON vs.verse_id = e.verse_start"
    " JOIN core_verses ve ON ve.verse_id = e.verse_end"
    " WHERE vs.ordinal <= :o AND ve.ordinal >= :o ORDER BY e.utes_start, e.event_id"
)


def format_utes(utes: int, precision_tier: str) -> str:
    d = utime.utes_to_date(utes)
    year, era = utime.astronomical_to_era(d.year)
    match _LABEL_PRECISION.get(precision_tier, "minute"):
        case "year":
            return f"c. {year} {era}"
        case "month":
            return f"{year} {era}-{d.month:02d}"
        case "day":
            return d.label(with_time=False)
        case _:
            return d.label()


def _ph(n: int) -> str:
    return ",".join("?" * n)


def _get(row: sqlite3.Row | None, key: str) -> Any:
    return row[key] if row is not None else None


class UrimEngine:
    def __init__(self, bundles_dir: str | Path, default_lang: str = "en"):
        self.bundles_dir = Path(bundles_dir)
        self.core_path = core_path(self.bundles_dir)
        if not self.core_path.exists():
            raise FileNotFoundError(f"no core bundle at {self.core_path}")
        self.default_lang = default_lang
        self._local = threading.local()
        self._vocab_cache: dict[str, dict[tuple[str, str], str]] = {}

        conn = self._open(self.core_path)
        try:
            self.core_meta: dict[str, str] = dict(
                conn.execute("SELECT key, value FROM core_meta").fetchall()
            )
        finally:
            conn.close()
        self._lang_paths = discover_langs(self.bundles_dir)
        self._manifests: dict[str, dict[str, Any]] = {}
        for lang, path in self._lang_paths.items():
            c = self._open(path)
            try:
                self._manifests[lang] = dict(c.execute("SELECT * FROM bundle_manifest").fetchone())
            finally:
                c.close()

    # -----------------------------------------------------------------------------------------
    # Connections
    # -----------------------------------------------------------------------------------------

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(sqlite_uri(path, immutable=True), uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def languages(self) -> list[LanguageInfo]:
        return [
            LanguageInfo(
                lang_code=lang,
                lang_name=m["lang_name"],
                baseline_translation=m["baseline_translation"],
                compatible=m["core_id_surface_hash"] == self.core_meta["id_surface_hash"],
            )
            for lang, m in self._manifests.items()
        ]

    def _schemas(self, lang: str) -> list[tuple[str, str]]:
        """Attached language schemas in fallback order, as (schema, lang_code)."""
        out = [("lang_active", lang)] if lang != "en" else []
        if "en" in self._lang_paths:
            out.append(("lang_en", "en"))
        return out

    def _conn(self, lang: str) -> sqlite3.Connection:
        conns: dict[str, sqlite3.Connection] = self._local.__dict__.setdefault("conns", {})
        if lang in conns:
            return conns[lang]
        if lang not in self._lang_paths:
            raise LanguageNotAvailable(
                f"no language bundle for {lang!r}; available: {sorted(self._lang_paths)}"
            )
        for code in {lang, "en"} & set(self._lang_paths):
            if self._manifests[code]["core_id_surface_hash"] != self.core_meta["id_surface_hash"]:
                raise BundleMismatch(
                    f"lang-{code} was compiled against a different core; recompile it"
                )
        conn = self._open(self.core_path)
        if "en" in self._lang_paths:
            conn.execute(
                "ATTACH DATABASE ? AS lang_en",
                (sqlite_uri(self._lang_paths["en"], immutable=True),),
            )
        if lang != "en":
            conn.execute(
                "ATTACH DATABASE ? AS lang_active",
                (sqlite_uri(self._lang_paths[lang], immutable=True),),
            )
        conns[lang] = conn
        return conn

    def close(self) -> None:
        for conn in self._local.__dict__.pop("conns", {}).values():
            conn.close()

    # -----------------------------------------------------------------------------------------
    # Hydration helpers
    # -----------------------------------------------------------------------------------------

    def _text(
        self, conn: sqlite3.Connection, lang: str, table: str, key: str, ids: Iterable[Any]
    ) -> dict[Any, tuple[sqlite3.Row, str]]:
        """Localized rows by id, falling back to English. Values are (row, lang_code)."""
        wanted = {i for i in ids if i is not None}
        found: dict[Any, tuple[sqlite3.Row, str]] = {}
        for schema, code in self._schemas(lang):
            missing = [i for i in wanted if i not in found]
            for chunk in batched(missing, 500, strict=False):
                sql = f"SELECT * FROM {schema}.{table} WHERE {key} IN ({_ph(len(chunk))})"
                for row in conn.execute(sql, chunk):
                    found[row[key]] = (row, code)
        return found

    def _vocab(self, conn: sqlite3.Connection, lang: str) -> dict[tuple[str, str], str]:
        if lang not in self._vocab_cache:
            vocab: dict[tuple[str, str], str] = {}
            for schema, _ in reversed(self._schemas(lang)):
                for row in conn.execute(f"SELECT kind, code, label FROM {schema}.i18n_vocab"):
                    vocab[(row["kind"], row["code"])] = row["label"]
            self._vocab_cache[lang] = vocab
        return self._vocab_cache[lang]

    def _coded(self, conn, lang, kind: str, code: str | None) -> Coded | None:
        return Coded(code=code, label=self._vocab(conn, lang).get((kind, code))) if code else None

    def _entity_refs(self, conn, lang, ids: Iterable[str | None]) -> dict[str, EntityRef]:
        wanted = sorted({i for i in ids if i})
        if not wanted:
            return {}
        texts = self._text(conn, lang, "i18n_entities", "entity_id", wanted)
        rows = conn.execute(
            f"SELECT entity_id, entity_type FROM core_entities WHERE entity_id IN "
            f"({_ph(len(wanted))})",
            wanted,
        )
        return {
            r["entity_id"]: EntityRef(
                entity_id=r["entity_id"],
                entity_type=r["entity_type"],
                name=_get(texts.get(r["entity_id"], (None,))[0], "canonical_name")
                or r["entity_id"],
            )
            for r in rows
        }

    def _event_views(self, conn, lang, rows: list[sqlite3.Row]) -> list[EventView]:
        texts = self._text(conn, lang, "i18n_events", "event_id", [r["event_id"] for r in rows])
        locs = self._entity_refs(conn, lang, [r["location_entity_id"] for r in rows])
        out = []
        for r in rows:
            t, text_lang = texts.get(r["event_id"], (None, None))
            tier = r["precision_tier"]
            out.append(
                EventView(
                    event_id=r["event_id"],
                    parent_event_id=r["parent_event_id"],
                    title=_get(t, "title"),
                    narrative_summary=_get(t, "narrative_summary"),
                    temporal_reasoning_note=_get(t, "temporal_reasoning_note"),
                    verse_start=r["verse_start"],
                    verse_end=r["verse_end"],
                    utes_start=r["utes_start"],
                    utes_end=r["utes_end"],
                    duration_seconds=r["duration_seconds"],
                    utes_margin_seconds=r["utes_margin_seconds"],
                    relative_margin_seconds=r["relative_margin_seconds"],
                    precision_tier=self._coded(conn, lang, "precision_tier", tier),
                    start_label=format_utes(r["utes_start"], tier),
                    end_label=format_utes(r["utes_end"], tier),
                    anchor_id=r["anchor_id"],
                    anchor_point=r["anchor_point"],
                    relative_offset_seconds=r["relative_offset_seconds"],
                    time_of_day=self._coded(conn, lang, "diurnal", r["time_of_day"]),
                    ancient_year_marker=_get(t, "ancient_year_marker"),
                    ancient_season_marker=_get(t, "ancient_season_marker"),
                    ancient_diurnal_marker=_get(t, "ancient_diurnal_marker"),
                    location=locs.get(r["location_entity_id"]),
                    text_lang=text_lang,
                )
            )
        return out

    def _causal_links(self, conn, lang, rows: list[sqlite3.Row]) -> list[CausalLink]:
        texts = self._text(
            conn, lang, "i18n_causal_edges", "causal_id", [r["causal_id"] for r in rows]
        )
        return [
            CausalLink(
                causal_id=r["causal_id"],
                cause_event_id=r["cause_event_id"],
                effect_event_id=r["effect_event_id"],
                causal_type=self._coded(conn, lang, "causal_type", r["causal_type"]),
                elapsed_seconds=r["elapsed_seconds"],
                confidence=r["confidence"],
                explanation=_get(texts.get(r["causal_id"], (None,))[0], "causal_explanation"),
            )
            for r in rows
        ]

    def _component_views(self, conn, lang, rows: list[sqlite3.Row]) -> list[ComponentView]:
        texts = self._text(
            conn, lang, "i18n_components", "component_id", [r["component_id"] for r in rows]
        )
        targets = self._entity_refs(conn, lang, [r["target_entity_id"] for r in rows])
        out = []
        for r in rows:
            t = texts.get(r["component_id"], (None,))[0]
            out.append(
                ComponentView(
                    component_id=r["component_id"],
                    entity_id=r["entity_id"],
                    category=r["category"],
                    component_key=r["component_key"],
                    value_code=r["value_code"],
                    target=targets.get(r["target_entity_id"]),
                    supersedes_component_id=r["supersedes_component_id"],
                    label_key=_get(t, "label_key"),
                    label_value=_get(t, "label_value"),
                    evidence_explanation=_get(t, "evidence_explanation"),
                    acquired_at_verse=r["acquired_at_verse"],
                    expired_at_verse=r["expired_at_verse"],
                    utes_start=r["utes_start"],
                    utes_end=r["utes_end"],
                )
            )
        return out

    def _edge_views(self, conn, lang, rows: list[sqlite3.Row]) -> list[EdgeView]:
        texts = self._text(conn, lang, "i18n_edges", "edge_id", [r["edge_id"] for r in rows])
        refs = self._entity_refs(
            conn, lang, [x for r in rows for x in (r["source_entity_id"], r["target_entity_id"])]
        )
        out = []
        for r in rows:
            t = texts.get(r["edge_id"], (None,))[0]
            out.append(
                EdgeView(
                    edge_id=r["edge_id"],
                    source=refs[r["source_entity_id"]],
                    target=refs[r["target_entity_id"]],
                    interaction_type=r["interaction_type"],
                    interaction_label=_get(t, "interaction_label"),
                    description=_get(t, "description"),
                    verse_id=r["verse_id"],
                    event_id=r["event_id"],
                    utes_timestamp=r["utes_timestamp"],
                )
            )
        return out

    def _instance_views(self, conn, lang, rows: list[sqlite3.Row]) -> list[SystemInstanceView]:
        texts = self._text(
            conn, lang, "i18n_system_instances", "instance_id", [r["instance_id"] for r in rows]
        )
        names = self._text(conn, lang, "i18n_systems", "system_id", [r["system_id"] for r in rows])
        parsed = [
            (r, json.loads(r["target_entity_ids_json"]), json.loads(r["artifact_entity_ids_json"]))
            for r in rows
        ]
        refs = self._entity_refs(
            conn,
            lang,
            [
                x
                for r, targets, artifacts in parsed
                for x in (r["initiator_entity_id"], r["location_entity_id"], *targets, *artifacts)
            ],
        )
        out = []
        for r, targets, artifacts in parsed:
            t = texts.get(r["instance_id"], (None,))[0]
            out.append(
                SystemInstanceView(
                    instance_id=r["instance_id"],
                    system_id=r["system_id"],
                    system_name=_get(names.get(r["system_id"], (None,))[0], "name"),
                    event_id=r["event_id"],
                    verse_start=r["verse_start"],
                    verse_end=r["verse_end"],
                    utes_timestamp=r["utes_timestamp"],
                    initiator=refs[r["initiator_entity_id"]],
                    targets=[refs[x] for x in targets],
                    artifacts=[refs[x] for x in artifacts],
                    location=refs.get(r["location_entity_id"]),
                    tags=json.loads(r["tags_json"]),
                    outcome_summary=_get(t, "outcome_summary"),
                    significance_note=_get(t, "significance_note"),
                )
            )
        return out

    def _verse_ordinal(self, conn, verse_id: str) -> int:
        return conn.execute(
            "SELECT ordinal FROM core_verses WHERE verse_id = ?", (verse_id,)
        ).fetchone()[0]

    # -----------------------------------------------------------------------------------------
    # References
    # -----------------------------------------------------------------------------------------

    def resolve_ref(self, ref: str) -> str:
        """Canonical verse_id for "1KGS.18.27", "1Kgs 18:27" or an alias like "KJV:1Kgs.18.33"."""
        try:
            scheme, vref = parse_ref(ref)
        except ValueError as e:
            raise NotFoundError(str(e)) from e
        conn = self._conn(self.default_lang)
        if scheme:
            row = conn.execute(
                "SELECT verse_id FROM core_verse_map WHERE scheme = ? AND scheme_ref = ? "
                "ORDER BY coverage = 'FULL' DESC, verse_id LIMIT 1",
                (scheme, vref.verse_id),
            ).fetchone()
            if row:
                return row[0]
        if conn.execute(
            "SELECT 1 FROM core_verses WHERE verse_id = ?", (vref.verse_id,)
        ).fetchone():
            return vref.verse_id
        raise NotFoundError(f"verse {ref!r} is not in the compiled corpus")

    # -----------------------------------------------------------------------------------------
    # 1. get_verse_matrix / 2. get_chapter_stream
    # -----------------------------------------------------------------------------------------

    def get_verse_matrix(
        self, verse_id: str, lang: str = "en", include_ecs: bool = True
    ) -> VerseMatrix:
        conn = self._conn(lang)
        vid = self.resolve_ref(verse_id)
        row = conn.execute(
            "SELECT v.*, b.book_code FROM core_verses v JOIN core_books b USING (book_id) "
            "WHERE v.verse_id = ?",
            (vid,),
        ).fetchone()
        return self._verse_matrices(conn, lang, [row], include_ecs)[0]

    def _verse_matrices(
        self, conn, lang, rows: list[sqlite3.Row], include_ecs: bool
    ) -> list[VerseMatrix]:
        ids = [r["verse_id"] for r in rows]
        per_schema: dict[str, list[tuple[sqlite3.Row, str]]] = {}
        for schema, code in self._schemas(lang):
            for chunk in batched(ids, 500, strict=False):
                for t in conn.execute(
                    f"SELECT * FROM {schema}.i18n_verses WHERE verse_id IN ({_ph(len(chunk))})",
                    chunk,
                ):
                    per_schema.setdefault(t["verse_id"], []).append((t, code))
        books = self._text(conn, lang, "i18n_books", "book_id", {r["book_id"] for r in rows})
        aliases: dict[str, list[str]] = {}
        for chunk in batched(ids, 500, strict=False):
            for a in conn.execute(
                f"SELECT scheme, scheme_ref, verse_id FROM core_verse_map "
                f"WHERE verse_id IN ({_ph(len(chunk))}) ORDER BY scheme, scheme_ref",
                chunk,
            ):
                aliases.setdefault(a["verse_id"], []).append(f"{a['scheme']}:{a['scheme_ref']}")

        out = []
        for r in rows:
            candidates = per_schema.get(r["verse_id"], [])
            base, base_lang = next(
                ((t, c) for t, c in candidates if t["traditional_baseline"]), (None, None)
            )
            layers, layers_lang = next(
                ((t, c) for t, c in candidates if t["translation_literal"] is not None),
                (None, None),
            )
            glosses = {
                g["pos"]: g["gloss"] for g in json.loads(_get(layers, "token_glosses_json") or "[]")
            }
            tokens = [
                TokenView(**tok, gloss=glosses.get(tok["pos"]))
                for tok in json.loads(r["tokens_json"])
            ]
            events = self._event_views(
                conn, lang, conn.execute(_COVERING_EVENTS, {"o": r["ordinal"]}).fetchall()
            )
            primary = next((e for e in events if e.event_id == r["primary_event_id"]), None)
            out.append(
                VerseMatrix(
                    verse_id=r["verse_id"],
                    book_code=r["book_code"],
                    book_name=_get(books.get(r["book_id"], (None,))[0], "name"),
                    chapter=r["chapter"],
                    verse=r["verse"],
                    aliases=aliases.get(r["verse_id"], []),
                    source_language=r["source_language"],
                    source_text=r["source_text"],
                    tokens=tokens,
                    baseline_translation=(
                        self._manifests[base_lang]["baseline_translation"] if base_lang else None
                    ),
                    traditional_baseline=_get(base, "traditional_baseline"),
                    translation_literal=_get(layers, "translation_literal"),
                    translation_dramatic=_get(layers, "translation_dramatic"),
                    directors_commentary=_get(layers, "directors_commentary"),
                    philological_notes=json.loads(_get(layers, "philological_notes_json") or "[]"),
                    baseline_lang=base_lang,
                    layers_lang=layers_lang,
                    utes=primary.utes_start if primary else None,
                    events=events,
                    ecs=self._verse_ecs(conn, lang, r, events) if include_ecs else None,
                )
            )
        return out

    def _verse_ecs(self, conn, lang, verse: sqlite3.Row, events: list[EventView]) -> VerseEcs:
        o = verse["ordinal"]
        edges = conn.execute(
            "SELECT * FROM core_edges WHERE verse_id = ? ORDER BY edge_id", (verse["verse_id"],)
        ).fetchall()
        instances = conn.execute(
            "SELECT i.* FROM core_system_instances i"
            " JOIN core_verses vs ON vs.verse_id = i.verse_start"
            " JOIN core_verses ve ON ve.verse_id = i.verse_end"
            " WHERE vs.ordinal <= :o AND ve.ordinal >= :o ORDER BY i.utes_timestamp",
            {"o": o},
        ).fetchall()
        event_ids = [e.event_id for e in events]
        entity_ids = {e.location.entity_id for e in events if e.location}
        entity_ids |= {
            r[0]
            for r in conn.execute(
                f"SELECT entity_id FROM core_event_participants WHERE event_id IN "
                f"({_ph(len(event_ids))})",
                event_ids,
            )
        }
        entity_ids |= {x for e in edges for x in (e["source_entity_id"], e["target_entity_id"])}
        for i in instances:
            entity_ids |= {
                i["initiator_entity_id"],
                *json.loads(i["target_entity_ids_json"]),
                *json.loads(i["artifact_entity_ids_json"]),
            }
        entity_ids.discard(None)
        ids = sorted(entity_ids)
        components = conn.execute(
            "SELECT c.* FROM core_components c"
            " JOIN core_verses a ON a.verse_id = c.acquired_at_verse"
            " LEFT JOIN core_verses x ON x.verse_id = c.expired_at_verse"
            f" WHERE c.entity_id IN ({_ph(len(ids))}) AND a.ordinal <= ?"
            " AND (x.ordinal IS NULL OR x.ordinal > ?) ORDER BY c.utes_start, c.component_id",
            [*ids, o, o],
        ).fetchall()
        refs = self._entity_refs(conn, lang, ids)
        return VerseEcs(
            entities=[refs[i] for i in ids],
            components=self._component_views(conn, lang, components),
            system_instances=self._instance_views(conn, lang, instances),
            edges=self._edge_views(conn, lang, edges),
        )

    def get_chapter_stream(
        self, book_code: str, chapter: int, lang: str = "en", include_ecs: bool = False
    ) -> ChapterStream:
        conn = self._conn(lang)
        rows = conn.execute(
            "SELECT v.*, b.book_code FROM core_verses v JOIN core_books b USING (book_id) "
            "WHERE b.book_code = ? AND v.chapter = ? ORDER BY v.ordinal",
            (book_code.upper(), chapter),
        ).fetchall()
        if not rows:
            raise NotFoundError(f"chapter {book_code} {chapter} is not in the compiled corpus")
        verses = self._verse_matrices(conn, lang, rows, include_ecs)
        lo, hi = rows[0]["ordinal"], rows[-1]["ordinal"]
        event_rows = conn.execute(
            _EVENT_SELECT + " JOIN core_verses vs ON vs.verse_id = e.verse_start"
            " JOIN core_verses ve ON ve.verse_id = e.verse_end"
            " WHERE vs.ordinal <= ? AND ve.ordinal >= ? ORDER BY e.utes_start, e.event_id",
            (hi, lo),
        ).fetchall()
        ids = [r["event_id"] for r in event_rows]
        links = conn.execute(
            f"SELECT * FROM core_causal_edges WHERE cause_event_id IN ({_ph(len(ids))}) "
            f"OR effect_event_id IN ({_ph(len(ids))}) ORDER BY causal_id",
            ids + ids,
        ).fetchall()
        return ChapterStream(
            book_code=rows[0]["book_code"],
            book_name=verses[0].book_name,
            chapter=chapter,
            verses=verses,
            events=self._event_views(conn, lang, event_rows),
            causal_links=self._causal_links(conn, lang, links),
        )

    # -----------------------------------------------------------------------------------------
    # 3. get_entity_dossier
    # -----------------------------------------------------------------------------------------

    def get_entity_dossier(
        self,
        entity_id: str,
        lang: str = "en",
        at_utes: int | None = None,
        at_verse: str | None = None,
    ) -> EntityDossier:
        if at_utes is not None and at_verse is not None:
            raise ValueError("pass at_utes or at_verse, not both")
        conn = self._conn(lang)
        e = conn.execute("SELECT * FROM core_entities WHERE entity_id = ?", (entity_id,)).fetchone()
        if e is None:
            raise NotFoundError(f"unknown entity {entity_id!r}")

        verse_id = self.resolve_ref(at_verse) if at_verse is not None else None
        if verse_id is not None:
            o = self._verse_ordinal(conn, verse_id)
            components = conn.execute(
                "SELECT c.* FROM core_components c"
                " JOIN core_verses a ON a.verse_id = c.acquired_at_verse"
                " LEFT JOIN core_verses x ON x.verse_id = c.expired_at_verse"
                " WHERE c.entity_id = ? AND a.ordinal <= ? AND (x.ordinal IS NULL OR x.ordinal > ?)"
                " ORDER BY c.utes_start, c.component_id",
                (entity_id, o, o),
            ).fetchall()
            edge_filter, edge_args = (
                " AND verse_id IN (SELECT verse_id FROM core_verses WHERE ordinal <= ?)",
                [o],
            )
            event_filter, event_args = (
                " AND e.verse_start IN (SELECT verse_id FROM core_verses WHERE ordinal <= ?)",
                [o],
            )
        elif at_utes is not None:
            components = conn.execute(
                "SELECT * FROM core_components WHERE entity_id = ? AND utes_start <= ?"
                " AND (utes_end IS NULL OR utes_end > ?) ORDER BY utes_start, component_id",
                (entity_id, at_utes, at_utes),
            ).fetchall()
            edge_filter, edge_args = " AND utes_timestamp <= ?", [at_utes]
            event_filter, event_args = " AND e.utes_start <= ?", [at_utes]
        else:
            components = conn.execute(
                "SELECT * FROM core_components WHERE entity_id = ? ORDER BY utes_start, "
                "component_id",
                (entity_id,),
            ).fetchall()
            edge_filter = event_filter = ""
            edge_args, event_args = [], []

        edges = conn.execute(
            "SELECT * FROM core_edges WHERE (source_entity_id = ? OR target_entity_id = ?)"
            + edge_filter
            + " ORDER BY utes_timestamp, edge_id",
            [entity_id, entity_id, *edge_args],
        ).fetchall()
        events = conn.execute(
            _EVENT_SELECT + " WHERE (e.location_entity_id = ? OR e.event_id IN"
            " (SELECT event_id FROM core_event_participants WHERE entity_id = ?))"
            + event_filter
            + " ORDER BY e.utes_start, e.event_id",
            [entity_id, entity_id, *event_args],
        ).fetchall()
        t, text_lang = self._text(conn, lang, "i18n_entities", "entity_id", [entity_id]).get(
            entity_id, (None, None)
        )
        return EntityDossier(
            entity_id=entity_id,
            entity_type=e["entity_type"],
            tipnr_id=e["tipnr_id"],
            source_script_name=e["source_script_name"],
            transliterated_name=e["transliterated_name"],
            canonical_name=_get(t, "canonical_name"),
            phonetic_name=_get(t, "phonetic_name"),
            aliases=json.loads(_get(t, "aliases_json") or "[]"),
            etymology_meaning=_get(t, "etymology_meaning"),
            summary_bio=_get(t, "summary_bio"),
            first_mention_verse=e["first_mention_verse"],
            geo=Geo(lat=e["geo_lat"], lon=e["geo_lon"], elevation_m=e["geo_elevation_m"])
            if e["geo_lat"] is not None
            else None,
            at_utes=at_utes,
            at_verse=verse_id,
            components=self._component_views(conn, lang, components),
            interactions=self._edge_views(conn, lang, edges),
            events=self._event_views(conn, lang, events),
            text_lang=text_lang,
        )

    # -----------------------------------------------------------------------------------------
    # 4. get_system_codex
    # -----------------------------------------------------------------------------------------

    def get_system_codex(self, system_id: str, lang: str = "en") -> SystemCodex:
        conn = self._conn(lang)
        s = conn.execute("SELECT * FROM core_systems WHERE system_id = ?", (system_id,)).fetchone()
        if s is None:
            raise NotFoundError(f"unknown system {system_id!r}")
        t = self._text(conn, lang, "i18n_systems", "system_id", [system_id]).get(
            system_id, (None,)
        )[0]
        instances = conn.execute(
            "SELECT * FROM core_system_instances WHERE system_id = ? "
            "ORDER BY utes_timestamp, instance_id",
            (system_id,),
        ).fetchall()
        return SystemCodex(
            system_id=system_id,
            category=s["category"],
            name=_get(t, "name"),
            ancient_near_east_context=_get(t, "ancient_near_east_context"),
            rules_and_mechanics=json.loads(_get(t, "rules_and_mechanics_json") or "[]"),
            first_occurrence_verse=s["first_occurrence_verse"],
            instances=self._instance_views(conn, lang, instances),
        )

    # -----------------------------------------------------------------------------------------
    # 5. query_timeline / 6. trace_causal_chain
    # -----------------------------------------------------------------------------------------

    def get_event(self, event_id: str, lang: str = "en") -> EventView:
        conn = self._conn(lang)
        row = conn.execute(_EVENT_SELECT + " WHERE e.event_id = ?", (event_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"unknown event {event_id!r}")
        return self._event_views(conn, lang, [row])[0]

    def query_timeline(
        self,
        utes_start: int,
        utes_end: int,
        entity_filter: list[str] | None = None,
        lang: str = "en",
    ) -> Timeline:
        if utes_end < utes_start:
            raise ValueError("utes_end must be >= utes_start")
        conn = self._conn(lang)
        sql = _EVENT_SELECT + " WHERE e.utes_start <= ? AND e.utes_end >= ?"
        args: list[Any] = [utes_end, utes_start]
        if entity_filter:
            ph = _ph(len(entity_filter))
            sql += (
                f" AND (e.location_entity_id IN ({ph}) OR e.event_id IN (SELECT event_id"
                f" FROM core_event_participants WHERE entity_id IN ({ph})))"
            )
            args += [*entity_filter, *entity_filter]
        rows = conn.execute(sql + " ORDER BY e.utes_start, e.event_id", args).fetchall()
        views = self._event_views(conn, lang, rows)
        ids = [r["event_id"] for r in rows]
        link_rows = conn.execute(
            f"SELECT * FROM core_causal_edges WHERE cause_event_id IN ({_ph(len(ids))}) "
            f"OR effect_event_id IN ({_ph(len(ids))}) ORDER BY causal_id",
            ids + ids,
        ).fetchall()
        links = self._causal_links(conn, lang, link_rows)
        entries, prev = [], None
        for v in views:
            entries.append(
                TimelineEntry(
                    event=v,
                    delta_from_previous_seconds=None if prev is None else v.utes_start - prev,
                    causes=[x for x in links if x.effect_event_id == v.event_id],
                    effects=[x for x in links if x.cause_event_id == v.event_id],
                )
            )
            prev = v.utes_start
        return Timeline(utes_start=utes_start, utes_end=utes_end, entries=entries)

    def trace_causal_chain(
        self,
        event_id: str,
        direction: Literal["upstream", "downstream", "both"] = "both",
        depth: int = 5,
        lang: str = "en",
    ) -> CausalGraph:
        if direction not in ("upstream", "downstream", "both"):
            raise ValueError("direction must be upstream, downstream or both")
        depth = max(1, min(depth, 50))
        conn = self._conn(lang)
        if not conn.execute("SELECT 1 FROM core_events WHERE event_id = ?", (event_id,)).fetchone():
            raise NotFoundError(f"unknown event {event_id!r}")
        seen_nodes, seen_links = {event_id}, {}
        queue = deque([(event_id, 0)])
        while queue:
            node, d = queue.popleft()
            if d == depth:
                continue
            steps = []
            if direction in ("upstream", "both"):
                steps.append(("effect_event_id", "cause_event_id"))
            if direction in ("downstream", "both"):
                steps.append(("cause_event_id", "effect_event_id"))
            for here, there in steps:
                for r in conn.execute(f"SELECT * FROM core_causal_edges WHERE {here} = ?", (node,)):
                    seen_links[r["causal_id"]] = r
                    if r[there] not in seen_nodes:
                        seen_nodes.add(r[there])
                        queue.append((r[there], d + 1))
        ids = sorted(seen_nodes)
        nodes = conn.execute(
            _EVENT_SELECT + f" WHERE e.event_id IN ({_ph(len(ids))})"
            " ORDER BY e.utes_start, e.event_id",
            ids,
        ).fetchall()
        return CausalGraph(
            root_event_id=event_id,
            direction=direction,
            depth=depth,
            nodes=self._event_views(conn, lang, nodes),
            links=self._causal_links(conn, lang, [seen_links[k] for k in sorted(seen_links)]),
        )

    # -----------------------------------------------------------------------------------------
    # 7. semantic_search
    # -----------------------------------------------------------------------------------------

    def semantic_search(
        self,
        query: str,
        lang: str = "en",
        scope: Literal["verses", "entities", "systems", "events", "all"] = "all",
        top_k: int = 10,
    ) -> list[SearchHit]:
        """Keyword (FTS5 / BM25) search in the requested language.

        Phase 3 replaces this with sqlite-vec similarity plus the same relational hydration.
        """
        if scope not in _SEARCH_KINDS:
            raise ValueError(f"scope must be one of {sorted(_SEARCH_KINDS)}")
        terms = re.findall(r"\w+", query)
        if not terms:
            return []
        conn = self._conn(lang)
        schema = self._schemas(lang)[0][0]
        kinds = _SEARCH_KINDS[scope]
        rows = conn.execute(
            f"SELECT doc_kind, doc_id, title,"
            f" snippet(i18n_search, 3, '[', ']', '…', 16) AS snip, bm25(i18n_search) AS rank"
            f" FROM {schema}.i18n_search WHERE i18n_search MATCH ?"
            f" AND doc_kind IN ({_ph(len(kinds))}) ORDER BY rank LIMIT ?",
            [" OR ".join(f'"{t}"' for t in terms), *kinds, max(1, min(top_k, 100))],
        ).fetchall()
        return [
            SearchHit(
                kind=r["doc_kind"],
                id=r["doc_id"],
                title=r["title"],
                snippet=r["snip"],
                score=-r["rank"],
            )
            for r in rows
        ]
