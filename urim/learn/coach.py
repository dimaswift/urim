"""Which questions to ask: what is due first, then what you have not met, kinds mixed.

Practice follows the schedule in the learner store; an exam ignores it and samples every kind
evenly, so a passed exam says you know the chapter, not only the cards you happened to drill.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from urim.learn.quiz import FAMILIES, Facts, Key, Question, content_words, make, subjects
from urim.learn.store import Learner, card_id

EXAM_SIZE = 15


@dataclass(frozen=True)
class Candidate:
    kind: str
    subject: str
    item: str

    def card(self, chapter: str) -> str:
        return card_id(self.kind, chapter, self.item)


def candidates(f: Facts, kinds: tuple[str, ...]) -> list[Candidate]:
    lemma = {f"{v.verse_id}~{t.pos}": t.strongs or t.lemma for v, t in content_words(f)}
    out = []
    for kind in kinds:
        for s in subjects(f, kind):
            item = (
                s.split("~")[0]
                if kind == "who"
                else lemma.get(s, s)
                if kind in ("gloss", "word")
                else s
            )
            out.append(Candidate(kind, s, item))
    return out


def facts_count(f: Facts) -> int:
    """Distinct facts a chapter offers, the denominator of its mastery."""
    kinds = tuple(k for ks in FAMILIES.values() for k in ks)
    return len({c.card(f.chapter) for c in candidates(f, kinds)})


def _interleave(rng: random.Random, pool: list[Candidate]) -> list[Candidate]:
    by_kind: dict[str, list[Candidate]] = defaultdict(list)
    for c in pool:
        by_kind[c.kind].append(c)
    for group in by_kind.values():
        rng.shuffle(group)
    out, order = [], list(by_kind)
    rng.shuffle(order)
    while any(by_kind.values()):
        for kind in order:
            if by_kind[kind]:
                out.append(by_kind[kind].pop())
    return out


def session(
    f: Facts,
    learner: Learner | None,
    *,
    mode: str = "practice",
    families: tuple[str, ...] = tuple(FAMILIES),
    n: int = 10,
    seed: int | None = None,
) -> list[tuple[Question, Key]]:
    rng = random.Random(seed)
    kinds = tuple(k for fam in families for k in FAMILIES[fam])
    pool = candidates(f, kinds)
    if mode == "exam":
        queue = _interleave(rng, pool)
        n = EXAM_SIZE
    else:
        by_card: dict[str, list[Candidate]] = defaultdict(list)
        for c in pool:
            by_card[c.card(f.chapter)].append(c)
        due = [r["card_id"] for r in learner.due(f.chapter)] if learner else []
        seen = learner.seen(f.chapter) if learner else set()
        first = [rng.choice(by_card[cid]) for cid in due if cid in by_card]
        fresh = _interleave(rng, [c for c in pool if c.card(f.chapter) not in seen])
        again = _interleave(rng, [c for c in pool if c.card(f.chapter) in seen])
        queue = first + fresh + again
    out, used = [], set()
    for c in queue:
        if len(out) == n:
            break
        if c.card(f.chapter) in used:
            continue
        made = make(f, c.kind, c.subject, rng.randrange(1_000_000))
        if made:
            used.add(c.card(f.chapter))
            out.append(made)
    return out
