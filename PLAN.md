# URIM build plan

PoC fragment: **1 Kings 17–19** (91 verses). It has an extra-biblical date anchor (Ahab at
Qarqar, 853 BCE), a KJV/Hebrew verse-numbering split inside the range (18:33–34), diurnal
and multi-day timing, rituals, a theophany, and a succession. A second fragment,
**Genesis 18–19**, will test generalization: dense diurnal sequencing (heat of the day → evening
→ dawn → sunrise), a prophecy fulfilled a year later (18:10 → 21:2), name and state changes,
and no absolute anchor.

## Decisions (2026-10-27)

| Topic | Decision |
|---|---|
| Vector store | sqlite-vec inside each `i18n_{iso}.sqlite`; FTS5 keyword search until Phase 3 |
| Chronology | Thiele as the default scheme; schemes are switchable at link time |
| Verse numbering | Source text (WLC / Greek) is canonical; KJV, Synodal, … are aliases via TVTMS |
| Calendar | Proleptic Gregorian, day arithmetic via Julian Day Numbers |
| LLM models | Run every agent with Opus 5.5, Sonnet 5.5 and Haiku 5.5 on the PoC; pick per agent from measurements |
| Architecture | Compiler: agents → JSON IR → deterministic linker → SQLite |
| Python | 3.13, uv-managed (sqlite-vec needs `enable_load_extension`) |
| MCP | SDK 2.x `MCPServer` (FastMCP was renamed in 2.0) |

## Phase 0: skeleton without LLM ✅

- [x] uv project, Ruff, pytest + Hypothesis
- [x] `utime.py`: JDN-based UTES, BCE numbering, diurnal markers, round-trip property tests
- [x] Schema v1.1 (`STRICT`, deferred FKs, verse map, chronology anchors, participants)
- [x] IR models + loader
- [x] Source fixture for 1 Kings 17–19 from OSHB + scrollmapper (KJV, Synodal)
- [x] Hand-authored golden IR: 19 events, 16 entities, 9 causal links, 4 components, 5 systems
      (en full; ru covers every id, layers for 18:27 and 19:19)
- [x] Linker + deterministic critic; reproducible core builds; chronology switching
- [x] `UrimEngine` with all 7 operations + `resolve_ref` / `get_event`; English fallback
- [x] REST (FastAPI) and MCP adapters; CLI
- [x] Acceptance criteria 1–4 passing against the golden IR (53 tests)

## Phase 1: ingest (deterministic, no LLM) ✅

`urim ingest 1KGS.17-19` → `build/ir/{source,registry,commentary}`. A fresh ingest reproduces
the committed fixture byte for byte (tested whenever `data/sources` exists).

- [x] Fetch layer: GitHub sources pinned to commit SHAs, every file's SHA-256 in
      `sources.lock.json`; changed bytes fail loudly, `--refresh` re-pins
- [x] STEPBible TAHOT → tokens (surface, stress-marked transliteration, dStrong, lemma, ETCBC
      morphology, Qere/Ketiv reading, TIPNR name link) and STEPBible English word glosses
- [x] KJV ↔ Hebrew verse map derived from TAHOT's **word-level** references (exact: Hebrew
      18:34 words 1–10 are KJV 18:33); TVTMS cross-checks every whole-verse renumbering and
      contributes versification notes
- [x] scrollmapper baselines: KJV, YLT, ASV, BBE, Webster (KJV numbering), RusSynodal
- [x] TIPNR → entity registry: 31 individuals in 1 Kings 17–19, joined on dStrong, with
      token-level mentions, family links, descriptions and proposed ids (`person.elijah`;
      namesakes get a reference suffix)
- [x] OpenBible → coordinates for 14 of 15 places by shared verse references, with vote-based
      confidence (Tishbe falls back to TIPNR's map link)
- [x] Sefaria (API v3, cached and pinned): Rashi, Radak, Ralbag, Metzudat David, Metzudat Zion,
      Malbim, Targum Jonathan → `commentary/{BOOK}.json` (agent input; not committed, not shipped)
- [x] Linker: coordinates come from the registry (IR geo is an override, provenance recorded);
      TIPNR identities must be unique; first mentions are checked against real mentions;
      English word glosses fill every verse until the Philologist writes its own
- [x] Fixture regenerated from the ingest; gold entities carry TIPNR ids

Deviations and open items:

- **Synodal numbering**: TVTMS has no Synodal tradition. RusSynodal is treated as Hebrew
  numbering, which holds for 1 Kings 17–19 (verified at 18:33–34) but not for e.g. Psalms.
  Candidate source for a real map: the SWORD project's Synodal versification.
- **Sub-verse baselines**: KJV text can't be split at a Hebrew word boundary without an
  English–Hebrew alignment, so a split verse still shows the whole KJV verse(s) it overlaps,
  flagged PARTIAL in the map. Revisit with the Philologist's alignment in Phase 2.
- **TBESH** dropped: TAHOT already carries the lemma and gloss for every word.
- **WEB** (eBible.org) not added yet; five English baselines are enough for the Philologist.
- **STEPBible tagging quirk**: the nation "Israel" carries Jacob's dStrong, so the registry
  lists Jacob/Israel with 14 mentions; the Ontologist must resolve nation vs patriarch.
- **Licenses**: Sefaria reports Radak's digitization as "unknown"; commentaries stay
  compile-time input only.

## Phase 2: agents + model comparison

Prerequisite: Anthropic credentials (`ant auth login` or `ANTHROPIC_API_KEY`).

- [ ] `compiler/llm.py`: Anthropic SDK, `messages.parse()` with the IR models as structured
      outputs (forced `tool_choice` is rejected on Opus 5.5 / Sonnet 5.5), explicit `effort`,
      prompt caching on the shared per-chapter source bundle, content-addressed response cache,
      Message Batches for large runs
- [ ] Id lockfile and override layer
- [ ] Philologist → `i18n/en`; Chronologist → events / time / causality; Ontologist → ECS;
      Critic (LLM) → review notes
- [ ] `urim compile-core --chapters 1KGS.17-19 --model {opus,sonnet,haiku}` writes to
      `build/runs/{model}/ir/`, then links and runs the acceptance tests on each run

**Comparison harness** (`urim eval`), per agent and model, against the golden fixture:

| Agent | Automatic metrics | Judged |
|---|---|---|
| Philologist | verse coverage, gloss alignment, notes present, baseline-audit present | blind pairwise vs gold and across models (Opus 5.5 judge) + human spot-check of ~10 verses |
| Chronologist | linker pass, event-boundary F1 (verse-range IoU), relative offsets within margin, causal-edge F1 | temporal reasoning notes |
| Ontologist | entity P/R, component transitions, instance F1 | — |
| All | cost and latency per chapter (from `usage`) | — |

Decision rule: per agent, the cheapest model whose scores stay within an agreed tolerance of
Opus. Cost basis (Anthropic list prices, Oct 2026, per 1M input/output tokens): Opus 5.5 $4 /
$20, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50 for prompts up to 100K tokens ($0.50 / $2.50
beyond). Batches are 50% off. Keep per-chapter prompts under 100K tokens so Haiku stays in its
cheap tier.

## Phase 3: localization + vectors

- [ ] Localizer agent → `i18n/ru` for 1 Kings 17–19, aligned to source tokens, auditing the Synodal
- [ ] `urim compile-lang --lang ru` end to end (Localizer + link + package `.urim-lang` zip)
- [ ] Embeddings (bge-m3 or similar with an ONNX build) → sqlite-vec table in each bundle;
      `semantic_search` becomes hybrid vector + BM25
- [ ] Query-time embedding as the `urim[search]` extra

## Phase 4: scale

- [ ] Genesis 18–19 as the generalization test (floating chronology)
- [ ] Process in chronological narrative arcs (Kings and Chronicles interleave), parallel where
      the rolling state allows
- [ ] Batch API for the full canon; measured cost per chapter decides the model mix
- [ ] Additional chronology schemes (e.g. Galil) for the divided monarchy

## Open questions

- Which absolute frame to use for pre-monarchic narratives (Genesis): Masoretic Anno Mundi with
  very wide margins, or "floating" events with relative anchors only?
- How much human review per chapter before a bundle ships?
