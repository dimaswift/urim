"""STEPBible TAHOT: the Hebrew text, one word per line, with morphology and lexical tags.

Each word line is keyed by its English (KJV) reference with the Hebrew reference in parentheses
when they differ, e.g. `1Ki.18.33(18.34)#01=L` is word 1 of Hebrew 18:34, which English Bibles
print as part of 18:33. Word numbers count within the Hebrew verse. That gives an exact,
word-level KJV <-> Hebrew versification map for free.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from urim.canon import BOOKS_BY_STEPBIBLE, Book, parse_ref
from urim.ir.models import SourceVerse, Token, VerseMapRow

_REF = re.compile(
    r"^(?P<book>[1-3]?[A-Z][a-z]{1,3})\.(?P<ch>\d+)\.(?P<v>\d+)"
    r"(?:\((?P<hch>\d+)\.(?P<hv>\d+)\))?#(?P<word>\d+)=(?P<type>\S+)$"
)
_BRACED = re.compile(r"\{([^}]*)\}")
_NAME_REF = re.compile(r"^[^@\s]+@[1-3]?[A-Z][a-z]{1,3}\.\d+\.\d+[a-z]?(?:-[1-3]?[A-Za-z.\d]*)?$")
_KEPT_PUNCTUATION = {"־", "׃"}  # maqqef, sof pasuq; paragraph markers (פ / ס) are dropped


@dataclass(frozen=True)
class TahotWord:
    eng_ref: str  # verse id in KJV numbering, e.g. "1KGS.18.33"
    heb_ref: str  # verse id in source (Hebrew) numbering
    word_no: int  # position within the Hebrew verse
    reading: str  # L = Leningrad; Q(K = Qere with Ketiv variant; ...
    hebrew: str
    punctuation: str
    translit: str
    gloss_en: str
    dstrong: str | None
    morph: str
    lemma: str | None
    name_ref: str | None


def _split_hebrew(field: str) -> tuple[str, str]:
    word, _, punct = field.partition("\\")
    return word.replace("/", ""), "".join(c for c in punct if c in _KEPT_PUNCTUATION)


def _clean_translit(field: str) -> str:
    return field.split("\\")[0].replace("/", "").replace(".", "").rstrip("-")


def _clean_gloss(field: str) -> str:
    return re.sub(r"\s+", " ", field.replace("/ ", " ").replace("/", "")).strip()


def _main_tag(expanded: str) -> tuple[str | None, str | None, str | None]:
    """(dStrong, lemma, TIPNR name) from the braced main lexeme of the Expanded Strong tags."""
    m = _BRACED.search(expanded)
    if not m:
        return None, None, None
    parts = m.group(1).split("=")
    dstrong = parts[0] or None
    lemma = parts[1] if len(parts) > 1 and parts[1] else None
    name = None
    if len(parts) > 2 and "»" in parts[2]:
        candidate = parts[2].rsplit("»", 1)[1]
        name = candidate if _NAME_REF.match(candidate) else None
    return dstrong, lemma, name


def read_tahot(paths: Iterable[Path], wanted: dict[str, set[int] | None]) -> list[TahotWord]:
    """Words for the wanted books (our code -> Hebrew chapters, None = all)."""
    words: list[TahotWord] = []
    for path in paths:
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                head, _, rest = line.partition("\t")
                m = _REF.match(head)
                if not m:
                    continue
                book: Book | None = BOOKS_BY_STEPBIBLE.get(m["book"])
                if book is None or book.code not in wanted:
                    continue
                heb_ch = int(m["hch"] or m["ch"])
                chapters = wanted[book.code]
                if chapters is not None and heb_ch not in chapters:
                    continue
                cols = rest.rstrip("\r\n").split("\t")
                hebrew, punct = _split_hebrew(cols[0])
                dstrong, lemma, name = _main_tag(cols[10] if len(cols) > 10 else "")
                if dstrong is None:
                    braced = _BRACED.search(cols[3])
                    dstrong = braced.group(1) if braced else None
                words.append(
                    TahotWord(
                        eng_ref=f"{book.code}.{m['ch']}.{m['v']}",
                        heb_ref=f"{book.code}.{heb_ch}.{m['hv'] or m['v']}",
                        word_no=int(m["word"]),
                        reading=m["type"],
                        hebrew=hebrew,
                        punctuation=punct,
                        translit=_clean_translit(cols[1]),
                        gloss_en=_clean_gloss(cols[2]),
                        dstrong=dstrong,
                        morph=cols[4],
                        lemma=lemma,
                        name_ref=name,
                    )
                )
    return words


def build_verses(words: list[TahotWord]) -> list[SourceVerse]:
    by_verse: dict[str, list[TahotWord]] = defaultdict(list)
    for w in words:
        by_verse[w.heb_ref].append(w)
    verses = []
    for vid in sorted(by_verse, key=lambda v: parse_ref(v)[1].ordinal):
        ws = sorted(by_verse[vid], key=lambda w: w.word_no)
        text = ""
        for w in ws:
            text += ("" if not text or text.endswith("־") else " ") + w.hebrew + w.punctuation
        verses.append(
            SourceVerse(
                verse_id=vid,
                source_text=text,
                tokens=[
                    Token(
                        pos=i,
                        surface=w.hebrew,
                        translit=w.translit or None,
                        lemma=w.lemma,
                        strongs=w.dstrong,
                        morph=w.morph or None,
                        name_ref=w.name_ref,
                        reading=None if w.reading == "L" else w.reading,
                    )
                    for i, w in enumerate(ws, start=1)
                ],
                glosses={"en": [w.gloss_en for w in ws]},
            )
        )
    return verses


def kjv_verse_map(words: list[TahotWord]) -> list[VerseMapRow]:
    """Alias rows wherever KJV and Hebrew verse boundaries differ.

    A scheme ref that maps anywhere unusual lists *all* its target verses, and a source verse
    fed by an unusual ref lists *all* its source refs, so lookups never fall back to identity
    halfway through a split.
    """
    words_per_heb: dict[str, Counter[str]] = defaultdict(Counter)
    for w in words:
        words_per_heb[w.heb_ref][w.eng_ref] += 1
    pairs = {(eng, heb) for heb, engs in words_per_heb.items() for eng in engs}
    odd = {(e, h) for e, h in pairs if e != h}
    odd_eng = {e for e, _ in odd}
    odd_heb = {h for _, h in odd}
    rows = [
        VerseMapRow(
            scheme="KJV",
            scheme_ref=e,
            verse_id=h,
            coverage="FULL" if set(words_per_heb[h]) == {e} else "PARTIAL",
        )
        for e, h in pairs
        if e in odd_eng or h in odd_heb
    ]
    return sorted(
        rows, key=lambda r: (parse_ref(r.scheme_ref)[1].ordinal, parse_ref(r.verse_id)[1].ordinal)
    )


def kjv_refs_for(words: list[TahotWord]) -> set[str]:
    """Every KJV verse that holds at least one of these words."""
    return {w.eng_ref for w in words}
