"""Text embeddings for semantic search: optional, installed with `urim[search]`.

bge-m3 runs through ONNX Runtime from pinned files (`urim model fetch`). The int8 export carries
bge-m3's own CLS pooling and normalization, so a text goes in and a unit vector comes out. The
linker caches vectors by text hash, so a relink embeds only what changed. Each bundle records
the model it was built with, and a query is embedded only by that same model.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Protocol

MODEL_ID = "bge-m3-int8@4de1325"
MODEL_DIR = "models/bge-m3"
MODEL_FILE = "sentence_transformers_int8.onnx"
TOKENIZER_FILE = "tokenizer.json"
MAX_TOKENS = 1024  # bge-m3 reads 8192, but verses and dossiers fit in far less
BATCH = 8


class Embedder(Protocol):
    model_id: str
    dims: int

    def embed(self, texts: Sequence[str]) -> list[bytes]:
        """One float32 little-endian unit vector per text, in order."""
        ...


class OnnxEmbedder:
    def __init__(self, model_dir: Path):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self.model_id = MODEL_ID
        self.tokenizer = Tokenizer.from_file(str(model_dir / TOKENIZER_FILE))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        pad = self.tokenizer.token_to_id("<pad>")
        self.tokenizer.enable_padding(pad_id=pad, pad_token="<pad>")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model_dir / MODEL_FILE), options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        outputs = [o.name for o in self.session.get_outputs()]
        self.output = "sentence_embedding" if "sentence_embedding" in outputs else outputs[0]
        self.dims = self.session.get_outputs()[outputs.index(self.output)].shape[-1]
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[bytes]:
        np = self._np
        vectors: list[bytes] = [b""] * len(texts)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # less padding
        for start in range(0, len(order), BATCH):
            batch = order[start : start + BATCH]
            encoded = self.tokenizer.encode_batch([texts[i] for i in batch])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            feed = {
                "input_ids": ids,
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
            }
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            with self._lock:
                out = self.session.run([self.output], feed)[0]
            if out.ndim == 3:  # token states: bge-m3 pools on the CLS token
                out = out[:, 0]
            out = out / np.linalg.norm(out, axis=1, keepdims=True)
            for i, v in zip(batch, out, strict=True):
                vectors[i] = v.astype("<f4").tobytes()
        return vectors


def unavailable(sources_dir: Path) -> str | None:
    """Why semantic search cannot run here, or None when it can."""
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import sqlite_vec  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError as e:
        return f"{e.name} is not installed: install the extra with `uv sync --extra search`"
    model_dir = Path(sources_dir) / MODEL_DIR
    if not (model_dir / MODEL_FILE).exists() or not (model_dir / TOKENIZER_FILE).exists():
        return f"no embedding model in {model_dir}: run `urim model fetch`"
    return None


@cache
def _load(model_dir: str) -> OnnxEmbedder:
    return OnnxEmbedder(Path(model_dir))


def load_embedder(sources_dir: Path) -> Embedder | None:
    """The pinned bge-m3, loaded once per process; None when it is unavailable."""
    if unavailable(sources_dir):
        return None
    return _load(str((Path(sources_dir) / MODEL_DIR).resolve()))


class EmbeddingCache:
    """Vectors by model and text hash, so a relink embeds only new or changed text."""

    def __init__(self, cache_dir: Path, model_id: str):
        path = Path(cache_dir) / "embeddings" / f"{model_id.replace('/', '_')}.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB)")
        self.model_id = model_id
        self.hits = self.misses = 0

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_id}\0{text}".encode()).hexdigest()

    def embed(self, embedder: Embedder, texts: Sequence[str]) -> list[bytes]:
        keys = [self.key(t) for t in texts]
        found: dict[str, bytes] = {}
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), 500):
            chunk = unique[start : start + 500]
            found |= dict(
                self.conn.execute(
                    f"SELECT key, vector FROM vectors WHERE key IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
            )
        missing = {k: t for k, t in zip(keys, texts, strict=True) if k not in found}
        self.hits += len(unique) - len(missing)  # running totals across calls
        self.misses += len(missing)
        if missing:
            vectors = embedder.embed(list(missing.values()))
            with self.conn:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                    zip(missing, vectors, strict=True),
                )
            found |= dict(zip(missing, vectors, strict=True))
        return [found[k] for k in keys]


@dataclass
class Vectorizer:
    """What the linker needs: an embedder, optionally behind a cache."""

    embedder: Embedder
    cache: EmbeddingCache | None = None

    @property
    def model_id(self) -> str:
        return self.embedder.model_id

    @property
    def dims(self) -> int:
        return self.embedder.dims

    def __call__(self, texts: Sequence[str]) -> list[bytes]:
        if self.cache is None:
            return self.embedder.embed(texts)
        return self.cache.embed(self.embedder, texts)


def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Register sqlite-vec on a connection; False when the extra is not installed."""
    try:
        import sqlite_vec
    except ImportError:
        return False
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    return True
