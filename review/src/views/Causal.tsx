import dagre from "@dagrejs/dagre";
import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CausalLink, EventView } from "../api";
import { CausalRow, EventBrief, Loading, Panel, ReviewBar } from "../components";
import { useT, type TFunc } from "../i18n";
import { useApi, useApp } from "../state";
import { duration, go, range, type Route } from "../util";

interface Data { events: EventView[]; links: CausalLink[] }
const W = 220, H = 66;
const TYPE_COLOR: Record<string, string> = {
  TRIGGERS: "var(--amber)", FULFILLS_PROPHECY: "var(--violet)", RETALIATES_FOR: "var(--red)",
  ENABLES: "var(--cyan)", DEFERRED_BY: "var(--gold)",
};

function typeName(t: TFunc, code: string): string {
  switch (code) {
    case "TRIGGERS": return t("causal.type.triggers");
    case "FULFILLS_PROPHECY": return t("causal.type.fulfills_prophecy");
    case "RETALIATES_FOR": return t("causal.type.retaliates_for");
    case "ENABLES": return t("causal.type.enables");
    case "DEFERRED_BY": return t("causal.type.deferred_by");
  }
  return code.replace("_", " ").toLowerCase();
}

function wrap(text: string, max = 30): string[] {
  const words = text.split(" ");
  const lines: string[] = [""];
  for (const w of words) {
    if ((lines.at(-1)! + " " + w).trim().length > max && lines.length < 2) lines.push(w);
    else lines[lines.length - 1] = (lines.at(-1)! + " " + w).trim();
  }
  if (lines[1] && lines[1].length > max) lines[1] = lines[1].slice(0, max - 1) + "…";
  return lines;
}

export default function Causal({ route }: { route: Route }) {
  const { lang, ledger } = useApp();
  const t = useT();
  const { data } = useApi<Data>(`/api/events?lang=${lang}`);
  const [showIsolated, setShowIsolated] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const focus = route.arg || null;

  const layout = useMemo(() => {
    if (!data) return null;
    const linked = new Set(data.links.flatMap((l) => [l.cause_event_id, l.effect_event_id]));
    const nodes = data.events.filter((e) => showIsolated || linked.has(e.event_id));
    const g = new dagre.graphlib.Graph({ multigraph: true });
    g.setGraph({ rankdir: "LR", nodesep: 26, ranksep: 90, marginx: 30, marginy: 30 });
    g.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((e) => g.setNode(e.event_id, { width: W, height: H }));
    data.links.forEach((l) => g.hasNode(l.cause_event_id) && g.hasNode(l.effect_event_id) && g.setEdge(l.cause_event_id, l.effect_event_id, { width: 120, height: 24 }, l.causal_id));
    dagre.layout(g);
    return { g, nodes, size: g.graph() as { width: number; height: number } };
  }, [data, showIsolated]);

  const chain = useMemo(() => {
    if (!data || !focus) return null;
    const up = new Set<string>([focus]), down = new Set<string>([focus]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const l of data.links) {
        if (up.has(l.effect_event_id) && !up.has(l.cause_event_id)) { up.add(l.cause_event_id); grew = true; }
        if (down.has(l.cause_event_id) && !down.has(l.effect_event_id)) { down.add(l.effect_event_id); grew = true; }
      }
    }
    return new Set([...up, ...down]);
  }, [data, focus]);

  useEffect(() => {
    if (!svgRef.current || !gRef.current || !layout) return;
    const svg = d3.select(svgRef.current), g = d3.select(gRef.current);
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 3]).on("zoom", (e) => g.attr("transform", e.transform.toString()));
    svg.call(zoom);
    const { width, height } = svgRef.current.getBoundingClientRect();
    const k = Math.min(width / layout.size.width, height / layout.size.height, 1);
    svg.call(zoom.transform, d3.zoomIdentity.translate((width - layout.size.width * k) / 2, (height - layout.size.height * k) / 2).scale(k));
  }, [layout]);

  if (!data || !layout) return <Loading what={t("causal.loading")} />;
  const titles = Object.fromEntries(data.events.map((e) => [e.event_id, e.title]));
  const ev = focus ? data.events.find((e) => e.event_id === focus) : null;
  const line = d3.line<{ x: number; y: number }>().x((p) => p.x).y((p) => p.y).curve(d3.curveBasis);

  return (
    <div className="view full" style={{ display: "grid", gridTemplateColumns: ev ? "1fr 360px" : "1fr", height: "100%" }}>
      <div style={{ position: "relative" }}>
        <div className="row" style={{ position: "absolute", left: 20, top: 16, zIndex: 2, flexWrap: "wrap" }}>
          <div>
            <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("causal.kicker")}</div>
            <h1>{t("causal.title")}</h1>
          </div>
        </div>
        <div className="row" style={{ position: "absolute", left: 20, top: 76, zIndex: 2, gap: 6, flexWrap: "wrap" }}>
          {Object.entries(TYPE_COLOR).map(([code, c]) => <span key={code} className="chip" style={{ color: c }}>■ {typeName(t, code)}</span>)}
          <span className={`chip click ${showIsolated ? "on" : ""}`} onClick={() => setShowIsolated((v) => !v)}>{t("causal.isolated")}</span>
          {focus && <span className="chip click" onClick={() => go("causal")}>{t("causal.clear_focus")}</span>}
        </div>
        <svg ref={svgRef} className="svg-fill" style={{ cursor: "grab" }}>
          <defs>
            {Object.entries(TYPE_COLOR).map(([code, c]) => (
              <marker key={code} id={`arrow-${code}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 0 10 5 0 10z" fill={c} />
              </marker>
            ))}
          </defs>
          <g ref={gRef}>
            {data.links.map((l) => {
              const e = layout.g.edge(l.cause_event_id, l.effect_event_id, l.causal_id) as { points: { x: number; y: number }[]; x: number; y: number } | undefined;
              if (!e) return null;
              const dim = chain && !(chain.has(l.cause_event_id) && chain.has(l.effect_event_id));
              const color = TYPE_COLOR[l.causal_type.code] ?? "var(--dim)";
              return (
                <g key={l.causal_id} opacity={dim ? 0.12 : 1}>
                  <path d={line(e.points) ?? ""} fill="none" stroke={color} strokeWidth={1.8} markerEnd={`url(#arrow-${l.causal_type.code})`}
                        strokeDasharray={l.causal_type.code === "FULFILLS_PROPHECY" ? "6 4" : undefined} />
                  <rect x={e.x - 52} y={e.y - 10} width={104} height={20} rx={3} fill="#071018" stroke={color} strokeOpacity={0.5} />
                  <text x={e.x} y={e.y + 4} textAnchor="middle" fontSize="10" fontFamily="var(--mono)" fill={color}>
                    {l.elapsed_seconds < 0 ? t("causal.overlap") : `+${duration(l.elapsed_seconds, 1)}`}
                  </text>
                </g>
              );
            })}
            {layout.nodes.map((e) => {
              const n = layout.g.node(e.event_id);
              const status = ledger[`event:${e.event_id}`]?.status;
              const color = status === "approved" ? "var(--green)" : status === "changes_requested" ? "var(--red)" : "var(--amber)";
              const dim = chain && !chain.has(e.event_id);
              const on = e.event_id === focus;
              const lines = wrap(e.title ?? e.event_id);
              return (
                <g key={e.event_id} transform={`translate(${n.x - W / 2}, ${n.y - H / 2})`} opacity={dim ? 0.18 : 1}
                   style={{ cursor: "pointer" }} onClick={() => go("causal", e.event_id)}>
                  <rect width={W} height={H} rx={4} fill={on ? "#1a1408" : "#0b141c"} stroke={color} strokeWidth={on ? 2 : 1}
                        style={{ filter: on ? `drop-shadow(0 0 8px ${color})` : undefined }} />
                  <rect width={4} height={H} fill={color} />
                  {lines.map((text, i) => <text key={i} x={12} y={20 + i * 15} fontSize="12.5" fontWeight="700" fontFamily="var(--hud)" fill="var(--text)">{text}</text>)}
                  <text x={12} y={H - 9} fontSize="10" fontFamily="var(--mono)" fill="var(--dim)">{range(e.verse_start, e.verse_end)} · {e.start_label}</text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      {ev && (
        <div style={{ borderLeft: "1px solid var(--line)", overflow: "auto", padding: 16 }}>
          <Panel title={t("causal.focus")} right={<ReviewBar itemKey={`event:${ev.event_id}`} />}>
            <h2 style={{ marginBottom: 8 }}>{ev.title}</h2>
            <EventBrief event={ev} />
            <div className="grid" style={{ gap: 6, marginTop: 12 }}>
              {data.links.filter((l) => l.cause_event_id === ev.event_id || l.effect_event_id === ev.event_id).map((l) => (
                <CausalRow key={l.causal_id} link={l} titles={titles} from={ev.event_id} />
              ))}
            </div>
            <button className="btn small" style={{ marginTop: 12 }} onClick={() => go("chronicle", ev.event_id)}>{t("causal.open_chronicle")}</button>
          </Panel>
        </div>
      )}
    </div>
  );
}
