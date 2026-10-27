-- urim-core.sqlite: language-agnostic topology, source text and UTES timeline.
-- Every value here is produced by the deterministic linker from validated IR; agents never
-- write integers (timestamps, offsets, elapsed times) directly.
-- All foreign keys are DEFERRABLE so the linker can insert in any order inside one transaction.

CREATE TABLE core_meta (
    key   TEXT PRIMARY KEY,  -- schema_version, chronology_scheme, id_surface_hash, content_hash, ...
    value TEXT NOT NULL
) STRICT;

-- ============================================================================
-- 1. CANON, VERSES, VERSIFICATION
-- ============================================================================
CREATE TABLE core_books (
    book_id   INTEGER PRIMARY KEY,           -- 1-66, Protestant canon order
    book_code TEXT NOT NULL UNIQUE,          -- "1KGS" (uppercased OSIS)
    osis_code TEXT NOT NULL UNIQUE,          -- "1Kgs"
    testament TEXT NOT NULL CHECK (testament IN ('OT', 'NT'))
) STRICT;

CREATE TABLE core_verses (
    verse_id           TEXT PRIMARY KEY,     -- "1KGS.18.27", source-text (WLC / Greek) numbering
    book_id            INTEGER NOT NULL REFERENCES core_books(book_id) DEFERRABLE INITIALLY DEFERRED,
    chapter            INTEGER NOT NULL,
    verse              INTEGER NOT NULL,
    ordinal            INTEGER NOT NULL UNIQUE,  -- book_id*1e6 + chapter*1e3 + verse
    source_language    TEXT NOT NULL CHECK (source_language IN ('HEBREW', 'ARAMAIC', 'GREEK')),
    source_text        TEXT NOT NULL,
    tokens_json        TEXT NOT NULL CHECK (json_valid(tokens_json)),
    primary_event_id   TEXT REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    location_entity_id TEXT REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

-- Sparse alias table: only references whose numbering differs from the source text.
-- coverage = FULL when the whole source verse lies inside the scheme verse, else PARTIAL.
CREATE TABLE core_verse_map (
    scheme     TEXT NOT NULL,                -- "KJV", "SYNODAL", ...
    scheme_ref TEXT NOT NULL,                -- "1KGS.18.33" as numbered in that scheme
    verse_id   TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    coverage   TEXT NOT NULL CHECK (coverage IN ('FULL', 'PARTIAL')),
    PRIMARY KEY (scheme, scheme_ref, verse_id)
) STRICT;

-- ============================================================================
-- 2. CHRONOLOGY, EVENTS, CAUSALITY (UTES)
-- ============================================================================
-- Root anchors of the active chronology scheme (core_meta.chronology_scheme). Relinking with a
-- different scheme swaps these rows and re-materializes every event; no agent re-runs.
CREATE TABLE core_chronology_anchors (
    anchor_id      TEXT PRIMARY KEY,         -- "anchor.ahab_accession"
    utes           INTEGER NOT NULL,
    margin_seconds INTEGER NOT NULL CHECK (margin_seconds >= 0),
    precision_tier TEXT NOT NULL,
    basis          TEXT NOT NULL             -- bibliographic citation for the date
) STRICT;

CREATE TABLE core_events (
    event_id                TEXT PRIMARY KEY,  -- "evt.1kgs_18.carmel_contest"
    parent_event_id         TEXT REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    verse_start             TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    verse_end               TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,

    utes_start              INTEGER NOT NULL,
    utes_end                INTEGER NOT NULL,
    duration_seconds        INTEGER GENERATED ALWAYS AS (utes_end - utes_start) VIRTUAL,
    utes_margin_seconds     INTEGER NOT NULL,  -- absolute uncertainty: root anchor + whole chain
    relative_margin_seconds INTEGER NOT NULL,  -- uncertainty relative to the anchor only
    precision_tier          TEXT NOT NULL CHECK (precision_tier IN
        ('MACRO_ERA', 'REGNAL_YEAR', 'SEASONAL_MONTH', 'DAY_SEQUENCE', 'DIURNAL_HOUR')),

    -- Relative anchoring: utes_start = anchor point + relative_offset_seconds.
    anchor_event_id         TEXT REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    anchor_chronology_id    TEXT REFERENCES core_chronology_anchors(anchor_id) DEFERRABLE INITIALLY DEFERRED,
    anchor_point            TEXT NOT NULL CHECK (anchor_point IN ('START', 'END')),
    relative_offset_seconds INTEGER NOT NULL,
    time_of_day             TEXT,              -- Diurnal marker code or "HH:MM"

    location_entity_id      TEXT REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,

    CHECK (utes_end >= utes_start),
    CHECK ((anchor_event_id IS NULL) != (anchor_chronology_id IS NULL))
) STRICT;

CREATE TABLE core_event_participants (
    event_id  TEXT NOT NULL REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    entity_id TEXT NOT NULL REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    role      TEXT NOT NULL CHECK (role IN ('AGENT', 'PATIENT', 'PRESENT', 'MENTIONED')),
    PRIMARY KEY (event_id, entity_id)
) STRICT;

-- Edges always point cause -> effect. For FULFILLS_PROPHECY the cause is the oracle and the
-- effect is the fulfilment; for DEFERRED_BY the cause is the deferring act (e.g. repentance)
-- and the effect is the deferred outcome.
CREATE TABLE core_causal_edges (
    causal_id       TEXT PRIMARY KEY,
    cause_event_id  TEXT NOT NULL REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    effect_event_id TEXT NOT NULL REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    causal_type     TEXT NOT NULL CHECK (causal_type IN
        ('TRIGGERS', 'FULFILLS_PROPHECY', 'RETALIATES_FOR', 'ENABLES', 'DEFERRED_BY')),
    elapsed_seconds INTEGER NOT NULL,          -- effect.utes_start - cause.utes_end (linker)
    confidence      REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    UNIQUE (cause_event_id, effect_event_id, causal_type),
    CHECK (cause_event_id != effect_event_id)
) STRICT;

-- ============================================================================
-- 3. ENTITIES
-- ============================================================================
CREATE TABLE core_entities (
    entity_id           TEXT PRIMARY KEY,      -- "person.elijah", "loc.mount_carmel"
    tipnr_id            TEXT UNIQUE,           -- STEPBible TIPNR disambiguation id
    entity_type         TEXT NOT NULL CHECK (entity_type IN
        ('PERSON', 'DEITY', 'SPIRIT_BEING', 'LOCATION', 'GROUP', 'ARTIFACT', 'SUBSTANCE')),
    source_script_name  TEXT,                  -- "אֵלִיָּהוּ"
    transliterated_name TEXT,                  -- SBL academic transliteration
    first_mention_verse TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    created_at_utes     INTEGER,
    destroyed_at_utes   INTEGER,
    geo_lat             REAL,
    geo_lon             REAL,
    geo_elevation_m     REAL
) STRICT;

-- ============================================================================
-- 4. STATEFUL COMPONENTS
-- Validity is half-open: active at verse V iff acquired.ordinal <= V.ordinal < expired.ordinal,
-- and at time t iff utes_start <= t < utes_end.
-- ============================================================================
CREATE TABLE core_components (
    component_id            TEXT PRIMARY KEY,  -- "comp.person.elisha.economic_tier.1"
    entity_id               TEXT NOT NULL REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    category                TEXT NOT NULL CHECK (category IN
        ('TRAIT', 'ROLE_TITLE', 'PSYCH_STATE', 'POSSESSION', 'LOCATION_STATE', 'ALLEGIANCE')),
    component_key           TEXT NOT NULL,     -- "economic_tier", "role", "held_artifact"
    value_code              TEXT,              -- machine value: "WEALTHY_LANDOWNER"
    target_entity_id        TEXT REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    supersedes_component_id TEXT REFERENCES core_components(component_id) DEFERRABLE INITIALLY DEFERRED,
    acquired_at_verse       TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    expired_at_verse        TEXT REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    acquired_in_event_id    TEXT NOT NULL REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    expired_in_event_id     TEXT REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    utes_start              INTEGER NOT NULL,  -- = acquired_in_event.utes_start
    utes_end                INTEGER            -- = expired_in_event.utes_start; NULL = indefinite
) STRICT;

-- ============================================================================
-- 5. SYSTEMS & INSTANCES
-- ============================================================================
CREATE TABLE core_systems (
    system_id              TEXT PRIMARY KEY,   -- "sys.minchah_offering"
    category               TEXT NOT NULL CHECK (category IN
        ('LITURGICAL_RITUAL', 'SUPERNATURAL_ACT', 'LEGAL_CUSTOM', 'SOCIAL_CUSTOM',
         'PROPHETIC_ORACLE', 'THEOPHANY', 'MILITARY_PROTOCOL')),
    first_occurrence_verse TEXT REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED
                                               -- earliest instance in the compiled corpus (linker)
) STRICT;

CREATE TABLE core_system_instances (
    instance_id              TEXT PRIMARY KEY,
    system_id                TEXT NOT NULL REFERENCES core_systems(system_id) DEFERRABLE INITIALLY DEFERRED,
    event_id                 TEXT NOT NULL REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    verse_start              TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    verse_end                TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    utes_timestamp           INTEGER NOT NULL, -- = event.utes_start
    initiator_entity_id      TEXT NOT NULL REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    target_entity_ids_json   TEXT NOT NULL CHECK (json_valid(target_entity_ids_json)),
    artifact_entity_ids_json TEXT NOT NULL CHECK (json_valid(artifact_entity_ids_json)),
    location_entity_id       TEXT REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    tags_json                TEXT NOT NULL CHECK (json_valid(tags_json))
) STRICT;

-- ============================================================================
-- 6. INTERACTION EDGES
-- ============================================================================
CREATE TABLE core_edges (
    edge_id          TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    target_entity_id TEXT NOT NULL REFERENCES core_entities(entity_id) DEFERRABLE INITIALLY DEFERRED,
    interaction_type TEXT NOT NULL,            -- open vocabulary, UPPER_SNAKE: "MOCKED", "FLED_FROM"
    verse_id         TEXT NOT NULL REFERENCES core_verses(verse_id) DEFERRABLE INITIALLY DEFERRED,
    event_id         TEXT NOT NULL REFERENCES core_events(event_id) DEFERRABLE INITIALLY DEFERRED,
    utes_timestamp   INTEGER NOT NULL          -- = event.utes_start
) STRICT;

CREATE INDEX idx_verses_ordinal ON core_verses(ordinal);
CREATE INDEX idx_events_utes ON core_events(utes_start, utes_end);
CREATE INDEX idx_participants_entity ON core_event_participants(entity_id);
CREATE INDEX idx_causal_cause ON core_causal_edges(cause_event_id);
CREATE INDEX idx_causal_effect ON core_causal_edges(effect_event_id);
CREATE INDEX idx_components_entity_utes ON core_components(entity_id, utes_start, utes_end);
CREATE INDEX idx_instances_system ON core_system_instances(system_id, utes_timestamp);
CREATE INDEX idx_edges_source ON core_edges(source_entity_id, utes_timestamp);
CREATE INDEX idx_edges_target ON core_edges(target_entity_id, utes_timestamp);
CREATE INDEX idx_edges_verse ON core_edges(verse_id);
