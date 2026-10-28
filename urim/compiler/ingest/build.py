"""`urim ingest`: sources -> source IR, entity registry and commentary for a scope of chapters.

Everything here is deterministic. Re-ingesting a scope replaces that scope's data and leaves
other chapters already in the IR untouched.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from urim.canon import BOOKS_BY_CODE, TRANSLATION_SCHEMES, Book, parse_ref
from urim.compiler.ingest.fetch import SOURCES, TAHOT_FILES, Fetcher
from urim.compiler.ingest.geo import OpenBibleIndex
from urim.compiler.ingest.sefaria import fetch_chapter, works_for
from urim.compiler.ingest.tahot import TahotWord, build_verses, kjv_verse_map, read_tahot
from urim.compiler.ingest.tipnr import TipnrIndex, TipnrRecord, read_tipnr
from urim.compiler.ingest.tvtms import read_tvtms
from urim.ir.load import write_model
from urim.ir.models import (
    CommentaryIR,
    CommentaryWork,
    EntitySeed,
    GeoPoint,
    Mention,
    RegistryIR,
    SourceBookIR,
)

BASELINES = ("KJV", "YLT", "ASV", "BBE", "Webster", "RusSynodal")
STEPBIBLE_ATTRIBUTION = [
    "Hebrew text, morphology and word glosses: STEPBible TAHOT (Tyndale House Cambridge), "
    "CC BY 4.0, based on the Leningrad Codex",
    "Versification notes: STEPBible TVTMS, CC BY 4.0",
]
REGISTRY_ATTRIBUTION = [
    "Proper names: STEPBible TIPNR (Tyndale House Cambridge), CC BY 4.0",
    "Geocoding: OpenBible.info Bible Geocoding Data, CC BY 4.0",
]
_KIND_BY_TYPE = {
    "Male": "person",
    "Female": "person",
    "Group": "group",
    "Place": "loc",
    "Supernatural": "deity",
}
_PREFERRED_IDS = {"LORD@Gen.1.1-Rev": "deity.yhwh"}
_SCOPE = re.compile(r"^([1-3]?[A-Za-z]+)(?:\.(\d+)(?:-(\d+))?)?$")


class IngestError(RuntimeError):
    pass


@dataclass
class IngestReport:
    scope: str
    verses: int = 0
    tokens: int = 0
    verse_map_rows: int = 0
    baselines: dict[str, int] = field(default_factory=dict)
    commentaries: dict[str, int] = field(default_factory=dict)
    entities: int = 0
    geocoded: int = 0
    warnings: list[str] = field(default_factory=list)


def parse_scope(scope: str) -> tuple[Book, set[int] | None]:
    """'1KGS.17-19' -> (1 Kings, {17, 18, 19}); '1KGS' -> (1 Kings, None = every chapter)."""
    m = _SCOPE.match(scope.strip())
    if not m or m[1].upper() not in BOOKS_BY_CODE:
        raise IngestError(f"bad scope {scope!r}; expected e.g. 1KGS.17-19, 1KGS.18 or 1KGS")
    book = BOOKS_BY_CODE[m[1].upper()]
    if m[2] is None:
        return book, None
    lo, hi = int(m[2]), int(m[3] or m[2])
    if hi < lo:
        raise IngestError(f"bad chapter range in {scope!r}")
    return book, set(range(lo, hi + 1))


def propose_ids(records: list[TipnrRecord]) -> dict[str, str]:
    """Readable, stable entity ids for every TIPNR individual of a known kind.

    The most-referenced bearer of a name gets the bare slug (person.elijah); namesakes get the
    reference from their TIPNR name as a suffix (person.elijah.ezr_10_21).
    """
    groups: dict[str, list[TipnrRecord]] = defaultdict(list)
    for rec in records:
        kind = _KIND_BY_TYPE.get(rec.type or "")
        if kind is None:
            continue
        base = rec.unique_name.split("@")[0].split("|")[-1]
        slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
        if slug:
            groups[f"{kind}.{slug}"].append(rec)
    out: dict[str, str] = {}
    for base_id, recs in groups.items():
        recs.sort(key=lambda r: (-len(r.all_refs), r.unique_name))
        for i, rec in enumerate(recs):
            if i == 0:
                out[rec.unique_name] = base_id
            else:
                first = rec.unique_name.split("@")[1].split("-")[0]
                out[rec.unique_name] = f"{base_id}.{re.sub(r'[^a-z0-9]+', '_', first.lower())}"
    out.update(_PREFERRED_IDS)
    return out


def _display_names(english: str) -> list[str]:
    """TIPNR's 'Abel-meholah =ESV,KJV; Abel Meholah =NIV' or '(Mount )Carmel' -> clean names."""
    names = []
    for piece in english.split(";"):
        for form in piece.split("=")[0].split(","):
            form = re.sub(r"\(([^)]*)\)", r"\1", form).strip()
            if form:
                names.append(form)
    return names


def _is_proper_noun(morph: str) -> bool:
    """ETCBC/OSHB morphology: 'HNpm' or 'HR/Np' -> True; 'HVNp3fs' (a Niphal verb) -> False."""
    segments = morph.split("/")
    segments[0] = segments[0][1:]  # language prefix: H(ebrew) / A(ramaic)
    return any(seg.startswith("Np") for seg in segments)


def _read_scrollmapper(path: Path, book: Book, refs: set[str]) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    chapters = data["books"][book.book_id - 1]["chapters"]
    out = {}
    for ch in chapters:
        for v in ch["verses"]:
            vid = f"{book.code}.{ch['chapter']}.{v['verse']}"
            if vid in refs:
                out[vid] = v["text"].strip()
    return out


def _ordinal(vid: str) -> int:
    return parse_ref(vid)[1].ordinal


def _registry(
    words: list[TahotWord], tipnr: TipnrIndex, geo: OpenBibleIndex, report: IngestReport
) -> list[EntitySeed]:
    ids = propose_ids(tipnr.records)
    mentions: dict[str, list[Mention]] = defaultdict(list)
    found: dict[str, TipnrRecord] = {}
    position: dict[tuple[str, int], int] = {}
    for vid in sorted({w.heb_ref for w in words}, key=_ordinal):
        for i, w in enumerate(
            sorted((w for w in words if w.heb_ref == vid), key=lambda w: w.word_no), start=1
        ):
            position[(vid, w.word_no)] = i
    unresolved: dict[str, int] = defaultdict(int)
    for w in words:
        if w.name_ref is None and not _is_proper_noun(w.morph):
            continue
        rec = tipnr.lookup(w.dstrong, w.name_ref)
        if rec is None:
            unresolved[w.name_ref or w.dstrong or w.hebrew] += 1
            continue
        found[rec.unique_name] = rec
        mentions[rec.unique_name].append(
            Mention(verse_id=w.heb_ref, pos=position[(w.heb_ref, w.word_no)])
        )
    for name, n in sorted(unresolved.items()):
        report.warnings.append(f"registry: {n} mention(s) of {name} have no TIPNR record")

    seeds = []
    for name, rec in sorted(found.items()):
        point = geo.match(rec) if rec.category == "PLACE" else None
        if point is None and rec.google_latlon:
            point = GeoPoint(lat=rec.google_latlon[0], lon=rec.google_latlon[1], source="tipnr")
        if rec.category == "PLACE" and point is None:
            report.warnings.append(f"registry: no coordinates for {name}")
        seeds.append(
            EntitySeed(
                tipnr_id=name,
                proposed_entity_id=ids.get(name),
                tipnr_category=rec.category,
                tipnr_type=rec.type,
                dstrongs=rec.dstrongs,
                names=list(dict.fromkeys(x for n in rec.names for x in _display_names(n.english))),
                source_names=list(dict.fromkeys(n.source_form for n in rec.names if n.source_form)),
                description=rec.description or None,
                brief=rec.brief,
                short=rec.short,
                parents=rec.parents,
                siblings=rec.siblings,
                partners=rec.partners,
                offspring=rec.offspring,
                tribe=rec.tribe,
                mentions=sorted(mentions[name], key=lambda m: (_ordinal(m.verse_id), m.pos)),
                geo=point,
            )
        )
    return seeds


def _merge_source(path: Path, new: SourceBookIR) -> SourceBookIR:
    if not path.exists():
        return new
    old = SourceBookIR.model_validate_json(path.read_bytes())
    fresh = {v.verse_id for v in new.verses}
    fresh_refs = {r.scheme_ref for r in new.verse_map}
    verses = {v.verse_id: v for v in old.verses} | {v.verse_id: v for v in new.verses}
    baselines = {k: dict(v) for k, v in old.baselines.items()}
    for name, texts in new.baselines.items():
        baselines.setdefault(name, {}).update(texts)
    notes = {k: v for k, v in old.versification_notes.items() if k not in fresh}
    return SourceBookIR(
        book_code=new.book_code,
        source_language=new.source_language,
        attribution=sorted(set(old.attribution) | set(new.attribution)),
        verses=sorted(verses.values(), key=lambda v: _ordinal(v.verse_id)),
        verse_map=sorted(
            [r for r in old.verse_map if r.verse_id not in fresh and r.scheme_ref not in fresh_refs]
            + new.verse_map,
            key=lambda r: (r.scheme, _ordinal(r.scheme_ref), _ordinal(r.verse_id)),
        ),
        baselines=baselines,
        versification_notes=dict(
            sorted((notes | new.versification_notes).items(), key=lambda kv: _ordinal(kv[0]))
        ),
    )


def _merge_registry(path: Path, new: RegistryIR, fresh_verses: set[str]) -> RegistryIR:
    if not path.exists():
        return new
    old = {e.tipnr_id: e for e in RegistryIR.model_validate_json(path.read_bytes()).entities}
    merged = dict(old)
    for seed in new.entities:
        kept = (
            [m for m in old[seed.tipnr_id].mentions if m.verse_id not in fresh_verses]
            if seed.tipnr_id in old
            else []
        )
        merged[seed.tipnr_id] = seed.model_copy(
            update={
                "mentions": sorted(
                    kept + seed.mentions, key=lambda m: (_ordinal(m.verse_id), m.pos)
                )
            }
        )
    return RegistryIR(
        attribution=sorted(set(new.attribution)), entities=[merged[k] for k in sorted(merged)]
    )


def _merge_commentary(path: Path, new: CommentaryIR) -> CommentaryIR:
    if not path.exists():
        return new
    old = CommentaryIR.model_validate_json(path.read_bytes())
    works = dict(old.works)
    for name, work in new.works.items():
        verses = dict(works[name].verses) if name in works else {}
        verses.update(work.verses)
        works[name] = work.model_copy(
            update={"verses": dict(sorted(verses.items(), key=lambda kv: _ordinal(kv[0])))}
        )
    return CommentaryIR(book_code=new.book_code, works=works)


def ingest(
    scope: str,
    ir_dir: Path,
    sources_dir: Path,
    lockfile: Path,
    *,
    refresh: bool = False,
    commentaries: bool = True,
) -> IngestReport:
    book, chapters = parse_scope(scope)
    if book.testament != "OT":
        raise IngestError("only the Hebrew Bible is supported so far (TAGNT ingest is pending)")
    part = next(p for p, codes in TAHOT_FILES.items() if book.code in codes)
    report = IngestReport(scope=scope)
    ir_dir = Path(ir_dir)

    with Fetcher(sources_dir, lockfile, refresh=refresh) as fetcher:
        tahot_path = fetcher.get(SOURCES[f"stepbible/tahot_{part.lower().replace('-', '_')}"])
        words = read_tahot([tahot_path], {book.code: chapters})
        if not words:
            raise IngestError(f"TAHOT has no words for {scope}")
        verses = build_verses(words)
        verse_ids = {v.verse_id for v in verses}
        present_chapters = sorted({parse_ref(v)[1].chapter for v in verse_ids})
        report.verses, report.tokens = len(verses), sum(len(v.tokens) for v in verses)
        verse_map = kjv_verse_map(words)
        report.verse_map_rows = len(verse_map)

        # TVTMS: cross-check whole-verse renumberings, carry notes onto source verses.
        tvtms = read_tvtms(fetcher.get(SOURCES["stepbible/tvtms"]))
        eng_of: dict[str, set[str]] = defaultdict(set)
        heb_of: dict[str, set[str]] = defaultdict(set)
        for w in words:
            eng_of[w.heb_ref].add(w.eng_ref)
            heb_of[w.eng_ref].add(w.heb_ref)
        for heb, std in tvtms.hebrew_renumbers().items():
            if heb in eng_of and std not in eng_of[heb]:
                report.warnings.append(
                    f"TVTMS maps Hebrew {heb} to {std}; TAHOT puts it in {sorted(eng_of[heb])}"
                )
        notes: dict[str, list[str]] = defaultdict(list)
        for std, texts in tvtms.notes().items():
            for heb in heb_of.get(std, ()):
                notes[heb].extend(texts)

        # Baselines, each in its own versification.
        kjv_refs = {w.eng_ref for w in words}
        baselines = {}
        for name in BASELINES:
            refs = kjv_refs if TRANSLATION_SCHEMES.get(name) == "KJV" else verse_ids
            texts = _read_scrollmapper(fetcher.get(SOURCES[f"scrollmapper/{name}"]), book, refs)
            baselines[name] = texts
            report.baselines[name] = len(texts)
            if missing := sorted(refs - set(texts), key=_ordinal):
                report.warnings.append(f"{name}: {len(missing)} missing, e.g. {missing[0]}")

        # Registry: TIPNR individuals mentioned in the scope, with OpenBible coordinates.
        tipnr = TipnrIndex(read_tipnr(fetcher.get(SOURCES["stepbible/tipnr"])))
        geo = OpenBibleIndex(fetcher.get(SOURCES["openbible/ancient"]))
        seeds = _registry(words, tipnr, geo, report)
        report.entities = len(seeds)
        report.geocoded = sum(s.geo is not None for s in seeds)

        # Commentaries.
        commentary = CommentaryIR(book_code=book.code, works={})
        if commentaries and book.sefaria:
            for work in works_for(book):
                collected: dict[str, list[str]] = {}
                meta = None
                for ch in present_chapters:
                    wc = fetch_chapter(fetcher, work, book, ch)
                    if wc is None:
                        report.warnings.append(f"Sefaria: no {work.sefaria_title(book)} {ch}")
                        continue
                    meta = wc
                    for v, comments in wc.verses.items():
                        vid = f"{book.code}.{ch}.{v}"
                        if vid in verse_ids:
                            collected[vid] = comments
                if meta is not None:
                    commentary.works[work.name] = CommentaryWork(
                        version_title=meta.version_title, license=meta.license, verses=collected
                    )
                    report.commentaries[work.name] = len(collected)

    attribution = STEPBIBLE_ATTRIBUTION + [
        f"{name} baseline: scrollmapper/bible_databases (public domain)" for name in BASELINES
    ]
    source = SourceBookIR(
        book_code=book.code,
        source_language="HEBREW",
        attribution=sorted(attribution),
        verses=verses,
        verse_map=verse_map,
        baselines=baselines,
        versification_notes=dict(sorted(notes.items(), key=lambda kv: _ordinal(kv[0]))),
    )
    write_model(
        ir_dir / "source" / f"{book.code}.json",
        _merge_source(ir_dir / "source" / f"{book.code}.json", source),
    )
    registry = RegistryIR(attribution=sorted(REGISTRY_ATTRIBUTION), entities=seeds)
    write_model(
        ir_dir / "registry" / "entities.json",
        _merge_registry(ir_dir / "registry" / "entities.json", registry, verse_ids),
    )
    if commentary.works:
        write_model(
            ir_dir / "commentary" / f"{book.code}.json",
            _merge_commentary(ir_dir / "commentary" / f"{book.code}.json", commentary),
        )
    return report
