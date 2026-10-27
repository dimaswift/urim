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

# Commentaries on the Prophets and Writings; Torah would use Onkelos instead of Jonathan.
PROPHETS_WORKS = (
    "Rashi",
    "Radak",
    "Ralbag",
    "Metzudat David",
    "Metzudat Zion",
    "Malbim",
    "Targum Jonathan",
)

_TAG = re.compile(r"<[^>]+>")


@dataclass
class WorkChapter:
    work: str
    version_title: str
    license: str
    verses: dict[int, list[str]]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", text))).strip()


def fetch_chapter(fetcher: Fetcher, work: str, book: Book, chapter: int) -> WorkChapter | None:
    title = f"{work} on {book.sefaria}"
    slug = title.replace(" ", "_")
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
        work=work,
        version_title=version.get("versionTitle", "").strip(),
        license=version.get("license") or "unknown",
        verses=verses,
    )
