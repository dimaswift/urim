"""The review game's backend: demo corpus, game state, deck, decisions, map data, SQL guard."""

import pytest
from fastapi.testclient import TestClient

from urim.config import Paths, load_paths
from urim.review.basemap import clip_ring, simplify
from urim.review.demo import build_demo
from urim.review.progress import level_for
from urim.review.server import create_review_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    real = load_paths()
    paths = Paths(
        corpus=real.corpus,
        inputs=real.inputs,
        bundles=real.bundles,
        runs=tmp_path_factory.mktemp("runs"),
        fixtures=real.fixtures,
    )
    demo = build_demo(paths)
    return TestClient(create_review_app(demo, demo=True))


def test_overview_reports_territory_player_and_badges(client):
    o = client.get("/api/overview").json()
    assert o["totals"]["chapters_ingested"] == 3 and o["totals"]["chapters_in_canon"] == 1189
    kings = next(b for b in o["books"] if b["book_code"] == "1KGS")
    assert len(kings["chapters"]) == 22
    ch17 = kings["chapters"][16]
    assert ch17["ingested"] and ch17["approval"] == 1.0
    assert not kings["chapters"][0]["ingested"]
    assert o["player"]["xp"] > 0 and o["player"]["rank"] in ("Scout", "Runner", "Scribe")
    assert next(b for b in o["badges"] if b["id"] == "first_seal")["earned"]


def test_levels():
    assert level_for(0)["level"] == 1 and level_for(0)["rank"] == "Scout"
    assert level_for(50)["level"] == 2 and level_for(199)["level_ceiling"] == 200
    assert level_for(10**7)["rank"] == "Sanhedrin"


def test_deck_is_in_reading_order_and_counts_ignore_the_kind_filter(client):
    q = client.get(
        "/api/queue",
        params={"status": "draft", "chapter": "1KGS.19", "kind": "event", "limit": 100},
    ).json()
    verses = [c["payload"]["event"]["verse_start"] for c in q["cards"]]
    assert verses == sorted(verses, key=lambda v: int(v.split(".")[2]))
    assert q["by_kind"]["entity"] > 0  # counts cover every kind in the chapter
    sent_back = client.get("/api/queue", params={"status": "changes_requested"}).json()
    assert [c["key"] for c in sent_back["cards"]] == ["entity:loc.kishon_brook"]
    assert "river mouth" in sent_back["cards"][0]["history"][-1]["note"]


def test_review_decisions_award_xp_and_need_notes(client):
    card = client.get("/api/queue", params={"status": "draft", "limit": 1}).json()["cards"][0]
    r = client.post("/api/review", json={"keys": [card["key"]], "status": "approved"}).json()
    assert r["changed"] == [card["key"]] and r["xp_gained"] > 0
    bad = client.post("/api/review", json={"keys": [card["key"]], "status": "changes_requested"})
    assert bad.status_code == 400 and "note is required" in bad.json()["detail"]
    assert client.get("/api/ledger").json()[card["key"]]["status"] == "approved"


def test_atlas_reconstructs_journeys(client):
    a = client.get("/api/atlas").json()
    elijah = next(j for j in a["journeys"] if j["entity_id"] == "person.elijah")
    stops = [s["place"] for s in elijah["stops"]]
    assert stops[0] == "loc.mount_carmel" and stops[-1] == "loc.abel_meholah"
    assert "loc.mount_horeb" in stops
    horeb = next(p for p in a["places"] if p["entity_id"] == "loc.mount_horeb")
    assert horeb["source"].startswith("openbible") and 0 < horeb["confidence"] < 1


def test_reading_endpoints(client):
    assert client.get("/api/verse/1KGS.18.27").json()["tokens"][15]["strongs"] == "H7873"
    assert len(client.get("/api/entities").json()) == 16
    elijah = client.get("/api/entity/person.elijah").json()
    assert len(elijah["mentions"]) == 39  # every word naming him, from TIPNR + TAHOT
    assert len(client.get("/api/systems").json()) == 5
    assert client.get("/api/search", params={"q": "mantle"}).json()


def test_sql_console_is_read_only(client):
    ok = client.post("/api/sql", json={"query": "SELECT count(*) FROM core_events"}).json()
    assert ok["rows"] == [[18]]
    for statement in (
        "DELETE FROM core_events",
        "DROP TABLE core_events",
        "ATTACH DATABASE '/tmp/x.db' AS x",
    ):
        assert client.post("/api/sql", json={"query": statement}).status_code == 400
    joined = client.post(
        "/api/sql",
        json={
            "query": (
                "SELECT t.title FROM core_events e JOIN lang_en.i18n_events t USING (event_id) "
                "WHERE e.event_id = 'evt.1kgs_18.minchah_fire'"
            )
        },
    ).json()
    assert joined["rows"] == [["Fire falls at the hour of the minchah"]]


def test_basemap_geometry():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    clipped = clip_ring(square, bbox=(5, -5, 15, 5))
    assert sorted(set(clipped)) == [(5.0, 0.0), (5.0, 5.0), (10.0, 0.0), (10.0, 5.0)]
    ring = [(0.0, 0.0), (1.0, 0.001), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
    simple = simplify(ring, tolerance=0.01)
    assert (1.0, 0.001) not in simple and len(simple) >= 4  # closed rings keep their shape


def test_codex_reader_endpoints(client):
    toc = client.get("/api/toc").json()
    assert toc[0]["name"] == "1 Kings" and [c["chapter"] for c in toc[0]["chapters"]] == [
        17,
        18,
        19,
    ]
    assert (
        client.get("/api/toc", params={"lang": "ru"})
        .json()[0]["name"]
        .startswith("3-я книга Царств")
    )
    elisha = next(
        e
        for e in client.get("/api/entities", params={"lang": "ru"}).json()
        if e["entity_id"] == "person.elisha"
    )
    assert elisha["source_script_name"] == "אֱלִישָׁע" and elisha["summary_bio"].startswith("Сын")
    r = client.get("/codex", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/codex.html"
