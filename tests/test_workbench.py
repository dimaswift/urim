"""The session workbench: fragments, merge rules, locks, ledger, packets and status."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from urim.cli import app
from urim.compiler.link import link_core
from urim.config import Paths
from urim.workbench import gold
from urim.workbench.fragments import FragmentError, ReviewerNote, key_for_note, load_fragment
from urim.workbench.ledger import LedgerError, load_ledger, set_status
from urim.workbench.merge import merge_fragment
from urim.workbench.packets import TaskError, build_packet
from urim.workbench.status import corpus_status, next_steps

from .conftest import FIXTURE_IR

REPO = Path(__file__).resolve().parent.parent
CHAPTERS = ("1KGS.17", "1KGS.18", "1KGS.19")


@pytest.fixture
def corpus(tmp_path) -> Path:
    """An empty working corpus (anchors and bundle labels only), reading the fixture's inputs."""
    target = tmp_path / "corpus"
    shutil.copytree(REPO / "corpus", target, ignore=shutil.ignore_patterns("core", "ledger"))
    for lang in ("en", "ru"):
        for p in (target / "i18n" / lang).glob("*.json"):
            if p.name != "_bundle.json":
                p.unlink()
    return target


def merge(fragment, corpus):
    return merge_fragment(fragment, corpus, FIXTURE_IR)


def merge_all_gold(corpus):
    for f in (
        [gold.chronology(c) for c in CHAPTERS]
        + [gold.ontology(c) for c in CHAPTERS]
        + [gold.philology(c) for c in ("1KGS.18", "1KGS.19")]
    ):
        result = merge(f, corpus)
        assert result.ok, (f.agent, f.chapter_ref, result.errors)


def content_hash(bundles: Path) -> str:
    rows = sqlite3.connect(bundles / "urim-core.sqlite").execute("SELECT key, value FROM core_meta")
    return dict(rows)["content_hash"]


def test_session_fragments_rebuild_the_gold_core_exactly(corpus, tmp_path):
    merge_all_gold(corpus)
    link_core(corpus, tmp_path / "rebuilt", inputs_dir=FIXTURE_IR)
    link_core(FIXTURE_IR, tmp_path / "gold")
    assert content_hash(tmp_path / "rebuilt") == content_hash(tmp_path / "gold")

    again = merge(gold.chronology("1KGS.18"), corpus)
    assert again.ok and not (again.added or again.changed or again.removed)
    assert len(again.unchanged) == 12


def test_ledger_records_provenance(corpus):
    merge(gold.chronology("1KGS.17"), corpus)
    item = load_ledger(corpus, "1KGS.17").items["event:evt.1kgs_17.drought_oath"]
    assert item.status == "draft" and item.produced_by.skill == "hand-written@0"


def test_chronology_may_not_touch_entity_links(tmp_path):
    frag = gold.chronology("1KGS.18").model_dump(mode="json")
    frag["events"][0]["participants"] = [{"entity_id": "person.elijah", "role": "AGENT"}]
    path = tmp_path / "f.json"
    path.write_text(__import__("json").dumps(frag))
    with pytest.raises(FragmentError, match="belong to the Ontologist"):
        load_fragment(path)


def test_scope_and_order_are_enforced(corpus):
    frag = gold.chronology("1KGS.18")
    frag.chapter_ref = "1KGS.19"
    assert any("outside 1KGS.19" in e for e in merge(frag, corpus).errors)

    onto = merge(gold.ontology("1KGS.17"), corpus)
    assert any("run the chronology task first" in e for e in onto.errors)

    unknown = gold.chronology("1KGS.17")
    unknown.chapter_ref = "1KGS.20"
    unknown.events = []
    unknown.event_texts = []
    assert any("not ingested yet" in e for e in merge(unknown, corpus).errors)


def test_dangling_references_fail_the_link_and_write_nothing(corpus):
    merge(gold.chronology("1KGS.17"), corpus)
    before = (corpus / "core" / "1KGS.17.json").read_text()
    result = merge(gold.chronology("1KGS.19"), corpus)  # anchors on 1KGS.18 events
    assert not result.ok and any("unknown event" in e for e in result.errors)
    assert (corpus / "core" / "1KGS.17.json").read_text() == before
    assert not (corpus / "core" / "1KGS.19.json").exists()


def test_approved_items_are_locked_until_reopened(corpus):
    merge(gold.chronology("1KGS.17"), corpus)
    merge(gold.chronology("1KGS.18"), corpus)
    k = "event:evt.1kgs_18.elijah_mocks_baal"
    set_status(corpus, [k], "approved")

    changed = gold.chronology("1KGS.18")
    mocks = next(e for e in changed.events if e.event_id == "evt.1kgs_18.elijah_mocks_baal")
    mocks.time.duration.value = 2
    assert any(f"{k} is approved and locked" in e for e in merge(changed, corpus).errors)

    omitted = gold.chronology("1KGS.18")
    omitted.events = [e for e in omitted.events if e.event_id != "evt.1kgs_18.elijah_mocks_baal"]
    omitted.event_texts = [
        t for t in omitted.event_texts if t.event_id != "evt.1kgs_18.elijah_mocks_baal"
    ]
    result = merge(omitted, corpus)
    assert result.ok and k in result.kept_locked

    set_status(corpus, [k], "draft", "time it at 12:30 instead")
    result = merge(changed, corpus)
    assert result.ok and k in result.changed
    assert load_ledger(corpus, "1KGS.18").items[k].status == "draft"


def test_dropped_draft_items_leave_the_corpus_and_ledger(corpus):
    merge(gold.chronology("1KGS.17"), corpus)
    merge(gold.chronology("1KGS.18"), corpus)
    frag = gold.chronology("1KGS.18")
    frag.events = [e for e in frag.events if e.event_id != "evt.1kgs_18.carmel_assembly"]
    frag.event_texts = [t for t in frag.event_texts if t.event_id != "evt.1kgs_18.carmel_assembly"]
    result = merge(frag, corpus)
    assert result.ok and result.removed == ["event:evt.1kgs_18.carmel_assembly"]
    assert "event:evt.1kgs_18.carmel_assembly" not in load_ledger(corpus, "1KGS.18").items


def test_entities_live_in_their_first_chapter(corpus):
    for c in CHAPTERS:
        merge(gold.chronology(c), corpus)
    merge(gold.ontology("1KGS.17"), corpus)
    frag = gold.ontology("1KGS.18")
    elijah = gold.ontology("1KGS.17").entities[0]
    frag.entities.append(elijah)
    assert any("first mentioned at 1KGS.17.1" in e for e in merge(frag, corpus).errors)

    update = gold.ontology("1KGS.18")
    bio = (
        gold.ontology("1KGS.17")
        .entity_texts[0]
        .model_copy(
            update={
                "summary_bio": "Prophet from Tishbe; at Carmel he defeats the prophets of Baal."
            }
        )
    )
    update.entity_texts.append(bio)
    result = merge(update, corpus)
    assert result.ok and "entity:person.elijah" in result.changed
    assert "at Carmel" in (corpus / "i18n" / "en" / "1KGS.17.json").read_text()


def test_philology_merges_verse_windows(corpus):
    for c in ("1KGS.17", "1KGS.18"):
        merge(gold.chronology(c), corpus)
    full = gold.philology("1KGS.18")
    window = full.model_copy(update={"verses": full.verses[:1]})
    assert merge(window, corpus).ok
    rest = full.model_copy(update={"verses": full.verses[1:]})
    result = merge(rest, corpus)
    assert result.ok and len(result.added) == 2 and not result.removed


def test_reviewer_notes_reach_the_ledger(corpus):
    frag = gold.chronology("1KGS.17")
    frag.reviewer_notes = [
        ReviewerNote(item="evt.1kgs_17.drought_oath", note="Regnal year is a guess."),
        ReviewerNote(note="No other events in 17:1; the rest of the chapter is pending."),
    ]
    merge(frag, corpus)
    led = load_ledger(corpus, "1KGS.17")
    assert led.items["event:evt.1kgs_17.drought_oath"].agent_notes == ["Regnal year is a guess."]
    assert led.notes[0].note.startswith("No other events")


def test_note_keys():
    assert key_for_note("evt.1kgs_18.x", "chronology") == "event:evt.1kgs_18.x"
    assert key_for_note("evt.1kgs_18.x", "ontology") == "event_links:evt.1kgs_18.x"
    assert key_for_note("1KGS.18.27", "philology") == "verse.en:1KGS.18.27"
    assert key_for_note("person.elijah", "ontology") == "entity:person.elijah"
    assert key_for_note("whatever", "ontology") is None


def test_change_requests_need_a_note_and_show_up_in_packets(corpus, tmp_path):
    merge(gold.chronology("1KGS.17"), corpus)
    with pytest.raises(LedgerError, match="note is required"):
        set_status(corpus, ["event:evt.1kgs_17.drought_oath"], "changes_requested")
    set_status(
        corpus,
        ["event:evt.1kgs_17.drought_oath"],
        "changes_requested",
        "Anchor the oath later in the reign.",
    )
    packet = build_packet(
        "chronology", "1KGS.17", Paths(corpus=corpus, inputs=FIXTURE_IR, work=tmp_path / "work")
    )
    assert "Reviewer requests" in packet.text and "later in the reign" in packet.text


def test_packets_carry_the_context_each_agent_needs(corpus, tmp_path):
    paths = Paths(corpus=corpus, inputs=FIXTURE_IR, work=tmp_path / "work")
    merge(gold.chronology("1KGS.17"), corpus)
    merge(gold.chronology("1KGS.18"), corpus)

    chrono = build_packet("chronology", "1KGS.19", paths).text
    assert "anchor.ahab_accession" in chrono
    assert "evt.1kgs_18.chariot_run_to_jezreel" in chrono  # rolling state
    assert "Beersheba – " in chrono or " – Beersheba" in chrono  # distances

    onto = build_packet("ontology", "1KGS.19", paths).text
    assert "No events yet" in onto and "Elisha@1Ki.19.16-Luk" in onto

    philo = build_packet("philology", "1KGS.18.27", paths)
    assert "| 16 |" in philo.text and "H7873" in philo.text  # sig, word 16 of 18:27
    assert "Elijah mocks Baal at noon" in philo.text
    assert philo.fragment_path.name == "1KGS.18.27-27.fragment.json"

    with pytest.raises(TaskError, match="whole chapters"):
        build_packet("chronology", "1KGS.18.1-5", paths)


def test_chronology_packets_carry_the_targum_and_time_commentary(corpus, tmp_path):
    inputs = tmp_path / "inputs"
    shutil.copytree(FIXTURE_IR, inputs)
    comments = {
        "Targum Jonathan": {"1KGS.17.7": ["וַהֲוָה מִסוֹף יוֹמִין וִיבַשׁ נַחְלָא"]},
        "Metzudat Zion": {"1KGS.17.15": ["ימים. אמרו רבותינו ז״ל: שנה:"]},
        "Radak": {"1KGS.17.12": ["שנים עצים. לאפות בו:"], "1KGS.17.1": ["חי ה׳. ענין שבועה:"]},
    }
    works = {w: {"version_title": w, "license": "test", "verses": v} for w, v in comments.items()}
    (inputs / "commentary").mkdir()
    (inputs / "commentary" / "1KGS.json").write_text(
        json.dumps({"book_code": "1KGS", "works": works}, ensure_ascii=False)
    )
    paths = Paths(corpus=corpus, inputs=inputs, work=tmp_path / "work")

    chrono = build_packet("chronology", "1KGS.17", paths).text
    assert "Targum Jonathan: וַהֲוָה מִסוֹף יוֹמִין" in chrono  # the Targum, on every verse
    assert "Metzudat Zion: ימים. אמרו רבותינו" in chrono  # "days": a time word
    assert "שנים עצים" not in chrono  # "two sticks", not years
    assert "ענין שבועה" not in chrono  # an oath, no time word
    assert "Targum Jonathan" not in build_packet("ontology", "1KGS.17", paths).text


def test_packets_name_entities_by_id(corpus, tmp_path):
    # Source word tags spell TIPNR names their own way; packets show the entity id instead.
    paths = Paths(corpus=corpus, inputs=FIXTURE_IR, work=tmp_path / "work")
    chrono = build_packet("chronology", "1KGS.17", paths).text
    assert "of Yahweh{deity.yhwh}" in chrono and "LORD@Gen.1.1-Heb" not in chrono
    philo = build_packet("philology", "1KGS.18.19", paths).text
    assert "| deity.baal |" in philo and "Baal@Num.22.41-Rom" not in philo


def test_ledger_says_whether_a_request_still_stands(corpus):
    merge(gold.chronology("1KGS.17"), corpus)
    k = "event:evt.1kgs_17.drought_oath"

    def note():
        return load_ledger(corpus, "1KGS.17").items[k].review_note()

    assert note() is None
    set_status(corpus, [k], "changes_requested", "date it later")
    assert note() == "[open request] date it later"

    revised = gold.chronology("1KGS.17")
    revised.events[0].time.duration.value = 2
    assert merge(revised, corpus).ok
    assert note().startswith("[requested ") and ", revised " in note()
    set_status(corpus, [k], "approved")
    assert note().endswith(", approved] date it later")


def test_status_suggests_one_chronology_chapter_at_a_time(corpus):
    paths = Paths(corpus=corpus, inputs=FIXTURE_IR)
    assert next_steps(corpus_status(paths)) == ["/urim-chronologist 1KGS.17"]
    merge(gold.chronology("1KGS.17"), corpus)
    steps = next_steps(corpus_status(paths), limit=10)
    assert "/urim-ontologist 1KGS.17" in steps and "/urim-chronologist 1KGS.18" in steps
    assert sum(s.startswith("/urim-chronologist") for s in steps) == 1
    assert "1KGS.17: review 1 draft item(s)" in steps


def test_cli_merge_status_and_approve(corpus, tmp_path):
    path = tmp_path / "frag.json"
    path.write_text(gold.chronology("1KGS.17").model_dump_json())
    runner = CliRunner()
    common = ["--ir", str(corpus), "--inputs", str(FIXTURE_IR)]
    result = runner.invoke(
        app, ["ir", "merge", str(path), *common, "--bundles", str(tmp_path / "bundles")]
    )
    assert result.exit_code == 0, result.output
    assert "1 added" in result.output and (tmp_path / "bundles" / "urim-core.sqlite").exists()
    result = runner.invoke(app, ["approve", "--chapter", "1KGS.17", "--ir", str(corpus)])
    assert result.exit_code == 0 and "1 item(s) now approved" in result.output
    result = runner.invoke(app, ["status", *common])
    assert "1KGS.17" in result.output and "/urim-chronologist 1KGS.18" in result.output


def test_chronology_merges_report_the_linked_timeline(corpus, tmp_path):
    merge(gold.chronology("1KGS.17"), corpus)
    result = merge(gold.chronology("1KGS.18"), corpus)
    rows = {t.event_id: t for t in result.timeline}
    assert rows["evt.1kgs_18.minchah_fire"].start.endswith("15:00")
    assert rows["evt.1kgs_18.elijah_mocks_baal"].anchor == (
        "evt.1kgs_18.carmel_contest start → TZOHORAYIM, 6.5 h later"
    )
    assert [t.event_id for t in result.timeline][0] == "evt.1kgs_18.carmel_contest"
    assert {c.causal_id for c in result.causes} >= {"caus.1kgs_17.drought_oath.rain_returns"}
    assert not merge(gold.ontology("1KGS.17"), corpus).timeline

    path = tmp_path / "frag.json"
    path.write_text(gold.chronology("1KGS.18").model_dump_json())
    runner = CliRunner()
    bundles = ["--bundles", str(tmp_path / "bundles")]
    args = ["ir", "merge", str(path), "--ir", str(corpus), "--inputs", str(FIXTURE_IR)]
    assert "timeline 1KGS.18" in runner.invoke(app, [*args, *bundles]).output
    result = runner.invoke(app, ["timeline", "1KGS.18", *bundles])
    assert result.exit_code == 0
    assert "from evt.1kgs_17.drought_oath start → SHACHAR, 2.5 y later" in result.output


def test_travel_times_come_from_coordinates(corpus):
    from urim.workbench.travel import TravelError, find_place, journey

    carmel = find_place("Carmel", corpus, FIXTURE_IR)  # a word of "Mount Carmel"
    jezreel = find_place("loc.jezreel", corpus, FIXTURE_IR)
    assert carmel.entity_id == "loc.carmel_mount"
    leg = journey([carmel, jezreel], "chariot")
    assert 25 < leg.straight_km < 35 and leg.ir_duration == {"value": 3.5, "unit": "hours"}

    beersheba = find_place("Beersheba", corpus, FIXTURE_IR)
    flight = journey([jezreel, beersheba], "hurry")
    assert flight.elapsed_hours > 72 and flight.ir_duration["unit"] == "days"
    with pytest.raises(TravelError, match="no place"):
        find_place("Atlantis", corpus, FIXTURE_IR)

    result = CliRunner().invoke(
        app, ["travel", "Carmel", "Jezreel", "--ir", str(corpus), "--inputs", str(FIXTURE_IR)]
    )
    assert result.exit_code == 0 and "chariot" in result.output and "walk" in result.output
