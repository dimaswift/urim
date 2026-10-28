# URIM build plan

PoC fragment: **1 Kings 17–19** (91 verses). It has an extra-biblical date anchor (Ahab at
Qarqar, 853 BCE), a KJV/Hebrew verse-numbering split inside the range (18:33–34), diurnal
and multi-day timing, rituals, a theophany, and a succession. A second fragment,
**Genesis 37–40** (the Joseph story, 112 verses), tests generalization with no gold: time told
by a person's age, a chapter told out of order (38, "at that time", spanning two decades),
dreams that come true on a stated day (40:12–22), a deception with a goat and a garment told
twice, and no absolute anchor.

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
| Genesis frame (2026-10-28) | The Masoretic chain: pre-monarchic anchors are derived inside each scheme from its date for Solomon, with margins of centuries |

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
- [x] First real session: `/urim-chronologist 1KGS.17` on Haiku 5.5. Clean structure, sound
      span estimates; but five delays went into `margin` instead of `offset`, an undated reign
      was tagged `REGNAL_YEAR`, and two command → fulfilment links were missed
- [x] `urim-chronologist@2`: a margin never moves the start (self-check of every note against
      the timeline), a reign without a year number is `MACRO_ERA`, spoken words that come true
      are `FULFILLS_PROPHECY` within a chapter too; chronology packets carry the Targum and
      the commentaries whose heading phrase holds a time word (+5K chars for 1 Kings 17)
- [x] Rerun 1 Kings 17 with v2 (Haiku again): all six change requests resolved (notes now say
      "right after" where the text gives no interval; both fulfilment links; `MACRO_ERA`), and
      the Zarephath stay now follows Metzudat Zion's "days = a year" from the new packet
      commentary. Open for chapter 18: Cherith (placeholder six months) plus Zarephath (one
      year) against 18:1's "third year"

**M4: model comparison** on 1 Kings 18–19 against the gold fixture: `/urim-compare` runs the
same packet through Opus, Sonnet and Haiku subagents into `runs/<model>/`; `urim eval` scores
them (event F1, relative timing within margins, causal F1, entity P/R by TIPNR id, state
transitions, acceptance tests 1–4, philology checks plus a blind judge subagent). Result: a
default model per skill. All of it counts against the subscription allowance, not API billing.

First data point, before the M4 tooling: philology 1 Kings 17:1–12, the same packet and
`urim-philologist@1` through Haiku 5.5 (a session) and Sonnet 5.5 (a subagent), kept in
`runs/compare/philology-1KGS.17.1-12/` with a side-by-side file.

| Check | Haiku | Sonnet |
|---|---|---|
| Glosses complete | 12/12 | 12/12 |
| Literal layer: YHWH / Yahweh (the skill says YHWH) | 0 / 5 | 5 / 0 |
| Dramatic layer: words; trigrams shared with the KJV; archaic markers | 322; 26%; 5 | 446; 13%; 1 |
| Commentary words; notes on words | 1,304; 21 | 2,225; 28 |
| Citations found in the packet's commentaries | 29/29 | 45/49 (+4 BDB, allowed) |
| Read by hand | KJV-like drama; "many days" added at 17:7; "barrel" called Victorian | rules kept; real dramatic voice; deeper notes (*māṭār* vs *geshem*); drama sometimes adds interpretation ("a man of no standing") |

Mostly a model gap, not a skill gap: Sonnet kept every rule Haiku broke under the same text.
Sonnet's version is merged (about 12 minutes, 200K tokens). Working defaults until M4
measures them: Sonnet for philology, Haiku for chronology and ontology. Philologist v2
should mark the line between drawing out the text and adding interpretation in the drama,
and keep time words as vague as the Hebrew.

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
- [x] **M1 vectors.** bge-m3 (`Xenova/bge-m3` int8 export with pooling, 569 MB, pinned by
      commit and published SHA-256; `urim model fetch`) embeds every search document at link
      time into an `i18n_vectors` sqlite-vec table (cosine, 1024 dimensions) inside each
      language bundle; the manifest records the model. A text-hash cache in `data/cache` makes
      relinks cheap (209 documents: 20 s cold, 1.7 s warm). `semantic_search` fuses BM25 and
      cosine by reciprocal rank and reports `via` per hit; a query is embedded only by the
      bundle's own model, and without the extra search stays keyword-only. `--vectors` /
      `--no-vectors` on `link`; merges and `urim review` relink with vectors. Codex and War
      Room show how each hit was found
- [x] Query-time embedding as the `urim[search]` extra (ONNX Runtime, tokenizers, numpy,
      sqlite-vec)
- [ ] Later: drop very common words from the keyword half of hybrid search (English stopwords
      make nearly every document a keyword hit); one-word queries against long verse documents
      are weak for vectors alone; int8 vectors and a smaller vec0 chunk size once bundles grow
      (each bundle starts at about 4 MB of preallocated vector storage)

## Phase 4: scale

**M1: generalization, Genesis 37–40** (in place of Genesis 18–19)
- [x] `urim ingest GEN.37-40`: 112 verses, all six baselines, no versification splits; the
      Torah gets its own commentaries (Rashi, Rashbam, Ibn Ezra, Ramban, Radak, Sforno) and two
      Targums (Onkelos, and Pseudo-Jonathan, which Sefaria files as "Targum Jonathan on
      Genesis"); 31 registry names, 11 places with coordinates
- [x] The frame, an open question until now: the Masoretic chain. `anchor.joseph_birth` (THIELE)
      at c. 1915 BCE ± 220 years: 966 BCE for Solomon's temple + 480 years (1 Kgs 6:1) + 430
      years in Egypt (Ex 12:40 MT) + Joseph's 39 years at the descent. Other schemes derive it
      from their own Solomon; the margin covers a 13th-century Exodus and the LXX's Ex 12:40
- [x] Two books at once: `urim status` runs one chronology and one ontology chain per book;
      packets keep earlier events and open states within the book; the linker records the
      earliest real mention of an entity a later-written book names first, and warns only
      within a book
- [x] `urim-chronologist@3`: a stated age is an offset from that person's birth anchor
      (`REGNAL_YEAR`). Nothing about Genesis 38's order: that is what the test is for
- [x] First session: `/urim-chronologist GEN.37` on Sonnet 5.5 (v3), 18 events and 10 links.
      Every v3 rule kept: Joseph's birth + 17 years for 37:2, travel from `urim travel` (3 days
      Hebron → Shechem, 17 days to Egypt), Rashi's 22 years cited, Pseudo-Jonathan's angel
      noticed and set aside, v28's seller left open. But eleven events claimed more precision
      than the text gives (the Dothan scenes at the minute, guessed gaps of weeks as days),
      Jacob's mourning ran 22 years, and the dreams "triggered" a plot months later: 14 change
      requests sent
- [x] `urim-chronologist@4`: an event with no time word of its own takes the tier of the
      indication its scene falls under; estimated hours and gaps never raise a tier
- [ ] Sessions for GEN.37–40 (chronology, ontology, philology), reviewed, then the critic
- [ ] What to watch: where chapter 38 goes in time (Ibn Ezra: before the sale; Rashi on 37:34:
      Jacob mourned 22 years) and whether Judah's three sons can grow up inside it; 39:1
      resuming 37:36; "on the third day" in 40; TIPNR tags the Ishmaelites as Ishmael and the
      Midianites as Midian; Jacob's proposed id is `person.israel`. Packets run larger than in
      1 Kings: chronology GEN.37 44K characters (two Targums), philology GEN.37.1–12 59K
      against 40K for 1KGS.17.13–24 (eight commentaries, Ramban is long)

**Later in Phase 4**
- [ ] Process in chronological narrative arcs (Kings and Chronicles interleave), parallel where
      the rolling state allows
- [ ] API pipeline for speed: the skills become prompts, run through the Anthropic SDK with
      structured outputs, prompt caching and Message Batches; measured cost per chapter decides
      the model mix
- [ ] Additional chronology schemes (e.g. Galil) for the divided monarchy

## Open questions

- How much human review per chapter before a bundle ships?
