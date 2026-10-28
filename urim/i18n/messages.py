"""Interface messages: every word the War Room, the Codex and the quizzes show that is not
corpus content.

English is the source, written with the code in `urim/i18n/en/<namespace>.json`: a key maps
to its text, or to an object with the text (or plural forms) and a note for translators.
Translations are corpus content, written by the localizer and merged into
`corpus/i18n/<lang>/_ui.json`; each records the English it was made from in the language
ledger, so a changed English message shows up as stale. A missing translation falls back to
English, so a language can go live a namespace at a time.

Placeholders are `{name}`; a message with plural forms is chosen by `{count}` and the
language's plural rules (CLDR categories, as the browser's Intl.PluralRules has them).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

EN_DIR = Path(__file__).parent / "en"
UI_FILE = "_ui.json"
PLURAL_KEYS = ("zero", "one", "two", "few", "many", "other")
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# CLDR plural categories for cardinals, for the languages we expect to meet.
PLURAL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "ru": ("one", "few", "many", "other"),
    "uk": ("one", "few", "many", "other"),
    "be": ("one", "few", "many", "other"),
    "pl": ("one", "few", "many", "other"),
    "cs": ("one", "few", "many", "other"),
    "he": ("one", "two", "other"),
    "ar": ("zero", "one", "two", "few", "many", "other"),
    "ja": ("other",),
    "zh": ("other",),
    "ko": ("other",),
}


def plural_categories(lang: str) -> tuple[str, ...]:
    return PLURAL_CATEGORIES.get(lang, ("one", "other"))


def plural_category(lang: str, n: float) -> str:
    """The CLDR category of an integer count; enough for counts of things."""
    if n != int(n):
        return "other"
    n = abs(int(n))
    if lang in ("ru", "uk", "be"):
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang == "pl":
        if n == 1:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang == "cs":
        return "one" if n == 1 else "few" if 2 <= n <= 4 else "other"
    if lang == "he":
        return "one" if n == 1 else "two" if n == 2 else "other"
    if lang in ("ja", "zh", "ko"):
        return "other"
    if lang == "fr":
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


@dataclass(frozen=True)
class Source:
    """One English message: its text or plural forms, and a note for the translator."""

    key: str
    namespace: str
    text: str | None
    forms: dict[str, str] | None
    note: str

    @property
    def placeholders(self) -> set[str]:
        texts = [self.text] if self.text is not None else list((self.forms or {}).values())
        return {m for t in texts for m in _PLACEHOLDER.findall(t)}

    @property
    def hash(self) -> str:
        body = self.text if self.text is not None else json.dumps(self.forms, sort_keys=True)
        return source_hash(body)


def source_hash(value: object) -> str:
    """Short hash of what a translation was made from: a message, a text item, a label."""
    body = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


@cache
def english() -> dict[str, Source]:
    """Every English message, by key."""
    out: dict[str, Source] = {}
    for path in sorted(EN_DIR.glob("*.json")):
        for k, v in json.loads(path.read_text(encoding="utf-8")).items():
            if k in out:
                raise ValueError(f"message {k!r} is defined in {out[k].namespace} and {path.stem}")
            if isinstance(v, str):
                out[k] = Source(k, path.stem, v, None, "")
            else:
                forms = {p: v[p] for p in PLURAL_KEYS if p in v}
                out[k] = Source(k, path.stem, v.get("text"), forms or None, v.get("note", ""))
    return out


def english_catalog() -> dict[str, str | dict[str, str]]:
    return {k: s.text if s.text is not None else dict(s.forms or {}) for k, s in english().items()}


def load_translations(corpus: Path, lang: str) -> dict[str, str | dict[str, str]]:
    path = Path(corpus) / "i18n" / lang / UI_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def fill(text: str, vars: dict[str, object]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(vars.get(m[1], m[0])), text)


class Translator:
    """Messages in one language, English where a translation is missing."""

    def __init__(self, lang: str, translations: dict[str, str | dict[str, str]]):
        self.lang, self.translations = lang, translations

    def __call__(self, key: str, /, **vars: object) -> str:
        entry = self.translations.get(key)
        lang = self.lang
        if entry is None:
            src = english().get(key)
            if src is None:
                return key
            entry, lang = (src.text if src.text is not None else src.forms), "en"
        if isinstance(entry, dict):
            n = vars.get("count", 0)
            cat = plural_category(lang, float(n) if isinstance(n, int | float) else 0)
            entry = entry.get(cat) or entry.get("other") or next(iter(entry.values()))
        return fill(entry, vars)


class Messages:
    """Translators per language, re-read when a language's translations change."""

    def __init__(self, corpus: Path):
        self.corpus = Path(corpus)
        self._cache: dict[str, tuple[float, Translator]] = {}

    def __call__(self, lang: str) -> Translator:
        path = self.corpus / "i18n" / lang / UI_FILE
        stamp = path.stat().st_mtime if lang != "en" and path.exists() else 0.0
        cached = self._cache.get(lang)
        if cached is None or cached[0] != stamp:
            texts = load_translations(self.corpus, lang) if stamp else {}
            cached = self._cache[lang] = (stamp, Translator(lang, texts))
        return cached[1]


ENGLISH = Translator("en", {})
