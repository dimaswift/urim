"""Split the hand-written gold IR into the fragments a session would hand back."""

from pathlib import Path

from urim.ir.load import read_model
from urim.ir.models import CoreChapterIR, I18nChapterIR
from urim.workbench.fragments import (
    ChronologyFragment,
    EventLocation,
    OntologyFragment,
    ParticipantRow,
    PhilologyFragment,
    Provenance,
)

GOLD = Path(__file__).resolve().parent.parent.parent / "fixtures" / "ir"
BY = Provenance(model="gold", skill="hand-written@0")


def _load(chapter: str) -> tuple[CoreChapterIR, I18nChapterIR]:
    core = read_model(GOLD / "core" / f"{chapter}.json", CoreChapterIR)
    en_path = GOLD / "i18n" / "en" / f"{chapter}.json"
    en = (
        read_model(en_path, I18nChapterIR)
        if en_path.exists()
        else I18nChapterIR(chapter_ref=chapter)
    )
    return core, en


def chronology(chapter: str) -> ChronologyFragment:
    core, en = _load(chapter)
    events = [
        e.model_copy(update={"participants": [], "location_entity_id": None}) for e in core.events
    ]
    return ChronologyFragment(
        agent="chronology",
        chapter_ref=chapter,
        produced_by=BY,
        events=events,
        causal_edges=core.causal_edges,
        event_texts=en.events,
        causal_texts=en.causal_edges,
    )


def ontology(chapter: str) -> OntologyFragment:
    core, en = _load(chapter)
    return OntologyFragment(
        agent="ontology",
        chapter_ref=chapter,
        produced_by=BY,
        entities=core.entities,
        systems=core.systems,
        components=core.components,
        component_closures=core.component_closures,
        system_instances=core.system_instances,
        edges=core.edges,
        participants=[
            ParticipantRow(event_id=e.event_id, entity_id=p.entity_id, role=p.role)
            for e in core.events
            for p in e.participants
        ],
        event_locations=[
            EventLocation(event_id=e.event_id, location_entity_id=e.location_entity_id)
            for e in core.events
            if e.location_entity_id
        ],
        entity_texts=en.entities,
        system_texts=en.systems,
        component_texts=en.components,
        instance_texts=en.system_instances,
        edge_texts=en.edges,
    )


def philology(chapter: str) -> PhilologyFragment:
    _, en = _load(chapter)
    return PhilologyFragment(
        agent="philology", chapter_ref=chapter, produced_by=BY, verses=en.verses
    )
