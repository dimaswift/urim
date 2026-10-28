"""A static copy of the review API, so the War Room and the Codex can be read on GitHub Pages.

Pages serves files, not Python. Every GET the apps make whose answers can be listed in advance
(each chapter, verse and entity, in each language) is asked of the real server through a test
client and written under `api/`, so the static apps show exactly what `urim review` shows. What
depends on words a reader types travels as data the browser searches itself: the keyword index,
the stored vectors for similar items, and the bundles for the SQL console. Review decisions,
Learn and runs need the server and stay out.

Layout (review/src/static.ts reads it):

    api/meta.json, overview.json, ledger.json, i18n/progress.json, sql/schema.json
    api/queue.json                     chapters with a review deck
    api/<lang>/messages.json, toc.json, events.json, atlas.json, entities.json, systems.json
    api/<lang>/chapter/<ref>.json, verse/<id>.json, entity/<id>.json
    api/<lang>/queue/<chapter>.json    every card of the chapter, in deck order
    api/<lang>/search.json             the keyword index: documents and names
    api/<lang>/vectors.json, .bin      vectors as int8 rows, when the bundle has them
    db/core.sqlite, db/lang_<lang>.sqlite   the bundles without search tables, for SQL
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from urim.bundles import core_path, discover_langs, sqlite_uri
from urim.canon import parse_ref
from urim.config import Paths
from urim.embeddings import load_sqlite_vec
from urim.workbench.ledger import all_ledgers

# Everything a reader can ask for in a deck, whatever its status: the static app filters.
_WHOLE_DECK = 1_000_000


class SiteError(RuntimeError):
    pass


@dataclass
class SiteReport:
    files: int = 0
    bytes: int = 0
    langs: list[str] = field(default_factory=list)
    vectors: list[str] = field(default_factory=list)  # languages whose similar items work


def export_site(paths: Paths, out: Path) -> SiteReport:
    """Write the static API and console databases into `out`, next to the built apps."""
    from fastapi.testclient import TestClient

    from urim.review.server import create_review_app

    out = Path(out)
    for sub in ("api", "db"):
        shutil.rmtree(out / sub, ignore_errors=True)
    client = TestClient(create_review_app(paths))
    report = SiteReport(langs=list(discover_langs(paths.bundles)))

    def get(path: str, **params: Any) -> Any:
        r = client.get(f"/api/{path}", params=params)
        if r.status_code != 200:
            raise SiteError(f"/api/{path} {params}: {r.status_code} {r.text[:300]}")
        return r.json()

    def write(rel: str, data: Any) -> None:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        _put(out / "api" / rel, text.encode("utf-8"), report)

    meta = get("meta")
    meta.pop("corpus", None)  # a path on the machine that built it
    write("meta.json", meta | {"static": True})
    for path in ("overview", "ledger", "i18n/progress"):
        write(f"{path}.json", get(path))
    chapters = sorted(
        {led.chapter_ref for led in all_ledgers(paths.corpus)},
        key=lambda c: parse_ref(f"{c}.1")[1].ordinal,
    )
    write("queue.json", {"chapters": chapters})

    verse_ids = _verse_ids(core_path(paths.bundles))
    for lang, bundle in discover_langs(paths.bundles).items():
        write(f"{lang}/messages.json", get("messages", lang=lang))
        toc = get("toc", lang=lang)
        write(f"{lang}/toc.json", toc)
        for book in toc:
            for c in book["chapters"]:
                write(f"{lang}/chapter/{c['ref']}.json", get(f"chapter/{c['ref']}", lang=lang))
        for verse_id in verse_ids:
            write(f"{lang}/verse/{verse_id}.json", get(f"verse/{verse_id}", lang=lang))
        for path in ("events", "atlas", "systems"):
            write(f"{lang}/{path}.json", get(path, lang=lang))
        entities = get("entities", lang=lang)
        write(f"{lang}/entities.json", entities)
        for e in entities:
            entity_id = e["entity_id"]
            write(f"{lang}/entity/{entity_id}.json", get(f"entity/{entity_id}", lang=lang))
        for chapter in chapters:
            deck = get("queue", status="all", chapter=chapter, limit=_WHOLE_DECK, lang=lang)
            write(f"{lang}/queue/{chapter}.json", deck["cards"])
        write(f"{lang}/search.json", _search_index(bundle))
        if _write_vectors(paths, lang, bundle, out / "api" / lang, report):
            report.vectors.append(lang)

    # The console lists only what the browser can query: sql.js has no FTS5 and no sqlite-vec.
    kept = {"main": _console_copy(core_path(paths.bundles), out / "db" / "core.sqlite", report)}
    for lang, bundle in discover_langs(paths.bundles).items():
        kept[f"lang_{lang}"] = _console_copy(bundle, out / "db" / f"lang_{lang}.sqlite", report)
    write("sql/schema.json", [t for t in get("sql/schema") if t["table"] in kept[t["schema"]]])
    return report


def _put(path: Path, data: bytes, report: SiteReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    report.files += 1
    report.bytes += len(data)


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(sqlite_uri(path, immutable=True), uri=True)


def _verse_ids(core: Path) -> list[str]:
    conn = _connect(core)
    try:
        return [r[0] for r in conn.execute("SELECT verse_id FROM core_verses ORDER BY ordinal")]
    finally:
        conn.close()


def _search_index(bundle: Path) -> dict[str, Any]:
    """The language's FTS documents in table order, and every name an entity or system goes
    by, folded as the engine folds them, for keyword search in the browser."""
    conn = _connect(bundle)
    try:
        docs = [
            list(r) for r in conn.execute("SELECT doc_kind, doc_id, title, body FROM i18n_search")
        ]
        names: list[list[str]] = []
        for entity_id, name, aliases in conn.execute(
            "SELECT entity_id, canonical_name, aliases_json FROM i18n_entities"
        ):
            for n in dict.fromkeys([name, *json.loads(aliases)]):
                names.append([_fold(n), "entity", entity_id])
        for system_id, name in conn.execute("SELECT system_id, name FROM i18n_systems"):
            names.append([_fold(name), "system", system_id])
    finally:
        conn.close()
    return {"docs": docs, "names": names}


def _fold(name: str) -> str:
    return " ".join(name.casefold().split())


def _write_vectors(paths: Paths, lang: str, bundle: Path, dest: Path, report: SiteReport) -> bool:
    """The bundle's vectors as int8 rows (each scaled on its own: cosine ignores length), with
    the documents they belong to and every entity's type. False without vectors or sqlite-vec."""
    manifest = json.loads((bundle.parent / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("embedding_model"):
        return False
    try:
        import numpy as np
    except ImportError:
        return False
    conn = _connect(bundle)
    try:
        if not load_sqlite_vec(conn):
            return False
        rows = conn.execute("SELECT doc_kind, doc_id, embedding FROM i18n_vectors").fetchall()
    finally:
        conn.close()
    if not rows:
        return False
    matrix = np.frombuffer(b"".join(r[2] for r in rows), dtype="<f4").reshape(len(rows), -1)
    peak = np.maximum(np.abs(matrix).max(axis=1, keepdims=True), 1e-12)
    _put(dest / "vectors.bin", np.round(matrix * (127 / peak)).astype(np.int8).tobytes(), report)
    core = _connect(core_path(paths.bundles))
    try:
        types = dict(core.execute("SELECT entity_id, entity_type FROM core_entities"))
    finally:
        core.close()
    meta = {
        "model": manifest["embedding_model"],
        "dims": int(matrix.shape[1]),
        "docs": [[r[0], r[1]] for r in rows],
        "entity_types": types,
    }
    _put(dest / "vectors.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"), report)
    return True


def _console_copy(src: Path, dst: Path, report: SiteReport) -> set[str]:
    """The bundle's plain tables and indexes, for SQL in the browser; returns the tables kept.
    Search tables (FTS5 and vec0, with their shadow tables) need modules sql.js lacks."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    conn = sqlite3.connect(dst.resolve().as_uri(), uri=True)  # so ATTACH takes a URI too
    try:
        conn.execute("ATTACH DATABASE ? AS src", (sqlite_uri(src, immutable=True),))
        schema = conn.execute(
            "SELECT type, name, tbl_name, sql FROM src.sqlite_master WHERE sql IS NOT NULL"
            " AND name NOT LIKE 'sqlite_%' ORDER BY type = 'index', rowid"
        ).fetchall()
        virtual = [
            n for t, n, _, sql in schema if t == "table" and sql.startswith("CREATE VIRTUAL")
        ]

        def searchy(table: str) -> bool:
            return any(table == v or table.startswith(v + "_") for v in virtual)

        kept = set()
        for kind, name, table, sql in schema:
            if kind not in ("table", "index") or searchy(table):
                continue
            kept.add(table)
            conn.execute(sql)
            if kind == "table":  # table_info leaves out generated columns, which compute
                cols = ", ".join(
                    f'"{c[1]}"' for c in conn.execute(f'PRAGMA src.table_info("{name}")')
                )
                conn.execute(f'INSERT INTO main."{name}" ({cols}) SELECT {cols} FROM src."{name}"')
        conn.commit()
        conn.execute("DETACH DATABASE src")
        conn.execute("VACUUM")
    finally:
        conn.close()
    report.files += 1
    report.bytes += dst.stat().st_size
    return kept
