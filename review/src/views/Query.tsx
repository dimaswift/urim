import { useEffect, useState } from "react";
import { STATIC, api, post } from "../api";
import type { SearchHit } from "../api";
import { Panel, Similarity } from "../components";
import { num, useT, type TFunc } from "../i18n";
import { useApi, useApp } from "../state";
import { go } from "../util";

interface SqlResult { columns: string[]; rows: unknown[][]; truncated: boolean; ms: number }
interface TableInfo { schema: string; table: string; columns: string[] }

// The example queries; their descriptions are messages (examples() below).
const SQL = {
  events_in_order: `SELECT e.event_id, t.title, e.utes_start, e.duration_seconds / 3600.0 AS hours, e.location_entity_id
FROM core_events e LEFT JOIN lang_en.i18n_events t USING (event_id)
ORDER BY e.utes_start`,
  minchah_to_jezreel: `SELECT (b.utes_end - a.utes_start) / 3600.0 AS hours
FROM core_events a, core_events b
WHERE a.event_id = 'evt.1kgs_18.minchah_fire' AND b.event_id = 'evt.1kgs_18.chariot_run_to_jezreel'`,
  states_by_verse: `SELECT c.entity_id, c.component_key, i.label_value, c.acquired_at_verse, c.expired_at_verse
FROM core_components c LEFT JOIN lang_en.i18n_components i USING (component_id)
ORDER BY c.utes_start`,
  prophecies: `SELECT cause_event_id, effect_event_id, elapsed_seconds / 86400.0 AS days
FROM core_causal_edges WHERE causal_type = 'FULFILLS_PROPHECY'`,
  place_confidence: `SELECT entity_id, geo_lat, geo_lon, geo_source, geo_confidence
FROM core_entities WHERE geo_lat IS NOT NULL ORDER BY geo_confidence`,
  person_words: `SELECT v.verse_id, json_extract(t.value, '$.surface') AS word, json_extract(t.value, '$.name_ref') AS who
FROM core_verses v, json_each(v.tokens_json) t
WHERE v.verse_id LIKE '1KGS.18.%' AND json_extract(t.value, '$.name_ref') IS NOT NULL`,
};

function examples(t: TFunc): [string, string][] {
  return [
    [t("query.example.events_in_order"), SQL.events_in_order],
    [t("query.example.minchah_to_jezreel"), SQL.minchah_to_jezreel],
    [t("query.example.states_by_verse"), SQL.states_by_verse],
    [t("query.example.prophecies"), SQL.prophecies],
    [t("query.example.place_confidence"), SQL.place_confidence],
    [t("query.example.person_words"), SQL.person_words],
  ];
}

function Snippet({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]*\])/);
  return <span>{parts.map((p, i) => p.startsWith("[") ? <mark key={i} style={{ background: "rgba(255,179,71,.25)", color: "var(--amber)" }}>{p.slice(1, -1)}</mark> : p)}</span>;
}

function open(hit: SearchHit) {
  if (hit.kind === "verse") go("xray", hit.id);
  else if (hit.kind === "entity") go("dossiers", hit.id);
  else if (hit.kind === "system") go("codex", hit.id);
  else go("chronicle", hit.id);
}

function modes(t: TFunc): [string, string, string][] {
  const all: [string, string, string][] = [
    ["hybrid", t("query.mode.hybrid"), t("query.mode.hybrid_help")],
    ["keyword", t("query.mode.keyword"), t("query.mode.keyword_help")],
    ["meaning", t("query.mode.meaning"), t("query.mode.meaning_help")],
  ];
  // The static copy has no model to embed a query: words only.
  return STATIC ? all.filter(([m]) => m === "keyword") : all;
}

const SCOPES = ["all", "verses", "events", "entities", "systems"];
function scopeLabel(t: TFunc, scope: string): string {
  switch (scope) {
    case "all": return t("query.scope.all");
    case "verses": return t("query.scope.verses");
    case "events": return t("query.scope.events");
    case "entities": return t("query.scope.entities");
    case "systems": return t("query.scope.systems");
    default: return scope;
  }
}

/** A hit's kind as its tag shows it. */
function kindTag(t: TFunc, kind: string): string {
  switch (kind) {
    case "verse": return t("query.kind.verse");
    case "event": return t("query.kind.event");
    case "entity": return t("query.kind.entity");
    case "system": return t("query.kind.system");
    default: return kind;
  }
}

/** Which search found a hit: by words, by meaning. */
function viaLabel(t: TFunc, via: string): string {
  switch (via) {
    case "keyword": return t("query.via.keyword");
    case "meaning": return t("query.via.meaning");
    default: return via;
  }
}

const KIND_SCOPE: Record<string, string> = { verse: "verses", entity: "entities", system: "systems", event: "events" };

export default function Query() {
  const t = useT();
  const { lang } = useApp();
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("all");
  const [mode, setMode] = useState(STATIC ? "keyword" : "hybrid");
  const [like, setLike] = useState<SearchHit | null>(null);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [sql, setSql] = useState(SQL.events_in_order);
  const [result, setResult] = useState<SqlResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data: schema } = useApi<TableInfo[]>("/api/sql/schema");

  useEffect(() => {
    const path = like
      ? `/api/similar/${like.kind}/${encodeURIComponent(like.id)}?scope=${scope}&lang=${lang}&top_k=20`
      : q.trim() ? `/api/search?q=${encodeURIComponent(q)}&scope=${scope}&mode=${mode}&lang=${lang}` : null;
    if (!path) { setHits(null); setSearchErr(null); return; }
    let live = true;
    const id = setTimeout(() => {
      api<SearchHit[]>(path)
        .then((h) => { if (live) { setHits(h); setSearchErr(null); } })
        .catch((e) => { if (live) { setHits([]); setSearchErr((e as Error).message); } });
    }, like ? 0 : 220);
    return () => { live = false; clearTimeout(id); };
  }, [q, scope, mode, lang, like]);

  const findLike = (h: SearchHit) => { setLike(h); setScope(KIND_SCOPE[h.kind] ?? "all"); };

  const run = async () => {
    setErr(null);
    try { setResult(await post<SqlResult>("/api/sql", { query: sql })); }
    catch (e) { setErr((e as Error).message); setResult(null); }
  };

  return (
    <div className="view" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 280px", gap: 16, alignItems: "start" }}>
      <div className="grid">
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("query.kicker")}</div>
          <h1>{t("query.title")}</h1>
        </div>
        <Panel title={t("query.search")} count={hits?.length}>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <input autoFocus style={{ flex: "1 1 280px", fontSize: 16 }} value={q}
                   onChange={(e) => { setQ(e.target.value); setLike(null); }}
                   placeholder={t("query.placeholder")} />
            {modes(t).map(([m, label, help]) => (
              <span key={m} title={help} className={`chip click ${!like && mode === m ? "on" : ""}`} onClick={() => { setMode(m); setLike(null); }}>{label}</span>
            ))}
          </div>
          <div className="row" style={{ marginTop: 8, gap: 4, flexWrap: "wrap" }}>
            {SCOPES.map((s) => (
              <span key={s} className={`chip click ${scope === s ? "on" : ""}`} onClick={() => setScope(s)}>{scopeLabel(t, s)}</span>
            ))}
          </div>
          {like && (
            <div className="row" style={{ marginTop: 10, gap: 8 }}>
              <span className="hud upper muted" style={{ fontSize: 10 }}>{t("query.nearest_to")}</span>
              <span className="chip">{kindTag(t, like.kind)}</span><b className="hud">{like.title}</b>
              <span className="chip click" title={t("query.back_to_search")} onClick={() => setLike(null)}>✕</span>
            </div>
          )}
          {searchErr && <div className="intel red" style={{ marginTop: 10 }}><b>{t("query.search_error")}</b>{searchErr}</div>}
          {hits && !searchErr && (
            <div className="grid" style={{ gap: 6, marginTop: 12 }}>
              {hits.length === 0 && <div className="muted">{t("query.no_hits")}</div>}
              {hits.map((h) => (
                <div key={h.kind + h.id} className="row" style={{ alignItems: "flex-start", cursor: "pointer", padding: "6px 4px", borderBottom: "1px solid var(--line)" }} onClick={() => open(h)}>
                  <span className="chip" style={{ minWidth: 64, justifyContent: "center" }}>{kindTag(t, h.kind)}</span>
                  <div style={{ flex: 1 }}>
                    <div className="hud" style={{ fontWeight: 700 }}>{h.title}</div>
                    <div className="muted" style={{ fontSize: 13 }}><Snippet text={h.snippet} /></div>
                  </div>
                  <div style={{ display: "grid", justifyItems: "end", gap: 4 }}>
                    <span className="mono faint" style={{ fontSize: 11 }} title={t("query.score", { score: num(h.score, { minimumFractionDigits: 4, maximumFractionDigits: 4 }) })}>{(h.via ?? ["keyword"]).map((v) => viaLabel(t, v)).join(" + ")}</span>
                    <Similarity value={h.similarity} />
                    <span className="chip click" style={{ fontSize: 11 }} title={t("query.similar_title")}
                          onClick={(e) => { e.stopPropagation(); findLike(h); }}>≈ {t("query.similar")}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title={t("query.sql_console")} right={<span className="muted mono" style={{ fontSize: 11 }}>core + lang_en / lang_ru</span>}>
          <div className="row" style={{ marginBottom: 8, flexWrap: "wrap", gap: 4 }}>
            {examples(t).map(([label, text]) => <span key={label} className="chip click" onClick={() => setSql(text)}>{label}</span>)}
          </div>
          <textarea rows={6} className="mono" style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 12 }} value={sql}
                    onChange={(e) => setSql(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn amber" onClick={run}>{t("query.run")} <span className="kbd">⌘↵</span></button>
            {result && <span className="muted mono">{result.truncated ? t("query.rows_more", { count: result.rows.length }) : t("query.rows", { count: result.rows.length })} · {t("query.elapsed_ms", { ms: result.ms })}</span>}
          </div>
          {err && <div className="intel red" style={{ marginTop: 10 }}><b>{t("query.sql_error")}</b>{err}</div>}
          {result && (
            <div style={{ overflow: "auto", maxHeight: 420, marginTop: 10, border: "1px solid var(--line)" }}>
              <table className="data">
                <thead><tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{result.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v === null ? <span className="faint">null</span> : String(v)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
      <Panel title={t("query.schema")} count={schema?.length}>
        <div className="grid" style={{ gap: 8, maxHeight: "calc(100vh - 180px)", overflow: "auto" }}>
          {schema?.map((t) => (
            <details key={t.schema + t.table}>
              <summary className="mono" style={{ cursor: "pointer", fontSize: 12 }}>
                <span className="faint">{t.schema === "main" ? "" : t.schema + "."}</span><span style={{ color: "var(--amber)" }}>{t.table}</span>
              </summary>
              <div className="mono muted" style={{ fontSize: 11, paddingLeft: 12, lineHeight: 1.7 }}>
                {t.columns.map((c) => <div key={c} style={{ cursor: "pointer" }} onClick={() => setSql((s) => s + " " + c)}>{c}</div>)}
              </div>
            </details>
          ))}
        </div>
      </Panel>
    </div>
  );
}
