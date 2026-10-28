"""The review app's API, plus the built frontend (review/dist) as static files.

Reads come from the linked bundles through UrimEngine; review decisions write to the corpus
ledger. The engine is reloaded whenever a merge relinks the bundles.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from urim import __version__
from urim.bundles import core_path, discover_langs, sqlite_uri
from urim.canon import parse_ref
from urim.conductor.plan import is_escalated
from urim.conductor.run import RunState, alive, list_runs, load_state
from urim.config import Paths
from urim.i18n.messages import Messages, load_translations
from urim.i18n.progress import all_progress
from urim.ir.load import inputs_root, load_registry
from urim.learn.coach import EXAM_SIZE, facts_count, session
from urim.learn.quiz import FAMILIES, Facts, chapter_facts, judge, make, parse_id
from urim.learn.retell import RetellError, grade
from urim.learn.store import KNOWN_DAYS, PASS_MARK, Learner
from urim.review.cards import card, deck_order
from urim.review.progress import overview
from urim.runtime.engine import LanguageNotAvailable, NotFoundError, SearchUnavailable, UrimEngine
from urim.workbench.ledger import LedgerError, all_ledgers, set_status

SQL_ROW_LIMIT = 500
SQL_TIME_LIMIT_S = 3.0


_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


def _read_only_authorizer(action: int, *_: object) -> int:
    """Console guard: reads only. Blocks writes, schema changes, ATTACH/DETACH and PRAGMAs."""
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


class ReviewRequest(BaseModel):
    keys: list[str]
    status: Literal["approved", "changes_requested", "draft"]
    note: str | None = None


class SqlRequest(BaseModel):
    query: str


class AnswerRequest(BaseModel):
    question_id: str
    response: Any
    mode: Literal["practice", "exam"] = "practice"
    exam_id: int | None = None
    ms: int | None = None
    lang: str = "en"


class RetellRequest(BaseModel):
    chapter: str
    text: str
    lang: str = "en"


class EngineHolder:
    """One engine per bundle generation: re-created when a relink changes the files."""

    def __init__(self, bundles: Path, messages: Messages | None = None):
        self.bundles, self.messages = Path(bundles), messages
        self._engine: UrimEngine | None = None
        self._stamp: tuple | None = None
        self._lock = threading.Lock()

    def _files(self) -> list[Path]:
        return [core_path(self.bundles), *discover_langs(self.bundles).values()]

    def get(self) -> UrimEngine:
        stamp = tuple((str(p), p.stat().st_mtime_ns) for p in self._files() if p.exists())
        with self._lock:
            if stamp != self._stamp or self._engine is None:
                self._engine = UrimEngine(self.bundles, messages=self.messages)
                self._stamp = stamp
            return self._engine

    def console(self, guarded: bool = True) -> sqlite3.Connection:
        """Read-only connection with every language attached; `guarded` adds the console guard
        for user-typed SQL (internal fixed queries may use PRAGMA)."""
        conn = sqlite3.connect(sqlite_uri(core_path(self.bundles), immutable=True), uri=True)
        for lang, path in discover_langs(self.bundles).items():
            conn.execute(f"ATTACH DATABASE ? AS lang_{lang}", (sqlite_uri(path, immutable=True),))
        conn.execute("PRAGMA query_only = 1")
        if guarded:
            conn.set_authorizer(_read_only_authorizer)
        return conn


def _chapter_ordinal(chapter: str) -> int:
    return parse_ref(f"{chapter}.1")[1].ordinal


def create_review_app(
    paths: Paths,
    *,
    static_dir: Path | None = None,
    demo: bool = False,
    grader: Callable[[str], str] | None = None,
) -> FastAPI:
    translators = Messages(paths.corpus)  # generated words (dates, quizzes, cards) per language
    holder = EngineHolder(paths.bundles, translators)
    app = FastAPI(title="URIM review", version=__version__)
    # The demo corpus is the gold: answers to it stay out of your own record.
    learner = Learner(paths.runs / "demo" / "learner.sqlite" if demo else paths.learner)
    facts_cache: dict[tuple[int, str, str], Facts] = {}  # by engine, chapter and language

    @app.exception_handler(NotFoundError)
    def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(LanguageNotAvailable)
    def _no_lang(_: Request, exc: LanguageNotAvailable) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(SearchUnavailable)
    def _no_vectors(_: Request, exc: SearchUnavailable) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    def _bad(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def ledger_items():
        for led in all_ledgers(paths.corpus):
            for k, item in led.items.items():
                yield led, k, item

    # --- game state ---------------------------------------------------------------------------

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        engine = holder.get()
        return {
            "version": __version__,
            "demo": demo,
            "corpus": str(paths.corpus),
            "languages": [lang.model_dump() for lang in engine.languages()],
            "chronology_scheme": engine.core_meta.get("chronology_scheme"),
        }

    @app.get("/api/messages")
    def messages(lang: str = "en") -> dict[str, Any]:
        """Interface translations for one language; the apps carry English themselves."""
        return {
            "lang": lang,
            "messages": {} if lang == "en" else load_translations(paths.corpus, lang),
        }

    @app.get("/api/i18n/progress")
    def i18n_progress() -> list[dict[str, Any]]:
        """Each language's progress: chapter texts and verses, interface, bundle labels."""
        return all_progress(paths.corpus)

    @app.get("/api/toc")
    def toc(lang: str = "en") -> list[dict[str, Any]]:
        """Books and chapters present in the bundles, with localized book names."""
        conn = holder.console(guarded=False)
        try:
            schemas = [
                s
                for s in (f"lang_{lang}", "lang_en")
                if s.replace("lang_", "") in discover_langs(paths.bundles)
            ]
            names: dict[int, str] = {}
            for schema in reversed(schemas):
                names |= dict(conn.execute(f"SELECT book_id, name FROM {schema}.i18n_books"))
            rows = conn.execute(
                "SELECT b.book_id, b.book_code, b.osis_code, v.chapter, count(*),"
                " min(v.verse_id) FROM core_verses v JOIN core_books b USING (book_id)"
                " GROUP BY b.book_id, v.chapter ORDER BY b.book_id, v.chapter"
            ).fetchall()
            # A verse counts as translated when this language or the English fallback has a layer.
            translated: Counter[str] = Counter()
            for verse_id in {
                r[0]
                for schema in schemas
                for r in conn.execute(
                    f"SELECT verse_id FROM {schema}.i18n_verses WHERE translation_literal"
                    " IS NOT NULL OR translation_dramatic IS NOT NULL"
                )
            }:
                translated[verse_id.rsplit(".", 1)[0]] += 1
        finally:
            conn.close()
        books: dict[int, dict[str, Any]] = {}
        for book_id, code, osis, chapter, verses, _ in rows:
            book = books.setdefault(
                book_id,
                {"book_code": code, "osis": osis, "name": names.get(book_id, osis), "chapters": []},
            )
            ref = f"{code}.{chapter}"
            book["chapters"].append(
                {"chapter": chapter, "ref": ref, "verses": verses, "translated": translated[ref]}
            )
        return list(books.values())

    @app.get("/api/overview")
    def get_overview() -> dict[str, Any]:
        return overview(paths)

    @app.get("/api/ledger")
    def get_ledger() -> dict[str, Any]:
        return {
            k: {
                "status": i.status,
                "chapter": led.chapter_ref,
                "model": i.produced_by.model,
                "notes": len(i.agent_notes),
            }
            for led, k, i in ledger_items()
        }

    @app.get("/api/queue")
    def queue(
        status: str = "draft",
        chapter: str | None = None,
        kind: str | None = None,
        limit: int = 40,
        lang: str = "en",
    ) -> dict[str, Any]:
        engine = holder.get()
        scoped = [
            (led, k, i)
            for led, k, i in ledger_items()
            if (status == "all" or i.status == status)
            and (chapter is None or led.chapter_ref == chapter)
        ]
        counts = Counter(k.split(":")[0] for _, k, _ in scoped)
        picked = [x for x in scoped if kind is None or x[1].startswith(kind + ":")]
        cards = [card(engine, led, k, i, lang, translators(lang)) for led, k, i in picked]
        cards.sort(key=lambda c: deck_order(c, _chapter_ordinal(c["chapter"])))
        return {
            "total": len(picked),
            "by_kind": counts,
            "cards": cards[:limit],
        }

    @app.post("/api/review")
    def review(req: ReviewRequest) -> dict[str, Any]:
        keys, status, note = req.keys, req.status, req.note
        before = overview(paths)["player"]
        try:
            changed = set_status(paths.corpus, keys, status, note)
        except LedgerError as e:
            raise HTTPException(400, str(e)) from e
        state = overview(paths)
        return {
            "changed": [k for _, k in changed],
            "player": state["player"],
            "xp_gained": state["player"]["xp"] - before["xp"],
            "level_up": state["player"]["level"] > before["level"],
            "badges": state["badges"],
        }

    # --- reading ------------------------------------------------------------------------------

    @app.get("/api/verse/{ref}")
    def verse(ref: str, lang: str = "en") -> dict[str, Any]:
        engine = holder.get()
        m = engine.get_verse_matrix(ref, lang=lang)
        return m.model_dump(mode="json")

    @app.get("/api/chapter/{ref}")
    def chapter(ref: str, lang: str = "en") -> dict[str, Any]:
        book, ch = ref.rsplit(".", 1)
        return holder.get().get_chapter_stream(book, int(ch), lang).model_dump(mode="json")

    @app.get("/api/events")
    def events(lang: str = "en") -> dict[str, Any]:
        engine = holder.get()
        return {
            "events": [e.model_dump(mode="json") for e in engine.list_events(lang)],
            "links": [x.model_dump(mode="json") for x in engine.list_causal_links(lang)],
        }

    @app.get("/api/causal/{event_id}")
    def causal(
        event_id: str,
        direction: Literal["upstream", "downstream", "both"] = "both",
        depth: int = 6,
        lang: str = "en",
    ) -> dict[str, Any]:
        return (
            holder.get()
            .trace_causal_chain(event_id, direction, depth, lang)
            .model_dump(mode="json")
        )

    @app.get("/api/atlas")
    def atlas(lang: str = "en") -> dict[str, Any]:
        engine = holder.get()
        names = {r.entity_id: r for r in engine.list_entities(lang)}
        events = engine.list_events(lang)
        conn = holder.console()
        try:
            places = conn.execute(
                "SELECT entity_id, geo_lat, geo_lon, geo_source, geo_confidence "
                "FROM core_entities WHERE geo_lat IS NOT NULL ORDER BY entity_id"
            ).fetchall()
            cast = conn.execute(
                "SELECT event_id, entity_id, role FROM core_event_participants "
                "WHERE role IN ('AGENT', 'PATIENT', 'PRESENT')"
            ).fetchall()
        finally:
            conn.close()
        at_place: dict[str, list[str]] = defaultdict(list)
        for e in events:
            if e.location:
                at_place[e.location.entity_id].append(e.event_id)
        by_event = {e.event_id: e for e in events}
        journeys: dict[str, list[dict]] = defaultdict(list)
        for event_id, entity_id, _ in cast:
            e = by_event.get(event_id)
            if (
                e
                and e.location
                and names.get(entity_id)
                and names[entity_id].entity_type == "PERSON"
            ):
                journeys[entity_id].append(
                    {
                        "event_id": event_id,
                        "title": e.title,
                        "place": e.location.entity_id,
                        "utes": e.utes_start,
                        "label": e.start_label,
                    }
                )
        routes = []
        for entity_id, stops in journeys.items():
            stops.sort(key=lambda s: s["utes"])
            route = [
                s for i, s in enumerate(stops) if i == 0 or s["place"] != stops[i - 1]["place"]
            ]
            if len({s["place"] for s in route}) >= 2:
                routes.append(
                    {"entity_id": entity_id, "name": names[entity_id].name, "stops": route}
                )
        routes.sort(key=lambda r: -len(r["stops"]))
        return {
            "places": [
                {
                    "entity_id": p[0],
                    "name": names[p[0]].name if p[0] in names else p[0],
                    "lat": p[1],
                    "lon": p[2],
                    "source": p[3],
                    "confidence": p[4],
                    "events": at_place.get(p[0], []),
                }
                for p in places
            ],
            "journeys": routes,
            "events": {
                e.event_id: {"title": e.title, "label": e.start_label, "utes": e.utes_start}
                for e in events
            },
        }

    @app.get("/api/entities")
    def entities(lang: str = "en") -> list[dict[str, Any]]:
        engine = holder.get()
        names = {r.entity_id: r for r in engine.list_entities(lang)}
        conn = holder.console()
        try:
            rows = conn.execute(
                "SELECT e.entity_id, e.entity_type, e.tipnr_id, e.first_mention_verse,"
                " (SELECT count(*) FROM core_event_participants p WHERE p.entity_id = e.entity_id),"
                " (SELECT count(*) FROM core_edges x WHERE x.source_entity_id = e.entity_id"
                "    OR x.target_entity_id = e.entity_id),"
                " (SELECT count(*) FROM core_components c WHERE c.entity_id = e.entity_id),"
                " e.geo_lat IS NOT NULL, e.source_script_name"
                " FROM core_entities e ORDER BY e.entity_id"
            ).fetchall()
        finally:
            conn.close()
        bios: dict[str, str] = {}
        conn = holder.console(guarded=False)
        try:
            for code in ("en", lang):
                if code in discover_langs(paths.bundles):
                    bios |= dict(
                        conn.execute(
                            f"SELECT entity_id, summary_bio FROM lang_{code}.i18n_entities"
                        )
                    )
        finally:
            conn.close()
        return [
            {
                "entity_id": r[0],
                "name": names[r[0]].name,
                "entity_type": r[1],
                "tipnr_id": r[2],
                "first_mention_verse": r[3],
                "events": r[4],
                "interactions": r[5],
                "states": r[6],
                "located": bool(r[7]),
                "source_script_name": r[8],
                "summary_bio": bios.get(r[0]),
            }
            for r in rows
        ]

    @app.get("/api/entity/{entity_id}")
    def entity(entity_id: str, lang: str = "en", at_verse: str | None = None) -> dict[str, Any]:
        engine = holder.get()
        dossier = engine.get_entity_dossier(entity_id, lang, at_verse=at_verse)
        registry = load_registry(inputs_root(paths.corpus, paths.inputs))
        mentions: list[dict] = []
        if registry and dossier.tipnr_id:
            seed = next((s for s in registry.entities if s.tipnr_id == dossier.tipnr_id), None)
            if seed:
                mentions = [m.model_dump() for m in seed.mentions]
        return {"dossier": dossier.model_dump(mode="json"), "mentions": mentions}

    @app.get("/api/systems")
    def systems(lang: str = "en") -> list[dict[str, Any]]:
        return [c.model_dump(mode="json") for c in holder.get().list_systems(lang)]

    @app.get("/api/search")
    def search(
        q: str,
        lang: str = "en",
        scope: Literal["verses", "entities", "systems", "events", "all"] = "all",
        top_k: int = 20,
        mode: Literal["hybrid", "keyword", "meaning"] = "hybrid",
    ) -> list[dict[str, Any]]:
        hits = holder.get().semantic_search(q, lang, scope, top_k, mode)
        return [h.model_dump() for h in hits]

    @app.get("/api/similar/{kind}/{item_id}")
    def similar(
        kind: Literal["verse", "entity", "system", "event"],
        item_id: str,
        lang: str = "en",
        scope: Literal["verses", "entities", "systems", "events", "all"] | None = None,
        top_k: int = 12,
        same_type: bool = False,
    ) -> list[dict[str, Any]]:
        hits = holder.get().find_similar(kind, item_id, lang, scope, top_k, same_type)
        return [h.model_dump() for h in hits]

    # --- SQL console --------------------------------------------------------------------------

    @app.get("/api/sql/schema")
    def sql_schema() -> list[dict[str, Any]]:
        conn = holder.console(guarded=False)
        try:
            out = []
            for schema in ["main", *[f"lang_{x}" for x in discover_langs(paths.bundles)]]:
                for (table,) in conn.execute(
                    f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%search_%'"
                    # vec0 tables need sqlite-vec, which the console does not load
                    " AND name NOT LIKE '%vectors%' ORDER BY name"
                ):
                    cols = [c[1] for c in conn.execute(f"PRAGMA {schema}.table_info({table})")]
                    out.append({"schema": schema, "table": table, "columns": cols})
            return out
        finally:
            conn.close()

    @app.post("/api/sql")
    def sql(req: SqlRequest) -> dict[str, Any]:
        query = req.query
        conn = holder.console()
        deadline = time.monotonic() + SQL_TIME_LIMIT_S
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        started = time.monotonic()
        try:
            cur = conn.execute(query)
            rows = cur.fetchmany(SQL_ROW_LIMIT + 1)
            columns = [d[0] for d in cur.description or []]
        except sqlite3.Error as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}") from e
        finally:
            conn.close()
        return {
            "columns": columns,
            "rows": [list(r) for r in rows[:SQL_ROW_LIMIT]],
            "truncated": len(rows) > SQL_ROW_LIMIT,
            "ms": round((time.monotonic() - started) * 1000, 1),
        }

    @app.middleware("http")
    async def no_stale_pages(request: Request, call_next):
        """Hashed assets may be cached; the HTML that names them must not be."""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # --- learning -------------------------------------------------------------------------------

    def facts(chapter: str, lang: str) -> Facts:
        engine = holder.get()
        k = (id(engine), chapter, lang)
        cached = facts_cache.get(k)
        # Rebuilt when the language's interface translations change, too.
        if cached is None or cached.t is not translators(lang):
            if len(facts_cache) > 300:
                facts_cache.clear()
            cached = facts_cache[k] = chapter_facts(engine, chapter, lang, translators)
        return cached

    @app.get("/api/learn/overview")
    def learn_overview(lang: str = "en") -> dict[str, Any]:
        rows, counts = [], {}
        for book in toc(lang):
            for c in book["chapters"]:
                f = facts(c["ref"], lang)
                counts[c["ref"]] = facts_count(f)
                rows.append(
                    {
                        "chapter": c["ref"],
                        "book": book["name"],
                        "verses": c["verses"],
                        "translated": c["translated"],
                        "events": len(f.events),
                    }
                )
        progress = learner.progress(counts)
        return {
            "chapters": [r | progress.get(r["chapter"], {}) for r in rows],
            "families": FAMILIES,
            "pass_mark": PASS_MARK,
            "exam_size": EXAM_SIZE,
            "known_days": KNOWN_DAYS,
        }

    @app.get("/api/learn/session")
    def learn_session(
        chapter: str,
        mode: Literal["practice", "exam"] = "practice",
        families: str = ",".join(FAMILIES),
        n: int = 10,
        lang: str = "en",
    ) -> dict[str, Any]:
        chosen = tuple(x for x in families.split(",") if x in FAMILIES) or tuple(FAMILIES)
        made = session(facts(chapter, lang), learner, mode=mode, families=chosen, n=n)
        exam_id = learner.start_exam(chapter, len(made)) if mode == "exam" and made else None
        return {"exam_id": exam_id, "questions": [q.model_dump() for q, _ in made]}

    @app.post("/api/learn/answer")
    def learn_answer(req: AnswerRequest) -> dict[str, Any]:
        kind, chapter, subject, seed = parse_id(req.question_id)
        f = facts(chapter, req.lang)
        made = make(f, kind, subject, seed)
        if made is None:
            raise HTTPException(410, f.t("quiz.error.gone"))
        q, key = made
        try:
            judged = judge(q, key, req.response, f.t)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f.t("quiz.error.unreadable_answer", error=e)) from e
        card = learner.record(
            question_id=q.id,
            kind=q.kind,
            chapter=chapter,
            item=q.item,
            correct=judged.correct,
            score=judged.score,
            mode=req.mode,
            exam_id=req.exam_id,
            ms=req.ms,
        )
        return judged.model_dump() | {"card": card}

    @app.post("/api/learn/exam/{exam_id}/finish")
    def learn_finish(exam_id: int) -> dict[str, Any]:
        try:
            return learner.finish_exam(exam_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/api/learn/retell")
    def learn_retell(req: RetellRequest) -> dict[str, Any]:
        f = facts(req.chapter, req.lang)
        if not f.events:
            raise HTTPException(409, f.t("quiz.error.no_events", chapter=req.chapter))
        try:
            result = grade(f, req.text, run=grader, lang=req.lang)
        except RetellError as e:
            raise HTTPException(422, str(e)) from e
        learner.record_retell(req.chapter, req.text, result.model_dump())
        return result.model_dump() | {"titles": {e.event_id: e.title for e in f.events}}

    # --- autonomous runs ------------------------------------------------------------------------

    def run_view(state: RunState, full: bool) -> dict[str, Any]:
        live = state.status in ("running", "waiting") and alive(state.pid)
        view = state.model_dump(exclude={"steps", "log"} if not full else set())
        view |= {
            "status": state.status
            if live or state.status not in ("running", "waiting")
            else "interrupted",
            "totals": state.totals,
            "running": [s.model_dump() for s in state.steps if s.status == "running" and live],
        }
        if full:
            wanted = {c.chapter for c in state.chapters}
            view["escalated"] = [
                {"key": k, "chapter": led.chapter_ref, "note": item.history[-1].note}
                for led, k, item in ledger_items()
                if led.chapter_ref in wanted and is_escalated(item)
            ]
            view["steps"] = [s.model_dump() for s in state.steps[-120:]]
        return view

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [run_view(r, full=False) for r in list_runs(paths)]

    @app.get("/api/run/{name}")
    def run(name: str) -> dict[str, Any]:
        state = load_state(paths, name)
        if state is None:
            raise HTTPException(404, f"no run {name!r}")
        return run_view(state, full=True)

    @app.get("/codex", include_in_schema=False)
    def codex_redirect() -> RedirectResponse:
        return RedirectResponse("/codex.html")

    if static_dir and static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="app")
    return app
