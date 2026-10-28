"""Vectors in language bundles, hybrid search, search by meaning and similar items, with a small
fake embedder (and the real one when it is installed)."""

import sqlite3
import struct
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from urim.bundles import lang_bundle_path
from urim.compiler.link import link_all
from urim.config import load_paths
from urim.embeddings import EmbeddingCache, Vectorizer, load_embedder, load_sqlite_vec, unavailable
from urim.review.server import create_review_app
from urim.runtime.engine import NotFoundError, SearchUnavailable, UrimEngine

from .conftest import FIXTURE_IR, BagOfWords

pytest.importorskip("sqlite_vec")


@pytest.fixture(scope="module")
def vector_bundles(tmp_path_factory):
    root = tmp_path_factory.mktemp("vectors")
    embedder = BagOfWords()
    vectors = Vectorizer(embedder, EmbeddingCache(root / "cache", embedder.model_id))
    link_all(FIXTURE_IR, root / "bundles", vectors=vectors)
    return root, embedder, vectors


def test_link_stores_a_vector_per_search_document(vector_bundles):
    root, embedder, vectors = vector_bundles
    conn = sqlite3.connect(lang_bundle_path(root / "bundles", "en"))
    load_sqlite_vec(conn)
    docs = conn.execute("SELECT count(*) FROM i18n_search").fetchone()[0]
    assert conn.execute("SELECT count(*) FROM i18n_vectors").fetchone()[0] == docs > 0
    model = conn.execute("SELECT embedding_model FROM bundle_manifest").fetchone()[0]
    assert model == "bag-of-words@1"

    before = embedder.embedded
    link_all(FIXTURE_IR, root / "bundles", vectors=vectors)  # unchanged text: all from cache
    assert embedder.embedded == before and vectors.cache.hits > 0


def test_search_fuses_keywords_and_meaning(vector_bundles):
    root, embedder, _ = vector_bundles
    engine = UrimEngine(root / "bundles", embedder=embedder)
    hits = engine.semantic_search("ravens feed Elijah", top_k=5)
    assert hits and all("meaning" in h.via or "keyword" in h.via for h in hits)
    assert any(h.via == ["keyword", "meaning"] for h in hits)
    assert all(h.title and h.snippet for h in hits)
    assert {h.kind for h in engine.semantic_search("Elijah", scope="events", top_k=5)} == {"event"}

    keyword_only = UrimEngine(root / "bundles", embedder=None).semantic_search("ravens", top_k=5)
    assert keyword_only and all(h.via == ["keyword"] for h in keyword_only)
    # A query embedder must be the bundle's own model, or its vectors are not comparable.
    other = UrimEngine(root / "bundles", embedder=BagOfWords("another-model@2"))
    assert all(h.via == ["keyword"] for h in other.semantic_search("ravens", top_k=5))


def test_search_by_meaning_alone_ranks_by_similarity(vector_bundles):
    root, embedder, _ = vector_bundles
    engine = UrimEngine(root / "bundles", embedder=embedder)
    hits = engine.semantic_search("the ravens brought bread", mode="meaning", top_k=8)
    assert len(hits) == 8 and all(h.via == ["meaning"] and h.title for h in hits)
    sims = [h.similarity for h in hits]
    assert sims == sorted(sims, reverse=True) and all(0 < s <= 1 for s in sims)
    assert [h.score for h in hits] == sims
    # Hybrid hits found by meaning carry their similarity too; keyword-only ones do not.
    hybrid = engine.semantic_search("ravens", top_k=30)
    assert all((h.similarity is not None) == ("meaning" in h.via) for h in hybrid)
    assert engine.semantic_search("Sinai")[0].id == "loc.mount_horeb"  # names still lead

    without_model = UrimEngine(root / "bundles", embedder=None)
    with pytest.raises(SearchUnavailable, match="keyword only"):
        without_model.semantic_search("ravens", mode="meaning")


def test_find_similar_compares_stored_vectors(vector_bundles):
    root, embedder, _ = vector_bundles
    # No query is embedded: the bundle's vectors are enough, without the model.
    engine = UrimEngine(root / "bundles", embedder=None)
    hits = engine.find_similar("entity", "person.elijah", top_k=6)
    assert len(hits) == 6 and "person.elijah" not in {h.id for h in hits}
    assert {h.kind for h in hits} == {"entity"} and all(h.title and h.snippet for h in hits)
    sims = [h.similarity for h in hits]
    assert sims == sorted(sims, reverse=True)

    types = {e.entity_id: e.entity_type for e in engine.list_entities()}
    people = engine.find_similar("entity", "person.elijah", top_k=4, same_type=True)
    assert people and {types[h.id] for h in people} == {"PERSON"}

    event = engine.list_events()[0].event_id
    assert len({h.kind for h in engine.find_similar("event", event, scope="all")}) > 1
    with pytest.raises(NotFoundError):
        engine.find_similar("entity", "person.nobody")
    with pytest.raises(ValueError):
        engine.find_similar("event", event, same_type=True)


def test_review_app_serves_similar_items_and_a_console_schema(vector_bundles):
    root, _, _ = vector_bundles
    paths = replace(load_paths(), bundles=root / "bundles", runs=root / "runs")
    client = TestClient(create_review_app(paths))
    r = client.get("/api/similar/entity/person.elijah", params={"same_type": True, "top_k": 3})
    assert r.status_code == 200 and len(r.json()) == 3
    assert all(h["similarity"] is not None for h in r.json())
    # The console cannot open vec0 tables (no sqlite-vec there), so the schema leaves them out.
    schema = client.get("/api/sql/schema")
    assert schema.status_code == 200
    assert not any("vectors" in t["table"] for t in schema.json())


@pytest.mark.skipif(
    unavailable(load_paths().sources) is not None, reason="bge-m3 not installed (urim model fetch)"
)
def test_bge_m3_puts_paraphrases_and_translations_close():
    embedder = load_embedder(load_paths().sources)
    texts = [
        "The ravens brought him bread and meat in the morning and in the evening.",
        "Birds carried food to the prophet hiding by the brook.",
        "Ahab gathered all Israel to Mount Carmel.",
        "Вороны приносили ему хлеб и мясо поутру и вечером.",
    ]
    v = [struct.unpack(f"<{embedder.dims}f", b) for b in embedder.embed(texts)]
    cos = [sum(a * b for a, b in zip(v[0], x, strict=True)) for x in v]
    assert embedder.dims == 1024 and abs(cos[0] - 1) < 1e-3
    assert cos[3] > cos[1] > cos[2]  # translation, then paraphrase, then another scene
