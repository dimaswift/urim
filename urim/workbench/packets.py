"""`urim task`: the work packet a session reads before writing its fragment.

A packet is Markdown, sized for one chat: the verses with everything an agent needs about them,
the slice of the corpus that matters (earlier events, known entities, open states, locked items,
your change requests), and where to write the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from urim.canon import BOOKS_BY_CODE, parse_ref
from urim.compiler.link import Report, build_core
from urim.config import Paths
from urim.ir.load import inputs_root, load_core_corpus, load_registry, load_sources, read_model
from urim.ir.models import (
    CommentaryIR,
    EntitySeed,
    I18nBundleIR,
    SourceBookIR,
    SourceVerse,
)
from urim.runtime.engine import format_utes
from urim.workbench.fragments import key
from urim.workbench.ledger import ChapterLedger, load_ledger
from urim.workbench.merge import CorpusFiles, chapter_of
from urim.workbench.travel import distance_km

PHILOLOGY_WINDOW = 12
_SCOPE = re.compile(r"^([1-3]?[A-Za-z]+)\.(\d+)(?:\.(\d+)(?:-(\d+))?)?$")

# Chronology packets carry the Targum and the commentaries whose heading phrase (the words a
# comment is on) holds a time word: the full commentaries would triple a packet's size.
_HEBREW_MARKS = re.compile("[\u0591-\u05c7]")
_TIME_WORDS = {
    "יום", "ימים", "יומים", "ימי", "יומם", "שנה", "שנת", "שנות", "שנתים", "חדש", "חדשים",
    "חודש", "בוקר", "לילה", "לילות", "ליל", "צהרים", "צהריים", "מנחה", "עת", "זמן", "שעה",
    "מחר", "מחרת", "שבוע", "קץ", "אחרי", "שלישית", "ארבעים", "ערבים", "שחר",
}  # fmt: skip
# Ambiguous without their prefix: שנים is also "two", בקר "cattle", ערב "pleasant".
_TIME_EXACT = {"בבקר", "לבקר", "בבוקר", "בערב", "לערב", "ערב"}
_HEBREW_PREFIXES = set("והבכלמש")


class TaskError(ValueError):
    pass


@dataclass
class Packet:
    agent: str
    scope: str
    chapter_ref: str
    text: str
    packet_path: Path
    fragment_path: Path
    warnings: list[str] = field(default_factory=list)


def parse_task_scope(scope: str) -> tuple[str, int | None, int | None]:
    """'1KGS.18' -> ('1KGS.18', None, None); '1KGS.18.1-12' -> ('1KGS.18', 1, 12)."""
    m = _SCOPE.match(scope.strip())
    if not m or m[1].upper() not in BOOKS_BY_CODE:
        raise TaskError(f"bad scope {scope!r}; expected e.g. 1KGS.18 or 1KGS.18.1-12")
    chapter = f"{m[1].upper()}.{int(m[2])}"
    if m[3] is None:
        return chapter, None, None
    lo, hi = int(m[3]), int(m[4] or m[3])
    if hi < lo:
        raise TaskError(f"bad verse range in {scope!r}")
    return chapter, lo, hi


# --- context ----------------------------------------------------------------------------------


class Context:
    def __init__(self, paths: Paths, chapter: str):
        self.paths = paths
        self.chapter = chapter
        self.book = chapter.split(".")[0]
        root = inputs_root(paths.corpus, paths.inputs)
        book = next((b for b in load_sources(root) if b.book_code == self.book), None)
        if book is None or not any(chapter_of(v.verse_id) == chapter for v in book.verses):
            raise TaskError(f"{chapter} is not ingested yet: run `urim ingest {chapter}`")
        self.source: SourceBookIR = book
        self.verses = [v for v in book.verses if chapter_of(v.verse_id) == chapter]
        registry = load_registry(root)
        self.seeds: list[EntitySeed] = registry.entities if registry else []
        commentary_path = root / "commentary" / f"{self.book}.json"
        self.commentary = (
            read_model(commentary_path, CommentaryIR) if commentary_path.exists() else None
        )
        self.files = CorpusFiles(paths.corpus)
        self.ledger: ChapterLedger = load_ledger(paths.corpus, chapter)
        bundle_path = paths.corpus / "i18n" / "en" / "_bundle.json"
        self.bundle = read_model(bundle_path, I18nBundleIR) if bundle_path.exists() else None
        self.times = self._event_times()

    def _event_times(self) -> dict[str, tuple[int, int, str]]:
        try:
            corpus = load_core_corpus(self.paths.corpus, self.paths.inputs)
        except Exception:
            return {}
        report = Report()
        tables = build_core(corpus, corpus.chronology.default_scheme, report)
        if not tables:
            return {}
        cols, rows = tables["core_events"]
        i = {c: n for n, c in enumerate(cols)}
        return {
            r[i["event_id"]]: (r[i["utes_start"]], r[i["utes_end"]], r[i["precision_tier"]])
            for r in rows
        }

    def when(self, event_id: str) -> str:
        t = self.times.get(event_id)
        return format_utes(t[0], t[2]) if t else "?"

    def seeds_in(self, verse_ids: set[str]) -> list[EntitySeed]:
        return [s for s in self.seeds if any(m.verse_id in verse_ids for m in s.mentions)]

    def corpus_entities(self) -> dict[str, tuple[str, str, str | None]]:
        """entity_id -> (type, home chapter, tipnr_id) for the whole corpus."""
        out = {}
        for ch in self.files.chapters():
            for e in self.files.core(ch).entities:
                out[e.entity_id] = (e.entity_type, ch, e.tipnr_id)
        return out

    def requests(self, keys: set[str] | None = None) -> list[str]:
        out = []
        for k, item in self.ledger.items.items():
            if item.status == "changes_requested" and (keys is None or k in keys):
                out.append(f"- `{k}`: {item.last_note}")
        return out

    def status(self, item_key: str) -> str:
        s = self.ledger.status(item_key)
        return {
            "approved": "LOCKED (approved)",
            "changes_requested": "changes requested",
            "draft": "draft",
            None: "new",
        }[s]


def _kjv_refs(src: SourceBookIR, verse_id: str) -> list[str]:
    refs = [r.scheme_ref for r in src.verse_map if r.scheme == "KJV" and r.verse_id == verse_id]
    return refs or [verse_id]


def _short(ref: str) -> str:
    _, r = parse_ref(ref)
    return f"{r.chapter}:{r.verse}"


def _interlinear(v: SourceVerse) -> str:
    glosses = v.glosses.get("en", [])
    parts = []
    for t, g in zip(v.tokens, glosses, strict=False):
        name = f"[{t.name_ref}]" if t.name_ref else ""
        parts.append(f"{t.surface}={g}{name}")
    return " · ".join(parts)


def _baselines(src: SourceBookIR, verse_id: str, names: tuple[str, ...]) -> list[str]:
    lines = []
    for name in names:
        texts = src.baselines.get(name, {})
        refs = _kjv_refs(src, verse_id) if name != "RusSynodal" else [verse_id]
        text = " ".join(texts[r] for r in refs if r in texts)
        if text:
            label = name if refs == [verse_id] else f"{name} ({', '.join(map(_short, refs))})"
            lines.append(f"{label}: {text}")
    return lines


def _seed_line(s: EntitySeed, verse_ids: set[str], known: dict[str, str]) -> str:
    mentions = ", ".join(
        f"{_short(m.verse_id)}#{m.pos}" for m in s.mentions if m.verse_id in verse_ids
    )
    defined = f" — already defined as `{known[s.tipnr_id]}`" if s.tipnr_id in known else ""
    names = " / ".join(s.names[:3])
    brief = f" — {s.brief}" if s.brief else ""
    return (
        f"- `{s.tipnr_id}` → proposed `{s.proposed_entity_id}` ({s.tipnr_type}): {names}"
        f"{brief}; mentions {mentions}{defined}"
    )


# --- sections ---------------------------------------------------------------------------------


def display_path(path: Path) -> str:
    """Relative to the working directory when inside it, so commands stay short."""
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _header(agent: str, scope: str, fragment_path: Path, ctx: Context) -> list[str]:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    fragment = display_path(fragment_path)
    return [
        f"# URIM task: {agent} {scope}",
        "",
        f"- Write the fragment to `{fragment}`, then run `urim ir merge {fragment}`.",
        f"- Schema: `urim schema {agent}`. Set `chapter_ref` to `{ctx.chapter}` and fill "
        "`produced_by` with your model id and skill version.",
        "- Put doubts and judgment calls in `reviewer_notes`; the reviewer sees them next to "
        "each item.",
        f"- Generated {stamp}.",
        "",
    ]


def _is_time_comment(comment: str) -> bool:
    plain = _HEBREW_MARKS.sub("", comment)
    heading = plain.split(".", 1)[0]
    if len(heading) > 60:  # no period after the heading phrase (Malbim): its first words
        heading = " ".join(plain.split()[:3])
    for word in re.findall("[\u05d0-\u05ea]+", heading):
        if word in _TIME_EXACT:
            return True
        stems = [word]
        if len(word) > 2 and word[0] in _HEBREW_PREFIXES:
            stems.append(word[1:])
            if len(word) > 3 and word[1] in _HEBREW_PREFIXES:
                stems.append(word[2:])
        if _TIME_WORDS.intersection(stems):
            return True
    return False


def _time_comments(ctx: Context, verse_id: str) -> list[str]:
    if not ctx.commentary:
        return []
    return [
        f"{name}: {c}"
        for name, work in ctx.commentary.works.items()
        for c in work.verses.get(verse_id, [])
        if name.startswith("Targum") or _is_time_comment(c)
    ]


def _narrative_verses(
    ctx: Context, verses: list[SourceVerse], commentary: bool = False
) -> list[str]:
    out = ["## Text", ""]
    if commentary and ctx.commentary:
        out += [
            "Under each verse: the Targum, and the classical commentaries on a phrase with a "
            "time word (day, year, morning, the hour of the offering, …). They often say how "
            "the tradition counted a vague span.",
            "",
        ]
    for v in verses:
        refs = _kjv_refs(ctx.source, v.verse_id)
        alias = "" if refs == [v.verse_id] else f" (KJV {', '.join(map(_short, refs))})"
        out += [f"### {v.verse_id}{alias}", f"HE  {v.source_text}", f"WD  {_interlinear(v)}"]
        out += _baselines(ctx.source, v.verse_id, ("KJV", "YLT"))
        if commentary:
            out += _time_comments(ctx, v.verse_id)
        out.append("")
    return out


def _chronology(ctx: Context) -> list[str]:
    out = []
    scheme = None
    try:
        chronology = load_core_corpus(ctx.paths.corpus, ctx.paths.inputs).chronology
        scheme = chronology.default_scheme
        labels = {a.anchor_id: a.label for a in (ctx.bundle.anchors if ctx.bundle else [])}
        out += [f"## Chronology anchors ({scheme})", ""]
        for a in chronology.schemes[scheme]:
            d = a.date
            out.append(
                f"- `{a.anchor_id}`: {labels.get(a.anchor_id, '')} — {d.year} {d.era}-"
                f"{d.month:02d}-{d.day:02d} ± {a.margin.value:g} {a.margin.unit} "
                f"({a.precision_tier}). Basis: {a.basis}"
            )
        out.append("")
    except Exception as e:  # noqa: BLE001 - shown to the session as context, not fatal
        out += [f"(chronology anchors unavailable: {e})", ""]

    this_order = parse_ref(f"{ctx.chapter}.1")[1].ordinal
    earlier = []
    for ch in ctx.files.chapters():
        if ch == ctx.chapter or parse_ref(f"{ch}.1")[1].ordinal > this_order:
            continue
        en = {t.event_id: t for t in ctx.files.i18n("en", ch).events}
        for e in ctx.files.core(ch).events:
            earlier.append((ctx.times.get(e.event_id, (0,))[0], e, en.get(e.event_id)))
    earlier.sort(key=lambda x: x[0])
    out += ["## Events already in the corpus before this chapter (latest 15)", ""]
    if not earlier:
        out.append("- none yet: anchor on a chronology anchor")
    for _, e, t in earlier[-15:]:
        title = t.title if t else ""
        out.append(
            f"- `{e.event_id}` {_short(e.verse_start)}–{_short(e.verse_end)}, starts "
            f"{ctx.when(e.event_id)}: {title}"
        )
    out.append("")

    core, en = ctx.files.core(ctx.chapter), ctx.files.i18n("en", ctx.chapter)
    if core.events:
        titles = {t.event_id: t.title for t in en.events}
        out += [
            "## Events already written for this chapter",
            "",
            "Your fragment replaces them, except LOCKED ones (keep those exactly or omit).",
            "",
        ]
        for e in core.events:
            out.append(
                f"- `{e.event_id}` [{ctx.status(key('event', e.event_id))}] "
                f"{_short(e.verse_start)}–{_short(e.verse_end)}: {titles.get(e.event_id)}"
            )
        out.append("")

    ids = {v.verse_id for v in ctx.verses}
    places = [s for s in ctx.seeds_in(ids) if s.tipnr_category == "PLACE" and s.geo]
    if places:
        out += ["## Places named in this chapter (for travel times)", ""]
        for s in places:
            conf = f", confidence {s.geo.confidence:g}" if s.geo.confidence is not None else ""
            out.append(
                f"- {s.names[0]} (`{s.proposed_entity_id}`): {s.geo.lat:.3f}, "
                f"{s.geo.lon:.3f} ({s.geo.source}{conf})"
            )
        if len(places) > 1:
            out += ["", "Straight-line distances (km):", ""]
            for a, b in combinations(places, 2):
                km = distance_km(a.geo.lat, a.geo.lon, b.geo.lat, b.geo.lon)
                out.append(f"- {a.names[0]} – {b.names[0]}: {km:.0f}")
        out += [
            "",
            "Journey times: `uv run urim travel FROM TO [--mode walk|hurry|run|donkey|army|"
            "chariot]` (ids or names; more than two places for a route).",
        ]
        out.append("")
    return out


def _ontology(ctx: Context) -> list[str]:
    core, en = ctx.files.core(ctx.chapter), ctx.files.i18n("en", ctx.chapter)
    out = ["## Events of this chapter", ""]
    if not core.events:
        out += [
            "**No events yet.** Run the chronology task for this chapter first: participants "
            "and locations attach to its events.",
            "",
        ]
    titles = {t.event_id: t.title for t in en.events}
    for e in core.events:
        cast = ", ".join(f"{p.entity_id}:{p.role}" for p in e.participants) or "—"
        where = e.location_entity_id or "—"
        out.append(
            f"- `{e.event_id}` {_short(e.verse_start)}–{_short(e.verse_end)} "
            f"({ctx.when(e.event_id)}): {titles.get(e.event_id)} | participants "
            f"[{ctx.status(key('event_links', e.event_id))}]: {cast} | place: {where}"
        )
    out.append("")

    known = ctx.corpus_entities()
    by_tipnr = {tipnr: eid for eid, (_, _, tipnr) in known.items() if tipnr}
    ids = {v.verse_id for v in ctx.verses}
    out += [
        "## Registry: individuals named in this chapter (STEPBible TIPNR)",
        "",
        "Mentions are `chapter:verse#word`. Use the proposed id unless there is a reason "
        "not to, and always set `tipnr_id`. Note that STEPBible tags the nation Israel "
        "with the patriarch's id.",
        "",
    ]
    out += [_seed_line(s, ids, by_tipnr) for s in ctx.seeds_in(ids)] or ["- none"]
    out.append("")

    book_entities = {k: v for k, v in known.items() if v[1].startswith(ctx.book + ".")}
    out += ["## Entities already in the corpus (this book)", ""]
    out += [
        f"- `{eid}` {etype}, defined in {home}" + (f", tipnr {tipnr}" if tipnr else "")
        for eid, (etype, home, tipnr) in sorted(book_entities.items())
    ] or ["- none yet"]
    out.append("")

    open_states = []
    for ch in ctx.files.chapters():
        closed = {
            c.component_id
            for x in ctx.files.chapters()
            for c in ctx.files.core(x).component_closures
        }
        for c in ctx.files.core(ch).components:
            if c.expired_at_verse is None and c.component_id not in closed:
                open_states.append(c)
    out += ["## Open states (not yet closed)", ""]
    out += [
        f"- `{c.component_id}` {c.entity_id}.{c.component_key} = "
        f"{c.value_code or c.target_entity_id} since {c.acquired_at_verse}"
        for c in open_states
    ] or ["- none"]
    out.append("")

    out += ["## Systems catalog (rituals, customs, supernatural acts)", ""]
    systems = []
    for ch in ctx.files.chapters():
        names = {t.system_id: t.name for t in ctx.files.i18n("en", ch).systems}
        systems += [
            f"- `{s.system_id}` {s.category}: {names.get(s.system_id, '')} (defined in {ch})"
            for s in ctx.files.core(ch).systems
        ]
    out += systems or ["- none yet"]
    out.append("")

    existing = (
        [("entity", e.entity_id) for e in core.entities]
        + [("system", s.system_id) for s in core.systems]
        + [("component", c.component_id) for c in core.components]
        + [("closure", c.component_id) for c in core.component_closures]
        + [("instance", i.instance_id) for i in core.system_instances]
        + [("edge", e.edge_id) for e in core.edges]
    )
    if existing:
        out += [
            "## Ontology items already written for this chapter",
            "",
            "Your fragment replaces them, except LOCKED ones (keep those exactly or omit).",
            "",
        ]
        out += [f"- `{key(k, i)}` [{ctx.status(key(k, i))}]" for k, i in existing]
        out.append("")
    return out


def _philology(ctx: Context, verses: list[SourceVerse]) -> list[str]:
    ids = {v.verse_id for v in verses}
    out = ["## Verses", ""]
    for v in verses:
        refs = _kjv_refs(ctx.source, v.verse_id)
        alias = "" if refs == [v.verse_id] else f" (KJV {', '.join(map(_short, refs))})"
        out += [
            f"### {v.verse_id}{alias} [{ctx.status(key('verse.en', v.verse_id))}]",
            "",
            f"Hebrew: {v.source_text}",
            "",
            "| # | word | translit | lemma | strongs | morph | STEPBible gloss | name |",
            "|---|---|---|---|---|---|---|---|",
        ]
        glosses = v.glosses.get("en", [])
        for t in v.tokens:
            g = glosses[t.pos - 1] if t.pos <= len(glosses) else ""
            reading = f" ({t.reading})" if t.reading else ""
            out.append(
                f"| {t.pos} | {t.surface}{reading} | {t.translit or ''} | "
                f"{t.lemma or ''} | {t.strongs or ''} | {t.morph or ''} | {g} | "
                f"{t.name_ref or ''} |"
            )
        out.append("")
        out += _baselines(ctx.source, v.verse_id, ("KJV", "YLT", "ASV", "BBE", "Webster"))
        for note in ctx.source.versification_notes.get(v.verse_id, []):
            out.append(f"Versification: {note}")
        if ctx.commentary:
            comments = [
                (w, c)
                for w, work in ctx.commentary.works.items()
                for c in work.verses.get(v.verse_id, [])
            ]
            if comments:
                out += ["", "Commentaries:"]
                out += [f"- {w}: {c}" for w, c in comments]
        out.append("")

    seeds = ctx.seeds_in(ids)
    if seeds:
        out += ["## Names in these verses", ""]
        out += [f"- {s.names[0]} (`{s.tipnr_id}`): {s.brief or s.description or ''}" for s in seeds]
        out.append("")
    core, en = ctx.files.core(ctx.chapter), ctx.files.i18n("en", ctx.chapter)
    titles = {t.event_id: t.title for t in en.events}
    first, last = (
        min(ids, key=lambda i: parse_ref(i)[1].ordinal),
        max(ids, key=lambda i: parse_ref(i)[1].ordinal),
    )
    covering = [
        e
        for e in core.events
        if parse_ref(e.verse_start)[1].ordinal <= parse_ref(last)[1].ordinal
        and parse_ref(e.verse_end)[1].ordinal >= parse_ref(first)[1].ordinal
    ]
    if covering:
        out += ["## Events these verses belong to", ""]
        out += [
            f"- {_short(e.verse_start)}–{_short(e.verse_end)}: {titles.get(e.event_id)} "
            f"({ctx.when(e.event_id)})"
            for e in covering
        ]
        out.append("")
    before = [
        v
        for v in ctx.files.i18n("en", ctx.chapter).verses
        if parse_ref(v.verse_id)[1].ordinal == parse_ref(first)[1].ordinal - 1
    ]
    if before:
        out += [
            f"## The verse before ({before[0].verse_id}), for continuity of voice",
            "",
            f"Dramatic: {before[0].translation_dramatic}",
            "",
        ]
    return out


# --- entry point ------------------------------------------------------------------------------


def build_packet(agent: str, scope: str, paths: Paths) -> Packet:
    if agent not in ("chronology", "ontology", "philology"):
        raise TaskError(f"unknown agent {agent!r}; expected chronology, ontology or philology")
    chapter, lo, hi = parse_task_scope(scope)
    ctx = Context(paths, chapter)
    warnings = []
    if agent != "philology" and lo is not None:
        raise TaskError(f"{agent} works on whole chapters: use {chapter}")
    verses = [v for v in ctx.verses if lo is None or lo <= parse_ref(v.verse_id)[1].verse <= hi]
    if not verses:
        raise TaskError(f"no ingested verses in {scope}")
    if agent == "philology" and len(verses) > PHILOLOGY_WINDOW:
        warnings.append(
            f"{len(verses)} verses is a lot for one session; windows of about "
            f"{PHILOLOGY_WINDOW} keep quality up"
        )
    label = scope if lo is None else f"{chapter}.{lo}-{hi}"
    fragment_path = paths.work / agent / f"{label}.fragment.json"
    packet_path = paths.work / agent / f"{label}.md"

    lines = _header(agent, label, fragment_path, ctx)
    request_keys = None
    if agent == "philology":
        request_keys = {key("verse.en", v.verse_id) for v in verses}
    requests = ctx.requests(request_keys)
    if requests:
        lines += ["## Reviewer requests (address these first)", "", *requests, ""]
    match agent:
        case "chronology":
            lines += _chronology(ctx) + _narrative_verses(ctx, verses, commentary=True)
        case "ontology":
            lines += _ontology(ctx) + _narrative_verses(ctx, verses)
        case "philology":
            lines += _philology(ctx, verses)
    text = "\n".join(lines).rstrip() + "\n"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(text, encoding="utf-8")
    return Packet(agent, label, chapter, text, packet_path, fragment_path, warnings)
