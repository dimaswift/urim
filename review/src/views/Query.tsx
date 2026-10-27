import { useEffect, useState } from "react";
import { api, post } from "../api";
import type { SearchHit } from "../api";
import { Panel } from "../components";
import { useApi, useApp } from "../state";
import { go } from "../util";

interface SqlResult { columns: string[]; rows: unknown[][]; truncated: boolean; ms: number }
interface TableInfo { schema: string; table: string; columns: string[] }

const EXAMPLES: [string, string][] = [
  ["Events in time order with their place", `SELECT e.event_id, t.title, e.utes_start, e.duration_seconds / 3600.0 AS hours, e.location_entity_id
FROM core_events e LEFT JOIN lang_en.i18n_events t USING (event_id)
ORDER BY e.utes_start`],
  ["Minchah fire to arrival at Jezreel (hours)", `SELECT (b.utes_end - a.utes_start) / 3600.0 AS hours
FROM core_events a, core_events b
WHERE a.event_id = 'evt.1kgs_18.minchah_fire' AND b.event_id = 'evt.1kgs_18.chariot_run_to_jezreel'`],
  ["Who holds which state, verse by verse", `SELECT c.entity_id, c.component_key, i.label_value, c.acquired_at_verse, c.expired_at_verse
FROM core_components c LEFT JOIN lang_en.i18n_components i USING (component_id)
ORDER BY c.utes_start`],
  ["Prophecies and how long fulfilment took (days)", `SELECT cause_event_id, effect_event_id, elapsed_seconds / 86400.0 AS days
FROM core_causal_edges WHERE causal_type = 'FULFILLS_PROPHECY'`],
  ["Places with their coordinate confidence", `SELECT entity_id, geo_lat, geo_lon, geo_source, geo_confidence
FROM core_entities WHERE geo_lat IS NOT NULL ORDER BY geo_confidence`],
  ["Words naming a person in 1 Kings 18", `SELECT v.verse_id, json_extract(t.value, '$.surface') AS word, json_extract(t.value, '$.name_ref') AS who
FROM core_verses v, json_each(v.tokens_json) t
WHERE v.verse_id LIKE '1KGS.18.%' AND json_extract(t.value, '$.name_ref') IS NOT NULL`],
];

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

export default function Query() {
  const { lang } = useApp();
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("all");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [sql, setSql] = useState(EXAMPLES[0][1]);
  const [result, setResult] = useState<SqlResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data: schema } = useApi<TableInfo[]>("/api/sql/schema");

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const id = setTimeout(() => {
      api<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}&scope=${scope}&lang=${lang}`).then(setHits).catch(() => setHits([]));
    }, 220);
    return () => clearTimeout(id);
  }, [q, scope, lang]);

  const run = async () => {
    setErr(null);
    try { setResult(await post<SqlResult>("/api/sql", { query: sql })); }
    catch (e) { setErr((e as Error).message); setResult(null); }
  };

  return (
    <div className="view" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 280px", gap: 16, alignItems: "start" }}>
      <div className="grid">
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>Signals intelligence</div>
          <h1>Query</h1>
        </div>
        <Panel title="Search" count={hits?.length}>
          <div className="row">
            <input autoFocus style={{ flex: 1, fontSize: 16 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Elijah, noon, mantle, Horeb, נביא…" />
            {["all", "verses", "events", "entities", "systems"].map((s) => (
              <span key={s} className={`chip click ${scope === s ? "on" : ""}`} onClick={() => setScope(s)}>{s}</span>
            ))}
          </div>
          {hits && (
            <div className="grid" style={{ gap: 6, marginTop: 12 }}>
              {hits.length === 0 && <div className="muted">No hits.</div>}
              {hits.map((h) => (
                <div key={h.kind + h.id} className="row" style={{ alignItems: "flex-start", cursor: "pointer", padding: "6px 4px", borderBottom: "1px solid var(--line)" }} onClick={() => open(h)}>
                  <span className="chip" style={{ minWidth: 64, justifyContent: "center" }}>{h.kind}</span>
                  <div style={{ flex: 1 }}>
                    <div className="hud" style={{ fontWeight: 700 }}>{h.title}</div>
                    <div className="muted" style={{ fontSize: 13 }}><Snippet text={h.snippet} /></div>
                  </div>
                  <span className="mono faint" title={`score ${h.score.toFixed(4)}`}>{(h.via ?? ["keyword"]).join(" + ")}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="SQL console (read-only)" right={<span className="muted mono" style={{ fontSize: 11 }}>core + lang_en / lang_ru</span>}>
          <div className="row" style={{ marginBottom: 8, flexWrap: "wrap", gap: 4 }}>
            {EXAMPLES.map(([label, text]) => <span key={label} className="chip click" onClick={() => setSql(text)}>{label}</span>)}
          </div>
          <textarea rows={6} className="mono" style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 12 }} value={sql}
                    onChange={(e) => setSql(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn amber" onClick={run}>Run <span className="kbd">⌘↵</span></button>
            {result && <span className="muted mono">{result.rows.length}{result.truncated ? "+" : ""} rows · {result.ms} ms</span>}
          </div>
          {err && <div className="intel red" style={{ marginTop: 10 }}><b>SQL ERROR</b>{err}</div>}
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
      <Panel title="Schema" count={schema?.length}>
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
