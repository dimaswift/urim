import { useEffect, useState } from "react";
import type { Token, VerseMatrix } from "../api";
import { EntityChip, EventBrief, Loading, Panel, ReviewBar } from "../components";
import { useApi, useApp } from "../state";
import { decodeMorph, go, href, short, type Route } from "../util";

const LAYERS = ["literal", "dramatic", "commentary", "baseline", "audit"] as const;
type Layer = (typeof LAYERS)[number];

function TokenCard({ t }: { t: Token }) {
  const morph = decodeMorph(t.morph);
  return (
    <div className="grid" style={{ gap: 6 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="hebrew" style={{ fontSize: 30, color: "var(--gold)" }}>{t.surface}</span>
        <span className="mono muted">#{t.pos}</span>
      </div>
      <dl className="kv">
        {t.translit && <><dt>Sound</dt><dd className="mono">{t.translit}</dd></>}
        {t.gloss && <><dt>Gloss</dt><dd>{t.gloss}</dd></>}
        {t.lemma && <><dt>Lemma</dt><dd className={/[\u0590-\u05FF]/.test(t.lemma) ? "hebrew" : "mono"} style={{ fontSize: /[\u0590-\u05FF]/.test(t.lemma) ? 18 : 12, textAlign: "left" }}>{t.lemma}</dd></>}
        {t.strongs && <><dt>Strong's</dt><dd className="mono">{t.strongs}</dd></>}
        {morph.length > 0 && <><dt>Grammar</dt><dd>{morph.slice(1).map((m) => <div key={m}>{m}</div>)}<span className="mono faint">{t.morph}</span></dd></>}
        {t.reading && <><dt>Reading</dt><dd className="mono">{t.reading}</dd></>}
        {t.name_ref && <><dt>Names</dt><dd className="mono" style={{ color: "var(--cyan)" }}>{t.name_ref}</dd></>}
      </dl>
    </div>
  );
}

function Layers({ m }: { m: VerseMatrix }) {
  const [layer, setLayer] = useState<Layer>("literal");
  const text: Record<Layer, string | null> = {
    literal: m.translation_literal, dramatic: m.translation_dramatic, commentary: m.directors_commentary,
    baseline: m.traditional_baseline, audit: null,
  };
  const missing = !m.translation_literal;
  return (
    <Panel title="Layers" right={m.layers_lang && m.layers_lang !== m.baseline_lang ? <span className="chip muted">layers from {m.layers_lang}</span> : undefined}>
      <div className="row" style={{ gap: 4, marginBottom: 12, flexWrap: "wrap" }}>
        {LAYERS.map((l) => (
          <span key={l} className={`chip click ${layer === l ? "on" : ""}`} onClick={() => setLayer(l)}>
            {l === "baseline" ? m.baseline_translation ?? "Baseline" : l[0].toUpperCase() + l.slice(1)}
          </span>
        ))}
      </div>
      {missing && layer !== "baseline" && (
        <div className="intel"><b>NO LAYERS YET</b>Send a Philologist on this verse: <span className="mono">/urim-philologist {m.verse_id}</span></div>
      )}
      {layer === "audit" && !missing ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div><div className="hud upper muted" style={{ fontSize: 10 }}>{m.baseline_translation} (tradition)</div><p>{m.traditional_baseline}</p></div>
          <div><div className="hud upper" style={{ fontSize: 10, color: "var(--amber)" }}>Literal (source)</div><p>{m.translation_literal}</p></div>
        </div>
      ) : (
        text[layer] && <p style={{ fontSize: layer === "dramatic" ? 18 : 15, lineHeight: 1.65, margin: 0, fontFamily: layer === "dramatic" ? "var(--hud)" : undefined }}>{text[layer]}</p>
      )}
    </Panel>
  );
}

export default function Xray({ route }: { route: Route }) {
  const { overview, lang } = useApp();
  const verseId = route.arg || "1KGS.18.27";
  const { data: m, error } = useApi<VerseMatrix>(`/api/verse/${encodeURIComponent(verseId)}?lang=${lang}`);
  const [hover, setHover] = useState<{ t: Token; x: number; y: number } | null>(null);
  const [pinned, setPinned] = useState<Token | null>(null);
  const chapter = verseId.split(".").slice(0, 2).join(".");
  const tile = overview?.books.flatMap((b) => b.chapters).find((c) => c.ref === chapter);
  const verses = tile?.verses ?? 0;
  const [book, ch, v] = verseId.split(".");
  const n = Number(v);

  useEffect(() => { setPinned(null); }, [verseId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "ArrowLeft" && n > 1) go("xray", `${book}.${ch}.${n - 1}`);
      if (e.key === "ArrowRight" && n < verses) go("xray", `${book}.${ch}.${n + 1}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const ingested = overview?.books.flatMap((b) => b.chapters.filter((c) => c.ingested)) ?? [];
  return (
    <div className="view">
      <style>{`
        .vstrip { display: flex; flex-wrap: wrap; gap: 3px; }
        .vstrip a { width: 26px; height: 22px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 3px; font: 600 11px var(--mono); color: var(--dim); }
        .vstrip a.on { border-color: var(--amber); color: var(--amber); box-shadow: var(--glow-amber); }
        .interlinear { display: flex; flex-wrap: wrap; direction: rtl; gap: 8px; }
        .tok { direction: ltr; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; cursor: pointer; min-width: 64px; background: rgba(255,255,255,.012); }
        .tok:hover, .tok.on { border-color: var(--gold); box-shadow: 0 0 10px rgba(232,196,106,.25); }
        .tok .he { font: 26px/1.4 var(--hebrew); color: var(--gold); direction: rtl; }
        .tok .tr { font: 11px var(--mono); color: var(--dim); }
        .tok .gl { font-size: 12px; text-align: center; max-width: 110px; }
        .tok.name { border-color: rgba(79,209,232,.5); }
        .tok.name .gl { color: var(--cyan); }
      `}</style>
      <div className="row" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>Verse X-ray</div>
          <h1>{m?.book_name ?? book} {ch}:{v}{m?.aliases.length ? <span className="muted mono" style={{ fontSize: 13, marginLeft: 10 }}>{m.aliases.join(" · ")}</span> : null}</h1>
        </div>
        <div className="spacer" />
        <select value={chapter} onChange={(e) => go("xray", `${e.target.value}.1`)}>
          {ingested.map((c) => <option key={c.ref} value={c.ref}>{c.ref.replace(".", " ")}</option>)}
        </select>
        <button className="btn small" disabled={n <= 1} onClick={() => go("xray", `${book}.${ch}.${n - 1}`)}>← Prev</button>
        <button className="btn small" disabled={n >= verses} onClick={() => go("xray", `${book}.${ch}.${n + 1}`)}>Next →</button>
      </div>
      <div className="vstrip" style={{ marginBottom: 14 }}>
        {Array.from({ length: verses }, (_, i) => i + 1).map((i) => (
          <a key={i} href={href("xray", `${book}.${ch}.${i}`)} className={i === n ? "on" : ""}>{i}</a>
        ))}
      </div>
      {error && <div className="intel red"><b>ERROR</b>{error}</div>}
      {!m && !error && <Loading what="Scanning" />}
      {m && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: 16, alignItems: "start" }}>
          <div className="grid">
            <Panel title="Source" right={<ReviewBar itemKey={`verse.en:${m.verse_id}`} />}>
              <div className="hebrew" style={{ fontSize: 30, lineHeight: 2, color: "var(--gold)", textAlign: "right", marginBottom: 14 }}>{m.source_text}</div>
              <div className="interlinear">
                {m.tokens.map((t) => (
                  <div key={t.pos} className={`tok ${t.name_ref ? "name" : ""} ${pinned?.pos === t.pos ? "on" : ""}`}
                       onMouseEnter={(e) => setHover({ t, x: e.clientX, y: e.clientY })}
                       onMouseMove={(e) => setHover({ t, x: e.clientX, y: e.clientY })}
                       onMouseLeave={() => setHover(null)} onClick={() => setPinned(t)}>
                    <span className="he">{t.surface}</span>
                    <span className="tr">{t.translit}</span>
                    <span className="gl">{t.gloss}</span>
                  </div>
                ))}
              </div>
            </Panel>
            <Layers m={m} />
            {m.philological_notes.length > 0 && (
              <Panel title="Philology" count={m.philological_notes.length}>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
                  {m.philological_notes.map((note) => (
                    <div key={note.term} className="panel" style={{ padding: 12 }}>
                      <div className="row"><span className="hebrew" style={{ fontSize: 24, color: "var(--gold)" }}>{note.term}</span>
                        <span className="mono muted">{note.translit}</span>{note.root && <span className="chip hebrew">√{note.root}</span>}</div>
                      <p style={{ margin: "6px 0 0", fontSize: 13 }}>{note.note}</p>
                      {note.sources && note.sources.length > 0 && <div className="muted" style={{ fontSize: 11 }}>{note.sources.join(" · ")}</div>}
                    </div>
                  ))}
                </div>
              </Panel>
            )}
          </div>
          <div className="grid">
            {pinned && <Panel title="Word" className="cyan"><TokenCard t={pinned} /></Panel>}
            <Panel title="Events" count={m.events.length}>
              <div className="grid">
                {m.events.length === 0 && <div className="muted">No events cover this verse yet.</div>}
                {m.events.map((e) => (
                  <div key={e.event_id}>
                    <a href={href("chronicle", e.event_id)} className="hud" style={{ fontWeight: 700, fontSize: 15 }}>{e.title ?? e.event_id}</a>
                    <EventBrief event={e} compact />
                  </div>
                ))}
              </div>
            </Panel>
            {m.ecs && (
              <>
                <Panel title="Present" count={m.ecs.entities.length}>
                  <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>{m.ecs.entities.map((e) => <EntityChip key={e.entity_id} entity={e} />)}</div>
                </Panel>
                {m.ecs.components.length > 0 && (
                  <Panel title="Active states" count={m.ecs.components.length}>
                    <div className="grid" style={{ gap: 6 }}>
                      {m.ecs.components.map((c) => (
                        <div key={c.component_id} style={{ fontSize: 13 }}>
                          <a href={href("dossiers", c.entity_id)}>{c.entity_id.split(".")[1]}</a>
                          <span className="muted"> · {c.label_key}: </span><b style={{ color: "var(--green)" }}>{c.label_value}</b>
                          <span className="mono faint"> {short(c.acquired_at_verse)}→{c.expired_at_verse ? short(c.expired_at_verse) : "…"}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>
                )}
                {m.ecs.edges.length > 0 && (
                  <Panel title="Interactions" count={m.ecs.edges.length}>
                    {m.ecs.edges.map((e) => (
                      <div key={e.edge_id} style={{ fontSize: 13 }}>{e.source.name} <span style={{ color: "var(--cyan)" }}>{e.interaction_label}</span> {e.target.name}</div>
                    ))}
                  </Panel>
                )}
                {m.ecs.system_instances.length > 0 && (
                  <Panel title="Rituals & mechanics" count={m.ecs.system_instances.length}>
                    {m.ecs.system_instances.map((i) => (
                      <div key={i.instance_id} style={{ fontSize: 13 }}><a href={href("codex", i.system_id)} style={{ color: "var(--violet)" }}>{i.system_name}</a> <span className="muted">{i.outcome_summary}</span></div>
                    ))}
                  </Panel>
                )}
              </>
            )}
          </div>
        </div>
      )}
      {hover && !pinned && (
        <div className="tooltip" style={{ left: Math.min(hover.x + 16, window.innerWidth - 360), top: hover.y + 16 }}><TokenCard t={hover.t} /></div>
      )}
    </div>
  );
}
