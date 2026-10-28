"""Hebrew commentaries and Targum from Sefaria (API v3), one request per work and chapter.

Sefaria numbers Tanakh verses as the Hebrew text does, so its refs are already source ids.
Responses are cached under data/sources/sefaria and pinned in the lockfile like any other
source. Commentaries are compile-time input for the agents; bundles never ship them.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from urllib.parse import quote

from urim.canon import Book
from urim.compiler.ingest.fetch import Fetcher

API = "https://www.sefaria.org/api/v3/texts/"


@dataclass(frozen=True)
class Work:
    """A commentary or Targum: the name packets and citations use, and its Sefaria title."""

    name: str
    title: str = "{work} on {book}"
    targum: bool = False

    def sefaria_title(self, book: Book) -> str:
        return self.title.format(work=self.name, book=book.sefaria)


# Sefaria's "Targum Jonathan on Genesis" is the Palestinian Pseudo-Jonathan, not the Targum
# Jonathan of the Prophets, so it goes by its scholarly name here.
TORAH_WORKS = (
    Work("Rashi"),
    Work("Rashbam"),
    Work("Ibn Ezra"),
    Work("Ramban"),
    Work("Radak"),
    Work("Sforno"),
    Work("Onkelos", "{work} {book}", targum=True),
    Work("Targum Pseudo-Jonathan", "Targum Jonathan on {book}", targum=True),
)
PROPHETS_WORKS = (
    Work("Rashi"),
    Work("Radak"),
    Work("Ralbag"),
    Work("Metzudat David"),
    Work("Metzudat Zion"),
    Work("Malbim"),
    Work("Targum Jonathan", targum=True),
)
TARGUMS = frozenset(w.name for w in TORAH_WORKS + PROPHETS_WORKS if w.targum)


def works_for(book: Book) -> tuple[Work, ...]:
    """The commentaries ingested for a book: the Torah has its own classical set and Onkelos."""
    return TORAH_WORKS if book.book_id <= 5 else PROPHETS_WORKS


_TAG = re.compile(r"<[^>]+>")


@dataclass
class WorkChapter:
    work: str
    version_title: str
    license: str
    verses: dict[int, list[str]]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", text))).strip()


def fetch_chapter(fetcher: Fetcher, work: Work, book: Book, chapter: int) -> WorkChapter | None:
    slug = work.sefaria_title(book).replace(" ", "_")
    path = fetcher.get_url(
        key=f"sefaria/{slug}.{chapter}",
        url=f"{API}{quote(slug)}.{chapter}?version=hebrew",
        rel_path=f"sefaria/{slug}/{chapter}.json",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("versions"):
        return None
    version = data["versions"][0]
    verses: dict[int, list[str]] = {}
    for i, item in enumerate(version.get("text") or [], start=1):
        comments = [item] if isinstance(item, str) else item
        cleaned = [c for c in (_clean(x) for x in comments if isinstance(x, str)) if c]
        if cleaned:
            verses[i] = cleaned
    return WorkChapter(
        work=work.name,
        version_title=version.get("versionTitle", "").strip(),
        license=version.get("license") or "unknown",
        verses=verses,
    )
