import { useEffect, useState } from "react";
import type { Token, VerseMatrix } from "../api";
import { EntityChip, EventBrief, Loading, Panel, ReviewBar } from "../components";
import { Msg, num, useT } from "../i18n";
import { useApi, useApp } from "../state";
import { decodeMorph, go, href, short, type Route } from "../util";

const LAYERS = ["literal", "dramatic", "commentary", "baseline", "audit"] as const;
type Layer = (typeof LAYERS)[number];

function TokenCard({ token: w }: { token: Token }) {
  const t = useT();
  const morph = decodeMorph(w.morph);
  return (
    <div className="grid" style={{ gap: 6 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="hebrew" style={{ fontSize: 30, color: "var(--gold)" }}>{w.surface}</span>
        <span className="mono muted">#{w.pos}</span>
      </div>
      <dl className="kv">
        {w.translit && <><dt>{t("xray.token.sound")}</dt><dd className="mono">{w.translit}</dd></>}
        {w.gloss && <><dt>{t("xray.token.gloss")}</dt><dd>{w.gloss}</dd></>}
        {w.lemma && <><dt>{t("xray.token.lemma")}</dt><dd className={/[\u0590-\u05FF]/.test(w.lemma) ? "hebrew" : "mono"} style={{ fontSize: /[\u0590-\u05FF]/.test(w.lemma) ? 18 : 12, textAlign: "left" }}>{w.lemma}</dd></>}
        {w.strongs && <><dt>{t("xray.token.strongs")}</dt><dd className="mono">{w.strongs}</dd></>}
        {morph.length > 0 && <><dt>{t("xray.token.grammar")}</dt><dd>{morph.slice(1).map((m) => <div key={m}>{m}</div>)}<span className="mono faint">{w.morph}</span></dd></>}
        {w.reading && <><dt>{t("xray.token.reading")}</dt><dd className="mono">{w.reading}</dd></>}
        {w.name_ref && <><dt>{t("xray.token.names")}</dt><dd className="mono" style={{ color: "var(--cyan)" }}>{w.name_ref}</dd></>}
      </dl>
    </div>
  );
}

function Layers({ m }: { m: VerseMatrix }) {
  const t = useT();
  const [layer, setLayer] = useState<Layer>("literal");
  const text: Record<Layer, string | null> = {
    literal: m.translation_literal, dramatic: m.translation_dramatic, commentary: m.directors_commentary,
    baseline: m.traditional_baseline, audit: null,
  };
  const missing = !m.translation_literal;
  const label = (l: Layer): string => {
    switch (l) {
      case "literal": return t("xray.layer.literal");
      case "dramatic": return t("xray.layer.dramatic");
      case "commentary": return t("xray.layer.commentary");
      case "baseline": return m.baseline_translation ?? t("xray.layer.baseline");
      case "audit": return t("xray.layer.audit");
    }
  };
  return (
    <Panel title={t("xray.layers")} right={m.layers_lang && m.layers_lang !== m.baseline_lang ? <span className="chip muted">{t("xray.layers_from", { lang: m.layers_lang })}</span> : undefined}>
      <div className="row" style={{ gap: 4, marginBottom: 12, flexWrap: "wrap" }}>
        {LAYERS.map((l) => (
          <span key={l} className={`chip click ${layer === l ? "on" : ""}`} onClick={() => setLayer(l)}>
            {label(l)}
          </span>
        ))}
      </div>
      {missing && layer !== "baseline" && (
        <div className="intel"><b>{t("xray.no_layers")}</b><Msg k="xray.no_layers_hint" vars={{ command: <span className="mono">/urim-philologist {m.verse_id}</span> }} /></div>
      )}
      {layer === "audit" && !missing ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div><div className="hud upper muted" style={{ fontSize: 10 }}>{t("xray.audit.tradition", { translation: m.baseline_translation ?? "" })}</div><p>{m.traditional_baseline}</p></div>
          <div><div className="hud upper" style={{ fontSize: 10, color: "var(--amber)" }}>{t("xray.audit.literal")}</div><p>{m.translation_literal}</p></div>
        </div>
      ) : (
        text[layer] && <p style={{ fontSize: layer === "dramatic" ? 18 : 15, lineHeight: 1.65, margin: 0, fontFamily: layer === "dramatic" ? "var(--hud)" : undefined }}>{text[layer]}</p>
      )}
    </Panel>
  );
}

export default function Xray({ route }: { route: Route }) {
  const { overview, lang } = useApp();
  const t = useT();
  const verseId = route.arg || "1KGS.18.27";
  const { data: m, error } = useApi<VerseMatrix>(`/api/verse/${encodeURIComponent(verseId)}?lang=${lang}`);
  const [hover, setHover] = useState<{ token: Token; x: number; y: number } | null>(null);
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
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("xray.kicker")}</div>
          <h1>{m?.book_name ?? book} {ch}:{v}{m?.aliases.length ? <span className="muted mono" style={{ fontSize: 13, marginLeft: 10 }}>{m.aliases.join(" · ")}</span> : null}</h1>
        </div>
        <div className="spacer" />
        <select value={chapter} onChange={(e) => go("xray", `${e.target.value}.1`)}>
          {ingested.map((c) => <option key={c.ref} value={c.ref}>{c.ref.replace(".", " ")}</option>)}
        </select>
        <button className="btn small" disabled={n <= 1} onClick={() => go("xray", `${book}.${ch}.${n - 1}`)}>{t("xray.prev")}</button>
        <button className="btn small" disabled={n >= verses} onClick={() => go("xray", `${book}.${ch}.${n + 1}`)}>{t("xray.next")}</button>
      </div>
      <div className="vstrip" style={{ marginBottom: 14 }}>
        {Array.from({ length: verses }, (_, i) => i + 1).map((i) => (
          <a key={i} href={href("xray", `${book}.${ch}.${i}`)} className={i === n ? "on" : ""}>{i}</a>
        ))}
      </div>
      {error && <div className="intel red"><b>{t("xray.error")}</b>{error}</div>}
      {!m && !error && <Loading what={t("xray.loading")} />}
      {m && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: 16, alignItems: "start" }}>
          <div className="grid">
            <Panel title={t("xray.source")} right={<ReviewBar itemKey={`verse.en:${m.verse_id}`} />}>
              <div className="hebrew" style={{ fontSize: 30, lineHeight: 2, color: "var(--gold)", textAlign: "right", marginBottom: 14 }}>{m.source_text}</div>
              <div className="interlinear">
                {m.tokens.map((token) => (
                  <div key={token.pos} className={`tok ${token.name_ref ? "name" : ""} ${pinned?.pos === token.pos ? "on" : ""}`}
                       onMouseEnter={(e) => setHover({ token, x: e.clientX, y: e.clientY })}
                       onMouseMove={(e) => setHover({ token, x: e.clientX, y: e.clientY })}
                       onMouseLeave={() => setHover(null)} onClick={() => setPinned(token)}>
                    <span className="he">{token.surface}</span>
                    <span className="tr">{token.translit}</span>
                    <span className="gl">{token.gloss}</span>
                  </div>
                ))}
              </div>
            </Panel>
            <Layers m={m} />
            {m.philological_notes.length > 0 && (
              <Panel title={t("xray.philology")} count={num(m.philological_notes.length)}>
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
            {pinned && <Panel title={t("xray.word")} className="cyan"><TokenCard token={pinned} /></Panel>}
            <Panel title={t("xray.events")} count={num(m.events.length)}>
              <div className="grid">
                {m.events.length === 0 && <div className="muted">{t("xray.no_events")}</div>}
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
                <Panel title={t("xray.present")} count={num(m.ecs.entities.length)}>
                  <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>{m.ecs.entities.map((e) => <EntityChip key={e.entity_id} entity={e} />)}</div>
                </Panel>
                {m.ecs.components.length > 0 && (
                  <Panel title={t("xray.active_states")} count={num(m.ecs.components.length)}>
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
                  <Panel title={t("xray.interactions")} count={num(m.ecs.edges.length)}>
                    {m.ecs.edges.map((e) => (
                      <div key={e.edge_id} style={{ fontSize: 13 }}>{e.source.name} <span style={{ color: "var(--cyan)" }}>{e.interaction_label}</span> {e.target.name}</div>
                    ))}
                  </Panel>
                )}
                {m.ecs.system_instances.length > 0 && (
                  <Panel title={t("xray.rituals")} count={num(m.ecs.system_instances.length)}>
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
        <div className="tooltip" style={{ left: Math.min(hover.x + 16, window.innerWidth - 360), top: hover.y + 16 }}><TokenCard token={hover.token} /></div>
      )}
    </div>
  );
}
