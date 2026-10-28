"""What a session hands back: one fragment per task, owned by exactly one agent.

Ownership keeps sessions from stepping on each other:

    chronology  events (time, verses, hierarchy), causal links, their English text
    ontology    entities, event participants and locations, states and closures, rituals and
                their occurrences, interactions, their English text
    philology   verse layers, notes and word glosses (English)
    localization  everything above in one other language, interface messages, bundle labels

Every reviewable unit has a ledger key `kind:id`, e.g. `event:evt.1kgs_18.carmel_contest`; a
translation's key carries its language: `event.ru:evt.1kgs_18.carmel_contest`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from urim.ir.models import (
    AnchorText,
    BookName,
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
    VocabEntry,
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


class InterfaceMessage(IRModel):
    key: str = Field(description="The message key as the packet lists it, e.g. campaign.sessions")
    text: str | None = Field(
        default=None,
        description="The translation. Keep every {placeholder} of the English, spelled the same",
    )
    forms: dict[str, str] | None = Field(
        default=None,
        description="Instead of text, for messages counted by {count}: one form per plural "
        "category of the language, as the packet names them (Russian: one, few, many, other)",
    )


class BundleTexts(IRModel):
    lang_name: str | None = Field(default=None, description="The language's own name for itself")
    books: list[BookName] = Field(default=[], description="Book names, by the English book_code")
    vocab: list[VocabEntry] = Field(default=[], description="Labels, by the English kind and code")
    anchors: list[AnchorText] = Field(
        default=[], description="Chronology anchors' labels and notes, by anchor_id"
    )


class LocalizationFragment(IRModel):
    agent: Literal["localization"]
    lang: str = Field(
        pattern=r"^[a-z]{2,3}$", description="The language you write, e.g. ru; never en"
    )
    scope: str = Field(
        description="As the packet names it: GEN.38 (a chapter's texts), GEN.38.1-12 (verses), "
        "ui.<namespace> (interface messages), bundle (book names and labels)"
    )
    produced_by: Provenance
    reviewer_notes: list[ReviewerNote] = []
    events: list[EventText] = []
    causal_edges: list[CausalText] = []
    entities: list[EntityText] = []
    components: list[ComponentText] = []
    systems: list[SystemText] = []
    system_instances: list[InstanceText] = []
    edges: list[EdgeText] = []
    verses: list[VerseText] = Field(
        default=[],
        description="Verse layers in the language: literal and dramatic translated from the "
        "Hebrew, commentary and notes from the English, a gloss for every Hebrew word",
    )
    messages: list[InterfaceMessage] = []
    bundle: BundleTexts | None = None

    @property
    def chapter_ref(self) -> str:
        """The chapter a texts or verses scope belongs to; the scope itself otherwise."""
        parts = self.scope.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 and parts[1].isdigit() else self.scope


Fragment = Annotated[
    ChronologyFragment | OntologyFragment | PhilologyFragment | LocalizationFragment,
    Field(discriminator="agent"),
]
FRAGMENT_MODELS: dict[str, type[IRModel]] = {
    "chronology": ChronologyFragment,
    "ontology": OntologyFragment,
    "philology": PhilologyFragment,
    "localization": LocalizationFragment,
}
_adapter: TypeAdapter = TypeAdapter(Fragment)


class FragmentError(ValueError):
    pass


def load_fragment(
    path: Path,
) -> ChronologyFragment | OntologyFragment | PhilologyFragment | LocalizationFragment:
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
    tail = f".{lang}" if agent == "localization" else ""
    for prefix, kind in _PREFIX_KIND.items():
        if item.startswith(prefix):
            if kind == "event" and agent == "ontology":
                kind = "event_links"
            return key(kind + tail, item)
    if re.match(r"^(person|deity|spirit|loc|group|artifact|substance)\.", item):
        return key("entity" + tail, item)
    return None
