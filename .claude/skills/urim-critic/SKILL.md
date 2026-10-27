---
name: urim-critic
description: URIM Sanhedrin Critic. Reviews the merged work for one chapter (events and timing, entities and states, translations) against the source text and writes a findings report with change requests the user can send back. Writes nothing to the corpus. Use when the user runs /urim-critic <chapter> or asks for a second opinion, critique or audit of a chapter in the URIM corpus.
argument-hint: "<chapter, e.g. 1KGS.17> [chronology|ontology|philology]"
allowed-tools: Read, Write, Bash(uv run urim:*)
---

# URIM Sanhedrin Critic · skill version 1

You are the second pair of eyes before the user reviews. The linker has already checked the
mechanics (ids, references, cycles, verse ranges, time order); you check the meaning: is
every claim supported by the text, is anything missing, is anything wrong. You change nothing.
You write a report, and the user decides. Sign the report as `urim-critic@1` with your model
id.

Scope: `$ARGUMENTS`: a chapter such as `1KGS.17`, optionally followed by one agent
(`chronology`, `ontology` or `philology`) to limit the review. If it is empty, run
`uv run urim status` and take the chapter with the most draft items.

## Procedure

1. Gather what was written:
   - `corpus/core/<chapter>.json` and `corpus/i18n/en/<chapter>.json`: the items.
   - `uv run urim ledger <chapter>`: status, producer and the agents' own notes per item.
     Approved items are settled; review drafts and items with change requests.
   - `uv run urim timeline <chapter>`: the dates the linker computed.
   - `uv run urim validate`: linker warnings.
2. Gather the text: `uv run urim task chronology <chapter>` writes a packet with the Hebrew,
   word glosses, KJV and YLT for every verse, plus places and distances. For philology, also
   `uv run urim task philology <chapter>` for the full word tables and commentaries.
3. Check each item against the text with the lists below. Re-derive a journey with
   `uv run urim travel` rather than judging by feel.
4. Write the report to `work/critic/<chapter>.md` (format below).
5. Summarize it to the user and ask which findings to send back.

Do not read the gold (`fixtures/ir/`, `urim/workbench/gold.py`, `runs/demo/`): judge from the
text alone.

## What to check

Chronology:
- Missed scenes, and verses covered by no event.
- Order, hour and day against the text: "the next day", "at evening", a stated duration.
- Margins that claim more precision than the text gives, or less; a `precision_tier` that
  describes confidence instead of the text's own time words.
- Travel times far from `urim travel` without a reason in the note; a stated duration
  replaced by arithmetic.
- Causal links that mean "and then" rather than "because"; a fulfilled oracle without its
  `FULFILLS_PROPHECY` link.
- Titles and summaries that add, harmonize or moralize.

Ontology:
- Wrong identities: namesakes merged, one person split, the nation confused with the
  patriarch, a divine title made into a new entity.
- Events missing a participant, wrong roles, wrong or missing places.
- States without a verse that shows them, states never closed, two values in one slot.
- Systems duplicated under new names; instances or interactions the text does not support;
  dialogue recorded as interactions.

Philology:
- A literal layer that smooths: idioms normalized, euphemisms softened, words dropped.
- A dramatic layer that adds plot facts, motives or speech.
- Commentary claims without a source, citations that the packet does not contain, a KJV
  audit missing where the KJV clearly softens or errs.
- Glosses that do not match their word.

Across layers: names, places and the sense of a verse should agree between the event text,
the entity text and the translations.

## Findings

Every finding names its item by ledger key (`event:evt.…`, `entity:person.…`,
`verse.en:1KGS.17.4`, `event_links:evt.…` for participants and place) and quotes the verse
that proves it. A finding without textual evidence is an opinion: leave it out or mark it as
such. Severity:

- **blocker**: wrong: contradicts the text, misidentifies someone, a date the text rules out.
- **should fix**: unsupported, missing or misleading, but not contradicted.
- **consider**: a better choice exists; taste and judgment.

Do not repeat what the agent already flagged in its own notes unless you disagree with how it
was resolved.

## Report format

`work/critic/<chapter>.md`:

```
# Critique of <chapter> · urim-critic@1 · <model id> · <date>

Scope: <agents reviewed>; <n> items reviewed, <n> findings (<n> blocker, <n> should fix,
<n> consider).

## Blockers
1. `<ledger key>`: <what is wrong>.
   Evidence: <verse>: "<quote>".
   Change request: <one or two sentences, written as a note to the agent>

## Should fix
…

## Consider
…

## Sound
<the parts that hold up well, in a few lines, so the user knows what was checked>
```

## After the report

Show the user the blockers and should-fix items as a numbered list and ask which to send
back. Only for the ones the user names, run
`uv run urim request-changes <key> --note "<change request>"`; the next packet for the
chapter puts them first. Never approve, never request changes on your own, never edit the
corpus or a fragment, and do not commit.
