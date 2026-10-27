"""Review cards: one per ledger item, carrying everything needed to judge it at a glance."""

from __future__ import annotations

from typing import Any

from urim.canon import parse_ref
from urim.runtime.engine import NotFoundError, UrimEngine
from urim.workbench.ledger import ChapterLedger, LedgerItem

KIND_ORDER = [
    "event",
    "causal",
    "event_links",
    "entity",
    "system",
    "component",
    "closure",
    "instance",
    "edge",
    "verse.en",
]
MAX_VERSES = 8


def _dump(model) -> Any:
    return model.model_dump(mode="json") if model is not None else None


def _kjv(engine: UrimEngine, verse_start: str, verse_end: str, lang: str) -> list[dict]:
    ids = engine.verse_range(verse_start, verse_end)
    out = []
    for vid in ids[:MAX_VERSES]:
        m = engine.get_verse_matrix(vid, lang=lang, include_ecs=False)
        out.append(
            {"verse_id": vid, "text": m.traditional_baseline, "translation": m.baseline_translation}
        )
    return out


def payload(engine: UrimEngine, kind: str, item_id: str, lang: str) -> tuple[str, Any]:
    """(title, payload) for one item; raises NotFoundError if the bundles lack it."""
    match kind:
        case "event":
            ev = engine.get_event(item_id, lang)
            chain = engine.trace_causal_chain(item_id, "both", 1, lang)
            return ev.title or item_id, {
                "event": _dump(ev),
                "causes": [_dump(x) for x in chain.links if x.effect_event_id == item_id],
                "effects": [_dump(x) for x in chain.links if x.cause_event_id == item_id],
                "neighbours": {n.event_id: n.title for n in chain.nodes},
                "verses": _kjv(engine, ev.verse_start, ev.verse_end, lang),
            }
        case "event_links":
            ev = engine.get_event(item_id, lang)
            return f"Cast of: {ev.title or item_id}", {
                "event": _dump(ev),
                "participants": [
                    {"entity": _dump(ref), "role": role}
                    for ref, role in engine.event_participants(item_id, lang)
                ],
                "verses": _kjv(engine, ev.verse_start, ev.verse_end, lang),
            }
        case "causal":
            link = engine.get_causal_link(item_id, lang)
            cause = engine.get_event(link.cause_event_id, lang)
            effect = engine.get_event(link.effect_event_id, lang)
            return f"{cause.title} → {effect.title}", {
                "link": _dump(link),
                "cause": _dump(cause),
                "effect": _dump(effect),
            }
        case "entity":
            d = engine.get_entity_dossier(item_id, lang)
            return d.canonical_name or item_id, {"dossier": _dump(d)}
        case "system":
            c = engine.get_system_codex(item_id, lang)
            return c.name or item_id, {"codex": _dump(c)}
        case "component" | "closure":
            comp = engine.get_component(item_id, lang)
            who = engine.get_entity_dossier(comp.entity_id, lang)
            label = f"{comp.label_key}: {comp.label_value}" if comp.label_key else item_id
            return f"{who.canonical_name} · {label}", {
                "component": _dump(comp),
                "entity_name": who.canonical_name,
            }
        case "instance":
            inst = engine.get_instance(item_id, lang)
            return inst.system_name or item_id, {"instance": _dump(inst)}
        case "edge":
            edge = engine.get_edge(item_id, lang)
            label = edge.interaction_label or edge.interaction_type
            return f"{edge.source.name} {label} {edge.target.name}", {"edge": _dump(edge)}
        case "verse.en":
            m = engine.get_verse_matrix(item_id, lang=lang, include_ecs=False)
            return item_id, {"verse": _dump(m)}
    raise NotFoundError(f"no card for kind {kind!r}")


def card(
    engine: UrimEngine, ledger: ChapterLedger, item_key: str, item: LedgerItem, lang: str = "en"
) -> dict[str, Any]:
    kind, item_id = item_key.split(":", 1)
    try:
        title, data = payload(engine, kind, item_id, lang)
        missing = False
    except NotFoundError:
        title, data, missing = item_id, None, True
    return {
        "key": item_key,
        "kind": kind,
        "id": item_id,
        "chapter": ledger.chapter_ref,
        "status": item.status,
        "produced_by": item.produced_by.model_dump(),
        "produced_at": item.produced_at,
        "agent_notes": item.agent_notes,
        "history": [h.model_dump() for h in item.history],
        "title": title,
        "missing": missing,
        "payload": data,
    }


def anchor_verse(c: dict[str, Any]) -> str | None:
    """The verse a card is about, for ordering the deck in reading order."""
    p = c["payload"] or {}
    match c["kind"]:
        case "event" | "event_links":
            return p["event"]["verse_start"]
        case "causal":
            return p["effect"]["verse_start"]
        case "entity":
            return p["dossier"]["first_mention_verse"]
        case "system":
            return p["codex"]["first_occurrence_verse"]
        case "component" | "closure":
            return p["component"]["acquired_at_verse"]
        case "instance":
            return p["instance"]["verse_start"]
        case "edge":
            return p["edge"]["verse_id"]
        case "verse.en":
            return c["id"]
    return None


def deck_order(c: dict[str, Any], chapter_ordinal: int) -> tuple:
    kind = c["kind"]
    order = KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)
    verse = anchor_verse(c) if not c["missing"] else None
    return (chapter_ordinal, order, parse_ref(verse)[1].ordinal if verse else 0, c["id"])
