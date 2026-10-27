import { useMemo, useState } from "react";
import type { Dossier, EntityRow } from "../api";
import { Loading, Panel, ReviewBar } from "../components";
import { useApi, useApp } from "../state";
import { ENTITY_COLOR, ENTITY_GLYPH, chapterOf, go, href, short, type Route } from "../util";

interface EntityPayload { dossier: Dossier; mentions: { verse_id: string; pos: number }[] }
const TYPES = ["PERSON", "DEITY", "SPIRIT_BEING", "LOCATION", "GROUP", "ARTIFACT"];

function StatBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "92px 1fr 30px", gap: 8, alignItems: "center" }}>
      <span className="hud upper muted" style={{ fontSize: 10 }}>{label}</span>
      <div style={{ height: 8, background: "#0f1b25", border: "1px solid var(--line)", borderRadius: 2 }}>
        <div style={{ height: "100%", width: `${(value / Math.max(max, 1)) * 100}%`, background: color, boxShadow: `0 0 8px ${color}` }} />
      </div>
      <span className="mono" style={{ textAlign: "right" }}>{value}</span>
    </div>
  );
}

function Sheet({ id, roster }: { id: string; roster: EntityRow[] }) {
  const { lang, overview } = useApp();
  const { data } = useApi<EntityPayload>(`/api/entity/${encodeURIComponent(id)}?lang=${lang}`);
  if (!data) return <Loading what="Opening dossier" />;
  const d = data.dossier;
  const row = roster.find((r) => r.entity_id === id);
  const color = ENTITY_COLOR[d.entity_type] ?? "var(--text)";
  const max = (k: keyof EntityRow) => Math.max(...roster.map((r) => Number(r[k]) || 0));

  // Appearances: mentions per verse over the ingested chapters.
  const chapters = overview?.books.flatMap((b) => b.chapters.filter((c) => c.ingested)) ?? [];
  const perVerse = new Map<string, number>();
  data.mentions.forEach((m) => perVerse.set(m.verse_id, (perVerse.get(m.verse_id) ?? 0) + 1));
  const peak = Math.max(1, ...perVerse.values());

  // State timeline on a verse axis.
  const allVerses = chapters.flatMap((c) => Array.from({ length: c.verses ?? 0 }, (_, i) => `${c.ref}.${i + 1}`));
  const idx = (v: string) => Math.max(allVerses.indexOf(v), 0);
  const lo = Math.max(Math.min(...d.components.map((c) => idx(c.acquired_at_verse)), allVerses.length) - 2, 0);
  // Open-ended states get room past their start, even beyond the last ingested verse.
  const hi = Math.max(...d.components.map((c) => (c.expired_at_verse ? idx(c.expired_at_verse) + 2 : idx(c.acquired_at_verse) + 6)), lo + 4);
  const pos = (v: string) => (idx(v) - lo) / Math.max(hi - lo, 1);
  const axis = allVerses.slice(lo, hi + 1);
  const axisStep = Math.max(1, Math.ceil(axis.length / 10));

  return (
    <div className="grid">
      <Panel>
        <div className="row" style={{ gap: 18, alignItems: "flex-start" }}>
          <div style={{ width: 92, height: 92, display: "grid", placeItems: "center", fontSize: 48, color,
                        border: `1px solid ${color}`, borderRadius: 4, background: `color-mix(in srgb, ${color} 8%, transparent)`,
                        boxShadow: `0 0 20px color-mix(in srgb, ${color} 30%, transparent)` }}>{ENTITY_GLYPH[d.entity_type]}</div>
          <div style={{ flex: 1 }}>
            <div className="hud upper" style={{ fontSize: 11, color, letterSpacing: "0.3em" }}>{d.entity_type.replace("_", " ")}</div>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <h1>{d.canonical_name}</h1>
              {d.source_script_name && <span className="hebrew" style={{ fontSize: 30, color: "var(--gold)" }}>{d.source_script_name}</span>}
            </div>
            <div className="muted">{d.phonetic_name}{d.transliterated_name && <span className="mono"> · {d.transliterated_name}</span>}{d.aliases.length > 0 && ` · ${d.aliases.join(" · ")}`}</div>
            <div className="mono faint" style={{ marginTop: 4 }}>{d.entity_id} · {d.tipnr_id ?? "no TIPNR id"} · first at <a href={href("xray", d.first_mention_verse)}>{d.first_mention_verse}</a></div>
          </div>
          <ReviewBar itemKey={`entity:${d.entity_id}`} />
        </div>
        <p style={{ marginBottom: 6 }}>{d.summary_bio}</p>
        <div className="muted" style={{ fontSize: 13 }}><b className="hud upper" style={{ fontSize: 10, color: "var(--gold)" }}>Name means&nbsp;</b>{d.etymology_meaning}</div>
      </Panel>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Panel title="Stats">
          <div className="grid" style={{ gap: 8 }}>
            <StatBar label="Events" value={row?.events ?? 0} max={max("events")} color="var(--amber)" />
            <StatBar label="Interactions" value={row?.interactions ?? 0} max={max("interactions")} color="var(--cyan)" />
            <StatBar label="States" value={row?.states ?? 0} max={max("states")} color="var(--green)" />
            <StatBar label="Mentions" value={data.mentions.length} max={Math.max(data.mentions.length, 40)} color="var(--violet)" />
          </div>
          {d.geo && (
            <div style={{ marginTop: 12 }} className="row">
              <span className="mono">{d.geo.lat.toFixed(3)}, {d.geo.lon.toFixed(3)}</span>
              <span className="muted">{d.geo.source} {d.geo.confidence != null && `· ${Math.round(d.geo.confidence * 100)}%`}</span>
              <button className="btn small" onClick={() => go("atlas", d.entity_id)}>On the map</button>
            </div>
          )}
        </Panel>
        <Panel title="Appearances" count={data.mentions.length}>
          {chapters.map((c) => (
            <div key={c.ref} style={{ display: "grid", gridTemplateColumns: "56px 1fr", gap: 8, alignItems: "end", marginBottom: 6 }}>
              <span className="mono muted" style={{ fontSize: 10 }}>{c.ref.replace(".", " ")}</span>
              <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 28 }}>
                {Array.from({ length: c.verses ?? 0 }, (_, i) => {
                  const vid = `${c.ref}.${i + 1}`;
                  const n = perVerse.get(vid) ?? 0;
                  return <a key={vid} href={href("xray", vid)} title={`${short(vid)}: ${n}`} style={{ flex: 1, height: `${Math.max(n / peak, 0.08) * 100}%`, background: n ? "var(--violet)" : "#13202b", boxShadow: n ? "0 0 4px var(--violet)" : undefined }} />;
                })}
              </div>
            </div>
          ))}
          {data.mentions.length === 0 && <div className="muted">No word-level mentions (not a TIPNR individual).</div>}
        </Panel>
      </div>
      {d.components.length > 0 && (
        <Panel title="State timeline" count={d.components.length}>
          <div style={{ position: "relative" }}>
            {d.components.map((c) => {
              const a = pos(c.acquired_at_verse), b = c.expired_at_verse ? pos(c.expired_at_verse) : 1;
              return (
                <div key={c.component_id} style={{ position: "relative", height: 30, marginBottom: 4 }}>
                  <div style={{ position: "absolute", left: `${a * 100}%`, width: `${Math.max((b - a) * 100, 1.5)}%`, top: 4, height: 22,
                                background: "rgba(69,224,138,.18)", border: "1px solid var(--green)", borderRadius: 3,
                                borderRightStyle: c.expired_at_verse ? "solid" : "dashed", overflow: "hidden", whiteSpace: "nowrap" }}>
                    <span style={{ fontSize: 12, padding: "0 6px", lineHeight: "20px" }}><b className="st-approved">{c.label_value}</b> <span className="muted">{c.label_key}</span></span>
                  </div>
                </div>
              );
            })}
            <div className="row mono faint" style={{ fontSize: 10, justifyContent: "space-between" }}>
              {axis.filter((_, i) => i % axisStep === 0).map((v) => <a key={v} href={href("xray", v)} className="faint">{short(v)}</a>)}
            </div>
          </div>
        </Panel>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Panel title="Events" count={d.events.length}>
          {d.events.map((e) => (
            <div key={e.event_id} style={{ fontSize: 13, marginBottom: 4 }}>
              <a href={href("chronicle", e.event_id)}>{e.title}</a> <span className="mono muted">{short(e.verse_start)} · {e.start_label}</span>
            </div>
          ))}
        </Panel>
        <Panel title="Interactions" count={d.interactions.length}>
          {d.interactions.map((x) => (
            <div key={x.edge_id} style={{ fontSize: 13, marginBottom: 4 }}>
              <a href={href("dossiers", x.source.entity_id)}>{x.source.name}</a>{" "}
              <span style={{ color: "var(--cyan)" }}>{x.interaction_label ?? x.interaction_type}</span>{" "}
              <a href={href("dossiers", x.target.entity_id)}>{x.target.name}</a>
              <span className="mono muted"> {short(x.verse_id)}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

export default function Dossiers({ route }: { route: Route }) {
  const { lang, ledger } = useApp();
  const { data } = useApi<EntityRow[]>(`/api/entities?lang=${lang}`);
  const [type, setType] = useState<string | null>(null);
  const roster = useMemo(() => (data ?? [])
    .filter((r) => !type || r.entity_type === type)
    .sort((a, b) => TYPES.indexOf(a.entity_type) - TYPES.indexOf(b.entity_type) || b.events - a.events || a.name.localeCompare(b.name)), [data, type]);
  if (!data) return <Loading what="Mustering" />;
  const id = route.arg || data.find((r) => r.entity_type === "PERSON")?.entity_id || data[0]?.entity_id;
  return (
    <div className="view" style={{ display: "grid", gridTemplateColumns: "300px minmax(0, 1fr)", gap: 16 }}>
      <div>
        <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>Personnel & places</div>
        <h1 style={{ marginBottom: 10 }}>Dossiers</h1>
        <div className="row" style={{ flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
          <span className={`chip click ${!type ? "on" : ""}`} onClick={() => setType(null)}>All <span className="n">{data.length}</span></span>
          {TYPES.filter((t) => data.some((r) => r.entity_type === t)).map((t) => (
            <span key={t} className={`chip click ${type === t ? "on" : ""}`} onClick={() => setType(t)}>
              <span style={{ color: ENTITY_COLOR[t] }}>{ENTITY_GLYPH[t]}</span>{t.replace("_", " ").toLowerCase()}
            </span>
          ))}
        </div>
        <div className="grid" style={{ gap: 6 }}>
          {roster.map((r) => {
            const status = ledger[`entity:${r.entity_id}`]?.status;
            return (
              <a key={r.entity_id} href={href("dossiers", r.entity_id)} className="panel" style={{ padding: "8px 10px", display: "grid", gridTemplateColumns: "28px 1fr auto", gap: 8, alignItems: "center", color: "var(--text)", borderColor: r.entity_id === id ? "var(--amber)" : undefined }}>
                <span style={{ fontSize: 18, color: ENTITY_COLOR[r.entity_type] }}>{ENTITY_GLYPH[r.entity_type]}</span>
                <span>
                  <div className="hud" style={{ fontWeight: 700, fontSize: 14 }}>{r.name}</div>
                  <div className="mono faint" style={{ fontSize: 10 }}>{r.events} ev · {r.interactions} int · {r.states} st · {chapterOf(r.first_mention_verse)}</div>
                </span>
                <span className={`st-${status ?? ""}`} style={{ fontSize: 10 }}>{status === "approved" ? "✦" : status === "changes_requested" ? "!" : "•"}</span>
              </a>
            );
          })}
        </div>
      </div>
      {id ? <Sheet id={id} roster={data} /> : <div className="empty">No entities yet</div>}
    </div>
  );
}
