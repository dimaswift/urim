"""FastAPI adapter over UrimEngine. Every route is a thin wrapper around one engine call."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from urim import __version__
from urim.runtime.engine import (
    BundleMismatch,
    LanguageNotAvailable,
    NotFoundError,
    UrimEngine,
)
from urim.runtime.models import (
    CausalGraph,
    ChapterStream,
    EntityDossier,
    LanguageInfo,
    SearchHit,
    SystemCodex,
    Timeline,
    VerseMatrix,
)

Lang = Annotated[str, Query(description="ISO 639-1 language bundle, e.g. en, ru")]


def create_app(bundles_dir: str | Path) -> FastAPI:
    engine = UrimEngine(bundles_dir)
    app = FastAPI(
        title="URIM",
        version=__version__,
        description="Unified Relational Interpretive Matrix: read-only query API",
    )

    @app.exception_handler(NotFoundError)
    def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(LanguageNotAvailable)
    def _no_lang(_: Request, exc: LanguageNotAvailable) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(BundleMismatch)
    def _mismatch(_: Request, exc: BundleMismatch) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/languages")
    def languages() -> list[LanguageInfo]:
        return engine.languages()

    @app.get("/verses/{ref}")
    def verse(ref: str, lang: Lang = "en", include_ecs: bool = True) -> VerseMatrix:
        return engine.get_verse_matrix(ref, lang=lang, include_ecs=include_ecs)

    @app.get("/chapters/{book_code}/{chapter}")
    def chapter(
        book_code: str, chapter: int, lang: Lang = "en", include_ecs: bool = False
    ) -> ChapterStream:
        return engine.get_chapter_stream(book_code, chapter, lang=lang, include_ecs=include_ecs)

    @app.get("/entities/{entity_id}")
    def entity(
        entity_id: str, lang: Lang = "en", at_utes: int | None = None, at_verse: str | None = None
    ) -> EntityDossier:
        return engine.get_entity_dossier(entity_id, lang=lang, at_utes=at_utes, at_verse=at_verse)

    @app.get("/systems/{system_id}")
    def system(system_id: str, lang: Lang = "en") -> SystemCodex:
        return engine.get_system_codex(system_id, lang=lang)

    @app.get("/timeline")
    def timeline(
        utes_start: int,
        utes_end: int,
        lang: Lang = "en",
        entity: Annotated[list[str] | None, Query()] = None,
    ) -> Timeline:
        return engine.query_timeline(utes_start, utes_end, entity_filter=entity, lang=lang)

    @app.get("/events/{event_id}/causal-chain")
    def causal_chain(
        event_id: str,
        lang: Lang = "en",
        direction: Literal["upstream", "downstream", "both"] = "both",
        depth: int = 5,
    ) -> CausalGraph:
        return engine.trace_causal_chain(event_id, direction=direction, depth=depth, lang=lang)

    @app.get("/search")
    def search(
        q: str,
        lang: Lang = "en",
        scope: Literal["verses", "entities", "systems", "events", "all"] = "all",
        top_k: int = 10,
    ) -> list[SearchHit]:
        return engine.semantic_search(q, lang=lang, scope=scope, top_k=top_k)

    return app
