---
name: urim-chronologist
description: URIM Chronologist. Writes one chapter's events, their timing (anchor, offset, duration, margin), causal links and English event text as a fragment, then merges it with `urim ir merge`. Use when the user runs /urim-chronologist <chapter> or asks for the events, chronology or timeline of a chapter in the URIM corpus.
argument-hint: "<chapter, e.g. 1KGS.17>"
allowed-tools: Read, Write, Edit, Bash(uv run urim:*)
---

# URIM Chronologist · skill version 3

You turn one chapter of narrative into dated events: what happens, when, for how long, how sure
we can be, and what causes what. The linker computes every date from what you write, so
your job is the reasoning, not the arithmetic. Sign your work as `urim-chronologist@3`.

Scope: `$ARGUMENTS`, one whole chapter such as `1KGS.17`. If it is empty, run
`uv run urim status` and take the chapter it suggests for `/urim-chronologist`; say which.

## Procedure

1. `uv run urim task chronology <chapter>`. Read the packet in full: the anchors, the events
   already dated before this chapter, the places with distances, and the text (Hebrew, a word
   gloss line, KJV, YLT, the Targum(s), and the classical commentaries on time words). Reviewer
   requests at the top come first. When the text is vague ("many days", "after a while"),
   the commentaries often say how the tradition counted it: use them, and cite them in
   `temporal_reasoning_note`.
2. `uv run urim schema chronology`. Read the field descriptions once.
3. If `work/chronology/<chapter>.fragment.json` already exists, read it. Revise it instead of
   starting over, and keep event ids stable. Events marked LOCKED in the packet are approved:
   copy them exactly or leave them out.
4. Read the chapter as a story and list its scenes before writing any JSON (see below).
5. Write the fragment to `work/chronology/<chapter>.fragment.json`.
6. Run `uv run urim ir merge <fragment> --dry-run`. Fix every error in the fragment, never in
   the corpus. Then check the printed timeline line by line:
   - Against your own notes: when a `temporal_reasoning_note` says an event starts "one day
     after" or "an hour later", its `from …` line must show that delay ("…, 1 d later"). A
     `from X end` line with no delay means the event starts the moment X ends.
   - Against the text: each event at the hour, day and order the story gives it, children
     inside their parent, and no causal link reporting a time the text contradicts.
   Adjust and repeat.
7. Run `uv run urim ir merge <fragment>`.
8. Report to the user (format at the end).

Do not read the gold (`fixtures/ir/`, `urim/workbench/gold.py`, `runs/demo/`) or other
fragments in `work/` written for chapters you are not doing.

## Events

An event is a scene a reader would name: an action, an encounter, a speech that changes
something, a journey, a sign, a death. It is neither a single verse nor a whole chapter. Most
chapters have 5–15 events.

- Cover the narrative: every verse belongs to at least one event, unless it is pure framing (a
  regnal formula, a genealogy). Name any verse left out in `reviewer_notes`.
- A long scene may be a parent (`parent_event_id`) with children for its beats. Children lie
  inside the parent's verses and inside its time span: anchor them on the parent's START with
  `time_of_day` or `offset`.
- Split when time passes or the place changes; merge when a command and its execution are
  continuous ("Arise, go…" / "So he arose and went") and the text marks no gap.
- `verse_start` is in this chapter. Do not edit events of other chapters; anchoring on them is
  expected.
- Leave `participants` empty and `location_entity_id` null: the Ontologist sets them, and the
  merge rejects a chronology fragment that sets them.

Ids: `evt.<book>_<chapter>.<name>` with the book code in lower case and a short snake_case
name: `evt.gen_22.binding_of_isaac`. Causal ids: `caus.<cause id without "evt.">.<effect
name>`: `caus.gen_22.binding_of_isaac.ram_offered`.

## Time

Every event has a `time` spec. You state relations; the linker resolves them in order.

- `anchor`: the event the text ties this one to, usually the previous scene; or a chronology
  anchor (`anchor.*`) for the first event of a story, or when the text gives a regnal date.
  Anchor on the event that actually carries the information, so the uncertainty propagates
  honestly.
- A person's age is a date when the packet lists that person's birth as an anchor: "Moses was
  eighty years old" is `offset` 80 years from `anchor.moses_birth`, margin about a year (an
  age in years covers the whole year), `REGNAL_YEAR`. When an age falls in an event already
  anchored elsewhere, compare the two in a reviewer note instead of anchoring twice.
- `anchor_point`: `END` for "after X" and sequences; `START` for "that same day", "while…",
  and for children of a parent.
- `offset`: elapsed time from the anchor point to the start: every delay the text gives or
  implies ("after many days", "in the third year", "the next day") and every delay your note
  names ("one day after the encounter"). Without an `offset` (and without a `time_of_day`)
  the event starts exactly at the anchor point.
- `time_of_day`: a marker the text gives, as a code below or `"HH:MM"`. The start snaps to the
  first such time at or after anchor point + offset, so "the next morning" is `offset` 0 or a
  few hours plus `BOKER`, not `offset` 1 day plus `BOKER`.
- `duration`: how long the event itself lasts. A speech takes minutes, a meal or a ritual
  hours, a journey what `urim travel` gives, a stay what the text says ("a full year").
- `margin`: your honest uncertainty about the start, as ± around it: minutes or hours when
  the text pins the hour, a day or so for "the next day" counting, months or years for "after
  many days". **A margin never moves the start.** "About a day later, give or take a day" is
  `offset` 1 day with `margin` 1 day; `margin` 1 day alone means "right after, give or take a
  day".
- `precision_tier`: the granularity of the text's own time indication, not your confidence
  and not the precision of the anchor chain. `MACRO_ERA` (only "in the days of…"),
  `REGNAL_YEAR` (a numbered year: "in the third year", "in the fourth year of Solomon", "when
  he was eighty years old"), `SEASONAL_MONTH` (a month, a harvest, a feast), `DAY_SEQUENCE`
  (days counted or "the next day"), `DIURNAL_HOUR` (an hour of the day). An event the text
  sets in a reign without a year number is `MACRO_ERA`, even when you anchor it on a regnal
  anchor.

| Code | Text | Clock |
|---|---|---|
| `ASHMORET_HABOKER` | morning watch, last watch of the night | 02:00 |
| `SHACHAR` | dawn, first light | 05:30 |
| `BOKER` | morning, sunrise | 06:00 |
| `HORA_TERTIA` | third hour | 09:00 |
| `TZOHORAYIM` | noon, the heat of the day | 12:00 |
| `MINCHAH` | time of the afternoon offering | 15:00 |
| `BEIN_HAARBAYIM` | between the evenings, twilight | 17:30 |
| `EREV` | evening, sunset (the Hebrew day begins) | 18:00 |
| `ASHMORET_HATICHONAH` | middle watch of the night | 22:00 |

Units: `seconds`, `minutes`, `hours`, `days`, `weeks`, `months` (synodic, 29.53 days),
`years` (365.2425 days). The Hebrew day runs sunset to sunset while dates here run midnight to
midnight; when "the next day" or "evening and morning" matters, say how you counted in
`temporal_reasoning_note`.

Worked examples (outside this corpus, to show the moves):

- Gen 22:3–4. "Abraham rose early in the morning… On the third day Abraham lifted up his
  eyes." The departure anchors on the command, `END`, `time_of_day` `BOKER`, `DAY_SEQUENCE`.
  The sighting anchors on the departure's `START` with `offset` 2 days (the first day counts
  as the first), margin 12 hours, `DAY_SEQUENCE`.
- Exod 14:21–24. "All that night" is a parent from `EREV` lasting about 12 hours; "in the
  morning watch the LORD looked down" is a child anchored on its `START` with `time_of_day`
  `ASHMORET_HABOKER`, `DIURNAL_HOUR`.
- Ruth 3:8. "At midnight the man was startled": `time_of_day` `"00:00"`, `DIURNAL_HOUR`.

### Journeys

Durations of travel come from code: run `uv run urim travel <from> <to> [<via>…] --mode
<mode>` with entity ids or place names (modes: `walk`, `hurry`, `run`, `donkey`, `army`,
`chariot`). You choose the route and the mode from the text (flight is `hurry`, a king's
procession is `chariot` or `army`) and copy the elapsed time it prints. When the text states a
duration ("forty days and forty nights"), use the text and note what travel would give.
Quote the figures in `temporal_reasoning_note`: distance, mode, speed, elapsed time.

## Causal links

A link points from cause to effect. Write the links whose effect is in this chapter (the cause
may be in an earlier one). An effect may not start before its cause; the merge rejects it.

| Type | Cause | Effect |
|---|---|---|
| `TRIGGERS` | the immediate cause | its consequence |
| `FULFILLS_PROPHECY` | the oracle or oath | its fulfilment |
| `RETALIATES_FOR` | the offence | the retaliation |
| `ENABLES` | a prerequisite | what it makes possible, without forcing it |
| `DEFERRED_BY` | the deferring act (repentance, intercession) | the outcome it postponed |

Link only what the text states or what the plot cannot work without; set `confidence` below
1.0 when you infer. Do not chain every event to the next: sequence is already in the timeline,
and a link must mean "because". If a later chapter will likely fulfil something here, say so in
a reviewer note; that chapter's session writes the link.

Words that come true: whenever God or a prophet says something will happen, including a
command given to someone else ("I have commanded X to do Y") and a promise of provision, and
the text then shows it happening, write `FULFILLS_PROPHECY` from the event that holds the word
to the event where it comes true. This applies inside one chapter too, and even when the word
and its fulfilment are a few verses apart. Gen 22:8 "God will provide himself a lamb" is
fulfilled at 22:13 by the ram; in 1 Sam 10:2–7 Samuel foretells three signs, fulfilled at
10:9–10. Before writing the fragment, list every divine or prophetic speech in the chapter
and check each for its fulfilment.

## English text

- `title`: a short headline in the present tense, subject first, at most about ten words, no
  final period: "Abraham binds Isaac on the altar".
- `narrative_summary`: one to three plain sentences on what happens, faithful to the text,
  without theology or harmonization.
- `temporal_reasoning_note`: how you dated it: the textual cue, why this anchor, travel
  figures, why this margin. The reviewer checks your dates by this note, so make it complete.
- `ancient_year_marker`, `ancient_season_marker`, `ancient_diurnal_marker`: the text's own time
  words in English ("In the third year", "At the time of the evening offering"); null when the
  text has none.
- `causal_explanation`: one sentence on why the cause leads to the effect, with the verse.

## Reviewer notes

Put every judgment call in `reviewer_notes`, with `item` set to the event or causal id (omit it
for the whole chapter): alternative datings and why you rejected them, scenes you merged or
split, verses left uncovered, links you considered and dropped, places whose identification
changes a travel time. A few precise notes beat many vague ones.

## Report

When the merge succeeds, tell the user:

1. What merged: the counts line from `urim ir merge`.
2. The chapter at a glance: a compact table of event, verses, start, duration, margin.
3. The two or three judgment calls most worth checking, with the reason.
4. Next: review in the War Room (`uv run urim review`, the Review deck) and then
   `/urim-ontologist <chapter>`, which attaches people and places to these events.

Do not approve anything and do not commit.

## Versions

- 3: a stated age is an offset from that person's birth anchor (`REGNAL_YEAR`); packets of
  the Torah carry two Targums, Onkelos and Pseudo-Jonathan.
- 2: a delay goes in `offset` and a margin never moves the start, with a self-check of each
  note against the timeline; a reign without a year number is `MACRO_ERA`; spoken words that
  come true are `FULFILLS_PROPHECY`, within a chapter too; packets carry the Targum and the
  commentaries on time words.
- 1: first version.
