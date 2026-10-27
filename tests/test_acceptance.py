"""PoC acceptance criteria (SPEC.md section 10), run against the hand-authored golden IR.

Phase 2 reruns these same assertions against agent-generated IR.
"""

import hashlib
import sqlite3
import unicodedata

import pytest

from urim.compiler.link import link_core, link_lang
from urim.runtime.engine import UrimEngine
from urim.utime import DAY

from .conftest import FIXTURE_IR


def strip_marks(text: str) -> str:
    """Drop niqqud and cantillation (Unicode Mn) so Hebrew compares on consonants."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 1. Multi-layer fidelity and translation audit ------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "translation", "baseline_start"),
    [("en", "KJV", "And it came to pass at noon"), ("ru", "RusSynodal", "В полдень Илия")],
)
def test_1_verse_matrix_has_all_layers(engine, lang, translation, baseline_start):
    m = engine.get_verse_matrix("1KGS.18.27", lang=lang)
    assert "שיג" in strip_marks(m.source_text)
    assert m.baseline_translation == translation
    assert m.traditional_baseline.startswith(baseline_start)
    assert m.translation_literal and m.translation_dramatic
    assert m.layers_lang == lang
    assert "שיג" in strip_marks(m.directors_commentary)
    assert m.tokens[15].strongs == "H7873" and m.tokens[15].gloss


# 2. UTES diurnal and multi-day deltas ---------------------------------------------------------


def test_2a_minchah_fire_to_jezreel_arrival(engine):
    fire = engine.get_event("evt.1kgs_18.minchah_fire")
    run = engine.get_event("evt.1kgs_18.chariot_run_to_jezreel")
    elapsed = run.utes_end - fire.utes_start
    assert 14_400 <= elapsed <= 18_000
    assert elapsed == 16_200
    assert fire.start_label.endswith("15:00")
    assert run.end_label.endswith("19:30")


def test_2b_forty_days_counted_from_the_broom_tree(engine):
    journey = engine.get_event("evt.1kgs_19.journey_to_horeb")
    assert journey.utes_end - journey.utes_start == 40 * DAY == 3_456_000
    # From leaving Beersheba (19:4) the total is longer: a day's walk and a day under the
    # broom tree come first. v1.0 of the spec asserted 40 days here, which the text contradicts.
    leaves_beersheba = engine.get_event("evt.1kgs_19.wilderness_day_journey")
    assert 41 * DAY <= journey.utes_end - leaves_beersheba.utes_start <= 43 * DAY


# 3. Stateful component transition -------------------------------------------------------------


def test_3_elisha_landowner_becomes_attendant(engine):
    at_call = {
        c.component_key: c
        for c in engine.get_entity_dossier("person.elisha", at_verse="1KGS.19.19").components
    }
    assert at_call["economic_tier"].label_value == "Wealthy landowner (12 yoke of oxen)"
    assert "role" not in at_call

    at_feast = {
        c.component_key: c
        for c in engine.get_entity_dossier("person.elisha", at_verse="1KGS.19.21").components
    }
    assert "economic_tier" not in at_feast
    role = at_feast["role"]
    assert role.label_value == "Attendant of Elijah"
    assert role.target.entity_id == "person.elijah"
    assert role.supersedes_component_id == at_call["economic_tier"].component_id

    # The same transition by time instead of by verse.
    before = engine.get_entity_dossier("person.elisha", at_utes=role.utes_start - 1)
    after = engine.get_entity_dossier("person.elisha", at_utes=role.utes_start)
    assert [c.component_key for c in before.components] == ["economic_tier"]
    assert [c.component_key for c in after.components] == ["role"]


# 4. Zero-recompile language hot-swap ----------------------------------------------------------


def test_4_language_bundles_never_touch_the_core(tmp_path):
    link_core(FIXTURE_IR, tmp_path)
    core = tmp_path / "urim-core.sqlite"
    before = sha256(core)
    link_lang(FIXTURE_IR, "en", tmp_path)
    link_lang(FIXTURE_IR, "ru", tmp_path)
    engine = UrimEngine(tmp_path)
    engine.get_verse_matrix("1KGS.18.27", lang="ru")
    engine.get_entity_dossier("person.elijah", lang="ru")
    engine.close()
    assert sha256(core) == before


def test_4_russian_bundle_is_fully_localized(engine, bundles):
    elisha = engine.get_entity_dossier("person.elisha", lang="ru")
    assert (elisha.canonical_name, elisha.phonetic_name, elisha.text_lang) == (
        "Елисей",
        "Элиша",
        "ru",
    )
    assert engine.get_system_codex("sys.mantle_investiture", lang="ru").name == "Облечение плащом"
    assert engine.get_event("evt.1kgs_18.minchah_fire", lang="ru").text_lang == "ru"

    core = sqlite3.connect(bundles / "urim-core.sqlite")
    ru = sqlite3.connect(bundles / "lang-ru" / "i18n_ru.sqlite")
    for core_table, ru_table, key in [
        ("core_entities", "i18n_entities", "entity_id"),
        ("core_events", "i18n_events", "event_id"),
        ("core_causal_edges", "i18n_causal_edges", "causal_id"),
        ("core_components", "i18n_components", "component_id"),
        ("core_systems", "i18n_systems", "system_id"),
        ("core_system_instances", "i18n_system_instances", "instance_id"),
        ("core_edges", "i18n_edges", "edge_id"),
        ("core_verses", "i18n_verses", "verse_id"),  # Synodal baseline for every verse
    ]:
        core_ids = {r[0] for r in core.execute(f"SELECT {key} FROM {core_table}")}
        ru_ids = {r[0] for r in ru.execute(f"SELECT {key} FROM {ru_table}")}
        assert core_ids == ru_ids, core_table
