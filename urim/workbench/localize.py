"""Localization: every English text of the corpus, the interface and the bundle, in one more
language, written by the localizer and merged like any other fragment.

English is the source. A chapter's texts (events, links, entities, states, rituals,
interactions) and its verses are ledger items in that chapter, keyed by language
(`event.ru:evt.…`, `verse.ru:GEN.38.4`), reviewed like the English ones, and each remembers
the English it was made from. When that English changes the translation is stale: it shows up
as work again, and its approval no longer locks it. Interface messages and bundle labels carry
the same memory in the language's records (`corpus/ledger/lang/<lang>.json`).

Translations follow the English, so a text can be translated only once its English exists:
a chapter's texts after its chronology and ontology, a verse after its philology.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from urim.canon import parse_ref
from urim.compiler.link import LinkError, link_all
from urim.i18n.messages import (
    UI_FILE,
    english,
    load_translations,
    plural_categories,
    source_hash,
)
from urim.ir.load import inputs_root, load_sources, read_model, write_model
from urim.ir.models import I18nBundleIR, IRModel
from urim.workbench.fragments import LocalizationFragment, key
from urim.workbench.ledger import (
    ChapterLedger,
    ChapterNote,
    Record,
    load_ledger,
    load_records,
    now,
    save_ledger,
    save_records,
    write_atomic,
)
from urim.workbench.merge import CorpusFiles, MergeResult, _dump, _record, chapter_of

# (ledger kind, I18nChapterIR section, id attribute), in reading order.
TEXT_SECTIONS = (
    ("event", "events", "event_id"),
    ("causal", "causal_edges", "causal_id"),
    ("entity", "entities", "entity_id"),
    ("system", "systems", "system_id"),
    ("component", "components", "component_id"),
    ("instance", "system_instances", "instance_id"),
    ("edge", "edges", "edge_id"),
)
_VERSE_SCOPE = re.compile(r"^[1-3]?[A-Z]+\.\d+\.\d+-\d+$")
_CHAPTER_SCOPE = re.compile(r"^[1-3]?[A-Z]+\.\d+$")
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class ScopeError(ValueError):
    pass


@dataclass(frozen=True)
class Scope:
    kind: str  # texts, verses, ui, bundle
    chapter: str = ""
    lo: int = 0
    hi: int = 0
    namespace: str = ""

    @property
    def label(self) -> str:
        match self.kind:
            case "texts":
                return self.chapter
            case "verses":
                return f"{self.chapter}.{self.lo}-{self.hi}"
            case "ui":
                return f"ui.{self.namespace}" if self.namespace else "ui"
        return "bundle"


def parse_scope(scope: str) -> Scope:
    s = scope.strip()
    if s == "bundle":
        return Scope("bundle")
    if s == "ui" or s.startswith("ui."):
        return Scope("ui", namespace=s[3:])
    if _CHAPTER_SCOPE.match(s):
        return Scope("texts", chapter=s)
    if _VERSE_SCOPE.match(s):
        head, _, span = s.rpartition(".")
        lo, hi = (int(n) for n in span.split("-"))
        if hi < lo:
            raise ScopeError(f"bad verse range in {scope!r}")
        return Scope("verses", chapter=head, lo=lo, hi=hi)
    raise ScopeError(
        f"bad localization scope {scope!r}; expected GEN.38 (texts), GEN.38.1-12 (verses), "
        "ui.<namespace> (interface) or bundle"
    )


def has_language(corpus: Path, lang: str) -> bool:
    return (Path(corpus) / "i18n" / lang / "_bundle.json").exists()


def languages(corpus: Path) -> list[str]:
    root = Path(corpus) / "i18n"
    return sorted(p.parent.name for p in root.glob("*/_bundle.json") if p.parent.name != "en")


# --- where each translation stands -------------------------------------------------------------


@dataclass
class ItemState:
    key: str
    item_id: str
    kind: str  # event … edge, verse, ui, book, vocab, anchor
    source: str  # hash of the English now
    status: str  # missing, stale, unrecorded, draft, changes_requested, approved

    @property
    def todo(self) -> bool:
        return self.status in ("missing", "stale")


def _hash(model: IRModel) -> str:
    return source_hash(model.model_dump(mode="json"))


def _status(led: ChapterLedger, k: str, translated: bool, source: str) -> str:
    if not translated:
        return "missing"
    item = led.items.get(k)
    if item is None:
        return "unrecorded"  # written by hand, before translations were tracked
    if item.source is not None and item.source != source:
        return "stale"
    return item.status


def text_states(files: CorpusFiles, led: ChapterLedger, lang: str, chapter: str) -> list[ItemState]:
    """A chapter's texts: one state per English text item."""
    en, tr = files.i18n("en", chapter), files.i18n(lang, chapter)
    out = []
    for kind, section, id_attr in TEXT_SECTIONS:
        have = {getattr(x, id_attr) for x in getattr(tr, section)}
        for item in getattr(en, section):
            i = getattr(item, id_attr)
            k, h = key(f"{kind}.{lang}", i), _hash(item)
            out.append(ItemState(k, i, kind, h, _status(led, k, i in have, h)))
    return out


def verse_states(
    files: CorpusFiles, led: ChapterLedger, lang: str, chapter: str
) -> list[ItemState]:
    """A chapter's verses that have English layers."""
    have = {v.verse_id for v in files.i18n(lang, chapter).verses}
    out = []
    for v in files.i18n("en", chapter).verses:
        k, h = key(f"verse.{lang}", v.verse_id), _hash(v)
        out.append(ItemState(k, v.verse_id, "verse", h, _status(led, k, v.verse_id in have, h)))
    return out


def message_states(corpus: Path, lang: str) -> list[ItemState]:
    translations = load_translations(corpus, lang)
    records = load_records(corpus, lang).items
    out = []
    for k, src in english().items():
        rec = records.get(f"ui:{k}")
        if k not in translations:
            status = "missing"
        elif rec is None:
            status = "unrecorded"
        else:
            status = "stale" if rec.source != src.hash else "approved"
        out.append(ItemState(f"ui:{k}", k, "ui", src.hash, status))
    return out


def bundle_states(corpus: Path, lang: str) -> list[ItemState]:
    en = _bundle(corpus, "en")
    tr = _bundle(corpus, lang)
    records = load_records(corpus, lang).items
    have = {
        **{f"book:{b.book_code}": b for b in tr.books},
        **{f"vocab:{v.kind}.{v.code}": v for v in tr.vocab},
        **{f"anchor:{a.anchor_id}": a for a in tr.anchors},
    }
    source = {
        **{f"book:{b.book_code}": b for b in en.books},
        **{f"vocab:{v.kind}.{v.code}": v for v in en.vocab},
        **{f"anchor:{a.anchor_id}": a for a in en.anchors},
    }
    out = []
    for k, item in source.items():
        h, rec = _hash(item), records.get(k)
        if k not in have:
            status = "missing"
        elif rec is None:
            status = "unrecorded"
        else:
            status = "stale" if rec.source != h else "approved"
        out.append(ItemState(k, k.split(":", 1)[1], k.split(":", 1)[0], h, status))
    return out


def _bundle(corpus: Path, lang: str) -> I18nBundleIR:
    return read_model(Path(corpus) / "i18n" / lang / "_bundle.json", I18nBundleIR)


# --- merging -----------------------------------------------------------------------------------


@dataclass
class _Ctx:
    f: LocalizationFragment
    scope: Scope
    corpus: Path
    inputs: Path
    result: MergeResult
    files: CorpusFiles = field(init=False)

    def __post_init__(self) -> None:
        self.files = CorpusFiles(self.corpus)


def merge_localization(
    f: LocalizationFragment, corpus: Path, inputs: Path, *, dry_run: bool = False
) -> MergeResult:
    corpus, inputs = Path(corpus), Path(inputs)
    result = MergeResult(agent="localization", chapter_ref=f"{f.lang} {f.scope}")
    try:
        scope = parse_scope(f.scope)
    except ScopeError as e:
        result.errors.append(str(e))
        return result
    if f.lang == "en":
        result.errors.append("English is the source: the localizer writes other languages")
        return result
    if not has_language(corpus, f.lang):
        result.errors.append(
            f"no language {f.lang!r}: a language starts with corpus/i18n/{f.lang}/_bundle.json "
            "(lang_code, lang_name, baseline_translation)"
        )
        return result
    filled = {
        "texts": any(getattr(f, s) for _, s, _ in TEXT_SECTIONS),
        "verses": bool(f.verses),
        "ui": bool(f.messages),
        "bundle": f.bundle is not None,
    }
    if stray := [k for k, v in filled.items() if v and k != scope.kind]:
        result.errors.append(
            f"scope {f.scope} is {scope.kind}; this fragment also carries {', '.join(stray)}"
        )
        return result
    ctx = _Ctx(f, scope, corpus, inputs, result)
    match scope.kind:
        case "texts" | "verses":
            return _merge_chapter(ctx, dry_run)
        case "ui":
            return _merge_messages(ctx, dry_run)
    return _merge_bundle(ctx, dry_run)


def _decide_item(
    k: str, old: IRModel | None, new: IRModel, source: str, led: ChapterLedger, r: MergeResult
) -> bool:
    """Whether to take `new`; an approved translation of unchanged English is locked."""
    item = led.items.get(k)
    if item is not None and item.status == "approved" and item.source in (None, source):
        if old is not None and _dump(old) != _dump(new):
            r.errors.append(
                f"{k} is approved and locked: leave it out or reproduce it exactly "
                "(reopen it to change it)"
            )
        r.kept_locked.append(k)
        return False
    if old is None:
        r.added.append(k)
    elif _dump(old) == _dump(new) and item is not None and item.source == source:
        r.unchanged.append(k)
    else:
        r.changed.append(k)
    r.sources[k] = source
    return True


def _merge_chapter(ctx: _Ctx, dry_run: bool) -> MergeResult:
    f, scope, r, files = ctx.f, ctx.scope, ctx.result, ctx.files
    ch, lang = scope.chapter, f.lang
    tokens = {
        v.verse_id: len(v.tokens)
        for b in load_sources(inputs_root(ctx.corpus, ctx.inputs))
        for v in b.verses
        if chapter_of(v.verse_id) == ch
    }
    if not tokens:
        r.errors.append(f"{ch} is not ingested yet: run `urim ingest {ch}`")
        return r
    led = load_ledger(ctx.corpus, ch)
    en, tr = files.i18n("en", ch), files.i18n(lang, ch)
    if scope.kind == "texts":
        for kind, section, id_attr in TEXT_SECTIONS:
            sources = {getattr(x, id_attr): x for x in getattr(en, section)}
            current = {getattr(x, id_attr): x for x in getattr(tr, section)}
            for item in getattr(f, section):
                i = getattr(item, id_attr)
                if i not in sources:
                    r.errors.append(
                        f"{i}: {ch} has no English {kind} text with this id to translate"
                    )
                    continue
                k = key(f"{kind}.{lang}", i)
                if _decide_item(k, current.get(i), item, _hash(sources[i]), led, r):
                    current[i] = item
            order = {i: n for n, i in enumerate(sources)}
            setattr(
                tr,
                section,
                sorted(current.values(), key=lambda x: order.get(getattr(x, id_attr), 1 << 30)),
            )
    else:
        sources = {v.verse_id: v for v in en.verses}
        current = {v.verse_id: v for v in tr.verses}
        for v in f.verses:
            no = parse_ref(v.verse_id)[1].verse if chapter_of(v.verse_id) == ch else None
            if no is None or not scope.lo <= no <= scope.hi:
                r.errors.append(f"{v.verse_id} is outside {scope.label}")
                continue
            if v.verse_id not in sources:
                r.errors.append(
                    f"{v.verse_id} has no English layers yet: localization follows philology"
                )
                continue
            n = tokens.get(v.verse_id, 0)
            if len(v.token_glosses) != n:
                r.warnings.append(f"{v.verse_id}: {len(v.token_glosses)} glosses for {n} words")
            k = key(f"verse.{lang}", v.verse_id)
            if _decide_item(k, current.get(v.verse_id), v, _hash(sources[v.verse_id]), led, r):
                current[v.verse_id] = v
        tr.verses = sorted(current.values(), key=lambda v: parse_ref(v.verse_id)[1].ordinal)
    files.touch_i18n(lang, ch)
    if r.errors or not _links(ctx):
        return r
    if not dry_run:
        r.written = files.write(ctx.corpus)
        _record(f, {ch: led}, r)
        save_ledger(ctx.corpus, led)
    return r


def _links(ctx: _Ctx) -> bool:
    """Link the merged corpus in a scratch copy: the language bundle must still compile."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "corpus"
        shutil.copytree(ctx.corpus, scratch)
        ctx.files.write(scratch)
        try:
            reports = link_all(scratch, Path(tmp) / "bundles", inputs_dir=ctx.inputs)
        except LinkError as e:
            ctx.result.errors += e.report.errors
            ctx.result.warnings += e.report.warnings
            return False
    ctx.result.warnings += [
        f"{name}: {w}" for name, rep in reports.items() if name == ctx.f.lang for w in rep.warnings
    ]
    return True


def check_message(
    lang: str, msg_key: str, text: str | None, forms: dict[str, str] | None
) -> list[str]:
    """Problems with one interface translation, against its English."""
    src = english().get(msg_key)
    if src is None:
        return [f"ui:{msg_key}: no such English message"]
    if (text is None) == (forms is None):
        return [f"ui:{msg_key}: give either text or forms"]
    errors = []
    wanted = src.placeholders
    if forms is not None:
        if src.forms is None and "count" not in wanted:
            errors.append(f"ui:{msg_key}: the English is not counted; give text, not forms")
        cats = plural_categories(lang)
        if set(forms) != set(cats):
            errors.append(f"ui:{msg_key}: forms must be exactly {', '.join(cats)} for {lang}")
        texts = list(forms.values())
    else:
        if src.forms is not None:
            errors.append(f"ui:{msg_key}: the English has plural forms; give forms")
        texts = [text or ""]
    for t in texts:
        used = set(_PLACEHOLDER.findall(t))
        if extra := used - wanted:
            errors.append(f"ui:{msg_key}: unknown placeholder {{{', '.join(sorted(extra))}}}")
        # A plural form may leave out {count} ("одна сессия"); every other placeholder stays.
        if missing := wanted - used - ({"count"} if forms is not None else set()):
            errors.append(f"ui:{msg_key}: keep {{{'}, {'.join(sorted(missing))}}}")
    return errors


def _merge_messages(ctx: _Ctx, dry_run: bool) -> MergeResult:
    f, r, ns = ctx.f, ctx.result, ctx.scope.namespace
    sources = english()
    current = load_translations(ctx.corpus, f.lang)
    records = load_records(ctx.corpus, f.lang)
    stamp = now()
    for m in f.messages:
        if errs := check_message(f.lang, m.key, m.text, m.forms):
            r.errors += errs
            continue
        src = sources[m.key]
        if ns and src.namespace != ns:
            r.errors.append(f"ui:{m.key} belongs to ui.{src.namespace}, not ui.{ns}")
            continue
        value: str | dict[str, str] = m.text if m.text is not None else dict(m.forms or {})
        k, old = f"ui:{m.key}", current.get(m.key)
        rec = records.items.get(k)
        if old is None:
            r.added.append(k)
        elif old == value and rec is not None and rec.source == src.hash:
            r.unchanged.append(k)
            continue
        else:
            r.changed.append(k)
        current[m.key] = value
        records.items[k] = Record(produced_by=f.produced_by, produced_at=stamp, source=src.hash)
    if r.errors or dry_run:
        return r
    path = ctx.corpus / "i18n" / f.lang / UI_FILE
    write_atomic(
        path, json.dumps(dict(sorted(current.items())), ensure_ascii=False, indent=1) + "\n"
    )
    records.notes += [
        ChapterNote(
            note=f"[{n.item}] {n.note}" if n.item else n.note, produced_by=f.produced_by, at=stamp
        )
        for n in f.reviewer_notes
    ]
    save_records(ctx.corpus, records)
    r.written.append(path)
    r.relink = False
    return r


def _merge_bundle(ctx: _Ctx, dry_run: bool) -> MergeResult:
    f, r = ctx.f, ctx.result
    assert f.bundle is not None
    en, tr = _bundle(ctx.corpus, "en"), _bundle(ctx.corpus, f.lang)
    records = load_records(ctx.corpus, f.lang)
    stamp = now()

    def take(section: str, item, k: str, source_item) -> None:
        if source_item is None:
            r.errors.append(f"{k}: the English bundle has no such entry")
            return
        current = {_bundle_key(section, x): x for x in getattr(tr, section)}
        old, h = current.get(k), _hash(source_item)
        rec = records.items.get(k)
        if old is None:
            r.added.append(k)
        elif _dump(old) == _dump(item) and rec is not None and rec.source == h:
            r.unchanged.append(k)
            return
        else:
            r.changed.append(k)
        current[k] = item
        order = [_bundle_key(section, x) for x in getattr(en, section)]
        setattr(tr, section, [current[x] for x in order if x in current])
        records.items[k] = Record(produced_by=f.produced_by, produced_at=stamp, source=h)

    sources = {
        section: {_bundle_key(section, x): x for x in getattr(en, section)}
        for section in ("books", "vocab", "anchors")
    }
    for section in ("books", "vocab", "anchors"):
        for item in getattr(f.bundle, section):
            k = _bundle_key(section, item)
            take(section, item, k, sources[section].get(k))
    if f.bundle.lang_name:
        tr.lang_name = f.bundle.lang_name
    if r.errors:
        return r
    path = ctx.corpus / "i18n" / f.lang / "_bundle.json"
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "corpus"
        shutil.copytree(ctx.corpus, scratch)
        write_model(scratch / "i18n" / f.lang / "_bundle.json", tr)
        try:
            link_all(scratch, Path(tmp) / "bundles", inputs_dir=ctx.inputs)
        except LinkError as e:
            r.errors += e.report.errors
            return r
    if dry_run:
        return r
    write_model(path, tr)
    save_records(ctx.corpus, records)
    r.written.append(path)
    return r


def _bundle_key(section: str, item) -> str:
    match section:
        case "books":
            return f"book:{item.book_code}"
        case "vocab":
            return f"vocab:{item.kind}.{item.code}"
    return f"anchor:{item.anchor_id}"
