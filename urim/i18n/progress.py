"""How far each language has come: a chapter's texts and verses, the interface, the bundle.

Counted from the corpus and its ledgers, like the run's own planning, so it is always current:
an item is missing, stale (its English changed since), translated (a draft or sent back), or
approved. Interface messages and bundle labels have no review; translated is as far as they go.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from urim.i18n.messages import english
from urim.ir.load import read_model
from urim.ir.models import I18nBundleIR
from urim.workbench.ledger import load_ledger
from urim.workbench.localize import (
    ItemState,
    bundle_states,
    languages,
    message_states,
    text_states,
    verse_states,
)
from urim.workbench.merge import CorpusFiles


def counts(states: list[ItemState]) -> dict[str, int]:
    c = Counter(s.status for s in states)
    return {
        "total": len(states),
        "missing": c["missing"],
        "stale": c["stale"],
        "requested": c["changes_requested"],
        "drafts": c["draft"],
        "approved": c["approved"] + c["unrecorded"],
        "translated": len(states) - c["missing"] - c["stale"],
    }


def language_progress(corpus: Path, lang: str) -> dict[str, Any]:
    corpus = Path(corpus)
    files = CorpusFiles(corpus)
    bundle = read_model(corpus / "i18n" / lang / "_bundle.json", I18nBundleIR)
    chapters = []
    for ch in files.chapters():
        led = load_ledger(corpus, ch)
        chapters.append(
            {
                "chapter": ch,
                "texts": counts(text_states(files, led, lang, ch)),
                "verses": counts(verse_states(files, led, lang, ch)),
            }
        )
    messages = message_states(corpus, lang)
    namespace = {k: s.namespace for k, s in english().items()}
    by_ns: dict[str, list[ItemState]] = defaultdict(list)
    for s in messages:
        by_ns[namespace[s.item_id]].append(s)
    return {
        "lang": lang,
        "lang_name": bundle.lang_name,
        "baseline": bundle.baseline_translation,
        "chapters": chapters,
        "interface": counts(messages)
        | {"namespaces": {ns: counts(states) for ns, states in sorted(by_ns.items())}},
        "bundle": counts(bundle_states(corpus, lang)),
    }


def all_progress(corpus: Path) -> list[dict[str, Any]]:
    return [language_progress(corpus, lang) for lang in languages(corpus)]
