# URIM — Unified Relational Interpretive Matrix
**Technical & Agentic Architecture Specification (v1.1)**

v1.1 revises v1.0 after checking it against the real source data. Changes are summarized in
[§11](#11-changes-from-v10). The SQL schema lives in [`urim/schema/core.sql`](urim/schema/core.sql)
and [`urim/schema/i18n.sql`](urim/schema/i18n.sql); the IR contract lives in
[`urim/ir/models.py`](urim/ir/models.py). Those files are authoritative. This document explains them.

---

## 1. Summary & principles

URIM is a headless, pre-compiled philological, narrative and temporal knowledge engine for
ancient scripture. It turns source texts and translations into a queryable Entity-Component-System
ontology, a four-layer translation matrix, and a unified temporal and causal graph.

1. **Compile-time heavy, runtime instant.** LLM agents do the philology, event segmentation,
   entity resolution and causal linking at compile time. The output is a set of static,
   read-only SQLite files.
2. **Built like a compiler.** Agents are the *front end*: they emit per-chapter JSON
   **IR** validated by Pydantic. A deterministic **linker** is the *back end*: it resolves
   references, computes every timestamp and derived value, enforces integrity, and writes the
   bundles. Agents never write integers such as timestamps, offsets or elapsed times. IR is
   diffable, reviewable, cacheable and patchable; relinking takes seconds and costs nothing.
3. **Topology and localization are separate.** One language-free **core** bundle holds the
   graph, source text, morphology and timeline. Each language is a hot-swappable bundle keyed
   on core ids. Adding a language never touches the core.
4. **One timeline (UTES).** Every time marker becomes a signed 64-bit count of seconds since
   1970-01-01 on the proleptic Gregorian calendar. Elapsed time is plain subtraction.
5. **One engine, three interfaces.** A Python SDK (`UrimEngine`), a FastAPI REST server, and an
   MCP server expose the same seven operations.

---

## 2. Bundle topology

```text
data/bundles/
├── urim-core.sqlite               language-free: canon, source text + morphology, verse map,
│                                  chronology anchors, events, causality, entities, components,
│                                  systems, interactions
├── lang-en/  i18n_en.sqlite       default English bundle (KJV baseline)
│             manifest.json
└── lang-ru/  i18n_ru.sqlite       pluggable Russian bundle (Synodal baseline)
              manifest.json
```

At runtime the core is opened **read-only and immutable** (`mode=ro&immutable=1`). English is
attached as `lang_en` and the requested language as `lang_active`:

```sql
ATTACH DATABASE 'file:.../lang-ru/i18n_ru.sqlite?mode=ro&immutable=1' AS lang_active;
```

Any text missing from the active bundle falls back to English. For verses, the fallback is per
field: the baseline comes from the active language and the layers from English when the active
bundle has none yet.

**Compatibility.** The linker computes `id_surface_hash` over every core id. Each language
bundle records the hash of the core it was built against, and the engine refuses to mount a
bundle whose hash differs. Re-linking the core with corrected dates or another chronology
keeps the hash, so existing bundles stay valid. Adding, removing or renaming ids changes it.

---

## 3. Sources

| Source | Provides | License |
|---|---|---|
| STEPBible **TAHOT** (TAGNT for the NT, pending) | Hebrew text word by word: transliteration, English gloss, disambiguated Strong's, lemma, ETCBC morphology, Qere/Ketiv, proper-name links; word-level KJV ↔ Hebrew references | CC BY 4.0 |
| STEPBible **TIPNR** | One record per individual: names, dStrongs, references, family links, descriptions | CC BY 4.0 |
| STEPBible **TVTMS** | Versification traditions: cross-check of renumberings, versification notes | CC BY 4.0 |
| scrollmapper/bible_databases | Baselines: KJV, YLT, ASV, BBE, Webster, RusSynodal (more available) | PD texts |
| Sefaria (API v3) | Rashi, Radak, Ralbag, Metzudat David/Zion, Malbim, Targum Jonathan (Hebrew/Aramaic) | per version; recorded |
| OpenBible.info | Coordinates, matched to TIPNR places by shared verse references | CC BY 4.0 |

`urim ingest SCOPE` fetches through a lockfile (`sources.lock.json`): GitHub sources are pinned
to commit SHAs and every file, including each Sefaria response, to a SHA-256. Bundles carry
attribution for the CC BY sources (`core_meta.attribution_json`). Commentaries are compile-time
agent input only and are never shipped in a bundle.

---

## 4. Time: UTES

### 4.1 Definition

`UTES = (JDN(date) − 2440588) × 86400 + seconds_since_midnight`, where `JDN` is the Julian Day
Number of a **proleptic Gregorian** date in astronomical year numbering (1 BCE = 0,
2 BCE = −1). Calendar dates always land on midnight; time-of-day offsets mean what they say.
Implementation: [`urim/utime.py`](urim/utime.py).

The nominal year (365.2425 days = 31,556,952 s) and the synodic month (29.530588 days) are used
only for **durations** ("three years later"), never to locate a calendar date. v1.0 used the
nominal year to locate dates, which put 860 BCE at 23:13 and made its own examples decode to
the wrong hours.

### 4.2 Time-of-day markers

| Code | Term | Clock |
|---|---|---|
| `ASHMORET_HABOKER` | Morning watch, last watch of the night (Exod 14:24) | 02:00 |
| `SHACHAR` | Dawn, first light | 05:30 |
| `BOKER` | Morning, sunrise | 06:00 |
| `HORA_TERTIA` | Third hour | 09:00 |
| `TZOHORAYIM` | Noon, "double light"; also *kchom hayom* | 12:00 |
| `MINCHAH` | *Ba'alot ha-minchah*, the afternoon offering | 15:00 |
| `BEIN_HAARBAYIM` | "Between the evenings", twilight | 17:30 |
| `EREV` | Sunset; start of the Hebrew day and of the first watch | 18:00 |
| `ASHMORET_HATICHONAH` | Middle night watch | 22:00 |

An `HH:MM` clock time is also accepted. The Hebrew day begins at sunset while UTES days begin at
midnight; narrative day-counting is the Chronologist's reasoning, recorded in
`temporal_reasoning_note`.

### 4.3 How an event's time is expressed (IR)

```json
"time": {
  "anchor": "evt.1kgs_18.carmel_contest",   // an event, or a chronology anchor ("anchor.*")
  "anchor_point": "START",                  // or END of the anchor event
  "offset": {"value": 2, "unit": "hours"},  // optional elapsed time from the anchor point
  "time_of_day": "MINCHAH",                 // optional: first such clock time at or after
  "duration": {"value": 30, "unit": "minutes"},
  "margin": {"value": 30, "unit": "minutes"}, // uncertainty relative to the anchor
  "precision_tier": "DIURNAL_HOUR"
}
```

`start = next time_of_day at or after (anchor point + offset)`; `end = start + duration`.
The linker resolves anchor chains in topological order, rejects cycles, and materializes
`utes_start`, `utes_end`, `relative_offset_seconds` (effective), `relative_margin_seconds`, and
`utes_margin_seconds`, the absolute uncertainty summed along the chain.

`precision_tier` is the granularity of the *textual* time indication (MACRO_ERA, REGNAL_YEAR,
SEASONAL_MONTH, DAY_SEQUENCE, DIURNAL_HOUR). Labels are formatted to it.

### 4.4 Chronology anchors and schemes

Root anchors are curated by hand, not generated by an LLM, and live in `chronology.json`
under named schemes. Every scheme defines the same anchor ids. **THIELE** is the default
(Ahab 874–853 BCE, fixed by Qarqar, 853 BCE). Relinking with another scheme
(`urim link core --chronology GALIL`) shifts every absolute date, keeps every relative offset,
and keeps language bundles valid. No agent re-runs.

Narratives before the monarchy have no outside synchronism. Their anchors are derived inside
each scheme from that scheme's own date for Solomon, through the Masoretic numbers, with a
margin wide enough for the main alternatives. `anchor.joseph_birth` is the founding of the
temple in Solomon's fourth year (966 BCE under Thiele) + 480 years to the Exodus (1 Kgs 6:1)
+ 430 years in Egypt (Ex 12:40, MT) + 39 years, Joseph's age at Jacob's descent (Gen 41:46,
45:6): c. 1915 BCE ± 220 years, covering a 13th-century Exodus and the LXX reading of Ex 12:40.
The text's own ages and spans are offsets from such an anchor ("seventeen years old" is 17
years after it), so the story's inner chronology stays exact while its absolute date floats
with the scheme. Genesis carries the chain back with the Masoretic ages: Jacob's birth (91
years before Joseph's, Gen 47:9 with 41:46 and 45:6), Isaac's (Gen 25:26), Abraham's (Gen 21:5,
c. 2166 BCE), the year the Flood began (292 years before Abram by Gen 11:10–26, c. 2458 BCE)
and creation, Anno Mundi 1 (1655 years before the Flood by Gen 5, c. 4113 BCE). From the Flood
back the margin grows by 60 years for Terah's age at Abram's birth (70 or 130). The anchors date
the text's own chronology; the LXX and Samaritan ages would be other schemes.

### 4.5 Causality

`core_causal_edges` always point **cause → effect**:

| Type | Cause | Effect |
|---|---|---|
| `TRIGGERS` | immediate cause | consequence |
| `FULFILLS_PROPHECY` | the oracle | its fulfilment |
| `RETALIATES_FOR` | the offence | the retaliation |
| `ENABLES` | the prerequisite | what it makes possible |
| `DEFERRED_BY` | the deferring act (e.g. repentance) | the deferred outcome |

`elapsed_seconds = effect.utes_start − cause.utes_end`, computed by the linker. It is negative
when the two overlap. The linker rejects an effect that starts before its cause, and any
cycle.

---

## 5. Data model

See the schema files for columns and constraints. Key rules:

**Verses and versification.** `verse_id` uses the **source-text numbering** (WLC for the OT,
Greek for the NT) with uppercased OSIS book codes (`1KGS.18.27`). Other numbering traditions
are aliases in the sparse `core_verse_map` (scheme, scheme_ref → verse_id, FULL/PARTIAL),
populated from TVTMS. The SDK resolves `"KJV:1Kgs.18.33"`, `"1Kgs 18:27"` and `"1KGS.18.27"`.
Baselines are assembled per source verse through the map. In 1 Kings 18:33–34 the KJV places
"Fill four barrels" in 18:33 while the Hebrew and Synodal place it in 18:34. `ordinal =
book_id·10⁶ + chapter·10³ + verse` replaces a dense `sequence_index`, so partial builds stay
stable.

**Tokens.** `tokens_json` holds, per word: surface, transliteration, lemma, disambiguated
Strong's, morphology, `name_ref` (the TIPNR individual a proper noun names) and `reading` (Qere/
Ketiv code when the text departs from plain Leningrad). Word glosses are language data and live
in the bundles; STEPBible's English glosses fill `lang-en` until the Philologist writes its own.

**Entities.** Types: PERSON, DEITY, SPIRIT_BEING, LOCATION, GROUP, ARTIFACT, SUBSTANCE. Ids are
`kind.slug`; ingest proposes them from TIPNR (the most-referenced bearer of a name gets the bare
slug, namesakes a reference suffix: `person.elijah`, `person.elijah.ezr_10_21`). `tipnr_id` is
unique and must exist in the registry. Coordinates are never written by agents: the linker takes
them from the registry (OpenBible, else TIPNR) and records `geo_source` and `geo_confidence`;
explicit IR coordinates override, marked `ir`.

**Event participants.** `core_event_participants(event_id, entity_id, role)`, with roles
AGENT / PATIENT / PRESENT / MENTIONED, drives timeline entity filters and dossiers.

**Components.** Each state opens and closes in a specific event (`acquired_in_event`,
`expired_in_event`); the linker derives `utes_start` and `utes_end` from those events.
Validity is **half-open**: active at verse V when `acquired ≤ V < expired`, and at time t
when `utes_start ≤ t < utes_end`. `supersedes_component_id` records replacement across keys
(Elisha: `economic_tier` → `role`). States opened in one chapter can be closed in a later one
with `component_closures`. Overlapping states for the same (entity, key) are rejected.

**Systems.** Categories: LITURGICAL_RITUAL, SUPERNATURAL_ACT, LEGAL_CUSTOM, SOCIAL_CUSTOM,
PROPHETIC_ORACLE, THEOPHANY, MILITARY_PROTOCOL. `first_occurrence_verse` is derived as the
earliest instance in the compiled corpus.

**Language bundles.** Everything human-readable lives here, including the ancient time
markers, which v1.0 kept in core: `i18n_events.ancient_*_marker`. Also here: `i18n_books`
(localized book names), `i18n_vocab` (labels for enum codes), and `i18n_chronology_anchors`.
Text layers in `i18n_verses` are nullable: a row exists as soon as a baseline exists.

---

## 6. Compiler

### 6.1 Pipeline

```text
ingest (deterministic)            agents (LLM, cached)                   link (deterministic)
──────────────────────            ────────────────────                   ────────────────────
TAHOT, TIPNR, TVTMS,     ──▶  source/{BOOK}.json  ──▶  Philologist  ─┐
scrollmapper, Sefaria,                                 Chronologist ─┼─▶  core/*.json      ──▶  urim-core.sqlite
OpenBible                     chronology.json (curated) Ontologist  ─┤    i18n/en/*.json   ──▶  lang-en/
                                                        Critic (LLM) ─┘    i18n/{iso}/*.json ──▶  lang-{iso}/
                                                        Localizer ───────▶
```

* **IR directory**: `source/`, `registry/entities.json` and `commentary/` (all from ingest),
  `chronology.json` (curated), `core/` and `i18n/{lang}/` (agents). Layout and models are in
  [`urim/ir/models.py`](urim/ir/models.py). The models double as the structured-output schemas
  for the LLM calls.
* **Registry**: every TIPNR individual mentioned in the ingested text, with token-level
  mentions, names, family links, descriptions, proposed id and coordinates. It is the
  Ontologist's lookup table; the linker uses it to check identities and first mentions.
  Books are written in any order, so an entity defined in one book may be named earlier in
  another: the bundle records the earliest mention, and only an earlier mention in the
  entity's own book is reported.
* **Linker** ([`urim/compiler/link.py`](urim/compiler/link.py)) is the deterministic half of the
  Sanhedrin Critic. It checks unknown references, duplicate ids, reversed verse ranges, anchor
  cycles, causal order and cycles, component overlaps, gloss positions, and orphaned
  translations, and it writes nothing while any error remains. The same IR always yields a
  byte-identical core.
* **LLM cache**: every agent call is keyed by a hash of (model, prompt version, input).
  Recompiles are free, and results are reproducible.
* **Stable ids**: agents propose slugs; an id lockfile keyed by (chapter, verse range, kind,
  slug) keeps ids stable across reruns so language bundles survive core recompiles.
* **Overrides**: human corrections live in a separate patch layer applied to IR before linking,
  so they survive agent reruns.

### 6.2 Agents

| Agent | Input | Output |
|---|---|---|
| **Philologist** | source tokens + morphology, 5 English baselines, Hebrew commentaries, TBESH | `i18n/en` verse layers, notes, glosses |
| **Chronologist** | chapter, Philologist output, rolling temporal state, anchors | events with `time` specs, participants, causal edges |
| **Ontologist** | chapter, TIPNR-seeded entity registry, system registry | entities, components and closures, systems, instances, interaction edges |
| **Critic (LLM)** | IR + linker report | semantic review: unsupported claims, missed events, wrong roles |
| **Localizer** | `i18n/en` IR, source tokens, target baseline, the language's names so far | `i18n/{iso}` IR (verses translated from the Hebrew), interface messages, bundle labels; see §6.6 |

The agent directives from v1.0 still apply. Layer 1 is ultra-literal with idioms and
euphemisms kept; Layer 2 is dramatic literary prose; Layer 3 is a historical, cultural and
linguistic commentary that explicitly audits where the baseline sanitized the text.
Commentary claims should cite the ingested sources (`philological_notes[].sources`).

Physical durations (travel, chariot runs) are derived from coordinates and a speed table by
code. The Chronologist chooses the mode of travel and the route; it does not do the arithmetic.

### 6.3 Session workbench

Agents can be Claude Code chats rather than API calls. A skill runs `urim task <agent> <scope>`
for a Markdown work packet, the session writes a **fragment** (one per agent, see
[`urim/workbench/fragments.py`](urim/workbench/fragments.py)) and `urim ir merge` folds it into
`corpus/`. Ownership: chronology owns events, timing and causality; ontology owns entities and
every event-to-entity link (participants, place), states, rituals and interactions; philology
owns verse layers. A fragment is authoritative for its agent's items in its chapter (philology:
for its verses only); approved items are locked; nothing is written until the merged corpus
links. The per-chapter ledger in `corpus/ledger/` records producer (model, skill version, date),
agent notes and review history.

### 6.4 Autonomous runs

`urim run <book>` (or a range, `GEN.38-40`) does the session loop unattended. The conductor is
code, not a model ([`urim/conductor/`](urim/conductor/)): it plans each step from the corpus and
its ledger, so a run that stops resumes by planning again, and it keeps no context to fill over
hundreds of sessions. Each step is a headless Claude Code session (`claude -p "/urim-… <scope>"`)
with the project skills, told it runs alone, kept from the gold, and limited to the tools the
skills need.

- Order: chronology one chapter at a time (each builds on the settled dates of the last);
  ontology after its chapter's chronology and its own previous chapter; philology windows of
  twelve verses side by side once a chapter's events are settled. Up to `--parallel` sessions
  at once; merges take a lock on the corpus.
- Review: after each layer of a chapter the critic writes a JSON report (`urim schema critic`,
  [`urim/workbench/critique.py`](urim/workbench/critique.py)). The run applies it in the
  critic's name: blocker and should-fix findings send the item back with the change request at
  the top of the next packet, every other reviewed draft is approved and locked, `consider`
  findings travel with the approval as advice. An agent that keeps an item unchanged sends it
  back to the critic. After `--rounds` sendings back (default 2) the last critique escalates
  what is still disputed: it stays a draft with the critic's note, for the user. Every decision
  records who made it (`by` in the ledger history); the user can reopen anything.
- Models: Sonnet 5.5 writes and Opus 5.5 critiques by default, per agent with `--model`.
- Limits: a usage limit pauses the run until the time the CLI reports, then it resumes. An
  API failure that is not about the session's own request (an account refusal, an outage, an
  overload) pauses it too, for 10 minutes doubling to 2 hours, with one desktop alert, and
  counts against no layer. A session that fails on its own work counts; three in a row mark
  the layer failed, and running the run again retries it.
- Unattended sessions are told that only `uv run urim …` runs: scripts, pipes and heredocs
  wait for an approval nobody can give, so fragments are written with Write and fixed with
  Edit.
- State: `work/run/<name>.json` (phases per chapter layer, steps with tokens, cost and the
  session's report, a log) and one transcript per session; the War Room's Campaign view reads
  it live, and the run ends with `work/run/<name>/report.md`.

### 6.5 Model selection

Every agent's model is configurable. For the PoC, each agent runs with **Claude Opus 5.5**,
**Sonnet 5.5** and **Haiku 5.5** and is scored against the golden fixture IR. See PLAN.md,
Phase 2.

---

### 6.6 Localization

Everything a reader sees exists in English first and can be translated by the localizer
(`/urim-localizer <lang> <scope>`, [`urim/workbench/localize.py`](urim/workbench/localize.py)):

| Scope | What | From |
|---|---|---|
| `GEN.38` | a chapter's event, link, entity, system, state, ritual and interaction texts | the English texts |
| `GEN.38.1-12` | verses: literal and dramatic layers and word glosses; commentary and notes | the Hebrew, with the English layers and the language's own Bible beside it; commentary and notes from the English |
| `ui.<namespace>` | the interface messages of one screen of the War Room or the Codex | `urim/i18n/en/<namespace>.json` |
| `bundle` | book names, vocabulary labels, chronology anchors | the English bundle |

- A translation is a fragment like any other and merges with `urim ir merge`. Chapter texts
  and verses are ledger items of their chapter keyed by language (`event.ru:evt.…`,
  `verse.ru:GEN.38.4`), reviewed like the English ones; a language is a layer the critic can
  review (`/urim-critic GEN.38 ru`).
- Each translation remembers a hash of the English it was made from (`source` in the ledger;
  `corpus/ledger/lang/<lang>.json` for messages and labels). When the English changes the
  translation is stale: it shows as work again, and its approval no longer locks it.
- Interface messages: English is written with the code (`urim/i18n/en/*.json`, a key → text,
  or plural forms, with a note for the translator); translations go to
  `corpus/i18n/<lang>/_ui.json`. Placeholders (`{name}`) must survive, counted messages take
  one form per CLDR plural category of the language. The apps call `t(key, vars)`; a missing
  translation falls back to English per message, and so does a missing corpus text, which the
  Codex marks.
- `urim run <book> --lang ru` adds the language as a layer: the interface and the bundle
  first, a chapter's texts once its English chronology and ontology are settled, its verses
  in windows once their philology is, then the critic. Progress: `urim lang [ru]` and the War
  Room's Languages view (per chapter and screen: missing, stale, translated, approved).
- A new language starts with `corpus/i18n/<lang>/_bundle.json` (code, name, its own Bible as
  baseline, pinned and ingested); the localizer writes the rest.

## 7. Runtime API

All three interfaces expose the same operations; every one takes `lang` (default `en`).

| Operation | Returns |
|---|---|
| `get_verse_matrix(verse_id, lang, include_ecs=True)` | source text + tokens (with glosses), aliases, baseline, three layers, covering events, active entities / components / instances / interactions |
| `get_chapter_stream(book_code, chapter, lang)` | ordered verse matrices + chapter events + causal links |
| `get_entity_dossier(entity_id, lang, at_utes=None, at_verse=None)` | profile, geo, component history or snapshot, interactions, events |
| `get_system_codex(system_id, lang)` | rules and context + every instance in order |
| `query_timeline(utes_start, utes_end, entity_filter=None, lang)` | events in order with Δt to the previous event, causes and effects |
| `trace_causal_chain(event_id, direction, depth, lang)` | causal subgraph with elapsed seconds per link |
| `semantic_search(query, lang, scope, top_k, mode)` | hits across verses, entities, systems, events |
| `find_similar(kind, item_id, lang, scope, top_k, same_type)` | the items nearest in meaning to one in the corpus |

The SDK also offers `resolve_ref`, `get_event` and `languages`. `semantic_search` has three
modes. `keyword` is FTS5/BM25 with a title (a name, an event's title) weighted ten times a
body word, and the last word matched as a prefix, so results follow typing. `meaning` embeds
the query and ranks by cosine similarity alone, for concepts and paraphrases that share no
word with the text ("deception with a garment"); it needs a bundle with vectors (an
`i18n_vectors` **sqlite-vec** table inside each `i18n_{iso}.sqlite`, so a language bundle
remains a single file) and the model they were built with. `hybrid`, the default, runs both
and fuses the rankings by reciprocal rank (k = 60); without vectors it is keyword search.
Outside `meaning`, entities and systems the query names come first, by name or alias
("Israel" finds Jacob) or by a name being typed ("Elij"). Each hit says which search found it
(`via`) and, when found by meaning, its cosine `similarity`. `find_similar` compares the
vector the bundle stores for an item, so it needs vectors but not the model; `same_type` keeps
entities of the item's type. The model is **bge-m3** (int8 ONNX, 1024 dimensions,
multilingual, so a Russian query finds English text), pinned in `sources.lock.json` and
installed with `urim model fetch`; its runtime (ONNX Runtime, tokenizers, sqlite-vec) is the
optional extra `urim[search]`. Linking caches vectors by text hash, so relinks embed only
what changed.

REST routes: `/languages`, `/verses/{ref}`, `/chapters/{book}/{ch}`, `/entities/{id}`,
`/systems/{id}`, `/timeline`, `/events/{id}/causal-chain`, `/search`,
`/similar/{kind}/{id}`. MCP: the eight tools, via the MCP Python SDK 2.x (`MCPServer`).

---

### 7.1 Review app ("War Room")

`urim review` serves a local web app for reviewing agent output, built as a strategy-game HUD:
Command (canon territory, rank, missions, honours), Learn, Campaign, Languages, Review deck,
X-Ray, Chronicle, Causal web, Atlas, Dossiers, Codex and Query. Both apps speak the language
chosen in their header (§6.6). Decisions write to the corpus ledger;
everything else is read from the bundles, which the server remounts after each relink. The SQL
console runs on a read-only, immutable connection with an authorizer that allows only reads.

### 7.2 Learning

Once a book is written, the War Room is for learning it ([`urim/learn/`](urim/learn/)). Quiz
questions are views of the linked data, built by code: no model writes them, so they always
agree with the corpus, and a question's id (`kind|chapter|subject|seed`) rebuilds it on the
server to check the answer.

| Family | Kinds |
|---|---|
| Story | who took part in a scene and in what role; which scene a passage tells; what caused an event; a state and how it changed; who did what to whom |
| Time and place | put scenes in the order they happened (by the linked timeline, which may differ from the telling); click the place on a map (scored by distance); choose the place; how long between two scenes; how old someone was (within the linked margins) |
| Hebrew and text | what a Hebrew word means in its verse; which word means a gloss; fill in a word of the verse |

Wrong choices come from the same book, and from search by meaning when the bundle has vectors,
so they are plausible; names that would give an answer away are masked. Answers go to
`data/learner.sqlite` (personal, never committed): one card per fact, scheduled by a small
SM-2 (a fact counts as known at a three-week interval), so practice brings back what is due
before what is new. A chapter's mastery is the share of its facts known; an exam of fifteen
questions across every kind, passed at 80%, proves it. Retelling a chapter from memory is the
one kind graded by a model: a headless Claude session compares the text with the chapter's
events and returns what was covered, missed and contradicted. The Command map has a Knowing
layer (violet for mastery, gold for proven) and each Codex chapter ends with a link to test it.

## 8. Stack

Python 3.13 (uv-managed) · Pydantic v2 · stdlib `sqlite3` with `STRICT` tables, no ORM ·
React 19 + TypeScript + Vite + D3 + dagre for the review app ·
FTS5 → sqlite-vec · Typer · FastAPI + Uvicorn · MCP SDK 2.x · Anthropic SDK (structured
outputs, Message Batches, prompt caching) · pytest + Hypothesis · Ruff.

---

## 9. Repository layout

```text
urim/
├── SPEC.md, PLAN.md, pyproject.toml
├── fixtures/ir/                     golden IR for 1 Kings 17–19: ingested source + registry, hand-authored core/i18n
├── urim/
│   ├── utime.py                     UTES math, JDN, time-of-day markers
│   ├── canon.py                     books, verse refs, translation → versification scheme
│   ├── bundles.py                   on-disk bundle layout
│   ├── schema/core.sql, i18n.sql
│   ├── ir/models.py, load.py        the IR contract
│   ├── compiler/link.py             linker + deterministic critic
│   ├── compiler/ingest/             fetch (lockfile) · tahot · tvtms · tipnr · geo · sefaria · build
│   ├── compiler/agents/             Phase 2
│   ├── workbench/                   packets, fragments, merge, ledger, critique (critic reports)
│   ├── conductor/                   urim run: plan from the corpus, headless sessions, run state
│   ├── learn/                       quiz kinds, sessions, spaced repetition, retelling grader
│   ├── i18n/                        interface messages (en/*.json), translators, language progress
│   ├── runtime/engine.py, models.py
│   ├── interfaces/rest_api.py, mcp_server.py
│   └── cli.py                       urim ingest · link · validate · task · ir merge · run · review · serve · mcp
├── sources.lock.json                pinned source URLs and SHA-256s
└── tests/
```

---

## 10. PoC acceptance criteria (v0.1)

Fragment: **1 Kings 17:1–19:21, 91 verses** (24 + 46 + 21; v1.0 said 113). The same assertions
run against the golden fixture now and against agent output in Phase 2
([`tests/test_acceptance.py`](tests/test_acceptance.py)).

1. **Multi-layer fidelity.** `get_verse_matrix("1KGS.18.27")` in `en` and `ru` returns the
   vocalized Hebrew, the KJV / Synodal baseline, the literal and dramatic layers, and a
   commentary that explains **שִׂיג** (*sig*).
2. **UTES deltas.**
   a. `chariot_run_to_jezreel.utes_end − minchah_fire.utes_start` ∈ [14,400, 18,000]
      (fixture: 16,200 = 15:00 → 19:30).
   b. `journey_to_horeb` lasts exactly 3,456,000 s (40 days). The forty days are counted
      from the broom tree (19:8). From leaving Beersheba (19:4) to arrival is 41–43 days,
      because a day's journey (19:4) and a day under the broom tree (19:5–7) come first.
      v1.0 asserted 40 days from 19:3.
3. **Component transition.** At `1KGS.19.19` Elisha has `economic_tier = Wealthy landowner
   (12 yoke of oxen)`. At `1KGS.19.21` that state has expired and `role = Attendant of
   Elijah` (target `person.elijah`, superseding it) is active. The same holds by `at_utes`.
4. **Zero-recompile hot-swap.** Building `lang-en` and `lang-ru` and serving queries in
   both leaves `urim-core.sqlite` byte-identical. The Russian bundle covers every core
   id: entities, events, causal edges, components, systems, instances, interactions, and a
   Synodal baseline for every verse.

---

## 11. Changes from v1.0

1. UTES locates dates through Julian Day Numbers; the nominal year is used only for durations.
2. Diurnal table: separated dawn (`SHACHAR`, 05:30) from the morning watch
   (`ASHMORET_HABOKER`, 02:00); defined "first at or after" snapping.
3. Event time is IR (`anchor + offset + time_of_day + duration + margin`), materialized by the
   linker. Root dates are curated chronology anchors under switchable schemes.
4. Source-text versification with `core_verse_map` aliases; `ordinal` replaces `sequence_index`.
5. Causal edges always point cause → effect; elapsed time is computed and may be negative.
6. Components are bound to events, use half-open validity, and can supersede and be closed in
   later chapters. The dossier gains `at_verse`.
7. Core is language-free: ancient markers moved to `i18n_events`; added `i18n_books`,
   `i18n_vocab` and `i18n_chronology_anchors`.
8. Bundles pin the core `id_surface_hash`; the engine refuses stale bundles.
9. sqlite-vec inside each language file replaces ChromaDB; FTS5 until vectors exist.
10. The compiler is front end / IR / linker; the Critic is split into a deterministic linker and
    an LLM review.
11. Added SPIRIT_BEING, SOCIAL_CUSTOM and event participants; `STRICT` tables with deferred FKs.
12. Acceptance criteria corrected (91 verses; Horeb counted from the broom tree).
13. Phase 1: TAHOT replaces OSHB and provides the KJV map at word level; TVTMS cross-checks;
    TBESH dropped (TAHOT carries lemmas); entity registry from TIPNR with OpenBible coordinates;
    `geo_source` / `geo_confidence` on entities; `name_ref` / `reading` on tokens.
