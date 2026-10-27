"""Ingest parsers on small real excerpts (tests/data), plus a full re-ingest when sources exist."""

import json
import shutil
import unicodedata
from pathlib import Path

import httpx
import pytest

from urim.compiler.ingest.build import (
    _is_proper_noun,
    _merge_source,
    ingest,
    parse_scope,
    propose_ids,
)
from urim.compiler.ingest.fetch import Fetcher, SourceChanged
from urim.compiler.ingest.geo import OpenBibleIndex
from urim.compiler.ingest.tahot import build_verses, kjv_verse_map, read_tahot
from urim.compiler.ingest.tipnr import TipnrIndex, TipnrRecord, read_tipnr
from urim.compiler.ingest.tvtms import read_tvtms
from urim.ir.models import SourceBookIR

from .conftest import FIXTURE_IR

DATA = Path(__file__).parent / "data"
REPO = Path(__file__).resolve().parent.parent
SOURCES = REPO / "data" / "sources"


def nfc(text: str) -> str:
    """Hebrew mark order differs between sources and editors; compare canonically."""
    return unicodedata.normalize("NFC", text)


def test_tahot_words_tokens_and_glosses():
    words = read_tahot([DATA / "tahot_sample.txt"], {"1KGS": None})
    elijah = next(w for w in words if w.heb_ref == "1KGS.18.27")
    assert (elijah.dstrong, elijah.name_ref) == ("H0452G", "Elijah@1Ki.17.1-Jas")
    assert nfc(elijah.lemma) == nfc("אֵלִיָּה")
    assert elijah.translit == "'eliYahu" and elijah.gloss_en == "Elijah"

    verse = next(v for v in build_verses(words) if v.verse_id == "1KGS.18.34")
    assert [t.pos for t in verse.tokens] == list(range(1, 17))
    assert nfc(verse.source_text).startswith(nfc("וַיֹּ֗אמֶר מִלְא֨וּ"))
    assert nfc("עַל־הָעֹלָ֖ה") in nfc(verse.source_text)  # maqqef joins without a space
    assert verse.source_text.endswith("׃")
    assert len(verse.glosses["en"]) == 16 and verse.glosses["en"][1] == "fill"


def test_tahot_word_level_kjv_map():
    rows = kjv_verse_map(read_tahot([DATA / "tahot_sample.txt"], {"1KGS": None}))
    assert [(r.scheme_ref, r.verse_id, r.coverage) for r in rows] == [
        ("1KGS.18.33", "1KGS.18.33", "FULL"),
        ("1KGS.18.33", "1KGS.18.34", "PARTIAL"),
        ("1KGS.18.34", "1KGS.18.34", "PARTIAL"),
    ]


def test_tahot_chapter_filter_uses_hebrew_numbering():
    assert read_tahot([DATA / "tahot_sample.txt"], {"1KGS": {17}}) == []
    assert read_tahot([DATA / "tahot_sample.txt"], {"2KGS": None}) == []


def test_tipnr_records_and_dstrong_lookup():
    recs = read_tipnr(DATA / "tipnr_sample.txt")
    elijah, carmel = recs
    assert (elijah.unique_name, elijah.category, elijah.type) == (
        "Elijah@1Ki.17.1-Jas",
        "PERSON",
        "Male",
    )
    assert elijah.brief and "1Ki.17.1" in elijah.all_refs
    assert carmel.category == "PLACE" and carmel.openbible_name == "Mount Carmel"
    assert carmel.google_latlon == pytest.approx((32.72935, 35.04979), abs=1e-4)
    index = TipnrIndex(recs)
    assert index.lookup("H3760H", None) is carmel
    assert index.lookup("H9999", "Elijah@1Ki.17.1-Jas") is elijah  # falls back to the name
    assert index.lookup("H9999", None) is None


def test_tvtms_renumbers_notes_and_start_different():
    tv = read_tvtms(DATA / "tvtms_sample.txt")
    assert tv.hebrew_renumbers() == {"1KGS.5.1": "1KGS.4.21", "1KGS.5.2": "1KGS.4.22"}
    assert tv.notes()["1KGS.18.34"] == ["In some Bibles this verse starts on a different word."]
    assert "1KGS.18.34" in tv.start_different and "1SAM.21.1" in tv.start_different


def test_openbible_match_by_shared_references():
    carmel = read_tipnr(DATA / "tipnr_sample.txt")[1]
    point = OpenBibleIndex(DATA / "openbible_sample.jsonl").match(carmel)
    assert (point.source, point.source_name, point.confidence) == ("openbible", "Mount Carmel", 1.0)
    assert (point.lat, point.lon) == pytest.approx((32.6725, 35.0233), abs=1e-4)

    elsewhere = TipnrRecord("Nowhere@Gen.1.1", "H1", "PLACE", "", "Place")
    assert OpenBibleIndex(DATA / "openbible_sample.jsonl").match(elsewhere) is None


def test_proper_noun_detection():
    assert _is_proper_noun("HNpm") and _is_proper_noun("HR/Npl")
    assert not _is_proper_noun("HVNp3fs")  # Niphal perfect, not a name
    assert not _is_proper_noun("Hc/Vqw3ms")


def test_parse_scope():
    assert parse_scope("1KGS.17-19")[1] == {17, 18, 19}
    assert parse_scope("1kgs.18")[1] == {18}
    assert parse_scope("GEN")[1] is None
    with pytest.raises(Exception, match="bad"):
        parse_scope("1KGS.19-17")


def test_proposed_ids_are_unique_and_stable():
    def rec(name, type_, refs):
        r = TipnrRecord(name, "H1", "PERSON", "", type_)
        r.names = [type("N", (), {"refs": refs, "dstrong": "H1"})()]
        return r

    ids = propose_ids(
        [
            rec("Elijah@1Ki.17.1-Jas", "Male", ["1Ki.17.1", "1Ki.18.1"]),
            rec("Elijah@Ezr.10.21", "Male", ["Ezr.10.21"]),
            rec("LORD@Gen.1.1-Rev", "Supernatural", ["Gen.1.1"]),
            rec("Kislev@Neh.1.1", "Time", ["Neh.1.1"]),
        ]
    )
    assert ids == {
        "Elijah@1Ki.17.1-Jas": "person.elijah",
        "Elijah@Ezr.10.21": "person.elijah.ezr_10_21",
        "LORD@Gen.1.1-Rev": "deity.yhwh",
    }


def test_fetcher_pins_and_detects_upstream_changes(tmp_path):
    body = {"v": b"first"}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=body["v"]))
    lock = tmp_path / "lock.json"
    with Fetcher(tmp_path / "src", lock, transport=transport) as f:
        path = f.get_url("demo", "https://example.test/a.txt", "demo/a.txt")
    assert path.read_bytes() == b"first"
    pinned = json.loads(lock.read_text())["demo"]["sha256"]

    path.unlink()
    body["v"] = b"changed"
    with pytest.raises(SourceChanged), Fetcher(tmp_path / "src", lock, transport=transport) as f:
        f.get_url("demo", "https://example.test/a.txt", "demo/a.txt")
    assert not path.exists()

    with Fetcher(tmp_path / "src", lock, refresh=True, transport=transport) as f:
        f.get_url("demo", "https://example.test/a.txt", "demo/a.txt")
    assert json.loads(lock.read_text())["demo"]["sha256"] != pinned

    path.write_bytes(b"edited locally")
    with pytest.raises(SourceChanged), Fetcher(tmp_path / "src", lock, transport=transport) as f:
        f.get_url("demo", "https://example.test/a.txt", "demo/a.txt")


def test_merge_source_replaces_only_the_reingested_chapters():
    full = SourceBookIR.model_validate_json((FIXTURE_IR / "source" / "1KGS.json").read_bytes())
    ch18 = [v for v in full.verses if v.verse_id.startswith("1KGS.18.")]
    edited = ch18[0].model_copy(update={"source_text": "EDITED"})
    partial = full.model_copy(
        update={"verses": [edited, *ch18[1:]], "verse_map": [], "baselines": {}}
    )
    tmp = FIXTURE_IR.parent.parent / "build" / "merge_test.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(full.model_dump_json())
    try:
        merged = _merge_source(tmp, partial)
    finally:
        tmp.unlink()
    assert len(merged.verses) == 91
    assert next(v for v in merged.verses if v.verse_id == "1KGS.18.1").source_text == "EDITED"
    assert len(merged.verse_map) == 0  # 18:33-34 rows belonged to the re-ingested chapter
    assert merged.baselines["KJV"] == full.baselines["KJV"]


@pytest.mark.skipif(
    not (SOURCES / "stepbible" / "tahot_jos_est.txt").exists(),
    reason="run `urim ingest 1KGS.17-19` once to download sources",
)
def test_reingest_reproduces_the_committed_fixture(tmp_path):
    lock = tmp_path / "lock.json"
    shutil.copy(REPO / "sources.lock.json", lock)
    report = ingest("1KGS.17-19", tmp_path / "ir", SOURCES, lock, commentaries=False)
    assert report.warnings == []
    for rel in ("source/1KGS.json", "registry/entities.json"):
        assert (tmp_path / "ir" / rel).read_bytes() == (FIXTURE_IR / rel).read_bytes(), rel
