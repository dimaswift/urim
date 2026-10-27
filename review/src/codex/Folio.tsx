import { useEffect, useMemo, useRef, useState } from "react";
import type { Codex, EventView, VerseMatrix } from "../api";
import { useApi } from "../hooks";
import { go, href, short, type Route } from "../util";
import type { TocBook } from "./CodexApp";
import { Corners, Ornament, Words, roman, useLang } from "./parts";

interface Chapter { book_code: string; book_name: string | null; chapter: number; verses: VerseMatrix[]; events: EventView[] }
type Layer = "baseline" | "literal" | "dramatic";

const ordinal = (verseId: string) => {
  const [, c, v] = verseId.split(".");
  return Number(c) * 1000 + Number(v);
};

function when(e: EventView): string {
  if (e.precision_tier.code === "DIURNAL_HOUR") return e.time_of_day?.label ?? e.start_label.split(" ").slice(-1)[0];
  return e.start_label;
}

function Gloss({ verseId }: { verseId: string }) {
  const { lang } = useLang();
  const { data: m } = useApi<VerseMatrix>(`/api/verse/${verseId}?lang=${lang}`);
  if (!m) return <div className="gloss muted">Unfolding…</div>;
  const layers = m.translation_literal || m.translation_dramatic;
  return (
    <div className="gloss" onClick={(e) => e.stopPropagation()}>
      <h4>The Hebrew, word by word</h4>
      <Words tokens={m.tokens} />
      {m.aliases.length > 0 && <div className="muted" style={{ fontSize: 14, marginTop: 6 }}>Numbered differently in English Bibles: {m.aliases.map((a) => a.replace("KJV:", "KJV ").replace(/^KJV (\w+)\.(\d+)\.(\d+)$/, "KJV $2:$3")).join(", ")}</div>}
      {layers ? (
        <>
          <h4>Translations</h4>
          {m.translation_literal && <div className="layer"><div className="label">Word for word</div>{m.translation_literal}</div>}
          {m.translation_dramatic && <div className="layer"><div className="label">As drama</div><i>{m.translation_dramatic}</i></div>}
          <div className="layer"><div className="label">{m.baseline_translation}</div>{m.traditional_baseline}</div>
        </>
      ) : (
        <p className="muted" style={{ fontStyle: "italic" }}>No new translations for this verse yet; the word glosses come from STEPBible.</p>
      )}
      {m.directors_commentary && (
        <>
          <h4>Commentary</h4>
          <p className="commentary" style={{ margin: 0 }}>{m.directors_commentary}</p>
        </>
      )}
      {m.philological_notes.length > 0 && (
        <>
          <h4>Notes on words</h4>
          {m.philological_notes.map((n) => (
            <div key={n.term} className="note-card">
              <span className="term">{n.term}</span> <i className="muted">{n.translit}</i>
              {n.root && <span className="muted"> · root <span style={{ fontFamily: "var(--hebrew)" }}>{n.root}</span></span>}
              <div>{n.note}</div>
            </div>
          ))}
        </>
      )}
      {m.ecs && m.ecs.entities.length > 0 && (
        <>
          <h4>In this verse</h4>
          {m.ecs.entities.map((e) => <a key={e.entity_id} className="chip" href={href("people", e.entity_id)}>{e.name}</a>)}
          {m.events.map((e) => <a key={e.event_id} className="chip" href={href("hours", e.event_id)} style={{ color: "var(--rubric)" }}>✠ {e.title}</a>)}
        </>
      )}
    </div>
  );
}

export default function Folio({ route, toc }: { route: Route; toc: TocBook[] }) {
  const { lang } = useLang();
  const chapters = toc.flatMap((b) => b.chapters);
  const ref = route.arg || chapters.find((c) => c.ref.endsWith(".18"))?.ref || chapters[0]?.ref;
  const { data } = useApi<Chapter>(ref ? `/api/chapter/${ref}?lang=${lang}` : null);
  const { data: systems } = useApi<Codex[]>(`/api/systems?lang=${lang}`);
  const [layer, setLayerState] = useState<Layer>(() => {
    try { return (localStorage.getItem("urim.codex.layer") as Layer) || "baseline"; } catch { return "baseline"; }
  });
  const setLayer = (l: Layer) => { setLayerState(l); try { localStorage.setItem("urim.codex.layer", l); } catch { /* ignore */ } };
  const open = route.params.get("v");
  const openRow = useRef<HTMLDivElement>(null);
  useEffect(() => { openRow.current?.scrollIntoView({ behavior: "smooth", block: "center" }); }, [open, data]);

  const rites = useMemo(() => {
    const out = new Map<string, string[]>();
    systems?.forEach((s) => s.instances.forEach((i) => out.set(i.verse_start, [...(out.get(i.verse_start) ?? []), s.name ?? s.system_id])));
    return out;
  }, [systems]);

  if (!ref) return <div className="loading">The codex is empty: nothing has been ingested yet.</div>;
  if (!data) return <div className="loading">Opening the folio…</div>;

  const idx = chapters.findIndex((c) => c.ref === ref);
  const prev = chapters[idx - 1], next = chapters[idx + 1];
  const inChapter = data.events.filter((e) => e.verse_start.startsWith(ref + "."));
  const starts = new Map<string, EventView[]>();
  inChapter
    .sort((a, b) => ordinal(a.verse_start) - ordinal(b.verse_start) || ordinal(b.verse_end) - ordinal(a.verse_end))
    .forEach((e) => starts.set(e.verse_start, [...(starts.get(e.verse_start) ?? []), e]));
  const places = [...new Set(inChapter.map((e) => e.location?.name).filter(Boolean))];
  const dated = inChapter.filter((e) => e.precision_tier.code !== "MACRO_ERA");
  const era = dated[0]?.start_label.split("-")[0] ?? inChapter[0]?.start_label;
  const parents = new Set(inChapter.map((e) => e.parent_event_id).filter(Boolean));

  return (
    <article className="folio">
      <Corners />
      <div className="heading">
        <div className="book">{data.book_name}</div>
        <h1>Chapter {roman(data.chapter)}</h1>
        {(era || places.length > 0) && <div className="sub">{[era, places.slice(0, 4).join(" · ")].filter(Boolean).join(" — ")}</div>}
        <Ornament />
      </div>
      <div className="layer-switch">
        {(["baseline", "literal", "dramatic"] as Layer[]).map((l) => (
          <button key={l} className={layer === l ? "on" : ""} onClick={() => setLayer(l)}>
            {l === "baseline" ? (data.verses[0]?.baseline_translation === "RusSynodal" ? "Synodal" : "King James") : l === "literal" ? "Word for word" : "As drama"}
          </button>
        ))}
      </div>
      <div>
        {data.verses.map((v, i) => {
          const chosen = layer === "literal" ? v.translation_literal : layer === "dramatic" ? v.translation_dramatic : null;
          const text = chosen ?? v.traditional_baseline ?? "";
          const fallback = layer !== "baseline" && !chosen;
          const isOpen = open === v.verse_id;
          const first = i === 0 && text.length > 0;
          return (
            <div key={v.verse_id} style={{ display: "contents" }}>
              {(starts.get(v.verse_id) ?? []).map((e) => (
                <div key={e.event_id} className={`rubric ${parents.has(e.event_id) ? "major" : ""}`}>
                  <span className="fleuron">{parents.has(e.event_id) ? "❧" : "✠"}</span>
                  <a href={href("hours", e.event_id)} style={{ color: "inherit" }}>{e.title}</a>
                  <span className="when">{when(e)}{e.location && !parents.has(e.event_id) ? ` · ${e.location.name}` : ""}</span>
                </div>
              ))}
              <div ref={isOpen ? openRow : undefined} className={`verse-row ${isOpen ? "open" : ""}`}
                   onClick={() => go("read", ref, isOpen ? {} : { v: v.verse_id })}>
                <span className="vnum">{v.verse}</span>
                <div className="vtext">
                  {first && <span className="initial">{text.charAt(0)}</span>}
                  {first ? text.slice(1) : text}
                  {fallback && <span className="fallback">({v.baseline_translation === "RusSynodal" ? "Synodal" : "KJV"})</span>}
                  {(v.directors_commentary || v.philological_notes.length > 0) && <span className="marks" title="Commentary and notes">❦</span>}
                  {rites.get(v.verse_id)?.map((r) => <span key={r} className="rite">✶ {r}</span>)}
                </div>
                <div className="vheb">{v.source_text}</div>
                {isOpen && <Gloss verseId={v.verse_id} />}
              </div>
            </div>
          );
        })}
      </div>
      <Ornament glyph="✠ ✠ ✠" />
      <div className="pager">
        {prev ? <a href={href("read", prev.ref)}>← Chapter {roman(prev.chapter)}</a> : <span />}
        <span className="muted">{data.verses.length} verses · {inChapter.length} events · tap a verse to unfold it</span>
        {next ? <a href={href("read", next.ref)}>Chapter {roman(next.chapter)} →</a> : <span />}
      </div>
      {open && <div className="muted" style={{ textAlign: "center", marginTop: 8, fontSize: 14 }}>Showing {short(open)}</div>}
    </article>
  );
}
