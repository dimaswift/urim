"""The static copy for GitHub Pages: the files answer what the server answers, every chapter,
verse and entity is there, and search, similar items and SQL travel as data for the browser."""

import json
import sqlite3

import numpy as np
import pytest
from fastapi.testclient import TestClient

from urim.config import Paths, load_paths
from urim.embeddings import EmbeddingCache, Vectorizer
from urim.review.demo import build_demo
from urim.review.server import create_review_app
from urim.review.site import export_site

from .conftest import BagOfWords

pytest.importorskip("sqlite_vec")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    real = load_paths()
    root = tmp_path_factory.mktemp("site")
    embedder = BagOfWords()
    vectors = Vectorizer(embedder, EmbeddingCache(root / "cache", embedder.model_id))
    paths = build_demo(
        Paths(corpus=real.corpus, inputs=real.inputs, runs=root / "runs", fixtures=real.fixtures),
        vectors,
    )
    report = export_site(paths, root / "out")
    return paths, root / "out", report, TestClient(create_review_app(paths))


def read(out, rel):
    return json.loads((out / "api" / rel).read_text(encoding="utf-8"))


def test_the_files_answer_what_the_server_answers(site):
    _, out, report, client = site
    assert report.langs == ["en", "ru"] and report.vectors == ["en", "ru"]
    meta = read(out, "meta.json")
    assert meta["static"] and "corpus" not in meta  # no path from the machine that built it
    assert [lang["lang_code"] for lang in meta["languages"]] == ["en", "ru"]
    for rel, path, params in [
        ("overview.json", "/api/overview", {}),
        ("i18n/progress.json", "/api/i18n/progress", {}),
        ("ru/toc.json", "/api/toc", {"lang": "ru"}),
        ("ru/chapter/1KGS.18.json", "/api/chapter/1KGS.18", {"lang": "ru"}),
        ("en/verse/1KGS.18.27.json", "/api/verse/1KGS.18.27", {"lang": "en"}),
        ("en/entity/person.elijah.json", "/api/entity/person.elijah", {"lang": "en"}),
        ("ru/events.json", "/api/events", {"lang": "ru"}),
    ]:
        assert read(out, rel) == client.get(path, params=params).json(), rel


def test_every_chapter_verse_entity_and_deck_is_there(site):
    _, out, _, client = site
    for lang in ("en", "ru"):
        for book in read(out, f"{lang}/toc.json"):
            for c in book["chapters"]:
                assert (out / "api" / lang / "chapter" / f"{c['ref']}.json").exists()
                verses = list((out / "api" / lang / "verse").glob(f"{c['ref']}.*.json"))
                assert len(verses) == c["verses"]
        for e in read(out, f"{lang}/entities.json"):
            assert (out / "api" / lang / "entity" / f"{e['entity_id']}.json").exists()
    # Each chapter's whole deck, in deck order; the browser filters by status and kind.
    chapters = read(out, "queue.json")["chapters"]
    assert chapters == ["1KGS.17", "1KGS.18", "1KGS.19"]
    deck = read(out, "en/queue/1KGS.19.json")
    served = client.get(
        "/api/queue", params={"status": "all", "chapter": "1KGS.19", "limit": 10**6}
    )
    assert [c["key"] for c in deck] == [c["key"] for c in served.json()["cards"]]
    drafts = [c["key"] for c in deck if c["status"] == "draft"]
    queue = client.get("/api/queue", params={"status": "draft", "chapter": "1KGS.19", "limit": 500})
    assert drafts == [c["key"] for c in queue.json()["cards"]]


def test_search_and_similar_items_travel_as_data(site):
    _, out, _, client = site
    index = read(out, "en/search.json")
    kinds = {kind for kind, *_ in index["docs"]}
    assert kinds == {"verse", "entity", "system", "event"}
    assert ["elijah", "entity", "person.elijah"] in index["names"]  # folded, as the engine folds

    meta = read(out, "en/vectors.json")
    rows = np.frombuffer((out / "api" / "en" / "vectors.bin").read_bytes(), dtype=np.int8)
    assert meta["dims"] == BagOfWords.dims and rows.size == len(meta["docs"]) * meta["dims"]
    assert meta["entity_types"]["person.elijah"] == "PERSON"
    # Cosine over the int8 rows finds the server's nearest neighbour.
    m = rows.reshape(len(meta["docs"]), -1).astype(float)
    m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)
    at = {(k, i): n for n, (k, i) in enumerate(meta["docs"])}
    sims = m @ m[at[("entity", "person.elijah")]]
    ranked = [
        meta["docs"][n][1]
        for n in np.argsort(-sims)
        if meta["docs"][n] != ["entity", "person.elijah"] and meta["docs"][n][0] == "entity"
    ]
    served = client.get("/api/similar/entity/person.elijah", params={"top_k": 1}).json()
    assert ranked[0] == served[0]["id"]


def test_the_console_databases_keep_plain_tables_only(site):
    paths, out, _, client = site
    conn = sqlite3.connect(out / "db" / "core.sqlite")
    conn.execute("ATTACH DATABASE ? AS lang_en", (str(out / "db" / "lang_en.sqlite"),))
    tables = {r[0] for r in conn.execute("SELECT name FROM lang_en.sqlite_master")}
    assert "i18n_events" in tables and not any("search" in t or "vectors" in t for t in tables)
    joined = conn.execute(
        "SELECT count(*) FROM core_events e JOIN lang_en.i18n_events t USING (event_id)"
    ).fetchone()[0]
    assert joined == len(client.get("/api/events").json()["events"])
    # Generated columns are computed again, not copied.
    source = sqlite3.connect(paths.bundles / "urim-core.sqlite")
    sql = "SELECT * FROM core_events ORDER BY event_id"
    assert conn.execute(sql).fetchall() == source.execute(sql).fetchall()
    # The console lists only what the browser can query: the FTS5 index stays with the server.
    conn.execute("ATTACH DATABASE ? AS lang_ru", (str(out / "db" / "lang_ru.sqlite"),))
    schema = read(out, "sql/schema.json")
    assert {t["schema"] for t in schema} == {"main", "lang_en", "lang_ru"}
    assert not any("search" in t["table"] for t in schema)
    for t in schema:
        conn.execute(f'SELECT count(*) FROM {t["schema"]}."{t["table"]}"')
