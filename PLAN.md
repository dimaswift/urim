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
| Agents | Claude Code sessions on the subscription, driven by project skills; API pipeline later for speed |
| LLM models | Compare Opus 5.5, Sonnet 5.5 and Haiku 5.5 per agent (subagents) on the PoC; pick per agent from measurements |
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

## Phase 2: session-driven agents + review game

Agents are **Claude Code chats on the subscription**, not API calls: you open a chat, invoke a
skill, it does one bounded task and you review the result. Produce a solid body of reviewed
output by hand first; the same skills become API prompts later if speed is needed (Phase 4).

The loop: `/urim-<agent> SCOPE` → `urim task` writes a compact work packet → the session writes
a fragment JSON → `urim ir merge` validates it (schema, ownership, locks, full link) and merges
it into `corpus/`, recording model, skill version and date → you review in the review app,
approve or request changes → commit.

**M1: workbench** (deterministic, no model calls) ✅
- [x] `corpus/` (committed): curated `chronology.json` and bundle labels, agent-written `core/`
      and `i18n/`, a review ledger per chapter; ingest output stays in `build/ir` as inputs;
      paths in `[tool.urim]`
- [x] Fragment schemas (`urim schema <agent>`). Ownership: chronology owns events, timing and
      causality; ontology owns entities and every link from an event to an entity
      (participants and place), states, rituals, interactions; philology owns verse layers
      and glosses
- [x] `urim ir merge`: ownership and scope checks, approved items locked, a full link in a
      scratch copy before anything is written, provenance and agent notes into the ledger,
      bundles relinked
- [x] `urim task <agent> <scope>`: Markdown packets of 8–17K tokens with rolling context
      (earlier events with dates, anchors, distances between places, registry, known
      entities, open states, systems, locked items, your change requests first)
- [x] `urim status` (chronology and ontology suggested one chapter at a time), `urim ledger`,
      `urim approve`, `urim request-changes`, `urim reopen`
- [x] Proof: the gold, split into fragments and merged chapter by chapter into an empty corpus,
      rebuilds a core identical to the gold (same content hash)

**M2: review game ("War Room")** ✅ first playable version
- [x] `urim review` (port 8765) serves the API (`urim/review/server.py`) and the built frontend
      (`review/`: React 19, TypeScript, Vite, D3, dagre, bundled fonts, no CDN at runtime);
      `urim review --demo` plays on a demo corpus built from the gold through the real
      workbench (`runs/demo/`, never touches `corpus/`)
- [x] Command: the canon as fog-of-war territory (1,189 chapter tiles: fog, revealed, written,
      held), commander rank/XP/streak, front-line rings, missions (agent commands copy to the
      clipboard), honours
- [x] Review deck: cards in reading order per kind, agent intel, your orders, provenance and
      history; A approve, R send back with a note, S/→ skip, ← back, O open; XP toasts, rank-up
- [x] X-Ray: pointed Hebrew, RTL interlinear with hover cards (decoded morphology, lemma,
      Strong's, TIPNR link), layer tabs with a tradition-vs-literal audit, philology cards, ECS
- [x] Chronicle: zoom from years to hours with uncertainty whiskers and a 24-hour day dial
      marked with the ancient hours; Causal web: dagre DAG, focus lights up a whole chain
- [x] Atlas: Natural Earth basemap (pinned, clipped, 211 KB, `urim basemap`), places with
      confidence halos, journeys animated stop by stop
- [x] Dossiers (RPG sheets: stats, per-verse appearances, state timeline), Codex (collectible
      ritual cards), Query (search + read-only SQL console behind a SQLite authorizer)
- [x] Illuminated Codex (`/codex`): the same data as a reader with no review logic. Folio
      (polyglot page: translation and Hebrew side by side, event rubrics, illuminated initial,
      KJV / word-for-word / drama switch, tap a verse to unfold the interlinear, translations,
      commentary and notes), Persons & Places (dramatis personae, story, states as ribbons),
      a parchment map with journeys by stage, and a Book of Hours (days, interludes of elapsed
      time, an illuminated wheel of the ancient hours)
- [ ] Later: keyboard-driven map, per-chapter briefing screen, timeline of your own review
      activity, localized UI chrome for `ru` (content already switches)


**M3: skills**
- [x] Project `CLAUDE.md`: layout, commands, ownership, and the rules (corpus only through
      merges, review decisions are the user's, no reading the gold during agent work, no
      timestamps or coordinates in IR, provenance, no commits)
- [x] `.claude/skills/`: `urim-chronologist`, `urim-ontologist`, `urim-philologist` (procedure:
      packet → schema → fragment → dry-run merge → merge → report; the v1.0 directives as
      concrete rules; worked examples from outside 1 Kings 17–19 so they cannot leak the gold)
      and `urim-critic` (checks meaning against the text, writes `work/critic/<chapter>.md`,
      sends back only what the user picks)
- [x] `urim travel A B [C…] --mode`: journey times from coordinates (great-circle × 1.25,
      a speed table per mode), so sessions choose route and mode and code does the arithmetic
- [x] Chronology merges print the linked timeline (start, end, duration, relative and absolute
      margin, how each event is anchored, elapsed time per causal link); `urim timeline <ch>`
      prints it for the corpus
- [ ] First real session: `/urim-chronologist 1KGS.17` (no gold beyond the opening oath)

**M4: model comparison** on 1 Kings 18–19 against the gold fixture: `/urim-compare` runs the
same packet through Opus, Sonnet and Haiku subagents into `runs/<model>/`; `urim eval` scores
them (event F1, relative timing within margins, causal F1, entity P/R by TIPNR id, state
transitions, acceptance tests 1–4, philology checks plus a blind judge subagent). Result: a
default model per skill. All of it counts against the subscription allowance, not API billing.

### Review game

Reviewing should feel like playing, not auditing. Planned elements, to be designed with you:

- **Progress map**: the canon as a tile world, books as regions and chapters as tiles that fill
  in as layers are written and approved; streaks, milestones and per-layer completion
- **Review deck**: pending items as cards with one-key approve / request changes / flag,
  showing the agent's own uncertainty notes; requested changes become the next session's tasks
- **Verse X-ray**: interlinear Hebrew with hover cards (lemma, decoded morphology, gloss, linked
  entity), layer toggles, baseline-versus-literal differences highlighted
- **Timeline**: zoom from centuries down to a single day's clock (dawn → noon → minchah →
  Jezreel at 19:30), with uncertainty shown as bands
- **Causal graph**: the event DAG with typed edges and elapsed times; click to trace
- **Map**: places with confidence, journeys animated along the timeline
- **Character sheets**: RPG-style entity cards with state bars over verses, possessions,
  relationships and appearances across chapters; rituals as collectible codex cards
- **Query tools**: search, filters (who, where, when), timeline brushing, and a read-only SQL
  console for power use

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
- [ ] API pipeline for speed: the skills become prompts, run through the Anthropic SDK with
      structured outputs, prompt caching and Message Batches; measured cost per chapter decides
      the model mix
- [ ] Additional chronology schemes (e.g. Galil) for the divided monarchy

## Open questions

- Which absolute frame to use for pre-monarchic narratives (Genesis): Masoretic Anno Mundi with
  very wide margins, or "floating" events with relative anchors only?
- How much human review per chapter before a bundle ships?
