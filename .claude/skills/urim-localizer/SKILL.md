---
name: urim-localizer
description: URIM Localizer. Writes one language's version of the corpus and the app — a chapter's event, entity, state, ritual and interaction texts, its verses (translated afresh from the Hebrew), the War Room and Codex interface messages, or the language's book names and labels — as a fragment, then merges it with `urim ir merge`. Use when the user runs /urim-localizer <lang> <scope>, when `urim run --lang` translates, or when the user asks to translate or localize part of URIM into another language.
argument-hint: "<lang> <scope, e.g. ru GEN.38 · ru GEN.38.1-12 · ru ui.campaign · ru bundle>"
allowed-tools: Read, Write, Edit, Bash(uv run urim:*)
---

# URIM Localizer · skill version 1

You make URIM read as if it had been written in another language: the story's texts, the
verses, the screens around them. English is the source of everything except the verses, which
you translate from the Hebrew, with the English layers beside you. Sign your work as
`urim-localizer@1`.

Arguments: `$ARGUMENTS`, a language code and a scope:

| Scope | What you write | Translated from |
|---|---|---|
| `GEN.38` | the chapter's texts: events, causal links, entities, systems, states, ritual instances, interactions | the English texts |
| `GEN.38.1-12` | verses: literal and dramatic layers, word glosses, commentary, notes | the Hebrew; commentary and notes from the English |
| `ui.<namespace>` | interface messages of one screen (`ui.campaign`, `ui.codex`) | the English messages |
| `bundle` | book names, vocabulary labels, chronology anchors | the English bundle |

If the scope is missing, run `uv run urim lang <lang>` and take the first thing it shows
undone; say which.

## Procedure

1. `uv run urim task localization <scope> --lang <lang>`. Read the packet in full. Reviewer
   requests at the top come first. Items are marked new, stale (the English changed since the
   last translation: translate the current English again), changes requested, draft, or
   LOCKED.
2. `uv run urim schema localization`. Read the field descriptions once.
3. If the fragment already exists in `work/localization/`, read it and revise it.
4. Write the fragment to the path the packet names, with `agent` "localization", `lang`,
   `scope`, `produced_by`, and the items. Carry every item marked new, stale or requested;
   leave out LOCKED items. A fragment replaces only the items it carries.
5. `uv run urim ir merge <fragment> --dry-run`. Fix every error and every gloss-count warning
   in the fragment, and repeat. Then `uv run urim ir merge <fragment>`.
6. Report (format at the end).

Do not read the gold (`fixtures/ir/`, `urim/workbench/gold.py`, `runs/demo/`).

## Everywhere

- Ids, ledger keys, verse references, codes (`MACRO_ERA`, `PERSON`), and Hebrew stay exactly
  as they are. Translate only the text fields.
- Names: use the forms the language's own Bible uses (the packet quotes it: the Synodal for
  Russian gives Иуда, Фамарь, Ир, Шуа, Хира, Одолламитянин, Фамна, Потифар). Once a name or a term is in
  the packet's "already in" list, use it as it is, so the whole book agrees. The divine name
  follows the target Bible's convention (Господь in Russian) except where the English keeps
  YHWH on purpose, as the literal layer does.
- Write natural prose in the target language, not English in disguise: its word order, its
  aspect and case, its punctuation (Russian «ёлочки» quotes, a long dash for asides). Keep the
  register of each field: titles short and plain, summaries clear, notes precise.
- Never add or drop a fact. When the English hedges ("about", "probably"), hedge the same.

## A chapter's texts

Translate every field of every item. `temporal_reasoning_note` and `evidence_explanation`
explain the reasoning to a reviewer: keep their logic and their verse references. A
component's `label_key` and `label_value` are what the reader sees for a state ("Life: Dead"):
translate both. `canonical_name` is the name as the target Bible spells it; `phonetic_name`
is how it is said in that language; `aliases` are other names the text uses, in that
language; `etymology_meaning` explains the Hebrew name in the target language.

## Verses

Read the Hebrew word by word in the packet's table, then write each layer in the target
language as the philologist would have written it there:

- `token_glosses`: one gloss per Hebrew word, `pos` 1 to n, its meaning here with its prefixes
  and suffixes, in the target language ("и сказал", "к горе"). The English gloss shows how the
  philologist read the word; follow the Hebrew where they differ.
- `translation_literal`: the exact structure of the Hebrew, its idioms, euphemisms, repetitions
  and "and" chains, with words the language needs but Hebrew lacks in [brackets]. YHWH stays
  YHWH. Do not translate the English literal layer: translate the Hebrew.
- `translation_dramatic`: literary prose for reading aloud, in the voice the English dramatic
  layer found, but written for the target language's ear. Never add a fact, motive or speech.
- `directors_commentary` and `philological_notes`: translate the English faithfully, keeping
  every claim and source. Where the commentary audits the KJV, keep that, and add one sentence
  when the target Bible (the packet quotes it) makes the same choice or a different one worth
  knowing. Notes keep `term`, `translit`, `root` and `sources` as they are; translate `note`.

## Interface messages

- Keep every `{placeholder}` exactly, spelled the same; translate the words around it.
- Counted messages take `forms`, one per plural category the packet lists (Russian: one, few,
  many, other), each a full phrase: `{"one": "{count} сессия", "few": "{count} сессии",
  "many": "{count} сессий", "other": "{count} сессии"}`.
- Short labels stay short: they sit on buttons, tabs, chips and table headers. Use the
  imperative or infinitive the platform's apps use for buttons in that language (Russian:
  infinitive or noun, "Одобрить", "Вернуть"). Read the note on each message for where it sits.
- Use the "terms already chosen" the packet lists; keep one word for one thing across screens.
- Game words (ranks, badges) and the Codex's manuscript voice keep their tone.

## Bundle

`books`: the target Bible's name and abbreviation for each book. `vocab`: labels of time words
and precision tiers, with the same hints in parentheses (`~06:00`). `anchors`: label and note
of each chronology anchor; the note's reasoning and numbers stay.

## Reviewer notes

Put judgment calls in `reviewer_notes` with `item` set to the id or verse (`evt.gen_38.…`,
`GEN.38.9`, or a message key): a name with two traditions, a pun you could not keep, a term
you chose for the first time.

## Report

When the merge succeeds:

1. What merged: the counts line from `urim ir merge`.
2. Two or three choices worth a reviewer's eye (a name, a pun, a term), each with its item.
3. Anything you were unsure of.
4. Next: `uv run urim lang <lang>` shows what is left.

Do not approve anything and do not commit.

## Versions

- 1: chapter texts, verses from the Hebrew, interface messages, bundle labels.
