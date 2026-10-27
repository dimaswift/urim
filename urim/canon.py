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


_OSIS_CODES = [
    "Gen",
    "Exod",
    "Lev",
    "Num",
    "Deut",
    "Josh",
    "Judg",
    "Ruth",
    "1Sam",
    "2Sam",
    "1Kgs",
    "2Kgs",
    "1Chr",
    "2Chr",
    "Ezra",
    "Neh",
    "Esth",
    "Job",
    "Ps",
    "Prov",
    "Eccl",
    "Song",
    "Isa",
    "Jer",
    "Lam",
    "Ezek",
    "Dan",
    "Hos",
    "Joel",
    "Amos",
    "Obad",
    "Jonah",
    "Mic",
    "Nah",
    "Hab",
    "Zeph",
    "Hag",
    "Zech",
    "Mal",
    "Matt",
    "Mark",
    "Luke",
    "John",
    "Acts",
    "Rom",
    "1Cor",
    "2Cor",
    "Gal",
    "Eph",
    "Phil",
    "Col",
    "1Thess",
    "2Thess",
    "1Tim",
    "2Tim",
    "Titus",
    "Phlm",
    "Heb",
    "Jas",
    "1Pet",
    "2Pet",
    "1John",
    "2John",
    "3John",
    "Jude",
    "Rev",
]

BOOKS: tuple[Book, ...] = tuple(
    Book(i, osis.upper(), osis, "OT" if i <= 39 else "NT")
    for i, osis in enumerate(_OSIS_CODES, start=1)
)
BOOKS_BY_CODE: dict[str, Book] = {b.code: b for b in BOOKS}

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
