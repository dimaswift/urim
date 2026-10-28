"""Quiz questions built from the bundles, so every question agrees with the corpus.

No model writes these: each kind of question is a view of the linked data. Who took part in a
scene, what caused what, how a state changed, the order of events, where they happened, how
long between them, how old someone was, what a Hebrew word means, which word a verse needs.
Wrong choices come from the same book, and from search by meaning when the bundle has vectors,
so they are plausible rather than random.

A question's id is `kind|chapter|subject|seed`: the server rebuilds the question from it to
check an answer, so nothing is stored between asking and answering.

Questions speak the learner's language: their own words come from the interface messages
(`urim/i18n/en/quiz.json`), and the corpus text they quote from the language bundle, which
falls back to English where a translation is missing.
"""

from __future__ import annotations

import math
import random
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

from pydantic import BaseModel

from urim import utime
from urim.bundles import discover_langs, sqlite_uri
from urim.canon import BOOKS_BY_CODE
from urim.i18n.messages import ENGLISH, Messages, Translator
from urim.runtime.engine import (
    _LABEL_PRECISION,
    LanguageNotAvailable,
    NotFoundError,
    SearchUnavailable,
    UrimEngine,
)
from urim.runtime.models import EntityDossier, EntityRef, EventView, TokenView, VerseMatrix

Format = Literal["choice", "order", "map", "number", "text"]
FAMILIES: dict[str, tuple[str, ...]] = {
    "story": ("who", "scene", "cause", "state", "deed"),
    "time_place": ("order", "where", "place", "span", "age"),
    "hebrew": ("gloss", "word", "cloze"),
}
FAMILY_OF = {kind: family for family, kinds in FAMILIES.items() for kind in kinds}
KINDS = tuple(FAMILY_OF)
YEAR = 365.2425 * 86400
ROLES = ("AGENT", "PATIENT", "PRESENT")
_GLOSS_SKIP = re.compile(
    r"^(the|a|an|and|or|to|of|in|on|at|by|for|with|from|that|which|who|not|no|if|as|"
    r"he|she|it|they|him|her|them|his|its|their|i|you|we|me|us|be|is|was|were|"
    r"и|а|но|или|в|во|на|к|ко|от|из|у|о|об|с|со|по|за|для|до|при|что|кто|не|ни|же|бы|"
    r"он|она|оно|они|его|её|ее|их|ему|ей|им|я|ты|мы|вы|меня|мне|нас|вас|быть|был|была|"
    r"было|были|есть|это|тот|та|те|"
    r"\[.*\]|<.*>|\W+)$",
    re.I,
)
_REGION = re.compile(
    r"^(the )?(land of (the )?)?(Canaan|Egypt|Israel|Judah|Aram|Midian|Edom|Moab|Ammon|"
    r"Philistia|Mesopotamia|Aram-naharaim|Paddan-aram|Goshen|Gilead|Assyria|Babylon|Cush|"
    r"Shinar|Seir|the East|the Negev|the South)$",
    re.I,
)
_STOPWORDS = frozenset(
    re.findall(
        r"\w+",
        """the and that with from into upon unto them they their there were which what when
        shall said have this your will been also then thee thou thy hath before after about
        these those every because against
        который которая которое которые когда тогда потому также только чтобы между перед после
        если будет были было была сказал этого этому этих своего своей своих своим""",
    )
)
_WORD = re.compile(r"[^\W\d_]+(?:'s)?")
# A name's last letter when it is a case ending ("Фамарь" → "Фамари", "Мария" → "Марию").
_SOFT_END = re.compile(r"[aeiouyаеёиоуыэюяйьъіїє]$", re.I)


class Choice(BaseModel):
    id: str
    label: str
    hebrew: bool = False


class MapFrame(BaseModel):
    west: float
    south: float
    east: float
    north: float


class Question(BaseModel):
    id: str
    kind: str
    family: str
    chapter: str
    item: str  # the fact being tested, for mastery: an event, link, state, word or verse
    format: Format
    prompt: str
    context: str | None = None
    hebrew: str | None = None  # Hebrew to show right to left, with the word in [brackets]
    choices: list[Choice] = []
    frame: MapFrame | None = None
    unit: str | None = None
    verse: str | None = None  # where to read it again


class Key(BaseModel):
    """The answer, kept on the server."""

    correct: list[str] = []  # the choice, or the ids in their right order
    point: tuple[float, float] | None = None  # lat, lon
    value: float | None = None
    tolerance: float = 0.0  # km on the map; units for a number
    accept: list[str] = []  # text answers
    answer: str
    explanation: str
    verse: str | None = None


class Judged(BaseModel):
    correct: bool
    score: float  # 0-1: partial credit for order, distance and estimates
    answer: str
    explanation: str
    verse: str | None = None
    point: tuple[float, float] | None = None  # the place, for a map question


# --- what a chapter offers ---------------------------------------------------------------------


@dataclass
class Facts:
    chapter: str
    lang: str
    events: list[EventView]
    book_events: list[EventView]
    verses: list[VerseMatrix]
    participants: dict[str, list[tuple[EntityRef, str]]]
    causal: list
    dossiers: dict[str, EntityDossier]
    entities: list[EntityRef]
    engine: UrimEngine
    t: Translator = ENGLISH
    book_label: str | None = None  # the book in references: "Быт", "Gen"
    gloss_lang: str = "en"  # the language of the word glosses: the learner's, else English
    gloss_verses: frozenset[str] | None = None  # verses glossed in gloss_lang; None for all
    _similar: dict[str, list[str]] = field(default_factory=dict)

    @property
    def titles(self) -> dict[str, str]:
        return {e.event_id: e.title or e.event_id for e in self.book_events}

    @property
    def inflects(self) -> bool:
        """Whether names change their endings in this language, so matching goes by stem."""
        return self.lang != "en"

    def names(self, entity_id: str) -> list[str]:
        d = self.dossiers.get(entity_id)
        names = [d.canonical_name, *d.aliases] if d else []
        ref = next((e for e in self.entities if e.entity_id == entity_id), None)
        return [n for n in {*names, ref.name if ref else None} if n]

    @cached_property
    def single_names(self) -> list[str]:
        """One-word names of the chapter's people and places, longest first."""
        names = {n for e in self.dossiers for n in self.names(e) if " " not in n.strip()}
        return sorted(names, key=len, reverse=True)

    def ref(self, verse_start: str, verse_end: str | None = None) -> str:
        return ref_label(verse_start, verse_end, self.book_label)

    def scene(self, ref: str, title: str) -> str:
        return self.t("quiz.context.scene", ref=ref, title=title)

    def duration(self, value: float, unit: str) -> str:
        n = round(value, 1)
        return self.t(f"quiz.unit.{unit}.count", count=int(n) if n == int(n) else n)

    def date(self, utes: int, precision_tier: str) -> str:
        """A date to the precision the corpus knows it, in the learner's words."""
        d = utime.utes_to_date(utes)
        year, era = utime.astronomical_to_era(d.year)
        label = self.t("time.bce" if era == "BCE" else "time.ce", year=year)
        match _LABEL_PRECISION.get(precision_tier, "minute"):
            case "year":
                return self.t("time.circa", date=label)
            case "month":
                return f"{label}-{d.month:02d}"
            case "day":
                return f"{label}-{d.month:02d}-{d.day:02d}"
        return f"{label}-{d.month:02d}-{d.day:02d} {d.hour:02d}:{d.minute:02d}"

    def similar(self, entity_id: str) -> list[str]:
        """Entities nearest in meaning to this one, when the bundle has vectors."""
        if entity_id not in self._similar:
            try:
                hits = self.engine.find_similar(
                    "entity", entity_id, self.lang, top_k=8, same_type=True
                )
                self._similar[entity_id] = [h.id for h in hits]
            except (SearchUnavailable, NotFoundError, ValueError):
                self._similar[entity_id] = []
        return self._similar[entity_id]


def _own_glosses(engine: UrimEngine, stream, lang: str) -> frozenset[str]:
    """Verses whose word glosses this language's bundle has itself, not by falling back to
    English: a verse's glosses come whole from one bundle, so differing from the English ones
    means they are the language's own."""
    try:
        english = engine.get_chapter_stream(stream.book_code, stream.chapter, "en").verses
    except (LanguageNotAvailable, NotFoundError):
        english = []
    en = {v.verse_id: [t.gloss for t in v.tokens] for v in english}
    return frozenset(
        v.verse_id
        for v in stream.verses
        if any(t.gloss for t in v.tokens) and [t.gloss for t in v.tokens] != en.get(v.verse_id)
    )


def _book_label(engine: UrimEngine, book_code: str, lang: str) -> str | None:
    """The book's short name as the language bundle has it ("3 Цар"), else English's."""
    bundles = discover_langs(engine.bundles_dir)
    book = BOOKS_BY_CODE.get(book_code)
    for code in dict.fromkeys((lang, "en")):
        if book is None or code not in bundles:
            continue
        uri = sqlite_uri(bundles[code], immutable=True)
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            row = conn.execute(
                "SELECT abbreviation FROM i18n_books WHERE book_id = ?", (book.book_id,)
            ).fetchone()
        if row and row[0]:
            return row[0]
    return None


def chapter_facts(
    engine: UrimEngine, chapter: str, lang: str = "en", messages: Messages | None = None
) -> Facts:
    book, number = chapter.split(".")
    stream = engine.get_chapter_stream(book, int(number), lang)
    # Word glosses in one language per chapter, so a question's choices never mix languages.
    gloss_lang, gloss_verses = "en", None
    if lang != "en" and (own := _own_glosses(engine, stream, lang)):
        gloss_lang, gloss_verses = lang, own
    events = [e for e in stream.events if e.verse_start.rsplit(".", 1)[0] == chapter]
    participants = {e.event_id: engine.event_participants(e.event_id, lang) for e in events}
    ids = {r.entity_id for parts in participants.values() for r, _ in parts}
    ids |= {e.location.entity_id for e in events if e.location}
    dossiers = {}
    for entity_id in sorted(ids):
        try:
            dossiers[entity_id] = engine.get_entity_dossier(entity_id, lang)
        except NotFoundError:
            continue
    book_events = [e for e in engine.list_events(lang) if e.verse_start.startswith(f"{book}.")]
    effects = {e.event_id for e in events}
    return Facts(
        chapter=chapter,
        lang=lang,
        events=events,
        book_events=book_events,
        verses=stream.verses,
        participants=participants,
        causal=[c for c in stream.causal_links if c.effect_event_id in effects],
        dossiers=dossiers,
        entities=engine.list_entities(lang),
        engine=engine,
        t=messages(lang) if messages else ENGLISH,
        book_label=_book_label(engine, stream.book_code, lang) or stream.book_name,
        gloss_lang=gloss_lang,
        gloss_verses=gloss_verses,
    )


# --- helpers -------------------------------------------------------------------------------------


def ref_label(verse_start: str, verse_end: str | None = None, book: str | None = None) -> str:
    """A reference such as "Gen 37:5–8", the book named as the language bundle has it."""
    code, ch, v = verse_start.split(".")
    label = f"{book or code.title()} {ch}:{v}"
    if verse_end and verse_end != verse_start:
        _, ch2, v2 = verse_end.split(".")
        label += f"–{v2}" if ch2 == ch else f"–{ch2}:{v2}"
    return label


def _stem(word: str) -> str:
    """The part of a name that stays when it inflects: a word longer than four letters less
    a final vowel or soft sign ("Иосиф" → "Иосиф", "Фамарь" → "Фамар")."""
    return _SOFT_END.sub("", word) if len(word) > 4 else word


def _name_pattern(name: str, inflects: bool) -> str:
    """A regex for a name; where names inflect, each long word may take an ending of up to
    three letters ("Иосиф" also finds "Иосифа", "Иосифу", "Иосифом")."""
    if not inflects:
        return re.escape(name)
    return r"\s+".join(
        re.escape(_stem(w)) + (r"\w{0,3}" if len(w) > 4 else "") for w in name.split()
    )


def mask(text: str, names: list[str], inflects: bool = False) -> str:
    for name in sorted(set(names), key=len, reverse=True):
        if len(name) > 1:
            text = re.sub(rf"\b{_name_pattern(name, inflects)}\b", "…", text, flags=re.I)
    return text


_RU_ENDING = r"(?:ь|и|ью|ый|ой|ая|ое|ого|ому|ом|ую|ые|ых|ым|ыми)?"
_NUMBER = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|thousand)(-\w+)?\b"
    # Russian numerals in their cases, and the words built on the longer ones
    # ("семнадцатилетний").
    r"|\b(?:од(?:ин|на|но|ного|ной|ному|ним|ном|ну)|дв(?:а|е|ух|ум|умя)|тр(?:и|[её]х|[её]м|емя)"
    r"|трет(?:ий|ья|ье|ьего|ьей|ьему|ьем|ью|ьи|ьих)|ст[оа]|сорок(?:а|ов)?"
    rf"|(?:перв|втор|четв[её]рт|пят|шест|сем|седьм|восем|восьм|девят|десят){_RU_ENDING}"
    r"|(?:четыр|\w*надцат|двадцат|тридцат|\w+десят|девяност|тысяч)\w*)\b",
    re.I,
)


def _name_parts(names: list[str]) -> list[str]:
    """A place's names and their proper words: "Valley of Hebron" also hides "Hebron"."""
    return names + [w for n in names for w in n.split() if len(w) >= 4 and w[0].isupper()]


def mask_numbers(text: str) -> str:
    """Hide the numbers in a scene's title when the question asks for one, in English or
    Russian (a title may be in either when its translation is missing)."""
    return _NUMBER.sub("…", text)


def _shuffle(rng: random.Random, correct: Choice, others: list[Choice]) -> list[Choice]:
    picked = [correct, *others]
    rng.shuffle(picked)
    return picked


def _distinct(
    rng: random.Random,
    pool: list[tuple[str, str]],
    avoid: set[str],
    n: int = 3,
    inflects: bool = False,
):
    """Up to n (id, label) pairs from the pool, skipping ids and labels in `avoid`, keeping
    the pool's order for the first half (the most plausible) and sampling the rest. A label
    that contains an avoided label, or is part of one ("The pit at Dothan" against "Dothan"),
    would be a second right answer, so it is skipped too; where words inflect, by their stems
    ("Фамари" against "Фамарь")."""
    seen, out = {a.casefold() for a in avoid}, []
    stems = {_stem(a) for a in seen} if inflects else set()
    head, tail = pool[: n * 2], pool[n * 2 :]
    rng.shuffle(tail)
    for item_id, label in head[:n] + tail + head[n:]:
        folded = label.casefold()
        if (
            item_id in seen
            or folded in seen
            or any(len(a) > 3 and (a in folded or folded in a) for a in seen)
            or any(len(a) > 3 and (a in folded or _stem(folded) in a) for a in stems)
        ):
            continue
        seen |= {item_id, folded}
        if inflects:
            stems.add(_stem(folded))
        out.append((item_id, label))
        if len(out) == n:
            break
    return out


def _entity_pool(f: Facts, target: EntityRef, avoid: set[str]) -> list[tuple[str, str]]:
    """Plausible wrong answers for an entity: similar in meaning, then the same type."""
    by_id = {e.entity_id: e for e in f.entities}
    similar = [by_id[i] for i in f.similar(target.entity_id) if i in by_id]
    same = [e for e in f.entities if e.entity_type == target.entity_type]
    book_ids = set(f.dossiers)
    ranked = similar + [e for e in same if e.entity_id in book_ids] + same
    return [(e.entity_id, e.name) for e in ranked if e.entity_id not in avoid]


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(h))


def _unit(seconds: float) -> tuple[str, float]:
    for unit, size, below in (
        ("hours", 3600, 2 * 86400),
        ("days", 86400, 60 * 86400),
        ("months", YEAR / 12, 2 * YEAR),
        ("years", YEAR, math.inf),
    ):
        if seconds < below:
            return unit, size
    return "years", YEAR


def content_words(f: Facts):
    """Content words of the chapter, first occurrence of each lemma, with their verse: only
    from verses glossed in the chapter's gloss language, so choices never mix languages."""
    seen = set()
    for v in f.verses:
        if f.gloss_verses is not None and v.verse_id not in f.gloss_verses:
            continue
        for t in v.tokens:
            gloss = re.sub(r"\s+", " ", re.sub(r"[<>\[\]]", "", t.gloss or "")).strip()
            lemma = t.strongs or t.lemma
            if (
                not lemma
                or lemma in seen
                or t.name_ref
                or not gloss
                or _GLOSS_SKIP.match(gloss)
                or len(re.sub(r"[֑-ׇ/]", "", t.surface)) < 3
            ):
                continue
            seen.add(lemma)
            yield v, t.model_copy(update={"gloss": gloss})


def _before(a: EventView, b: EventView) -> bool:
    """Whether the corpus settles that `a` starts before `b`: `b` is anchored on `a`, or their
    starts lie further apart than their margins. Margins relative to each event's anchor, not
    absolute ones: inside a chapter the anchor's own uncertainty (a year for a reign, centuries
    for Genesis) moves every event together."""
    gap = b.utes_start - a.utes_start
    if gap < 60 or a.event_id in (b.parent_event_id,) or b.event_id == a.parent_event_id:
        return False
    return b.anchor_id == a.event_id or gap > max(
        a.relative_margin_seconds, b.relative_margin_seconds
    )


def _orderable(f: Facts) -> list[EventView]:
    """A chain of the chapter's scenes, each settled as later than the one before. A parent
    that has its beats as children stands aside: the beats are what happen in order."""
    parents = {e.parent_event_id for e in f.events}
    out: list[EventView] = []
    leaves = (e for e in f.events if e.event_id not in parents)
    for e in sorted(leaves, key=lambda e: (e.utes_start, e.verse_start)):
        if not out or _before(out[-1], e):
            out.append(e)
    return out


# --- the kinds -----------------------------------------------------------------------------------

Made = tuple[Question, Key]


def _q(kind: str, f: Facts, subject: str, seed: int, item: str, **kw) -> Question:
    return Question(
        id=f"{kind}|{f.chapter}|{subject}|{seed}",
        kind=kind,
        family=FAMILY_OF[kind],
        chapter=f.chapter,
        item=item,
        **kw,
    )


def _who_subjects(f: Facts) -> list[str]:
    return [
        f"{e.event_id}~{r.entity_id}"
        for e in f.events
        for r, role in f.participants[e.event_id]
        if role in ROLES and r.entity_type in ("PERSON", "GROUP", "DEITY", "SPIRIT")
    ]


def who(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    event_id, entity_id = subject.split("~")
    e = next(x for x in f.events if x.event_id == event_id)
    parts = f.participants[event_id]
    target, role = next((r, role) for r, role in parts if r.entity_id == entity_id)
    names = [n for r, _ in parts for n in f.names(r.entity_id)]
    others = _distinct(
        rng,
        _entity_pool(f, target, {r.entity_id for r, _ in parts}),
        {target.name},
        inflects=f.inflects,
    )
    if len(others) < 2:
        return None
    ref = f.ref(e.verse_start, e.verse_end)
    q = _q(
        "who",
        f,
        subject,
        seed,
        event_id,
        format="choice",
        prompt=f.t(f"quiz.who.prompt.{role}"),
        context=f.scene(ref, mask(e.title or "", names, f.inflects)),
        choices=_shuffle(
            rng, Choice(id=entity_id, label=target.name), [Choice(id=i, label=n) for i, n in others]
        ),
        verse=e.verse_start,
    )
    return q, Key(
        correct=[entity_id],
        answer=target.name,
        explanation=f.t(f"quiz.who.explanation.{role}", name=target.name, title=e.title, ref=ref),
        verse=e.verse_start,
    )


def scene(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    e = next(x for x in f.events if x.event_id == subject)
    near = [x for x in f.events if x.event_id != subject] + [
        x for x in f.book_events if x.event_id != subject
    ]
    others = _distinct(
        rng,
        [(x.event_id, x.title or "") for x in near if x.title],
        {e.title or ""},
        inflects=f.inflects,
    )
    if len(others) < 2 or not e.title:
        return None
    ref = f.ref(e.verse_start, e.verse_end)
    q = _q(
        "scene",
        f,
        subject,
        seed,
        subject,
        format="choice",
        prompt=f.t("quiz.scene.prompt", ref=ref),
        choices=_shuffle(
            rng, Choice(id=subject, label=e.title), [Choice(id=i, label=t) for i, t in others]
        ),
        verse=e.verse_start,
    )
    return q, Key(
        correct=[subject],
        answer=e.title,
        explanation=e.narrative_summary or e.title,
        verse=e.verse_start,
    )


def cause(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    link = next(c for c in f.causal if c.causal_id == subject)
    titles = f.titles
    effect = next(x for x in f.book_events if x.event_id == link.effect_event_id)
    earlier = [
        x
        for x in sorted(f.book_events, key=lambda x: -x.utes_start)
        if x.utes_start <= effect.utes_start
        and x.event_id not in (link.cause_event_id, effect.event_id)
    ]
    others = _distinct(
        rng,
        [(x.event_id, x.title or "") for x in earlier if x.title],
        {titles.get(link.cause_event_id, "")},
        inflects=f.inflects,
    )
    if len(others) < 2 or link.cause_event_id not in titles:
        return None
    kind_word = (link.causal_type.label or link.causal_type.code).lower()
    q = _q(
        "cause",
        f,
        subject,
        seed,
        subject,
        format="choice",
        prompt=f.t("quiz.cause.prompt"),
        context=f.scene(f.ref(effect.verse_start, effect.verse_end), effect.title or ""),
        choices=_shuffle(
            rng,
            Choice(id=link.cause_event_id, label=titles[link.cause_event_id]),
            [Choice(id=i, label=t) for i, t in others],
        ),
        verse=effect.verse_start,
    )
    return q, Key(
        correct=[link.cause_event_id],
        answer=titles[link.cause_event_id],
        explanation=f.t("quiz.cause.explanation", explanation=link.explanation, kind=kind_word)
        if link.explanation
        else kind_word,
        verse=effect.verse_start,
    )


def _components(f: Facts):
    for d in f.dossiers.values():
        for c in d.components:
            if c.label_value and c.label_key:
                yield d, c


def state(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    d, c = next((d, c) for d, c in _components(f) if c.component_id == subject)
    pool = [
        (x.component_id, x.label_value)
        for _, x in _components(f)
        if x.component_key == c.component_key
    ]
    pool += [
        (x.component_id, x.label_value) for _, x in _components(f) if x.entity_id == c.entity_id
    ]
    others = _distinct(rng, pool, {c.component_id, c.label_value}, inflects=f.inflects)
    if len(others) < 2:
        return None
    name = d.canonical_name or d.entity_id
    q = _q(
        "state",
        f,
        subject,
        seed,
        subject,
        format="choice",
        prompt=f.t(
            "quiz.state.prompt",
            ref=f.ref(c.acquired_at_verse),
            name=name,
            state=c.label_key.lower(),
        ),
        choices=_shuffle(
            rng,
            Choice(id=c.component_id, label=c.label_value),
            [Choice(id=i, label=v) for i, v in others],
        ),
        verse=c.acquired_at_verse,
    )
    return q, Key(
        correct=[c.component_id],
        answer=c.label_value,
        explanation=c.evidence_explanation or c.label_value,
        verse=c.acquired_at_verse,
    )


def _edges(f: Facts):
    seen = set()
    for d in f.dossiers.values():
        for x in d.interactions:
            if x.edge_id not in seen and x.description and x.verse_id.startswith(f"{f.chapter}."):
                seen.add(x.edge_id)
                yield x


def deed(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    x = next(e for e in _edges(f) if e.edge_id == subject)
    others = _distinct(
        rng,
        _entity_pool(f, x.source, {x.source.entity_id, x.target.entity_id}),
        {x.source.name},
        inflects=f.inflects,
    )
    if len(others) < 2:
        return None
    q = _q(
        "deed",
        f,
        subject,
        seed,
        subject,
        format="choice",
        prompt=f.t(
            "quiz.deed.prompt",
            deed=x.interaction_label or x.interaction_type.lower(),
            target=x.target.name,
        ),
        context=f.scene(
            f.ref(x.verse_id), mask(x.description, f.names(x.source.entity_id), f.inflects)
        ),
        choices=_shuffle(
            rng,
            Choice(id=x.source.entity_id, label=x.source.name),
            [Choice(id=i, label=n) for i, n in others],
        ),
        verse=x.verse_id,
    )
    return q, Key(
        correct=[x.source.entity_id],
        answer=x.source.name,
        explanation=x.description,
        verse=x.verse_id,
    )


def order(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    events = _orderable(f)
    if len(events) < 3:
        return None
    picked = sorted(rng.sample(events, min(4, len(events))), key=lambda e: e.utes_start)
    shown = picked[:]
    while [e.event_id for e in shown] == [e.event_id for e in picked]:
        rng.shuffle(shown)
    q = _q(
        "order",
        f,
        subject,
        seed,
        subject,
        format="order",
        prompt=f.t("quiz.order.prompt"),
        choices=[Choice(id=e.event_id, label=e.title or e.event_id) for e in shown],
        verse=picked[0].verse_start,
    )
    told = sorted(picked, key=lambda e: e.verse_start) != picked
    dated = "; ".join(
        f"{e.title or e.event_id} ({f.date(e.utes_start, e.precision_tier.code)})" for e in picked
    )
    return q, Key(
        correct=[e.event_id for e in picked],
        answer=" → ".join(e.title or e.event_id for e in picked),
        explanation=f.t(
            "quiz.order.explanation_retold" if told else "quiz.order.explanation", events=dated
        ),
        verse=picked[0].verse_start,
    )


def _is_region(d: EntityDossier) -> bool:
    """A whole land, known by its English name or by its id ("loc.canaan"), which reads the
    same in every language."""
    id_name = d.entity_id.split(".", 1)[-1].replace("_", " ")
    return bool(_REGION.match(d.canonical_name or "") or _REGION.match(id_name))


def _located(f: Facts) -> list[tuple[EventView, EntityDossier]]:
    """Events set at a place. A whole land is left out: with "Canaan" as the answer, a city in
    Canaan is not wrong."""
    return [
        (e, d)
        for e in f.events
        if e.location and (d := f.dossiers.get(e.location.entity_id)) and not _is_region(d)
    ]


def where(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    e, place = next((e, p) for e, p in _located(f) if e.event_id == subject)
    if place.geo is None:
        return None
    pts = [(p.geo.lat, p.geo.lon) for _, p in _located(f) if p.geo] + [
        (d.geo.lat, d.geo.lon) for d in f.dossiers.values() if d.geo
    ]
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    pad = 2.0
    frame = MapFrame(
        west=min(lons) - pad, south=min(lats) - pad, east=max(lons) + pad, north=max(lats) + pad
    )
    diag = _haversine_km((frame.south, frame.west), (frame.north, frame.east))
    q = _q(
        "where",
        f,
        subject,
        seed,
        subject,
        format="map",
        prompt=f.t("quiz.where.prompt"),
        context=f.scene(f.ref(e.verse_start, e.verse_end), e.title or ""),
        frame=frame,
        verse=e.verse_start,
    )
    return q, Key(
        point=(place.geo.lat, place.geo.lon),
        tolerance=max(30.0, round(diag * 0.06)),
        answer=place.canonical_name or place.entity_id,
        explanation=f.t(
            "quiz.where.explanation",
            title=e.title or "",
            place=place.canonical_name or place.entity_id,
        ),
        verse=e.verse_start,
    )


def place(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    e, p = next((e, p) for e, p in _located(f) if e.event_id == subject)
    target = EntityRef(
        entity_id=p.entity_id, entity_type=p.entity_type, name=p.canonical_name or p.entity_id
    )
    others = _distinct(
        rng, _entity_pool(f, target, {p.entity_id}), {target.name}, inflects=f.inflects
    )
    if len(others) < 2:
        return None
    q = _q(
        "place",
        f,
        subject,
        seed,
        subject,
        format="choice",
        prompt=f.t("quiz.place.prompt"),
        context=f.scene(
            f.ref(e.verse_start, e.verse_end),
            mask(e.title or "", _name_parts(f.names(p.entity_id)), f.inflects),
        ),
        choices=_shuffle(
            rng,
            Choice(id=p.entity_id, label=target.name),
            [Choice(id=i, label=n) for i, n in others],
        ),
        verse=e.verse_start,
    )
    return q, Key(
        correct=[p.entity_id],
        answer=target.name,
        explanation=f.t("quiz.place.explanation", place=target.name),
        verse=e.verse_start,
    )


def _span_subjects(f: Facts) -> list[str]:
    """Pairs where the text times the second scene from the first ("on the third day")."""
    by_id = {e.event_id: e for e in f.events}
    out = []
    for b in f.events:
        a = by_id.get(b.anchor_id)
        gap = b.utes_start - a.utes_start if a else 0
        if (
            a
            and gap >= 3600
            and a.event_id != b.parent_event_id
            and b.relative_margin_seconds <= gap / 2
        ):
            out.append(f"{a.event_id}~{b.event_id}")
    return out


def span(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    a_id, b_id = subject.split("~")
    a = next(e for e in f.events if e.event_id == a_id)
    b = next(e for e in f.events if e.event_id == b_id)
    gap = b.utes_start - a.utes_start
    unit, size = _unit(gap)
    tolerance = max(b.relative_margin_seconds, gap * 0.25) / size
    q = _q(
        "span",
        f,
        subject,
        seed,
        subject,
        format="number",
        prompt=f.t(f"quiz.span.prompt.{unit}"),
        context=f.t(
            "quiz.span.context",
            first=mask_numbers(a.title or ""),
            first_ref=f.ref(a.verse_start),
            second=mask_numbers(b.title or ""),
            second_ref=f.ref(b.verse_start),
        ),
        unit=f.t(f"quiz.unit.{unit}"),
        verse=b.verse_start,
    )
    return q, Key(
        value=round(gap / size, 2),
        tolerance=round(tolerance, 2),
        answer=f.t(
            "quiz.span.answer",
            value=f.duration(gap / size, unit),
            tolerance=f.duration(tolerance, unit),
        ),
        explanation=b.temporal_reasoning_note
        or f"{f.date(a.utes_start, a.precision_tier.code)} → "
        f"{f.date(b.utes_start, b.precision_tier.code)}",
        verse=b.verse_start,
    )


def _age_subjects(f: Facts) -> list[str]:
    return [
        e.event_id
        for e in f.events
        if re.fullmatch(r"anchor\.[a-z]+_birth", e.anchor_id)
        and e.anchor_point == "START"
        and e.relative_offset_seconds >= YEAR
    ]


def _born(f: Facts, anchor_id: str) -> str:
    """Whose birth an anchor counts from, by the name the bundle gives that person."""
    key = anchor_id.split(".")[1].removesuffix("_birth")
    person = next(
        (
            e
            for e in f.entities
            if e.entity_id == f"person.{key}" or e.entity_id.startswith(f"person.{key}.")
        ),
        None,
    )
    return person.name if person else key.replace("_", " ").title()


def age(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    e = next(x for x in f.events if x.event_id == subject)
    who_name = _born(f, e.anchor_id)
    years = e.relative_offset_seconds / YEAR
    tolerance = max(1.0, e.relative_margin_seconds / YEAR)
    q = _q(
        "age",
        f,
        subject,
        seed,
        subject,
        format="number",
        prompt=f.t("quiz.age.prompt", name=who_name),
        context=f.scene(f.ref(e.verse_start, e.verse_end), mask_numbers(e.title or "")),
        unit=f.t("quiz.unit.years"),
        verse=e.verse_start,
    )
    return q, Key(
        value=round(years, 1),
        tolerance=round(tolerance, 1),
        answer=f.duration(years, "years"),
        explanation=e.temporal_reasoning_note or e.title or "",
        verse=e.verse_start,
    )


def _hebrew_line(v: VerseMatrix, pos: int) -> str:
    return " ".join(f"[{t.surface}]" if t.pos == pos else t.surface for t in v.tokens)


def _hebrew_word(t: TokenView) -> str:
    return f"{t.surface} ({t.translit})" if t.translit else t.surface


def _gloss_explanation(f: Facts, t: TokenView) -> str:
    if t.lemma:
        return f.t("quiz.gloss.explanation", word=_hebrew_word(t), lemma=t.lemma, gloss=t.gloss)
    return f.t("quiz.gloss.explanation_no_lemma", word=_hebrew_word(t), gloss=t.gloss)


def gloss(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    verse_id, pos = subject.split("~")
    found = [(v, t) for v, t in content_words(f)]
    v, t = next((v, t) for v, t in found if v.verse_id == verse_id and t.pos == int(pos))
    pool = [(x.strongs or x.lemma or "", x.gloss or "") for _, x in found]
    rng.shuffle(pool)
    others = _distinct(rng, pool, {t.gloss}, inflects=f.gloss_lang != "en")
    if len(others) < 2:
        return None
    english = f.gloss_lang != f.lang
    q = _q(
        "gloss",
        f,
        subject,
        seed,
        t.strongs or t.lemma or subject,
        format="choice",
        prompt=f.t(
            "quiz.gloss.prompt_english" if english else "quiz.gloss.prompt", word=_hebrew_word(t)
        ),
        context=f.ref(verse_id),
        hebrew=_hebrew_line(v, t.pos),
        choices=_shuffle(
            rng, Choice(id="ok", label=t.gloss), [Choice(id=i, label=g) for i, g in others]
        ),
        verse=verse_id,
    )
    return q, Key(
        correct=["ok"], answer=t.gloss, explanation=_gloss_explanation(f, t), verse=verse_id
    )


def word(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    verse_id, pos = subject.split("~")
    found = list(content_words(f))
    v, t = next((v, t) for v, t in found if v.verse_id == verse_id and t.pos == int(pos))
    pool = [(f"{x.pos}@{w.verse_id}", x.surface) for w, x in found if x.gloss != t.gloss]
    rng.shuffle(pool)
    others = _distinct(rng, pool, {t.surface})
    if len(others) < 2:
        return None
    q = _q(
        "word",
        f,
        subject,
        seed,
        t.strongs or t.lemma or subject,
        format="choice",
        prompt=f.t(
            "quiz.word.prompt_english" if f.gloss_lang != f.lang else "quiz.word.prompt",
            gloss=t.gloss,
            ref=f.ref(verse_id),
        ),
        choices=_shuffle(
            rng,
            Choice(id="ok", label=t.surface, hebrew=True),
            [Choice(id=i, label=s, hebrew=True) for i, s in others],
        ),
        verse=verse_id,
    )
    return q, Key(
        correct=["ok"],
        answer=_hebrew_word(t),
        explanation=_gloss_explanation(f, t),
        verse=verse_id,
    )


def _cloze_text(f: Facts, v: VerseMatrix) -> tuple[str, str] | None:
    """The verse in the learner's own language, with the prompt that names it: the language's
    traditional translation (the KJV for English), else its literal one; None when the bundle
    has neither, rather than a verse in another language."""
    if v.traditional_baseline and v.baseline_lang == f.lang:
        prompt = f.t("quiz.cloze.prompt", translation=v.baseline_translation or "")
        return v.traditional_baseline, prompt
    if v.translation_literal and v.layers_lang == f.lang:
        return v.translation_literal, f.t("quiz.cloze.prompt_literal")
    return None


def _name_of(f: Facts, word: str) -> str | None:
    """The bundle's one-word name that a word of a verse is, or is a form of ("Иосифа")."""
    for name in f.single_names:
        if word == name:
            return name
    if f.inflects:
        for name in f.single_names:
            stem = _stem(name)
            if len(name) > 4 and word.startswith(stem) and len(word) - len(stem) <= 3:
                return name
    return None


def _cloze_words(f: Facts, v: VerseMatrix) -> list[str]:
    """Words worth recalling in a verse: the names in it, or else its longer content words."""
    found = _cloze_text(f, v)
    words = _WORD.findall(found[0]) if found else []
    named = [w for w in words if _name_of(f, w)]
    content = [w for w in words if 5 <= len(w) <= 12 and w.lower() not in _STOPWORDS]
    return list(dict.fromkeys(named or content))


def cloze(f: Facts, subject: str, seed: int, rng: random.Random) -> Made | None:
    v = next(x for x in f.verses if x.verse_id == subject)
    words = _cloze_words(f, v)
    if not words:
        return None
    text, prompt = _cloze_text(f, v)
    target = rng.choice(words[:4])
    blanked = re.sub(rf"\b{re.escape(target)}\b", "_____", text, count=1)
    # A name may stand in the verse in another case; its name as the bundle has it counts too.
    accept = list(dict.fromkeys([target, _name_of(f, target) or target]))
    q = _q(
        "cloze",
        f,
        subject,
        seed,
        subject,
        format="text",
        prompt=prompt,
        context=f"{f.ref(subject)}: {blanked}",
        verse=subject,
    )
    return q, Key(accept=accept, answer=target, explanation=text, verse=subject)


GENERATORS: dict[str, Callable[[Facts, str, int, random.Random], Made | None]] = {
    "who": who,
    "scene": scene,
    "cause": cause,
    "state": state,
    "deed": deed,
    "order": order,
    "where": where,
    "place": place,
    "span": span,
    "age": age,
    "gloss": gloss,
    "word": word,
    "cloze": cloze,
}


def subjects(f: Facts, kind: str) -> list[str]:
    """Everything a kind of question can ask about in this chapter."""
    match kind:
        case "who":
            return _who_subjects(f)
        case "scene":
            return [e.event_id for e in f.events if e.title]
        case "cause":
            return [c.causal_id for c in f.causal]
        case "state":
            return [
                c.component_id
                for _, c in _components(f)
                if c.acquired_at_verse.startswith(f"{f.chapter}.")
            ]
        case "deed":
            return [x.edge_id for x in _edges(f)]
        case "order":
            return [f.chapter] if len(_orderable(f)) >= 3 else []
        case "where":
            return [e.event_id for e, p in _located(f) if p.geo]
        case "place":
            return [e.event_id for e, _ in _located(f)]
        case "span":
            return _span_subjects(f)
        case "age":
            return _age_subjects(f)
        case "gloss" | "word":
            return [f"{v.verse_id}~{t.pos}" for v, t in content_words(f)]
        case "cloze":
            return [v.verse_id for v in f.verses if _cloze_words(f, v)]
    raise ValueError(f"unknown kind {kind!r}")


def make(f: Facts, kind: str, subject: str, seed: int) -> Made | None:
    try:
        return GENERATORS[kind](f, subject, seed, random.Random(f"{kind}|{subject}|{seed}"))
    except StopIteration:  # the subject is gone from the corpus
        return None


def parse_id(question_id: str) -> tuple[str, str, str, int]:
    kind, chapter, subject, seed = question_id.split("|")
    if kind not in GENERATORS:
        raise ValueError(f"unknown kind {kind!r}")
    return kind, chapter, subject, int(seed)


def judge(q: Question, key: Key, response: object, t: Translator = ENGLISH) -> Judged:
    """Check a response against the key; `t` words the answer line in the learner's language."""
    correct, score = False, 0.0
    match q.format:
        case "choice":
            correct = response in key.correct
            score = float(correct)
        case "order":
            given = [r for r in (response or []) if r in key.correct]
            rank = {item: i for i, item in enumerate(key.correct)}
            pairs = [(a, b) for i, a in enumerate(given) for b in given[i + 1 :]]
            agree = sum(rank[a] < rank[b] for a, b in pairs)
            score = agree / len(pairs) if pairs and len(given) == len(key.correct) else 0.0
            correct = score == 1.0
        case "map":
            lat, lon = (float(x) for x in response)
            km = _haversine_km((lat, lon), key.point)
            correct = km <= key.tolerance
            score = 1.0 if correct else max(0.0, 1 - (km - key.tolerance) / (2 * key.tolerance))
            return Judged(
                correct=correct,
                score=round(score, 3),
                answer=t("quiz.where.distance", answer=key.answer, count=round(km)),
                explanation=key.explanation,
                verse=key.verse,
                point=key.point,
            )
        case "number":
            off = abs(float(response) - key.value)
            correct = off <= key.tolerance
            score = (
                1.0 if correct else max(0.0, 1 - (off - key.tolerance) / (key.tolerance * 2 + 1))
            )
        case "text":
            given = _norm(str(response))
            correct = any(
                given == _norm(a) or (len(a) >= 5 and _edit_distance(given, _norm(a)) <= 1)
                for a in key.accept
            )
            score = float(correct)
    return Judged(
        correct=correct,
        score=round(score, 3),
        answer=key.answer,
        explanation=key.explanation,
        verse=key.verse,
    )


def _norm(text: str) -> str:
    """Case, punctuation and the Russian ё (often typed as е) do not count."""
    return re.sub(r"[^\w]", "", text.casefold().replace("’", "'").replace("ё", "е"))


def _edit_distance(a: str, b: str) -> int:
    """Edits between two words, a swap of neighbouring letters counting as one (a typo)."""
    d = [[i + j if not i * j else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(
                d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1])
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]
