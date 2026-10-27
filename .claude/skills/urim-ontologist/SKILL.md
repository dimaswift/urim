---
name: urim-ontologist
description: URIM Ontologist (ECS). For one chapter whose events already exist, writes the entities, who takes part in each event and where, changing states, rituals and their occurrences, interactions and their English text as a fragment, then merges it with `urim ir merge`. Use when the user runs /urim-ontologist <chapter> or asks for the people, places, states or rituals of a chapter in the URIM corpus.
argument-hint: "<chapter, e.g. 1KGS.17>"
allowed-tools: Read, Write, Edit, Bash(uv run urim:*)
---

# URIM Ontologist · skill version 1

You model who and what the chapter is about, as an entity–component–system world: entities
(people, places, groups, objects), the events they take part in, the states they gain and
lose, the rituals and signs performed, and what they do to each other. Sign your work as
`urim-ontologist@1`.

Scope: `$ARGUMENTS`, one whole chapter such as `1KGS.17`. Its events must exist already; if
the packet says "No events yet", stop and suggest `/urim-chronologist <chapter>`. If the scope
is empty, run `uv run urim status` and take the chapter it suggests for `/urim-ontologist`.

## Procedure

1. `uv run urim task ontology <chapter>`. Read the packet in full: the chapter's events, the
   TIPNR registry of names in it, entities already in the corpus, open states, the systems
   catalog, and the text. Reviewer requests at the top come first.
2. `uv run urim schema ontology`. Read the field descriptions once.
3. If `work/ontology/<chapter>.fragment.json` already exists, read it and revise it, keeping
   ids stable. LOCKED items are approved: copy them exactly or leave them out.
4. Work through the chapter in this order: entities, participants and places, states, systems
   and instances, interactions, then the English text.
5. Write the fragment to `work/ontology/<chapter>.fragment.json`.
6. Run `uv run urim ir merge <fragment> --dry-run`. Fix every error in the fragment and repeat.
   Warnings about a first mention or a verse outside its event usually mean a wrong verse.
7. Run `uv run urim ir merge <fragment>`.
8. Report to the user (format at the end).

Do not read the gold (`fixtures/ir/`, `urim/workbench/gold.py`, `runs/demo/`) or other
fragments in `work/` written for chapters you are not doing.

## Entities

Define an entity in the chapter where the text first mentions it; later chapters refer to it.
The packet lists what already exists. Reuse those ids and never redefine them.

- Named individuals come from the registry (STEPBible TIPNR). Use the proposed id unless you
  have a reason not to, and always set `tipnr_id`: it keeps namesakes apart and supplies the
  coordinates. One TIPNR id belongs to one entity.
- Resolve what the registry conflates or splits. STEPBible tags the nation Israel with the
  patriarch's id: the people are a `group.` entity without that `tipnr_id`, and the patriarch
  keeps it. A divine title ("the LORD", "God of Israel") is the deity, not a new entity.
- Unnamed characters who act or are acted on (a servant, a messenger, a concubine, a crowd) are
  entities too, with `tipnr_id` null and an id that says who they are:
  `person.levite_of_ephraim` (Judg 19).
- Objects and substances only when the plot turns on them (the knife and the ram of Gen 22),
  not every noun.
- Ids: `person.`, `deity.`, `spirit.`, `loc.`, `group.`, `artifact.`, `substance.` plus a
  snake_case name; `entity_type` matches the prefix (`PERSON`, `DEITY`, `SPIRIT_BEING`,
  `LOCATION`, `GROUP`, `ARTIFACT`, `SUBSTANCE`).
- `first_mention_verse` is the first verse that names or clearly refers to it; the registry's
  mentions show where.
- `source_script_name`: the Hebrew form as in the text, vowels without cantillation marks.
  `transliterated_name`: a scholarly transliteration.
- Leave `geo_lat`, `geo_lon` and `geo_elevation_m` empty: coordinates come from the registry
  through `tipnr_id`. A place with no coordinates gets a reviewer note, not invented numbers.

## Participants and places

For every event of the chapter, list who takes part and, when known, where it happens. The
fragment replaces these links for the whole chapter, so cover every event.

- `AGENT` acts; `PATIENT` undergoes the action; `PRESENT` is there without acting; `MENTIONED`
  is named but absent (a deity sworn by, a king spoken of).
- God acting in the story (speaking, sending fire, providing) is an `AGENT`.
- The place is where the event happens, at the most precise level the text allows: a city or
  a mountain rather than a region. When the text does not restate it, the place carries over
  from the previous scene; when it is truly unknown, leave it out and say so in a note.

## States (components)

A component is a state of an entity that holds over a stretch of verses and matters to the
story: where someone is staying, an office or title, fear or grief, alive or dead, who holds
an object, whom someone serves. Permanent facts belong in the entity's `summary_bio` instead.

- `category`: `TRAIT`, `ROLE_TITLE`, `PSYCH_STATE`, `POSSESSION`, `LOCATION_STATE` or
  `ALLEGIANCE`. `component_key` names the slot in snake_case (`dwelling`, `office`, `mood`,
  `life`, `holds`). Give either a `value_code` in capitals (`SOJOURNER`, `DEAD`, `KING`) or a
  `target_entity_id` (the place stayed at, the object held, the master served).
- A state opens at `acquired_at_verse` in `acquired_in_event`. When it ends in the same
  chapter, set `expired_at_verse` and `expired_in_event` on it. When a state opened in an
  earlier chapter ends here, write a `component_closures` entry; the packet lists open states.
- One slot holds one value at a time. To change a value, close the old component where the new
  one opens, and set `supersedes_component_id` on the new one.
- Ids: `comp.<entity name>.<component_key>.<n>`, numbered per slot from 1:
  `comp.isaac.life.1`.

## Systems and instances

A system is a repeatable practice or kind of act: a ritual, a supernatural act, a legal or
social custom, an oracle, a theophany, a military protocol. Define it once, the first time it
occurs; the packet's catalog lists those that exist, so reuse them.

- `category`: `LITURGICAL_RITUAL`, `SUPERNATURAL_ACT`, `LEGAL_CUSTOM`, `SOCIAL_CUSTOM`,
  `PROPHETIC_ORACLE`, `THEOPHANY` or `MILITARY_PROTOCOL`. Id `sys.<name>`: `sys.burnt_offering`.
- An instance is one occurrence, inside one event: initiator, targets, artifacts used, place,
  and short `tags`. Id `inst.<book>_<chapter>.<name>`: `inst.gen_22.ram_offered`.
- Name a system by what is done, not by who did it once: `sys.sign_by_fleece`
  (Judg 6:36–40) only if it could recur; otherwise the general practice it belongs to
  (`sys.sign_requested`).

## Interactions (edges)

An edge is one significant act of one entity toward another at one verse, inside an event:
commands, blesses, curses, rescues, kills, deceives, pursues, swears to.

- `interaction_type` is a capitalised verb code (`COMMANDS`, `BLESSES`, `PURSUES`).
- Record the acts that move the plot or define a relationship, not every line of dialogue.
- Ids: `edge.<book>_<chapter>.<name>`: `edge.gen_22.abraham_binds_isaac`.

## English text

- Entities: `canonical_name` is the traditional English form; `phonetic_name` is the Hebrew
  pronunciation in plain Latin letters; `aliases` are other names the text uses;
  `etymology_meaning` gives the meaning of the name, marked "probably" or "folk etymology"
  where scholars differ; `summary_bio` is two or three sentences on who this is, from the text
  so far. You may also update the text of an entity from an earlier chapter when this chapter
  adds to it (`entity_texts` only, with its existing id).
- Components: `label_key` and `label_value` read as a short phrase ("Dwelling" / "Sojourning
  in Gerar"); `evidence_explanation` cites the verse that shows it.
- Systems: `name`; `ancient_near_east_context` on how the practice worked in the region and
  period; `rules_and_mechanics` as a list of short rules the text and its world attest.
- Instances: `outcome_summary` (what happened this time) and `significance_note` (why it
  matters in the story).
- Edges: `interaction_label` as a verb phrase ("commands") and a one-sentence `description`.

## Reviewer notes

Put every judgment call in `reviewer_notes` with `item` set to the id (an entity, `comp.`,
`sys.`, `inst.`, `edge.` or event id for its participants): identity decisions (who is this,
is it the same person as before), registry corrections, places without coordinates or with
doubtful identification, states you inferred rather than read, systems you defined rather than
reused.

## Report

When the merge succeeds, tell the user:

1. What merged: the counts line from `urim ir merge`.
2. The cast: each event with its agents, patients and place, compactly.
3. States opened and closed, systems defined, and the two or three judgment calls most worth
   checking.
4. Next: review in the War Room (`uv run urim review`), then `/urim-philologist` for the
   chapter's first window of verses (`uv run urim status` names it).

Do not approve anything and do not commit.
