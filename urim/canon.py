"""Book table, verse reference parsing and versification schemes.

Canonical verse ids use the *source-text* versification (Hebrew WLC for the OT, Greek for the
NT) and the form BOOK.CHAPTER.VERSE with uppercased OSIS book codes, e.g. "1KGS.18.27".
Other numbering traditions (KJV, Synodal, LXX, ...) are aliases resolved through
core_verse_map.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    book_id: int  # 1-66, Protestant canon order
    code: str  # "1KGS"
    osis: str  # "1Kgs"
    testament: str  # "OT" | "NT"
    stepbible: str  # STEPBible abbreviation: "1Ki"
    sefaria: str | None  # Sefaria index title: "I Kings" (Tanakh only)


# (OSIS, STEPBible, Sefaria) per book, in canon order.
# fmt: off
_BOOK_NAMES = [
    ("Gen", "Gen", "Genesis"), ("Exod", "Exo", "Exodus"), ("Lev", "Lev", "Leviticus"),
    ("Num", "Num", "Numbers"), ("Deut", "Deu", "Deuteronomy"), ("Josh", "Jos", "Joshua"),
    ("Judg", "Jdg", "Judges"), ("Ruth", "Rut", "Ruth"), ("1Sam", "1Sa", "I Samuel"),
    ("2Sam", "2Sa", "II Samuel"), ("1Kgs", "1Ki", "I Kings"), ("2Kgs", "2Ki", "II Kings"),
    ("1Chr", "1Ch", "I Chronicles"), ("2Chr", "2Ch", "II Chronicles"), ("Ezra", "Ezr", "Ezra"),
    ("Neh", "Neh", "Nehemiah"), ("Esth", "Est", "Esther"), ("Job", "Job", "Job"),
    ("Ps", "Psa", "Psalms"), ("Prov", "Pro", "Proverbs"), ("Eccl", "Ecc", "Ecclesiastes"),
    ("Song", "Sng", "Song of Songs"), ("Isa", "Isa", "Isaiah"), ("Jer", "Jer", "Jeremiah"),
    ("Lam", "Lam", "Lamentations"), ("Ezek", "Ezk", "Ezekiel"), ("Dan", "Dan", "Daniel"),
    ("Hos", "Hos", "Hosea"), ("Joel", "Jol", "Joel"), ("Amos", "Amo", "Amos"),
    ("Obad", "Oba", "Obadiah"), ("Jonah", "Jon", "Jonah"), ("Mic", "Mic", "Micah"),
    ("Nah", "Nam", "Nahum"), ("Hab", "Hab", "Habakkuk"), ("Zeph", "Zep", "Zephaniah"),
    ("Hag", "Hag", "Haggai"), ("Zech", "Zec", "Zechariah"), ("Mal", "Mal", "Malachi"),
    ("Matt", "Mat", None), ("Mark", "Mrk", None), ("Luke", "Luk", None), ("John", "Jhn", None),
    ("Acts", "Act", None), ("Rom", "Rom", None), ("1Cor", "1Co", None), ("2Cor", "2Co", None),
    ("Gal", "Gal", None), ("Eph", "Eph", None), ("Phil", "Php", None), ("Col", "Col", None),
    ("1Thess", "1Th", None), ("2Thess", "2Th", None), ("1Tim", "1Ti", None),
    ("2Tim", "2Ti", None), ("Titus", "Tit", None), ("Phlm", "Phm", None), ("Heb", "Heb", None),
    ("Jas", "Jas", None), ("1Pet", "1Pe", None), ("2Pet", "2Pe", None), ("1John", "1Jn", None),
    ("2John", "2Jn", None), ("3John", "3Jn", None), ("Jude", "Jud", None), ("Rev", "Rev", None),
]
# fmt: on

BOOKS: tuple[Book, ...] = tuple(
    Book(i, osis.upper(), osis, "OT" if i <= 39 else "NT", step, sefaria)
    for i, (osis, step, sefaria) in enumerate(_BOOK_NAMES, start=1)
)
BOOKS_BY_CODE: dict[str, Book] = {b.code: b for b in BOOKS}
BOOKS_BY_STEPBIBLE: dict[str, Book] = {b.stepbible: b for b in BOOKS}
BOOKS_BY_OSIS: dict[str, Book] = {b.osis: b for b in BOOKS}

# Versification scheme each baseline translation follows. Translations absent here follow the
# source-text numbering.
TRANSLATION_SCHEMES: dict[str, str] = {
    "KJV": "KJV",
    "KJVA": "KJV",
    "YLT": "KJV",
    "ASV": "KJV",
    "WEB": "KJV",
    "BBE": "KJV",
    "Webster": "KJV",
    "RusSynodal": "SYNODAL",
}

_REF_RE = re.compile(r"^\s*([1-3]?[A-Za-z]+)[\s.]+(\d+)[.:](\d+)\s*$")


@dataclass(frozen=True)
class VerseRef:
    book: Book
    chapter: int
    verse: int

    @property
    def verse_id(self) -> str:
        return f"{self.book.code}.{self.chapter}.{self.verse}"

    @property
    def ordinal(self) -> int:
        """Sortable position in canon order; stable across partial builds."""
        return verse_ordinal(self.book.book_id, self.chapter, self.verse)


def verse_ordinal(book_id: int, chapter: int, verse: int) -> int:
    return book_id * 1_000_000 + chapter * 1_000 + verse


def parse_ref(ref: str) -> tuple[str | None, VerseRef]:
    """Parse "1KGS.18.27", "1Kgs 18:27" or "KJV:1Kgs.18.33" into (scheme, VerseRef).

    scheme is None for source-text numbering.
    """
    scheme = None
    head, sep, tail = ref.partition(":")
    if sep and head.isalpha() and head.isupper() and head.upper() not in BOOKS_BY_CODE:
        scheme, ref = head, tail
    m = _REF_RE.match(ref)
    if not m:
        raise ValueError(f"unparseable verse reference: {ref!r}")
    code, chapter, verse = m.group(1).upper(), int(m.group(2)), int(m.group(3))
    book = BOOKS_BY_CODE.get(code)
    if book is None:
        raise ValueError(f"unknown book code: {m.group(1)!r}")
    return scheme, VerseRef(book, chapter, verse)
