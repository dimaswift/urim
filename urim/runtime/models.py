"""Response models shared by the SDK, the REST API and the MCP server."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class LanguageInfo(BaseModel):
    lang_code: str
    lang_name: str
    baseline_translation: str
    compatible: bool  # manifest's id-surface hash matches the mounted core


class EntityRef(BaseModel):
    entity_id: str
    entity_type: str
    name: str


class Coded(BaseModel):
    code: str
    label: str | None = None


class EventView(BaseModel):
    event_id: str
    parent_event_id: str | None
    title: str | None
    narrative_summary: str | None
    temporal_reasoning_note: str | None
    verse_start: str
    verse_end: str
    utes_start: int
    utes_end: int
    duration_seconds: int
    utes_margin_seconds: int
    relative_margin_seconds: int
    precision_tier: Coded
    start_label: str  # formatted to the precision tier
    end_label: str
    anchor_id: str
    anchor_point: str
    relative_offset_seconds: int
    time_of_day: Coded | None
    ancient_year_marker: str | None
    ancient_season_marker: str | None
    ancient_diurnal_marker: str | None
    location: EntityRef | None
    text_lang: str | None  # bundle that supplied the text (fallback is "en")


class CausalLink(BaseModel):
    causal_id: str
    cause_event_id: str
    effect_event_id: str
    causal_type: Coded
    elapsed_seconds: int  # effect.start - cause.end; negative when they overlap
    confidence: float
    explanation: str | None


class ComponentView(BaseModel):
    component_id: str
    entity_id: str
    category: str
    component_key: str
    value_code: str | None
    target: EntityRef | None
    supersedes_component_id: str | None
    label_key: str | None
    label_value: str | None
    evidence_explanation: str | None
    acquired_at_verse: str
    expired_at_verse: str | None
    utes_start: int
    utes_end: int | None


class EdgeView(BaseModel):
    edge_id: str
    source: EntityRef
    target: EntityRef
    interaction_type: str
    interaction_label: str | None
    description: str | None
    verse_id: str
    event_id: str
    utes_timestamp: int


class SystemInstanceView(BaseModel):
    instance_id: str
    system_id: str
    system_name: str | None
    event_id: str
    verse_start: str
    verse_end: str
    utes_timestamp: int
    initiator: EntityRef
    targets: list[EntityRef]
    artifacts: list[EntityRef]
    location: EntityRef | None
    tags: list[str]
    outcome_summary: str | None
    significance_note: str | None


class TokenView(BaseModel):
    pos: int
    surface: str
    translit: str | None = None
    lemma: str | None = None
    strongs: str | None = None
    morph: str | None = None
    name_ref: str | None = None  # TIPNR individual this word names
    reading: str | None = None  # Qere/Ketiv code when not plain Leningrad
    is_idiom_part: bool = False
    gloss: str | None = None


class VerseEcs(BaseModel):
    entities: list[EntityRef]
    components: list[ComponentView]
    system_instances: list[SystemInstanceView]
    edges: list[EdgeView]


class VerseMatrix(BaseModel):
    verse_id: str
    book_code: str
    book_name: str | None
    chapter: int
    verse: int
    aliases: list[str]  # the same verse under other numbering schemes, e.g. "KJV:1KGS.18.33"
    source_language: str
    source_text: str
    tokens: list[TokenView]
    baseline_translation: str | None
    traditional_baseline: str | None
    translation_literal: str | None
    translation_dramatic: str | None
    directors_commentary: str | None
    philological_notes: list[dict[str, Any]]
    baseline_lang: str | None  # bundle that supplied traditional_baseline
    layers_lang: str | None  # bundle that supplied the three layers (falls back to "en")
    utes: int | None  # start of the verse's primary event
    events: list[EventView]
    ecs: VerseEcs | None


class ChapterStream(BaseModel):
    book_code: str
    book_name: str | None
    chapter: int
    verses: list[VerseMatrix]
    events: list[EventView]
    causal_links: list[CausalLink]


class Geo(BaseModel):
    lat: float
    lon: float
    elevation_m: float | None
    source: str | None  # "openbible:Mount Carmel", "tipnr", "ir"
    confidence: float | None


class EntityDossier(BaseModel):
    entity_id: str
    entity_type: str
    tipnr_id: str | None
    source_script_name: str | None
    transliterated_name: str | None
    canonical_name: str | None
    phonetic_name: str | None
    aliases: list[str]
    etymology_meaning: str | None
    summary_bio: str | None
    first_mention_verse: str
    geo: Geo | None
    at_utes: int | None
    at_verse: str | None
    components: list[ComponentView]  # full history, or the snapshot at at_utes / at_verse
    interactions: list[EdgeView]
    events: list[EventView]
    text_lang: str | None


class SystemCodex(BaseModel):
    system_id: str
    category: str
    name: str | None
    ancient_near_east_context: str | None
    rules_and_mechanics: list[str]
    first_occurrence_verse: str | None
    instances: list[SystemInstanceView]


class TimelineEntry(BaseModel):
    event: EventView
    delta_from_previous_seconds: int | None
    causes: list[CausalLink]
    effects: list[CausalLink]


class Timeline(BaseModel):
    utes_start: int
    utes_end: int
    entries: list[TimelineEntry]


class CausalGraph(BaseModel):
    root_event_id: str
    direction: str
    depth: int
    nodes: list[EventView]
    links: list[CausalLink]


class SearchHit(BaseModel):
    kind: str
    id: str
    title: str
    snippet: str
    score: float
    via: list[Literal["keyword", "meaning"]] = []  # which search found it
