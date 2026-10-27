import pytest

from urim.compiler.link import link_core, link_lang
from urim.runtime.engine import BundleMismatch, LanguageNotAvailable, NotFoundError, UrimEngine

from .conftest import edit_json


@pytest.mark.parametrize(
    ("ref", "verse_id"),
    [
        ("1KGS.18.27", "1KGS.18.27"),
        ("1Kgs 18:27", "1KGS.18.27"),
        ("1kgs.18.27", "1KGS.18.27"),
        ("KJV:1Kgs.18.33", "1KGS.18.33"),
        ("KJV:1KGS.18.34", "1KGS.18.34"),
        ("KJV:1KGS.19.8", "1KGS.19.8"),  # no map row: identity
    ],
)
def test_resolve_ref(engine, ref, verse_id):
    assert engine.resolve_ref(ref) == verse_id


@pytest.mark.parametrize("ref", ["1KGS.25.1", "XYZ.1.1", "nonsense"])
def test_resolve_ref_unknown(engine, ref):
    with pytest.raises(NotFoundError):
        engine.resolve_ref(ref)


def test_versification_aliases_and_baseline_assembly(engine):
    m = engine.get_verse_matrix("1KGS.18.34", include_ecs=False)
    assert m.aliases == ["KJV:1KGS.18.33", "KJV:1KGS.18.34"]
    # KJV puts "Fill four barrels" in 18:33; the Hebrew (and Synodal) put it in 18:34.
    assert "Fill four barrels" in m.traditional_baseline
    ru = engine.get_verse_matrix("1KGS.18.34", lang="ru", include_ecs=False)
    assert ru.traditional_baseline.startswith("и сказал: наполните четыре ведра")


def test_missing_layers_fall_back_to_english(engine):
    m = engine.get_verse_matrix("1KGS.18.46", lang="ru")
    assert (m.baseline_lang, m.layers_lang) == ("ru", "en")
    assert m.traditional_baseline.startswith("И была на Илии рука Господня")
    assert m.translation_dramatic.startswith("Then the hand of the LORD")


def test_verse_ecs(engine):
    ecs = engine.get_verse_matrix("1KGS.19.19").ecs
    assert {e.entity_id for e in ecs.entities} >= {
        "person.elijah",
        "person.elisha",
        "artifact.elijahs_mantle",
        "loc.abel_meholah",
    }
    assert [i.system_id for i in ecs.system_instances] == ["sys.mantle_investiture"]
    assert [e.interaction_type for e in ecs.edges] == ["INVESTED"]
    held = {c.component_key: c for c in ecs.components}
    assert held["held_artifact"].target.entity_id == "artifact.elijahs_mantle"
    assert held["economic_tier"].entity_id == "person.elisha"


def test_chapter_stream(engine):
    s = engine.get_chapter_stream("1kgs", 19, lang="ru")
    assert s.book_name.startswith("3-я книга Царств")
    assert len(s.verses) == 21 and [v.verse for v in s.verses] == list(range(1, 22))
    assert s.events[0].event_id == "evt.1kgs_19.jezebel_threat"
    assert "caus.1kgs_18.execution_at_kishon.jezebel_threat" in {
        c.causal_id for c in s.causal_links
    }


def test_timeline_window_and_entity_filter(engine):
    day = engine.get_event("evt.1kgs_18.carmel_contest")
    t = engine.query_timeline(day.utes_start, day.utes_end)
    starts = [e.event.utes_start for e in t.entries]
    assert starts == sorted(starts)
    assert t.entries[0].delta_from_previous_seconds is None
    mocks = next(e for e in t.entries if e.event.event_id == "evt.1kgs_18.elijah_mocks_baal")
    assert mocks.event.time_of_day.code == "TZOHORAYIM"

    everything = engine.query_timeline(-(10**12), 0, entity_filter=["person.elisha"])
    assert [e.event.event_id for e in everything.entries] == [
        "evt.1kgs_19.theophany_at_horeb",
        "evt.1kgs_19.mantle_investiture",
        "evt.1kgs_19.farewell_feast",
    ]


def test_causal_chain(engine):
    down = engine.trace_causal_chain("evt.1kgs_17.drought_oath", direction="downstream")
    assert {n.event_id for n in down.nodes} == {
        "evt.1kgs_17.drought_oath",
        "evt.1kgs_18.rain_returns",
        "evt.1kgs_18.chariot_run_to_jezreel",
    }
    prophecy = next(x for x in down.links if x.causal_type.code == "FULFILLS_PROPHECY")
    assert 2 * 365 * 86400 < prophecy.elapsed_seconds < 3 * 365 * 86400

    up = engine.trace_causal_chain("evt.1kgs_19.flight_to_beersheba", direction="upstream", depth=1)
    assert {n.event_id for n in up.nodes} == {
        "evt.1kgs_19.flight_to_beersheba",
        "evt.1kgs_19.jezebel_threat",
    }


def test_search(engine):
    hits = engine.semantic_search("privy", scope="verses")
    assert hits[0].id == "1KGS.18.27"
    ru = engine.semantic_search("Елисей", lang="ru", scope="entities")
    assert ru[0].id == "person.elisha"
    assert engine.semantic_search("   ") == []


def test_dossier_history_and_errors(engine):
    elijah = engine.get_entity_dossier("person.elijah")
    assert [c.component_key for c in elijah.components] == ["mental_state", "held_artifact"]
    assert elijah.events[0].event_id == "evt.1kgs_17.drought_oath"
    with pytest.raises(ValueError):
        engine.get_entity_dossier("person.elijah", at_utes=0, at_verse="1KGS.19.1")
    with pytest.raises(NotFoundError):
        engine.get_entity_dossier("person.nobody")
    with pytest.raises(LanguageNotAvailable):
        engine.get_verse_matrix("1KGS.18.27", lang="de")


def test_bundle_built_for_another_core_is_refused(ir_copy, tmp_path):
    link_core(ir_copy, tmp_path)
    link_lang(ir_copy, "en", tmp_path)

    def add_entity(doc):
        doc["entities"].append(
            {
                "entity_id": "loc.tishbe",
                "entity_type": "LOCATION",
                "first_mention_verse": "1KGS.17.1",
            }
        )

    edit_json(ir_copy / "core" / "1KGS.17.json", add_entity)
    link_core(ir_copy, tmp_path)  # new id surface; lang-en is now stale

    engine = UrimEngine(tmp_path)
    assert [lang.compatible for lang in engine.languages()] == [False]
    with pytest.raises(BundleMismatch):
        engine.get_verse_matrix("1KGS.18.27")


def test_word_glosses_cover_every_verse(engine):
    en = engine.get_verse_matrix("1KGS.18.46", include_ecs=False)
    assert all(t.gloss for t in en.tokens)  # STEPBible glosses where no Philologist ran yet
    assert en.tokens[4].gloss == "Elijah" and en.tokens[4].name_ref == "Elijah@1Ki.17.1-Jas"
    ru = engine.get_verse_matrix("1KGS.18.46", lang="ru", include_ecs=False)
    assert ru.tokens[4].gloss == "Elijah"  # falls back to English
    assert engine.get_verse_matrix("1KGS.18.27", lang="ru").tokens[4].gloss == "Элиягу"


def test_dossier_geo_provenance(engine):
    geo = engine.get_entity_dossier("loc.abel_meholah").geo
    assert geo.source == "openbible:Abel-meholah" and 0 < geo.confidence < 1
