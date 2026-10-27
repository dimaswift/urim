-- i18n_{iso}.sqlite: one pluggable language bundle. Every row keys on a core id; SQLite cannot
-- enforce foreign keys across ATTACHed databases, so the linker checks coverage instead.
-- Text layers are nullable: a verse row exists as soon as a baseline exists, and layers fill in
-- as chapters are compiled. The engine falls back to the English bundle for missing rows.

CREATE TABLE bundle_manifest (
    lang_code                TEXT PRIMARY KEY,  -- ISO 639-1
    lang_name                TEXT NOT NULL,
    urim_core_version        TEXT NOT NULL,
    core_id_surface_hash     TEXT NOT NULL,     -- must equal core_meta.id_surface_hash
    baseline_translation     TEXT NOT NULL,     -- "KJV", "RusSynodal"
    source_translations_json TEXT NOT NULL CHECK (json_valid(source_translations_json)),
    embedding_model          TEXT,              -- NULL until vectors are built
    compiled_at              TEXT NOT NULL
) STRICT;

CREATE TABLE i18n_books (
    book_id      INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,                 -- "1 Kings" / "3-я книга Царств"
    abbreviation TEXT NOT NULL
) STRICT;

-- Labels for core enum codes: diurnal markers, precision tiers, causal types, ...
CREATE TABLE i18n_vocab (
    kind  TEXT NOT NULL,                        -- "diurnal", "precision_tier", "causal_type", ...
    code  TEXT NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY (kind, code)
) STRICT;

CREATE TABLE i18n_chronology_anchors (
    anchor_id TEXT PRIMARY KEY,
    label     TEXT NOT NULL,
    note      TEXT NOT NULL
) STRICT;

CREATE TABLE i18n_verses (
    verse_id                TEXT PRIMARY KEY,
    traditional_baseline    TEXT NOT NULL,      -- assembled through core_verse_map
    translation_literal     TEXT,               -- Layer 1: "The X-Ray"
    translation_dramatic    TEXT,               -- Layer 2: "The Cinema"
    directors_commentary    TEXT,               -- Layer 3: "The Context"
    philological_notes_json TEXT CHECK (philological_notes_json IS NULL OR json_valid(philological_notes_json)),
    token_glosses_json      TEXT CHECK (token_glosses_json IS NULL OR json_valid(token_glosses_json))
) STRICT;

CREATE TABLE i18n_events (
    event_id                TEXT PRIMARY KEY,
    title                   TEXT NOT NULL,
    narrative_summary       TEXT NOT NULL,
    temporal_reasoning_note TEXT NOT NULL,
    ancient_year_marker     TEXT,               -- "3rd year of the drought"
    ancient_season_marker   TEXT,
    ancient_diurnal_marker  TEXT
) STRICT;

CREATE TABLE i18n_causal_edges (
    causal_id          TEXT PRIMARY KEY,
    causal_explanation TEXT NOT NULL
) STRICT;

CREATE TABLE i18n_entities (
    entity_id         TEXT PRIMARY KEY,
    canonical_name    TEXT NOT NULL,            -- traditional name: "Elijah" / "Илия"
    phonetic_name     TEXT NOT NULL,            -- Hebrew phonetics: "Eliyahu" / "Элиягу"
    aliases_json      TEXT NOT NULL CHECK (json_valid(aliases_json)),
    etymology_meaning TEXT NOT NULL,
    summary_bio       TEXT NOT NULL
) STRICT;

CREATE TABLE i18n_components (
    component_id         TEXT PRIMARY KEY,
    label_key            TEXT NOT NULL,
    label_value          TEXT NOT NULL,
    evidence_explanation TEXT NOT NULL
) STRICT;

CREATE TABLE i18n_systems (
    system_id                 TEXT PRIMARY KEY,
    name                      TEXT NOT NULL,
    ancient_near_east_context TEXT NOT NULL,
    rules_and_mechanics_json  TEXT NOT NULL CHECK (json_valid(rules_and_mechanics_json))
) STRICT;

CREATE TABLE i18n_system_instances (
    instance_id       TEXT PRIMARY KEY,
    outcome_summary   TEXT NOT NULL,
    significance_note TEXT NOT NULL
) STRICT;

CREATE TABLE i18n_edges (
    edge_id           TEXT PRIMARY KEY,
    interaction_label TEXT NOT NULL,
    description       TEXT NOT NULL
) STRICT;

-- Keyword index used by semantic_search until vectors (sqlite-vec) are built in Phase 3.
CREATE VIRTUAL TABLE i18n_search USING fts5(
    doc_kind UNINDEXED,                         -- "verse" | "entity" | "system" | "event"
    doc_id UNINDEXED,
    title,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);
