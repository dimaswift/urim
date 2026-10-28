"""Localization: translations merged as fragments, keyed by language, locked when approved,
stale when their English changes; interface messages with placeholders and plural forms;
bundle labels; the localizer's packets; and a language's progress."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from urim.config import load_paths
from urim.i18n.messages import Translator, english, plural_categories, plural_category
from urim.i18n.progress import language_progress
from urim.ir.models import BookName, VerseText
from urim.workbench import gold
from urim.workbench.fragments import (
    BundleTexts,
    InterfaceMessage,
    LocalizationFragment,
    Provenance,
)
from urim.workbench.ledger import load_ledger, load_records, set_status
from urim.workbench.localize import (
    ScopeError,
    message_states,
    parse_scope,
    text_states,
    verse_states,
)
from urim.workbench.localize_packets import build_localization_packet
from urim.workbench.merge import CorpusFiles, merge_fragment
from urim.workbench.packets import TaskError

from .conftest import FIXTURE_IR

REPO = Path(__file__).resolve().parent.parent
BY = Provenance(model="claude-sonnet-5-5", skill="urim-localizer@1")
CH = "1KGS.18"


@pytest.fixture
def paths(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(REPO / "corpus", corpus, ignore=shutil.ignore_patterns("core", "ledger"))
    shutil.copy(FIXTURE_IR / "chronology.json", corpus / "chronology.json")
    for p in (corpus / "i18n").glob("*/*.json"):
        if not p.name.startswith("_"):
            p.unlink()
    (corpus / "i18n" / "ru" / "_ui.json").unlink(missing_ok=True)
    p = replace(
        load_paths(),
        corpus=corpus,
        inputs=FIXTURE_IR,
        work=tmp_path / "work",
        bundles=tmp_path / "b",
    )
    for chapter in ("1KGS.17", CH):
        for agent in ("chronology", "ontology"):
            assert merge_fragment(getattr(gold, agent)(chapter), corpus, FIXTURE_IR).ok
    verses = [
        VerseText(
            verse_id=f"{CH}.{n}",
            translation_literal=f"literal {n}",
            translation_dramatic=f"dramatic {n}",
            directors_commentary=f"commentary {n}",
        )
        for n in (1, 2, 3)
    ]
    frag = gold.philology(CH).model_copy(update={"verses": verses})
    assert merge_fragment(frag, corpus, FIXTURE_IR).ok
    return p


def texts_fragment(paths, prefix="ру ", **kw) -> LocalizationFragment:
    en = CorpusFiles(paths.corpus).i18n("en", CH)

    def ru(item):
        return item.model_copy(
            update={
                k: prefix + v
                for k, v in item.model_dump().items()
                if k.endswith(("title", "summary", "name"))
            }
        )

    return LocalizationFragment(
        agent="localization",
        lang="ru",
        scope=CH,
        produced_by=BY,
        events=[ru(e) for e in en.events],
        causal_edges=en.causal_edges,
        entities=[ru(e) for e in en.entities],
        components=en.components,
        systems=en.systems,
        system_instances=en.system_instances,
        edges=en.edges,
        **kw,
    )


def test_scopes_name_texts_verses_interface_and_bundle():
    assert parse_scope("GEN.38").kind == "texts"
    assert (parse_scope("GEN.38.1-12").lo, parse_scope("GEN.38.1-12").hi) == (1, 12)
    assert parse_scope("ui.campaign").namespace == "campaign"
    assert parse_scope("bundle").kind == "bundle"
    with pytest.raises(ScopeError):
        parse_scope("GEN")


def test_a_chapters_texts_merge_as_drafts_that_remember_their_english(paths):
    r = merge_fragment(texts_fragment(paths), paths.corpus, paths.inputs)
    assert r.ok, r.errors
    ru = CorpusFiles(paths.corpus).i18n("ru", CH)
    assert ru.events and ru.events[0].title.startswith("ру ")
    led = load_ledger(paths.corpus, CH)
    event_key = f"event.ru:{ru.events[0].event_id}"
    assert led.items[event_key].status == "draft" and led.items[event_key].source
    assert led.items[event_key].produced_by.skill == "urim-localizer@1"
    states = text_states(CorpusFiles(paths.corpus), led, "ru", CH)
    assert {s.status for s in states} == {"draft"}

    # Approved, it is locked while its English stays the same.
    set_status(paths.corpus, [event_key], "approved")
    r = merge_fragment(texts_fragment(paths, prefix="иначе "), paths.corpus, paths.inputs)
    assert any("approved and locked" in e for e in r.errors)

    # The English changes: the translation is stale, and no longer locked.
    en_frag = gold.chronology(CH)
    changed = en_frag.event_texts[0].model_copy(update={"title": "A new English title"})
    en_frag = en_frag.model_copy(update={"event_texts": [changed, *en_frag.event_texts[1:]]})
    assert merge_fragment(en_frag, paths.corpus, paths.inputs).ok
    led = load_ledger(paths.corpus, CH)
    states = {s.key: s for s in text_states(CorpusFiles(paths.corpus), led, "ru", CH)}
    assert states[f"event.ru:{changed.event_id}"].status == "stale"
    r = merge_fragment(texts_fragment(paths, prefix="иначе "), paths.corpus, paths.inputs)
    assert r.ok, r.errors
    assert load_ledger(paths.corpus, CH).items[f"event.ru:{changed.event_id}"].status == "draft"


def test_texts_must_translate_english_that_exists(paths):
    frag = texts_fragment(paths)
    stray = frag.events[0].model_copy(update={"event_id": "evt.1kgs_18.not_there"})
    r = merge_fragment(frag.model_copy(update={"events": [stray]}), paths.corpus, paths.inputs)
    assert any("no English event text" in e for e in r.errors)
    r = merge_fragment(frag.model_copy(update={"lang": "en"}), paths.corpus, paths.inputs)
    assert any("English is the source" in e for e in r.errors)
    mixed = frag.model_copy(update={"verses": [_verse(1, 0)]})
    assert any(
        "also carries verses" in e for e in merge_fragment(mixed, paths.corpus, paths.inputs).errors
    )


def _verse(n: int, glosses: int) -> VerseText:
    from urim.ir.models import TokenGloss

    return VerseText(
        verse_id=f"{CH}.{n}",
        translation_literal="и было",
        translation_dramatic="И было так",
        directors_commentary="комментарий",
        token_glosses=[TokenGloss(pos=i + 1, gloss="слово") for i in range(glosses)],
    )


def test_verses_follow_their_english_layers(paths):
    src = json.loads((FIXTURE_IR / "source" / "1KGS.json").read_text())
    n1 = next(len(v["tokens"]) for v in src["verses"] if v["verse_id"] == f"{CH}.1")
    frag = LocalizationFragment(
        agent="localization",
        lang="ru",
        scope=f"{CH}.1-3",
        produced_by=BY,
        verses=[_verse(1, n1), _verse(2, 1)],
    )
    r = merge_fragment(frag, paths.corpus, paths.inputs)
    assert r.ok, r.errors
    assert any(f"{CH}.2: 1 glosses" in w for w in r.warnings)
    led = load_ledger(paths.corpus, CH)
    assert led.items[f"verse.ru:{CH}.1"].status == "draft"
    states = {s.item_id: s.status for s in verse_states(CorpusFiles(paths.corpus), led, "ru", CH)}
    assert states == {f"{CH}.1": "draft", f"{CH}.2": "draft", f"{CH}.3": "missing"}

    outside = frag.model_copy(update={"verses": [_verse(5, 0)]})
    r = merge_fragment(outside, paths.corpus, paths.inputs)
    assert any("outside" in e for e in r.errors)
    early = frag.model_copy(update={"scope": f"{CH}.4-9", "verses": [_verse(4, 0)]})
    assert any(
        "no English layers" in e for e in merge_fragment(early, paths.corpus, paths.inputs).errors
    )


def _plural_key() -> str:
    return next(k for k, s in english().items() if s.forms)


def test_interface_messages_keep_placeholders_and_plural_forms(paths):
    plural = _plural_key()
    simple = next(k for k, s in english().items() if s.text and not s.placeholders)
    forms = {cat: f"{{count}} штук ({cat})" for cat in plural_categories("ru")}

    def frag(*messages):
        return LocalizationFragment(
            agent="localization", lang="ru", scope="ui", produced_by=BY, messages=list(messages)
        )

    r = merge_fragment(
        frag(
            InterfaceMessage(key=simple, text="Готово"), InterfaceMessage(key=plural, forms=forms)
        ),
        paths.corpus,
        paths.inputs,
    )
    assert r.ok, r.errors and not r.relink
    ui = json.loads((paths.corpus / "i18n" / "ru" / "_ui.json").read_text())
    assert ui[simple] == "Готово" and ui[plural]["few"].endswith("(few)")
    records = load_records(paths.corpus, "ru")
    assert records.items[f"ui:{simple}"].source == english()[simple].hash
    states = {s.item_id: s.status for s in message_states(paths.corpus, "ru")}
    assert states[simple] == "approved" and list(states.values()).count("missing") > 10

    bad = [
        InterfaceMessage(key=plural, forms={"one": "x", "other": "y"}),  # Russian has four
        InterfaceMessage(key=plural, text="без форм"),
        InterfaceMessage(key="no.such.key", text="?"),
    ]
    for m in bad:
        assert not merge_fragment(frag(m), paths.corpus, paths.inputs).ok
    placeholder = next(k for k, s in english().items() if s.text and s.placeholders - {"count"})
    lost = merge_fragment(
        frag(InterfaceMessage(key=placeholder, text="без меток")), paths.corpus, paths.inputs
    )
    assert any("keep {" in e for e in lost.errors)

    t = Translator("ru", ui)
    assert (
        t(simple) == "Готово"
        and t(plural, count=3).endswith("(few)")
        and t(plural, count=5).endswith("(many)")
    )
    assert [plural_category("ru", n) for n in (1, 2, 5, 11, 21, 22)] == [
        "one",
        "few",
        "many",
        "many",
        "one",
        "few",
    ]


def test_bundle_labels_merge_by_code(paths):
    frag = LocalizationFragment(
        agent="localization",
        lang="ru",
        scope="bundle",
        produced_by=BY,
        bundle=BundleTexts(
            books=[BookName(book_code="GEN", name="Книга Бытия", abbreviation="Быт")]
        ),
    )
    r = merge_fragment(frag, paths.corpus, paths.inputs)
    assert r.ok, r.errors
    bundle = json.loads((paths.corpus / "i18n" / "ru" / "_bundle.json").read_text())
    assert next(b for b in bundle["books"] if b["book_code"] == "GEN")["name"] == "Книга Бытия"
    assert "book:GEN" in load_records(paths.corpus, "ru").items
    stray = frag.model_copy(
        update={
            "bundle": BundleTexts(
                books=[BookName(book_code="EXO", name="Исход", abbreviation="Исх")]
            )
        }
    )
    assert any(
        "no such entry" in e for e in merge_fragment(stray, paths.corpus, paths.inputs).errors
    )


def test_packets_give_the_localizer_what_it_needs(paths):
    texts = build_localization_packet("ru", CH, paths)
    assert "## `events`" in texts.text and "[new]" in texts.text
    assert texts.fragment_path.name == f"ru.{CH}.fragment.json"
    verses = build_localization_packet("ru", f"{CH}.1-2", paths)
    assert "Hebrew:" in verses.text and "English literal: literal 1" in verses.text
    ns = english()[_plural_key()].namespace
    ui = build_localization_packet("ru", f"ui.{ns}", paths)
    assert "one, few, many, other" in ui.text and "to translate" in ui.text
    assert "## `books`" not in build_localization_packet("ru", "bundle", paths).text
    with pytest.raises(TaskError):
        build_localization_packet("xx", CH, paths)
    with pytest.raises(TaskError):
        build_localization_packet("en", CH, paths)


def test_progress_counts_a_languages_work(paths):
    assert merge_fragment(texts_fragment(paths), paths.corpus, paths.inputs).ok
    progress = language_progress(paths.corpus, "ru")
    row = next(c for c in progress["chapters"] if c["chapter"] == CH)
    assert row["texts"]["drafts"] == row["texts"]["total"] > 0
    assert row["verses"] == {
        "total": 3,
        "missing": 3,
        "stale": 0,
        "requested": 0,
        "drafts": 0,
        "approved": 0,
        "translated": 0,
    }
    assert progress["interface"]["total"] == len(english())
    assert progress["bundle"]["total"] > 0 and progress["lang_name"] == "Русский"


def test_the_review_app_serves_translations_and_progress(paths):
    from fastapi.testclient import TestClient

    from urim.review.server import create_review_app

    key = next(k for k, s in english().items() if s.text and not s.placeholders)
    frag = LocalizationFragment(
        agent="localization",
        lang="ru",
        scope="ui",
        produced_by=BY,
        messages=[InterfaceMessage(key=key, text="Готово")],
    )
    assert merge_fragment(frag, paths.corpus, paths.inputs).ok
    client = TestClient(create_review_app(paths))
    assert client.get("/api/messages", params={"lang": "ru"}).json()["messages"] == {key: "Готово"}
    assert client.get("/api/messages").json()["messages"] == {}
    [ru] = client.get("/api/i18n/progress").json()
    assert ru["lang"] == "ru" and ru["interface"]["translated"] == 1
