"""MCP server exposing the seven URIM operations as tools for AI agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from urim.config import load_paths
from urim.i18n.messages import Messages
from urim.runtime.engine import UrimEngine

INSTRUCTIONS = """\
URIM is a pre-compiled knowledge engine for biblical text. Verse ids use source-text
(Hebrew/Greek) numbering, e.g. "1KGS.18.27"; other numberings are accepted as aliases such as
"KJV:1KGS.18.33". Times are UTES integers: seconds since 1970-01-01 on the proleptic Gregorian
calendar, negative for antiquity, so subtracting two values gives elapsed seconds. Every tool
takes `lang` (default "en"); text missing from a language bundle falls back to English.
"""


def create_server(bundles_dir: str | Path) -> MCPServer:
    engine = UrimEngine(bundles_dir, messages=Messages(load_paths().corpus))
    server = MCPServer(name="urim", instructions=INSTRUCTIONS)

    @server.tool()
    def get_verse_matrix(
        verse_id: str, lang: str = "en", include_ecs: bool = True
    ) -> dict[str, Any]:
        """One verse: source text and morphology, traditional baseline, the literal / dramatic /
        commentary layers, the events covering it, and (with include_ecs) the entities,
        component states, ritual instances and interactions active at that verse."""
        return engine.get_verse_matrix(verse_id, lang, include_ecs).model_dump(mode="json")

    @server.tool()
    def get_chapter_stream(book_code: str, chapter: int, lang: str = "en") -> dict[str, Any]:
        """All verses of a chapter in order, with the chapter's events and causal links."""
        return engine.get_chapter_stream(book_code, chapter, lang).model_dump(mode="json")

    @server.tool()
    def get_entity_dossier(
        entity_id: str, lang: str = "en", at_utes: int | None = None, at_verse: str | None = None
    ) -> dict[str, Any]:
        """Profile of a person, place, group or artifact (e.g. "person.elisha"). Pass at_verse or
        at_utes for a snapshot of its state at that point; otherwise the full state history."""
        return engine.get_entity_dossier(entity_id, lang, at_utes, at_verse).model_dump(mode="json")

    @server.tool()
    def get_system_codex(system_id: str, lang: str = "en") -> dict[str, Any]:
        """A recurring ritual, custom or supernatural mechanic (e.g. "sys.mantle_investiture")
        with its rules and every occurrence in order."""
        return engine.get_system_codex(system_id, lang).model_dump(mode="json")

    @server.tool()
    def query_timeline(
        utes_start: int, utes_end: int, entity_filter: list[str] | None = None, lang: str = "en"
    ) -> dict[str, Any]:
        """Events overlapping [utes_start, utes_end] in time order, with the gap to the previous
        event and each event's causes and effects. Optionally only events involving entities."""
        return engine.query_timeline(utes_start, utes_end, entity_filter, lang).model_dump(
            mode="json"
        )

    @server.tool()
    def trace_causal_chain(
        event_id: str,
        direction: Literal["upstream", "downstream", "both"] = "both",
        depth: int = 5,
        lang: str = "en",
    ) -> dict[str, Any]:
        """Causes and consequences of an event (triggers, prophecy fulfilments, retaliation),
        with elapsed seconds on every link."""
        return engine.trace_causal_chain(event_id, direction, depth, lang).model_dump(mode="json")

    @server.tool()
    def semantic_search(
        query: str,
        lang: str = "en",
        scope: Literal["verses", "entities", "systems", "events", "all"] = "all",
        top_k: int = 10,
        mode: Literal["hybrid", "keyword", "meaning"] = "hybrid",
    ) -> list[dict[str, Any]]:
        """Search verses, entities, systems and events in the given language. `keyword` finds
        names and words, `meaning` finds concepts and paraphrases by embedding similarity
        ("grief over a lost son"), `hybrid` fuses both."""
        hits = engine.semantic_search(query, lang, scope, top_k, mode)
        return [h.model_dump(mode="json") for h in hits]

    @server.tool()
    def find_similar(
        kind: Literal["verse", "entity", "system", "event"],
        item_id: str,
        lang: str = "en",
        scope: Literal["verses", "entities", "systems", "events", "all"] | None = None,
        top_k: int = 10,
        same_type: bool = False,
    ) -> list[dict[str, Any]]:
        """Items nearest in meaning to a verse, entity, system or event, by embedding similarity.
        `scope` defaults to the item's own kind; `same_type` keeps entities of the same type
        (people like a person)."""
        hits = engine.find_similar(kind, item_id, lang, scope, top_k, same_type)
        return [h.model_dump(mode="json") for h in hits]

    return server
