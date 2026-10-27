"""What a session hands back: one fragment per task, owned by exactly one agent.

Ownership keeps sessions from stepping on each other:

    chronology  events (time, verses, hierarchy), causal links, their English text
    ontology    entities, event participants and locations, states and closures, rituals and
                their occurrences, interactions, their English text
    philology   verse layers, notes and word glosses (English)

Every reviewable unit has a ledger key `kind:id`, e.g. `event:evt.1kgs_18.carmel_contest`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from urim.ir.models import (
    CausalEdgeIR,
    CausalText,
    ChapterRef,
    ComponentClosureIR,
    ComponentIR,
    ComponentText,
    EdgeIR,
    EdgeText,
    EntityId,
    EntityIR,
    EntityText,
    EventId,
    EventIR,
    EventText,
    InstanceText,
    IRModel,
    ParticipantRole,
    SystemInstanceIR,
    SystemIR,
    SystemText,
    VerseText,
)

AgentName = Literal["chronology", "ontology", "philology"]


class Provenance(IRModel):
    model: str = Field(description="Model id of the session that wrote this, e.g. claude-opus-5-5")
    skill: str = Field(description="Skill name and version, e.g. urim-chronologist@1")
    run: str = Field(default="main", description="Corpus the work belongs to: main or a run name")


class ReviewerNote(IRModel):
    item: str | None = Field(
        default=None,
        description="Id or ledger key the note is about (evt.…, person.…, 1KGS.18.27); "
        "omit for a note about the whole task",
    )
    note: str = Field(description="Something the reviewer should check: doubts, choices, gaps")


class _Fragment(IRModel):
    chapter_ref: ChapterRef
    produced_by: Provenance
    reviewer_notes: list[ReviewerNote] = []


class ChronologyFragment(_Fragment):
    agent: Literal["chronology"]
    events: list[EventIR] = Field(
        description="Every event of the chapter (verse_start in this chapter). Leave "
        "participants empty and location_entity_id null: the Ontologist sets them."
    )
    causal_edges: list[CausalEdgeIR] = Field(
        default=[], description="Links whose effect event belongs to this chapter"
    )
    event_texts: list[EventText] = Field(description="English text for every event")
    causal_texts: list[CausalText] = Field(default=[], description="English for every link")

    @model_validator(mode="after")
    def _no_entity_links(self) -> ChronologyFragment:
        for e in self.events:
            if e.participants or e.location_entity_id:
                raise ValueError(
                    f"{e.event_id}: participants and location belong to the Ontologist"
                )
        return self


class ParticipantRow(IRModel):
    event_id: EventId
    entity_id: EntityId
    role: ParticipantRole


class EventLocation(IRModel):
    event_id: EventId
    location_entity_id: EntityId


class OntologyFragment(_Fragment):
    agent: Literal["ontology"]
    entities: list[EntityIR] = Field(
        default=[], description="Entities first mentioned in this chapter"
    )
    systems: list[SystemIR] = Field(default=[], description="Systems first seen in this chapter")
    components: list[ComponentIR] = Field(default=[], description="States acquired in this chapter")
    component_closures: list[ComponentClosureIR] = Field(
        default=[], description="States from earlier chapters that end in this chapter"
    )
    system_instances: list[SystemInstanceIR] = []
    edges: list[EdgeIR] = []
    participants: list[ParticipantRow] = Field(
        default=[], description="Who takes part in each event of this chapter"
    )
    event_locations: list[EventLocation] = Field(
        default=[], description="Where each event of this chapter happens, when known"
    )
    entity_texts: list[EntityText] = Field(
        default=[],
        description="English for every new entity; may also update the text of an entity "
        "defined in an earlier chapter",
    )
    system_texts: list[SystemText] = []
    component_texts: list[ComponentText] = []
    instance_texts: list[InstanceText] = []
    edge_texts: list[EdgeText] = []


class PhilologyFragment(_Fragment):
    agent: Literal["philology"]
    verses: list[VerseText] = Field(description="Layers, notes and glosses per verse")


Fragment = Annotated[
    ChronologyFragment | OntologyFragment | PhilologyFragment, Field(discriminator="agent")
]
FRAGMENT_MODELS: dict[str, type[_Fragment]] = {
    "chronology": ChronologyFragment,
    "ontology": OntologyFragment,
    "philology": PhilologyFragment,
}
_adapter: TypeAdapter = TypeAdapter(Fragment)


class FragmentError(ValueError):
    pass


def load_fragment(path: Path) -> ChronologyFragment | OntologyFragment | PhilologyFragment:
    try:
        return _adapter.validate_json(Path(path).read_bytes())
    except ValidationError as e:
        raise FragmentError(f"{path}: {e}") from e


# --- ledger keys ------------------------------------------------------------------------------

_VERSE = re.compile(r"^[1-3]?[A-Z]+\.\d+\.\d+$")
_PREFIX_KIND = {
    "evt.": "event",
    "caus.": "causal",
    "comp.": "component",
    "sys.": "system",
    "inst.": "instance",
    "edge.": "edge",
}


def key(kind: str, item_id: str) -> str:
    return f"{kind}:{item_id}"


def key_for_note(item: str, agent: str, lang: str = "en") -> str | None:
    """Ledger key for a reviewer note's `item`, which may be a key, an id or a verse ref."""
    if ":" in item:
        return item
    if _VERSE.match(item):
        return key(f"verse.{lang}", item)
    for prefix, kind in _PREFIX_KIND.items():
        if item.startswith(prefix):
            if kind == "event" and agent == "ontology":
                kind = "event_links"
            return key(kind, item)
    if re.match(r"^(person|deity|spirit|loc|group|artifact|substance)\.", item):
        return key("entity", item)
    return None
