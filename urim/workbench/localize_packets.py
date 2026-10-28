"""Work packets for the localizer: what to translate in one scope, with what it needs to do it
well: the English, the Hebrew for verses, the language's own Bible for names and register, and
the names and terms already chosen, so a book reads as one translation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from urim.canon import parse_ref
from urim.config import Paths
from urim.i18n.messages import english, load_translations, plural_categories
from urim.ir.load import read_model
from urim.ir.models import I18nBundleIR, IRModel
from urim.workbench.fragments import key
from urim.workbench.localize import (
    TEXT_SECTIONS,
    ItemState,
    ScopeError,
    _bundle_key,
    bundle_states,
    has_language,
    message_states,
    parse_scope,
    text_states,
    verse_states,
)
from urim.workbench.merge import CorpusFiles
from urim.workbench.packets import Context, Packet, TaskError, _baselines, display_path

LABEL = {
    "missing": "new",
    "stale": "stale: the English changed",
    "changes_requested": "changes requested",
    "draft": "draft",
    "approved": "LOCKED (approved)",
    "unrecorded": "translated",
}


def _json(model: IRModel | dict) -> str:
    data = model.model_dump(mode="json", exclude_none=True) if isinstance(model, IRModel) else model
    return json.dumps(data, ensure_ascii=False)


def _bundle(paths: Paths, lang: str) -> I18nBundleIR:
    return read_model(paths.corpus / "i18n" / lang / "_bundle.json", I18nBundleIR)


def _header(lang: str, scope: str, fragment: Path, bundle: I18nBundleIR) -> list[str]:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    frag = display_path(fragment)
    return [
        f"# URIM task: localization {lang} {scope}",
        "",
        f"- Language: {bundle.lang_name} (`{lang}`); its own Bible here is "
        f"{bundle.baseline_translation}.",
        f"- Write the fragment to `{frag}`, then run `urim ir merge {frag}`.",
        f'- Schema: `urim schema localization`. Set `agent` to "localization", `lang` to '
        f'"{lang}", `scope` to "{scope}", and fill `produced_by` with your model id and skill '
        "version.",
        "- Translate everything marked new, stale or changes requested. Leave out what is LOCKED; "
        "drafts only when a request names them.",
        "- Put doubts and judgment calls in `reviewer_notes`.",
        f"- Generated {stamp}.",
        "",
    ]


def _glossary(files: CorpusFiles, lang: str, bundle: I18nBundleIR) -> list[str]:
    """Names and terms this language already uses, across the corpus."""
    names, systems = [], []
    for ch in files.chapters():
        tr = files.i18n(lang, ch)
        names += [
            f"- `{e.entity_id}`: {e.canonical_name}"
            + (f" ({', '.join(e.aliases)})" if e.aliases else "")
            for e in tr.entities
        ]
        systems += [f"- `{s.system_id}`: {s.name}" for s in tr.systems]
    out = []
    if names or systems:
        out += [
            f"## Names and terms already in {bundle.lang_name} (use them as they are)",
            "",
            *names,
            *systems,
            "",
        ]
    if bundle.books:
        out += ["Books: " + "; ".join(f"{b.book_code} = {b.name}" for b in bundle.books), ""]
    return out


def _requests(states: list[ItemState], led) -> list[str]:
    out = []
    for s in states:
        if s.status == "changes_requested":
            out.append(f"- `{s.key}`: {led.items[s.key].last_note}")
    return ["## Reviewer requests (address these first)", "", *out, ""] if out else []


def _texts(ctx: Context, lang: str, bundle: I18nBundleIR) -> list[str]:
    files, ch = ctx.files, ctx.chapter
    states = {s.key: s for s in text_states(files, ctx.ledger, lang, ch)}
    en, tr = files.i18n("en", ch), files.i18n(lang, ch)
    out = _requests(list(states.values()), ctx.ledger) + _glossary(files, lang, bundle)
    left = []
    for kind, section, id_attr in TEXT_SECTIONS:
        current = {getattr(x, id_attr): x for x in getattr(tr, section)}
        todo = [
            x
            for x in getattr(en, section)
            if states[key(f"{kind}.{lang}", getattr(x, id_attr))].status
            in ("missing", "stale", "changes_requested")
        ]
        left += [getattr(x, id_attr) for x in getattr(en, section) if x not in todo]
        if not todo:
            continue
        out += [f"## `{section}` ({len(todo)} to translate)", ""]
        for x in todo:
            i = getattr(x, id_attr)
            out += [f"### {i} [{LABEL[states[key(f'{kind}.{lang}', i)].status]}]", ""]
            out += [f"English: {_json(x)}"]
            if i in current:
                out += ["", f"Current {lang}: {_json(current[i])}"]
            out.append("")
    if left:
        out += [f"Already translated, leave out unless requested: {', '.join(left)}", ""]
    verses = _baselines_block(ctx, bundle, [v.verse_id for v in ctx.verses])
    return out + verses


def _baselines_block(ctx: Context, bundle: I18nBundleIR, verse_ids: list[str]) -> list[str]:
    name = bundle.baseline_translation
    if name not in ctx.source.baselines:
        return []
    out = [f"## {name}, for names and register", ""]
    for vid in verse_ids:
        lines = _baselines(ctx.source, vid, (name,))
        if lines:
            out.append(f"- {vid}: {lines[0].split(': ', 1)[1]}")
    return [*out, ""]


def _verses(ctx: Context, lang: str, bundle: I18nBundleIR, lo: int, hi: int) -> list[str]:
    files, ch = ctx.files, ctx.chapter
    window = [v for v in ctx.verses if lo <= parse_ref(v.verse_id)[1].verse <= hi]
    states = {s.item_id: s for s in verse_states(files, ctx.ledger, lang, ch)}
    en = {v.verse_id: v for v in files.i18n("en", ch).verses}
    tr = {v.verse_id: v for v in files.i18n(lang, ch).verses}
    out = _requests([s for s in states.values() if lo <= _verse_no(s.item_id) <= hi], ctx.ledger)
    out += _glossary(files, lang, bundle)
    out += ["## Verses", ""]
    for v in window:
        st = states.get(v.verse_id)
        status = LABEL[st.status] if st else "no English layers yet: skip"
        out += [f"### {v.verse_id} [{status}]", "", f"Hebrew: {v.source_text}", ""]
        glosses = {g.pos: g.gloss for g in en[v.verse_id].token_glosses} if v.verse_id in en else {}
        out += [
            "| # | word | translit | lemma | strongs | morph | English gloss |",
            "|---|---|---|---|---|---|---|",
        ]
        for t in v.tokens:
            reading = f" ({t.reading})" if t.reading else ""
            out.append(
                f"| {t.pos} | {t.surface}{reading} | {t.translit or ''} | {t.lemma or ''} | "
                f"{t.strongs or ''} | {t.morph or ''} | {glosses.get(t.pos, '')} |"
            )
        out.append("")
        if v.verse_id in en:
            e = en[v.verse_id]
            out += [
                f"English literal: {e.translation_literal}",
                "",
                f"English dramatic: {e.translation_dramatic}",
                "",
                f"English commentary: {e.directors_commentary}",
                "",
            ]
            if e.philological_notes:
                notes = [n.model_dump(mode="json", exclude_none=True) for n in e.philological_notes]
                out += [f"English notes: {_json({'notes': notes})}", ""]
        out += _baselines(ctx.source, v.verse_id, (bundle.baseline_translation,))
        if v.verse_id in tr:
            out += ["", f"Current {lang}: {_json(tr[v.verse_id])}"]
        out.append("")
    return out


def _verse_no(verse_id: str) -> int:
    return parse_ref(verse_id)[1].verse


def _messages(paths: Paths, lang: str, bundle: I18nBundleIR, namespace: str) -> list[str]:
    sources = english()
    states = {s.item_id: s for s in message_states(paths.corpus, lang)}
    current = load_translations(paths.corpus, lang)
    todo = [
        s
        for k, s in sources.items()
        if (not namespace or s.namespace == namespace) and states[k].todo
    ]
    cats = plural_categories(lang)
    out = [
        "## How interface messages work",
        "",
        "- Keep every `{placeholder}` exactly as in the English. Translate the words around it.",
        f"- Counted messages (with `{{count}}`, or English plural forms) take `forms`: one entry "
        f"for each of {', '.join(cats)}. A form may leave out `{{count}}` when the word says it.",
        "- Short labels stay short: they sit on buttons, tabs and table headers. Match the tone "
        "of the screen the note describes. Keep the same word for the same thing everywhere.",
        "",
    ]
    common = {k: v for k, v in current.items() if k.startswith(("common.", "shell.", "status."))}
    if common:
        out += ["## Terms already chosen", ""]
        out += [f"- `{k}`: {json.dumps(v, ensure_ascii=False)}" for k, v in sorted(common.items())]
        out.append("")
    out += [f"## Messages ({len(todo)} to translate)", ""]
    for s in todo:
        english_text = s.text if s.text is not None else json.dumps(s.forms, ensure_ascii=False)
        line = f"- `{s.key}` [{LABEL[states[s.key].status]}]: {english_text}"
        if s.note:
            line += f"  — note: {s.note}"
        if s.key in current:
            line += f"  — current: {json.dumps(current[s.key], ensure_ascii=False)}"
        out.append(line)
    return [*out, ""]


def _bundle_entries(paths: Paths, lang: str, bundle: I18nBundleIR) -> list[str]:
    en = _bundle(paths, "en")
    states = {s.key: s for s in bundle_states(paths.corpus, lang)}
    current = {
        _bundle_key(section, x): x
        for section in ("books", "vocab", "anchors")
        for x in getattr(bundle, section)
    }
    out = [f"lang_name now: {bundle.lang_name}", ""]
    for section in ("books", "vocab", "anchors"):
        rows = []
        for x in getattr(en, section):
            k = _bundle_key(section, x)
            if not states[k].todo:
                continue
            rows.append(f"- `{k}` [{LABEL[states[k].status]}] English: {_json(x)}")
            if k in current:
                rows.append(f"  current: {_json(current[k])}")
        if rows:
            out += [f"## `{section}`", "", *rows, ""]
    return out


def build_localization_packet(lang: str, scope: str, paths: Paths) -> Packet:
    try:
        s = parse_scope(scope)
    except ScopeError as e:
        raise TaskError(str(e)) from e
    if lang == "en":
        raise TaskError("English is the source: localize into another language")
    if not has_language(paths.corpus, lang):
        raise TaskError(
            f"no language {lang!r}: start it with corpus/i18n/{lang}/_bundle.json "
            "(lang_code, lang_name, baseline_translation)"
        )
    bundle = _bundle(paths, lang)
    label = s.label
    base = paths.work / "localization" / f"{lang}.{label}"
    fragment_path = base.with_name(base.name + ".fragment.json")
    packet_path = base.with_name(base.name + ".md")
    lines = _header(lang, label, fragment_path, bundle)
    match s.kind:
        case "texts" | "verses":
            ctx = Context(paths, s.chapter)
            if s.kind == "texts":
                lines += _texts(ctx, lang, bundle)
            else:
                lines += _verses(ctx, lang, bundle, s.lo, s.hi)
        case "ui":
            if s.namespace and s.namespace not in {x.namespace for x in english().values()}:
                raise TaskError(f"no interface namespace {s.namespace!r}")
            lines += _messages(paths, lang, bundle, s.namespace)
        case _:
            lines += _bundle_entries(paths, lang, bundle)
    text = "\n".join(lines).rstrip() + "\n"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(text, encoding="utf-8")
    chapter = s.chapter or label
    return Packet("localization", label, chapter, text, packet_path, fragment_path)
