# URIM

A pre-compiled knowledge engine for scripture, built like a compiler: agents write JSON IR, a
deterministic linker turns it into SQLite bundles (a language-free core plus one bundle per
language), and a runtime serves them over Python, REST and MCP. PoC scope: 1 Kings 17–19,
with Genesis 37–40 (the Joseph story) as the generalization test, which has no gold.
[SPEC.md](SPEC.md) is the design; [PLAN.md](PLAN.md) is the build plan and its decisions.

## Layout

| Path | What | Who writes it |
|---|---|---|
| `urim/` | Python package: `utime` (UTES time), `ir/`, `compiler/` (ingest, linker), `workbench/`, `runtime/`, `interfaces/`, `review/` | code |
| `corpus/` | The working IR, committed: `core/`, `i18n/{lang}/`, `ledger/` | only `urim ir merge` and the review commands |
| `corpus/chronology.json`, `corpus/i18n/*/_bundle.json` | Curated anchors and labels | by hand, when the user asks |
| `build/ir/` | Ingest output: source text, tokens, baselines, TIPNR registry, commentaries | `urim ingest` (regenerable) |
| `fixtures/ir/` | **The gold**: hand-written IR for 1 Kings 17–19, the benchmark | nobody, unless the user asks |
| `work/{agent}/` | Task packets and fragments (gitignored scratch) | `urim task`, sessions |
| `runs/` | Other corpora: `runs/demo` (gold, for the review app), `runs/<model>` (comparisons) | commands |
| `review/` | Review frontend (React, TypeScript, Vite, D3): War Room (`/`) and Illuminated Codex (`/codex`) | code |
| `.claude/skills/` | The agent skills: `urim-chronologist`, `urim-ontologist`, `urim-philologist`, `urim-critic` | code |

## Commands

Everything runs through uv: `uv run urim …`.

```
urim status                          progress per chapter and the next tasks
urim task <agent> <scope>            write a work packet to work/<agent>/
urim schema <agent>                  JSON schema of that agent's fragment
urim ir merge <fragment> [--dry-run] check and merge a fragment (relinks the bundles)
urim timeline <chapter>              a chapter's events with linked dates
urim travel <place> <place>… [--mode] journey times from coordinates
urim ledger <chapter>                review status, producers and notes per item
urim approve / request-changes / reopen   review decisions (the user's)
urim review [--demo]                 review app on :8765 (War Room, and /codex)
urim link all · urim validate        link or check the corpus by hand (vectors when installed)
urim ingest 1KGS.17-19 · GEN.37-40   fetch pinned sources into build/ir
urim model fetch                     the pinned bge-m3 for semantic search (needs urim[search])
```

Checks: `uv run pytest -q`, `uv run ruff check urim tests`, `uv run ruff format urim tests`.
Frontend: `npm run build` in `review/` (the server serves `review/dist`).

## Agent work

Agents are Claude Code sessions run by the skills, one bounded task per chat. The user drives
the pace and reviews everything. The loop: `/urim-<agent> <scope>` → `urim task` → read the
packet → write the fragment → `urim ir merge` → the user reviews in the War Room → approves or
requests changes → the next packet shows the requests first.

Ownership: the **chronologist** writes events, their timing, causal links and their English
text; the **ontologist** writes entities, who takes part in each event and where, states,
rituals and interactions; the **philologist** writes verse translations, commentary, notes
and word glosses; the **critic** writes nothing to the corpus, only a report.

## Rules

- Change corpus content only through `urim ir merge`. Never edit `corpus/core/`,
  `corpus/i18n/*/<chapter>.json` or `corpus/ledger/` by hand, and never patch a merge error
  by editing the corpus: fix the fragment.
- Review decisions belong to the user. Never run `urim approve`, `request-changes` or
  `reopen` unless the user tells you to in chat, item by item or chapter by chapter.
- During agent work, do not read the gold: `fixtures/ir/`, `urim/workbench/gold.py`,
  `runs/demo/`. Model comparisons are scored against it, and a session that has seen it
  scores nothing. Never edit the gold unless the user asks.
- IR never holds timestamps or derived numbers. Time is anchor + offset + duration + margin;
  the linker computes dates. Coordinates come from the registry through `tipnr_id`; leave
  `geo_*` empty.
- Travel durations come from `urim travel`, not mental arithmetic; when the text states a
  duration, the text wins.
- Fill `produced_by.model` with your exact model id (from your system prompt) and
  `produced_by.skill` with the name and version the skill states (`urim-chronologist@4`).
- Do not commit unless asked; the user commits after reviewing.
- `--refresh` on ingest re-pins upstream sources: only when the user asks.

## Code

Python 3.13, Pydantic models, Typer CLI, sqlite3 with STRICT tables. Ruff at line length 100.
Modules open with a docstring that says why they exist; comments are rare and explain intent.
Tests use the gold through `tests/conftest.py` (`FIXTURE_IR`); a new behaviour gets a test in
the matching `tests/test_*.py`. IR models in `urim/ir/models.py` and fragments in
`urim/workbench/fragments.py` double as the schemas agents write against (`urim schema`), so
describe new fields with `Field(description=…)` written for an agent reading them. When a
fragment rule changes, update the skill that writes it and bump its version.
