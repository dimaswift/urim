"""The linker as critic: what it derives, and what it refuses to write."""

import hashlib
import json
import sqlite3

import pytest

from urim.compiler.link import LinkError, link_core, link_lang, validate
from urim.ir.load import IRLoadError
from urim.runtime.engine import UrimEngine

from .conftest import FIXTURE_IR, edit_json


def _core_rows(bundles, sql):
    return sqlite3.connect(bundles / "urim-core.sqlite").execute(sql).fetchall()


def test_fixture_links_without_errors_or_warnings():
    report = validate(FIXTURE_IR)
    assert report.errors == [] and report.warnings == []


def test_core_build_is_reproducible(tmp_path):
    link_core(FIXTURE_IR, tmp_path / "a")
    link_core(FIXTURE_IR, tmp_path / "b")
    digest = [
        hashlib.sha256((tmp_path / d / "urim-core.sqlite").read_bytes()).hexdigest()
        for d in ("a", "b")
    ]
    assert digest[0] == digest[1]


def test_derived_columns(bundles):
    assert _core_rows(
        bundles,
        "SELECT primary_event_id, location_entity_id FROM core_verses "
        "WHERE verse_id = '1KGS.18.27'",
    ) == [("evt.1kgs_18.elijah_mocks_baal", "loc.mount_carmel")]
    # Inherits Carmel through the parent contest event.
    assert _core_rows(
        bundles, "SELECT location_entity_id FROM core_verses WHERE verse_id = '1KGS.18.30'"
    ) == [("loc.mount_carmel",)]
    assert _core_rows(
        bundles,
        "SELECT first_occurrence_verse FROM core_systems "
        "WHERE system_id = 'sys.mantle_investiture'",
    ) == [("1KGS.19.19",)]
    (elapsed,) = _core_rows(
        bundles,
        "SELECT elapsed_seconds FROM core_causal_edges WHERE "
        "causal_id = 'caus.1kgs_18.execution_at_kishon.jezebel_threat'",
    )
    assert elapsed == (4 * 3600,)  # executions end 16:30, threat at 20:30


def test_switching_chronology_shifts_everything_without_breaking_language_bundles(
    ir_copy, tmp_path
):
    def add_scheme(doc):
        later = [
            dict(a, date=dict(a["date"], year=a["date"]["year"] - 10))
            for a in doc["schemes"]["THIELE"]
        ]
        doc["schemes"]["LATER_TEST"] = later

    edit_json(ir_copy / "chronology.json", add_scheme)
    link_core(ir_copy, tmp_path / "thiele")
    link_core(ir_copy, tmp_path / "later", scheme="LATER_TEST")
    link_lang(ir_copy, "en", tmp_path / "thiele")

    sql = "SELECT event_id, utes_start, relative_offset_seconds FROM core_events ORDER BY 1"
    a, b = _core_rows(tmp_path / "thiele", sql), _core_rows(tmp_path / "later", sql)
    shifts = {sb - sa for (_, sa, _), (_, sb, _) in zip(a, b, strict=True)}
    assert len(shifts) == 1 and shifts.pop() > 9 * 365 * 86400
    assert [r[2] for r in a] == [r[2] for r in b]

    # Same id surface, so the en bundle built against THIELE still mounts on LATER_TEST.
    (tmp_path / "later" / "lang-en").symlink_to(tmp_path / "thiele" / "lang-en")
    assert UrimEngine(tmp_path / "later").get_event("evt.1kgs_18.minchah_fire").title


def _link_errors(ir_dir) -> list[str]:
    with pytest.raises(LinkError) as exc:
        link_core(ir_dir, ir_dir.parent / "out")
    return exc.value.report.errors


def test_rejects_anchor_cycle(ir_copy):
    def cycle(doc):
        doc["events"][0]["time"]["anchor"] = "evt.1kgs_18.minchah_fire"

    edit_json(ir_copy / "core" / "1KGS.18.json", cycle)
    assert any("anchor cycle" in e for e in _link_errors(ir_copy))


def test_rejects_effect_before_cause(ir_copy):
    def backwards(doc):
        doc["causal_edges"].append(
            {
                "causal_id": "caus.test.backwards",
                "cause_event_id": "evt.1kgs_18.chariot_run_to_jezreel",
                "effect_event_id": "evt.1kgs_18.minchah_fire",
                "causal_type": "TRIGGERS",
            }
        )

    edit_json(ir_copy / "core" / "1KGS.18.json", backwards)
    assert any("effect starts before its cause" in e for e in _link_errors(ir_copy))


def test_rejects_overlapping_component_states(ir_copy):
    def overlap(doc):
        doc["components"].append(
            {
                "component_id": "comp.person.elisha.economic_tier.2",
                "entity_id": "person.elisha",
                "category": "TRAIT",
                "component_key": "economic_tier",
                "value_code": "POOR",
                "acquired_at_verse": "1KGS.19.20",
                "acquired_in_event": "evt.1kgs_19.mantle_investiture",
            }
        )

    edit_json(ir_copy / "core" / "1KGS.19.json", overlap)
    assert any("overlaps" in e for e in _link_errors(ir_copy))


def test_rejects_unknown_references_and_duplicates(ir_copy):
    def break_refs(doc):
        doc["edges"][0]["target_entity_id"] = "person.nobody"
        doc["entities"].append(dict(doc["entities"][0]))

    edit_json(ir_copy / "core" / "1KGS.19.json", break_refs)
    errors = _link_errors(ir_copy)
    assert any("unknown entity person.nobody" in e for e in errors)
    assert any("duplicate entity id loc.beersheba" in e for e in errors)


def test_rejects_malformed_time_of_day(ir_copy):
    def bad(doc):
        doc["events"][0]["time"]["time_of_day"] = "LUNCHTIME"

    edit_json(ir_copy / "core" / "1KGS.18.json", bad)
    with pytest.raises(IRLoadError, match="LUNCHTIME"):
        validate(ir_copy)


def test_language_bundle_rejects_orphans_and_bad_glosses(ir_copy, tmp_path):
    link_core(ir_copy, tmp_path)

    def orphan(doc):
        doc["events"].append(dict(doc["events"][0], event_id="evt.1kgs_18.not_in_core"))
        doc["verses"][0]["token_glosses"].append({"pos": 99, "gloss": "?"})

    edit_json(ir_copy / "i18n" / "en" / "1KGS.18.json", orphan)
    with pytest.raises(LinkError) as exc:
        link_lang(ir_copy, "en", tmp_path)
    errors = exc.value.report.errors
    assert any("unknown core id evt.1kgs_18.not_in_core" in e for e in errors)
    assert any("gloss for token 99" in e for e in errors)


def test_registry_supplies_coordinates_and_ir_overrides_them(bundles, ir_copy, tmp_path):
    rows = dict(
        (r[0], r[1:])
        for r in _core_rows(
            bundles,
            "SELECT entity_id, geo_lat, geo_source, geo_confidence, tipnr_id FROM core_entities",
        )
    )
    assert rows["loc.mount_carmel"] == (
        32.6725,
        "openbible:Mount Carmel",
        1.0,
        "Carmel_Mount@1Ki.18.19-2Ki",
    )
    assert rows["loc.mount_horeb"][1] == "openbible:Mount Sinai"
    assert rows["artifact.ahabs_chariot"][:3] == (None, None, None)

    def pin_carmel(doc):
        carmel = next(e for e in doc["entities"] if e["entity_id"] == "loc.mount_carmel")
        carmel.update(geo_lat=32.668, geo_lon=35.087)

    edit_json(ir_copy / "core" / "1KGS.18.json", pin_carmel)
    link_core(ir_copy, tmp_path)
    assert _core_rows(
        tmp_path,
        "SELECT geo_lat, geo_source FROM core_entities WHERE entity_id = 'loc.mount_carmel'",
    ) == [(32.668, "ir")]


def test_tipnr_identity_checks(ir_copy):
    def tamper(doc):
        doc["entities"][0]["tipnr_id"] = "Ahab@1Ki.16.28-Mic"  # Jezebel claims Ahab's identity
        doc["entities"][1]["tipnr_id"] = "Nobody@Gen.1.1"  # Baal points nowhere

    edit_json(ir_copy / "core" / "1KGS.18.json", tamper)
    report = validate(ir_copy)
    assert any("already used by person.ahab" in e for e in report.errors)
    assert any("Nobody@Gen.1.1 is not in the registry" in w for w in report.warnings)


def test_first_mention_is_checked_against_the_registry(ir_copy):
    def late(doc):
        elisha = next(e for e in doc["entities"] if e["entity_id"] == "person.elisha")
        elisha["first_mention_verse"] = "1KGS.19.19"

    edit_json(ir_copy / "core" / "1KGS.19.json", late)
    warnings = validate(ir_copy).warnings
    assert any("person.elisha: mentioned at 1KGS.19.16" in w for w in warnings)


def test_an_earlier_book_moves_the_first_mention_without_a_warning(ir_copy, tmp_path):
    # Books are written in any order: Genesis, ingested after 1 Kings, names the LORD first.
    verse = {
        "verse_id": "GEN.38.7",
        "source_text": "יְהוָה",
        "tokens": [{"pos": 1, "surface": "יְהוָה"}],
    }
    (ir_copy / "source" / "GEN.json").write_text(
        json.dumps(
            {"book_code": "GEN", "source_language": "HEBREW", "attribution": [], "verses": [verse]}
        )
    )

    def named_in_genesis(doc):
        lord = next(e for e in doc["entities"] if e["tipnr_id"] == "LORD@Gen.1.1-Rev")
        lord["mentions"].insert(0, {"verse_id": "GEN.38.7", "pos": 1})

    edit_json(ir_copy / "registry" / "entities.json", named_in_genesis)
    report = validate(ir_copy)
    assert report.errors == [] and not any("deity.yhwh" in w for w in report.warnings)
    link_core(ir_copy, tmp_path)
    assert _core_rows(
        tmp_path, "SELECT first_mention_verse FROM core_entities WHERE entity_id = 'deity.yhwh'"
    ) == [("GEN.38.7",)]
