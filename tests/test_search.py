"""Vectors in language bundles and hybrid search, with a small fake embedder (and the real one
when it is installed)."""

import hashlib
import math
import re
import sqlite3
import struct

import pytest

from urim.bundles import lang_bundle_path
from urim.compiler.link import link_all
from urim.config import load_paths
from urim.embeddings import EmbeddingCache, Vectorizer, load_embedder, load_sqlite_vec, unavailable
from urim.runtime.engine import UrimEngine

from .conftest import FIXTURE_IR

pytest.importorskip("sqlite_vec")


class BagOfWords:
    """Words hashed into 64 dimensions: texts that share words point the same way."""

    dims = 64

    def __init__(self, model_id: str = "bag-of-words@1"):
        self.model_id = model_id
        self.embedded = 0

    def embed(self, texts):
        self.embedded += len(texts)
        out = []
        for text in texts:
            v = [0.0] * self.dims
            for word in re.findall(r"\w+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dims] += 1
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append(struct.pack(f"<{self.dims}f", *(x / norm for x in v)))
        return out


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
