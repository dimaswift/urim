"""Intermediate representation: the contract between compiler agents and the linker.

Agents (and hand-written fixtures) emit these per-chapter JSON documents. They never contain
absolute timestamps or derived integers: time is expressed as anchor + offset + duration, and
the linker materializes UTES values deterministically. The same models double as the
structured-output schemas for LLM calls.

Layout of an IR directory:
    source/{BOOK}.json            SourceBookIR       (ingest: text, tokens, verse map, baselines)
    chronology.json               ChronologyIR       (curated root anchors per chronology scheme)
    core/{BOOK}.{CH}.json         CoreChapterIR      (Chronologist + Ontologist)
    i18n/{lang}/_bundle.json      I18nBundleIR       (book names, vocab labels, anchor labels)
    i18n/{lang}/{BOOK}.{CH}.json  I18nChapterIR      (Philologist / Localizer)
    registry/entities.json        RegistryIR         (ingest: TIPNR seeds, mentions, geocoding)
    commentary/{BOOK}.json        CommentaryIR       (ingest: Sefaria; agent input only)
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from urim import utime

VerseId = Annotated[str, StringConstraints(pattern=r"^[1-3]?[A-Z]+\.\d+\.\d+$")]
EventId = Annotated[str, StringConstraints(pattern=r"^evt\.[a-z0-9]+_\d+\.[a-z0-9_]+$")]
EntityId = Annotated[
    str,
    StringConstraints(
        pattern=r"^(person|deity|spirit|loc|group|artifact|substance)\.[a-z0-9_]+(\.[a-z0-9_]+)*$"
    ),
]
ComponentId = Annotated[str, StringConstraints(pattern=r"^comp\.[a-z0-9_.]+\.\d+$")]
SystemId = Annotated[str, StringConstraints(pattern=r"^sys\.[a-z0-9_]+$")]
InstanceId = Annotated[str, StringConstraints(pattern=r"^inst\.[a-z0-9_]+\.[a-z0-9_]+$")]
EdgeId = Annotated[str, StringConstraints(pattern=r"^edge\.[a-z0-9_]+\.[a-z0-9_]+$")]
CausalId = Annotated[str, StringConstraints(pattern=r"^caus\.[a-z0-9_.]+$")]
AnchorId = Annotated[str, StringConstraints(pattern=r"^anchor\.[a-z0-9_]+$")]
UpperCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
ChapterRef = Annotated[str, StringConstraints(pattern=r"^[1-3]?[A-Z]+\.\d+$")]

PrecisionTier = Literal[
    "MACRO_ERA", "REGNAL_YEAR", "SEASONAL_MONTH", "DAY_SEQUENCE", "DIURNAL_HOUR"
]
SourceLanguage = Literal["HEBREW", "ARAMAIC", "GREEK"]
EntityType = Literal[
    "PERSON", "DEITY", "SPIRIT_BEING", "LOCATION", "GROUP", "ARTIFACT", "SUBSTANCE"
]
ParticipantRole = Literal["AGENT", "PATIENT", "PRESENT", "MENTIONED"]
CausalType = Literal["TRIGGERS", "FULFILLS_PROPHECY", "RETALIATES_FOR", "ENABLES", "DEFERRED_BY"]
ComponentCategory = Literal[
    "TRAIT", "ROLE_TITLE", "PSYCH_STATE", "POSSESSION", "LOCATION_STATE", "ALLEGIANCE"
]
SystemCategory = Literal[
    "LITURGICAL_RITUAL",
    "SUPERNATURAL_ACT",
    "LEGAL_CUSTOM",
    "SOCIAL_CUSTOM",
    "PROPHETIC_ORACLE",
    "THEOPHANY",
    "MILITARY_PROTOCOL",
]


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------------------------


class Duration(IRModel):
    value: float = Field(ge=0)
    unit: utime.DurationUnit

    @property
    def seconds(self) -> int:
        return utime.duration_seconds(self.value, self.unit)


class HistoricalDate(IRModel):
    year: int = Field(ge=1)
    era: Literal["BCE", "CE"]
    month: int = Field(default=1, ge=1, le=12)
    day: int = Field(default=1, ge=1, le=31)

    @property
    def utes(self) -> int:
        year = utime.bce_to_astronomical(self.year) if self.era == "BCE" else self.year
        return utime.utes_from_date(year, self.month, self.day)


class EventTime(IRModel):
    """start = next `time_of_day` at or after (anchor point + offset); end = start + duration."""

    anchor: str = Field(description="An event_id (evt.*) or a chronology anchor_id (anchor.*)")
    anchor_point: Literal["START", "END"] = "START"
    offset: Duration | None = None
    time_of_day: str | None = Field(
        default=None, description="Diurnal marker (e.g. MINCHAH) or HH:MM clock time"
    )
    duration: Duration
    margin: Duration = Field(description="Uncertainty of start relative to the anchor point")
    precision_tier: PrecisionTier

    @field_validator("anchor")
    @classmethod
    def _anchor_kind(cls, v: str) -> str:
        if not v.startswith(("evt.", "anchor.")):
            raise ValueError("anchor must be an event_id (evt.*) or anchor_id (anchor.*)")
        return v

    @field_validator("time_of_day")
    @classmethod
    def _time_of_day(cls, v: str | None) -> str | None:
        if v is not None:
            utime.time_of_day_seconds(v)
        return v

    @model_validator(mode="after")
    def _root_anchor_point(self) -> EventTime:
        if self.anchor.startswith("anchor.") and self.anchor_point != "START":
            raise ValueError("chronology anchors are instants; anchor_point must be START")
        return self


# ---------------------------------------------------------------------------------------------
# Source (ingest output)
# ---------------------------------------------------------------------------------------------


class Token(IRModel):
    pos: int = Field(ge=1)
    surface: str
    translit: str | None = None
    lemma: str | None = None
    strongs: str | None = Field(default=None, description="Disambiguated Strong's, e.g. H0452G")
    morph: str | None = None
    name_ref: str | None = Field(default=None, description="TIPNR unique name of a proper noun")
    reading: str | None = Field(
        default=None,
        description="Text type unless plain Leningrad, e.g. Q(K) = Qere, Ketiv variant",
    )
    is_idiom_part: bool = False


class SourceVerse(IRModel):
    verse_id: VerseId
    source_text: str
    tokens: list[Token]
    glosses: dict[str, list[str]] = Field(
        default={},
        description="Reference word glosses per language, parallel to tokens (e.g. STEPBible en)",
    )


class VerseMapRow(IRModel):
    scheme: UpperCode
    scheme_ref: VerseId
    verse_id: VerseId
    coverage: Literal["FULL", "PARTIAL"]


class SourceBookIR(IRModel):
    book_code: str
    source_language: SourceLanguage
    attribution: list[str]
    verses: list[SourceVerse]
    verse_map: list[VerseMapRow] = []
    baselines: dict[str, dict[VerseId, str]] = Field(
        default={}, description="translation code -> verse ref in that translation's scheme -> text"
    )
    versification_notes: dict[VerseId, list[str]] = {}


class CommentaryWork(IRModel):
    version_title: str
    license: str
    verses: dict[VerseId, list[str]]


class CommentaryIR(IRModel):
    """Classical commentaries per book: compile-time input for agents, never shipped."""

    book_code: str
    works: dict[str, CommentaryWork]


class GeoPoint(IRModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source: str
    source_id: str | None = None
    source_name: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Mention(IRModel):
    verse_id: VerseId
    pos: int = Field(ge=1)


class EntitySeed(IRModel):
    """A TIPNR individual seen in the ingested text: the Ontologist's starting point."""

    tipnr_id: str
    proposed_entity_id: EntityId | None = None
    tipnr_category: Literal["PERSON", "PLACE", "OTHER"]
    tipnr_type: str | None = None
    dstrongs: list[str]
    names: list[str] = Field(description="English names, most common first")
    source_names: list[str] = Field(description="Hebrew/Greek forms")
    description: str | None = None
    brief: str | None = None
    short: str | None = None
    parents: list[str] = []
    siblings: list[str] = []
    partners: list[str] = []
    offspring: list[str] = []
    tribe: str | None = None
    mentions: list[Mention] = []
    geo: GeoPoint | None = None


class RegistryIR(IRModel):
    attribution: list[str]
    entities: list[EntitySeed]


class ChronologyAnchorIR(IRModel):
    anchor_id: AnchorId
    date: HistoricalDate
    margin: Duration
    precision_tier: PrecisionTier
    basis: str


class ChronologyIR(IRModel):
    default_scheme: UpperCode
    schemes: dict[UpperCode, list[ChronologyAnchorIR]]

    @model_validator(mode="after")
    def _same_anchor_ids(self) -> ChronologyIR:
        if self.default_scheme not in self.schemes:
            raise ValueError(f"default_scheme {self.default_scheme} is not defined")
        id_sets = {name: {a.anchor_id for a in anchors} for name, anchors in self.schemes.items()}
        first = next(iter(id_sets.values()))
        for name, ids in id_sets.items():
            if ids != first:
                raise ValueError(f"scheme {name} defines a different anchor set; ids must match")
        return self


# ---------------------------------------------------------------------------------------------
# Core chapter (Chronologist + Ontologist)
# ---------------------------------------------------------------------------------------------


class Participant(IRModel):
    entity_id: EntityId
    role: ParticipantRole


class EventIR(IRModel):
    event_id: EventId
    parent_event_id: EventId | None = None
    verse_start: VerseId
    verse_end: VerseId
    location_entity_id: EntityId | None = None
    time: EventTime
    participants: list[Participant] = []


class CausalEdgeIR(IRModel):
    causal_id: CausalId
    cause_event_id: EventId
    effect_event_id: EventId
    causal_type: CausalType
    confidence: float = Field(default=1.0, ge=0, le=1)


class EntityIR(IRModel):
    entity_id: EntityId
    tipnr_id: str | None = None
    entity_type: EntityType
    source_script_name: str | None = None
    transliterated_name: str | None = None
    first_mention_verse: VerseId
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lon: float | None = Field(default=None, ge=-180, le=180)
    geo_elevation_m: float | None = None


class ComponentIR(IRModel):
    component_id: ComponentId
    entity_id: EntityId
    category: ComponentCategory
    component_key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    value_code: UpperCode | None = None
    target_entity_id: EntityId | None = None
    supersedes_component_id: ComponentId | None = None
    acquired_at_verse: VerseId
    acquired_in_event: EventId
    expired_at_verse: VerseId | None = None
    expired_in_event: EventId | None = None

    @model_validator(mode="after")
    def _expiry_pair(self) -> ComponentIR:
        if (self.expired_at_verse is None) != (self.expired_in_event is None):
            raise ValueError("expired_at_verse and expired_in_event must be set together")
        return self


class ComponentClosureIR(IRModel):
    """Closes a component opened in an earlier chapter."""

    component_id: ComponentId
    expired_at_verse: VerseId
    expired_in_event: EventId


class SystemIR(IRModel):
    system_id: SystemId
    category: SystemCategory


class SystemInstanceIR(IRModel):
    instance_id: InstanceId
    system_id: SystemId
    event_id: EventId
    verse_start: VerseId
    verse_end: VerseId
    initiator_entity_id: EntityId
    target_entity_ids: list[EntityId] = []
    artifact_entity_ids: list[EntityId] = []
    location_entity_id: EntityId | None = None
    tags: list[str] = []


class EdgeIR(IRModel):
    edge_id: EdgeId
    source_entity_id: EntityId
    target_entity_id: EntityId
    interaction_type: UpperCode
    verse_id: VerseId
    event_id: EventId


class CoreChapterIR(IRModel):
    chapter_ref: ChapterRef
    entities: list[EntityIR] = []
    systems: list[SystemIR] = []
    events: list[EventIR] = []
    causal_edges: list[CausalEdgeIR] = []
    components: list[ComponentIR] = []
    component_closures: list[ComponentClosureIR] = []
    system_instances: list[SystemInstanceIR] = []
    edges: list[EdgeIR] = []


# ---------------------------------------------------------------------------------------------
# Language bundle (Philologist / Localizer)
# ---------------------------------------------------------------------------------------------


class PhilologicalNote(IRModel):
    term: str = Field(description="Source-script word or phrase")
    translit: str | None = None
    root: str | None = None
    note: str
    sources: list[str] = Field(default=[], description="e.g. 'Radak on 1 Kings 18:27'")


class TokenGloss(IRModel):
    pos: int = Field(ge=1)
    gloss: str


class VerseText(IRModel):
    verse_id: VerseId
    translation_literal: str
    translation_dramatic: str
    directors_commentary: str
    philological_notes: list[PhilologicalNote] = []
    token_glosses: list[TokenGloss] = []


class EventText(IRModel):
    event_id: EventId
    title: str
    narrative_summary: str
    temporal_reasoning_note: str
    ancient_year_marker: str | None = None
    ancient_season_marker: str | None = None
    ancient_diurnal_marker: str | None = None


class CausalText(IRModel):
    causal_id: CausalId
    causal_explanation: str


class EntityText(IRModel):
    entity_id: EntityId
    canonical_name: str
    phonetic_name: str
    aliases: list[str] = []
    etymology_meaning: str
    summary_bio: str


class ComponentText(IRModel):
    component_id: ComponentId
    label_key: str
    label_value: str
    evidence_explanation: str


class SystemText(IRModel):
    system_id: SystemId
    name: str
    ancient_near_east_context: str
    rules_and_mechanics: list[str]


class InstanceText(IRModel):
    instance_id: InstanceId
    outcome_summary: str
    significance_note: str


class EdgeText(IRModel):
    edge_id: EdgeId
    interaction_label: str
    description: str


class I18nChapterIR(IRModel):
    chapter_ref: ChapterRef
    verses: list[VerseText] = []
    events: list[EventText] = []
    causal_edges: list[CausalText] = []
    entities: list[EntityText] = []
    components: list[ComponentText] = []
    systems: list[SystemText] = []
    system_instances: list[InstanceText] = []
    edges: list[EdgeText] = []


class BookName(IRModel):
    book_code: str
    name: str
    abbreviation: str


class VocabEntry(IRModel):
    kind: str
    code: str
    label: str


class AnchorText(IRModel):
    anchor_id: AnchorId
    label: str
    note: str


class I18nBundleIR(IRModel):
    lang_code: Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}$")]
    lang_name: str
    baseline_translation: str
    source_translations: list[str]
    books: list[BookName] = []
    vocab: list[VocabEntry] = []
    anchors: list[AnchorText] = []
