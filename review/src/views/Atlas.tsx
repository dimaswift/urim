import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Journey, Place } from "../api";
import { Loading, Panel, ReviewBar } from "../components";
import { num, useT } from "../i18n";
import { useApi, useApp } from "../state";
import { go, href, type Route } from "../util";

type LonLat = [number, number];
interface Basemap {
  bbox: [number, number, number, number];
  land: { rings: LonLat[][] }[];
  lakes: { rings: LonLat[][]; name: string | null }[];
  rivers: { line: LonLat[]; name: string | null; scalerank: number | null }[];
  // Natural Earth names, with name_ru and name_he where the basemap has them.
  regions: { name: string; kind: string; lon: number; lat: number; min_zoom: number | null; [k: `name_${string}`]: string | undefined }[];
}
/** A share as a whole percent in the active language: 0.85 -> "85%" (or "85 %"). */
const pct = (x: number) => num(Math.round(x * 100) / 100, { style: "percent" });

interface AtlasData {
  places: Place[]; journeys: Journey[];
  events: Record<string, { title: string | null; label: string; utes: number }>;
}

export default function Atlas({ route }: { route: Route }) {
  const t = useT();
  const { lang, ledger } = useApp();
  const { data } = useApi<AtlasData>(`/api/atlas?lang=${lang}`);
  const [base, setBase] = useState<Basemap | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 1000, h: 700 });
  const [zt, setZt] = useState(d3.zoomIdentity);
  const [journeyId, setJourneyId] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const selected = route.arg || null;

  useEffect(() => { fetch("/geo/near_east.json").then((r) => r.json()).then(setBase); }, []);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const ro = new ResizeObserver(() => setSize({ w: svg.clientWidth, h: svg.clientHeight }));
    ro.observe(svg);
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.6, 60]).on("zoom", (e) => setZt(e.transform));
    d3.select(svg).call(zoom);
    return () => ro.disconnect();
  }, [base]);
  useEffect(() => { if (data && !journeyId && data.journeys.length) setJourneyId(data.journeys[0].entity_id); }, [data, journeyId]);

  // Fit the projection to the places (the theatre), with the Near East around them.
  const projection = useMemo(() => {
    const pts = data?.places.length ? data.places.map((p) => [p.lon, p.lat] as LonLat) : [[34, 29], [37, 34]] as LonLat[];
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    const pad = 1.2;
    const frame: GeoJSON.Feature = { type: "Feature", properties: {}, geometry: { type: "MultiPoint", coordinates: [
      [Math.min(...lons) - pad, Math.min(...lats) - pad], [Math.max(...lons) + pad, Math.max(...lats) + pad]] } };
    return d3.geoMercator().fitExtent([[40, 40], [size.w - 40, size.h - 40]], frame);
  }, [data, size]);

  const P = (lonlat: LonLat) => { const p = projection(lonlat)!; return [zt.applyX(p[0]), zt.applyY(p[1])]; };
  const ringPath = (ring: LonLat[]) => ring.map((p, i) => { const [x, y] = P(p); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("") + "Z";
  const linePath = (line: LonLat[]) => line.map((p, i) => { const [x, y] = P(p); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("");

  const journey = data?.journeys.find((j) => j.entity_id === journeyId) ?? null;
  const placeById = useMemo(() => Object.fromEntries((data?.places ?? []).map((p) => [p.entity_id, p])), [data]);
  const stops = (journey?.stops ?? []).filter((s) => placeById[s.place]);

  // Play: move a token along the route, one leg per second.
  const play = () => {
    if (!stops.length) return;
    const legs = Math.max(stops.length - 1, 1);
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / (legs * 1100), 1);
      setProgress(p);
      if (p < 1) requestAnimationFrame(tick);
      else setTimeout(() => setProgress(null), 1600);
    };
    requestAnimationFrame(tick);
  };
  let token: { x: number; y: number; stop: number } | null = null;
  if (progress !== null && stops.length > 1) {
    const legs = stops.length - 1;
    const f = progress * legs, i = Math.min(Math.floor(f), legs - 1), u = f - i;
    const a = placeById[stops[i].place], b = placeById[stops[i + 1].place];
    const [ax, ay] = P([a.lon, a.lat]), [bx, by] = P([b.lon, b.lat]);
    token = { x: ax + (bx - ax) * u, y: ay + (by - ay) * u, stop: u > 0.5 ? i + 1 : i };
  }

  if (!data || !base) return <Loading what={t("atlas.loading")} />;
  const place = selected ? placeById[selected] : null;
  const k = zt.k;
  const maxEvents = Math.max(1, ...data.places.map((p) => p.events.length));
  const labelAt = new Map<string, { dy: number }>();
  {
    const boxes: { x0: number; x1: number; y0: number; y1: number }[] = [];
    const sorted = [...data.places].sort((a, b) => P([a.lon, a.lat])[1] - P([b.lon, b.lat])[1]);
    for (const p of sorted) {
      const [x, y] = P([p.lon, p.lat]);
      const r = 5 + 7 * (p.events.length / maxEvents);
      const x0 = x + r + 6, x1 = x0 + p.name.length * 7.4;
      let dy = 0;
      for (const step of [0, 15, -15, 30, -30, 45, -45]) {
        const y0 = y - 8 + step, y1 = y + 6 + step;
        if (!boxes.some((b) => x0 < b.x1 && x1 > b.x0 && y0 < b.y1 && y1 > b.y0)) { dy = step; break; }
      }
      boxes.push({ x0, x1, y0: y - 8 + dy, y1: y + 6 + dy });
      labelAt.set(p.entity_id, { dy });
    }
  }

  return (
    <div className="view full" style={{ display: "grid", gridTemplateColumns: "1fr 340px", height: "100%" }}>
      <div style={{ position: "relative", background: "radial-gradient(ellipse at 40% 40%, #08131c, #03060a 70%)" }}>
        <div style={{ position: "absolute", left: 20, top: 16, zIndex: 2, pointerEvents: "none" }}>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("atlas.kicker")}</div>
          <h1>{t("atlas.title")}</h1>
        </div>
        <svg ref={svgRef} className="svg-fill" style={{ cursor: "grab" }}>
          <defs>
            <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
            <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(79,209,232,.05)" strokeWidth="2" /></pattern>
          </defs>
          {d3.range(base.bbox[0], base.bbox[2] + 0.1, 1).map((lon) => <path key={`lo${lon}`} d={linePath([[lon, base.bbox[1]], [lon, base.bbox[3]]])} stroke="rgba(79,209,232,.07)" fill="none" />)}
          {d3.range(base.bbox[1], base.bbox[3] + 0.1, 1).map((lat) => <path key={`la${lat}`} d={linePath([[base.bbox[0], lat], [base.bbox[2], lat]])} stroke="rgba(79,209,232,.07)" fill="none" />)}
          <g>
            {base.land.map((l, i) => <path key={i} d={l.rings.map(ringPath).join("")} fill="var(--land)" fillRule="evenodd" stroke="#2f5a72" strokeWidth={1} />)}
            {base.land.map((l, i) => <path key={`h${i}`} d={l.rings.map(ringPath).join("")} fill="url(#hatch)" fillRule="evenodd" />)}
            {base.land.map((l, i) => <path key={`g${i}`} d={l.rings.map(ringPath).join("")} fill="none" stroke="rgba(79,209,232,.35)" strokeWidth={2.5} filter="url(#glow)" opacity={0.5} />)}
          </g>
          {base.lakes.map((l, i) => <path key={i} d={l.rings.map(ringPath).join("")} fill="#04101a" stroke="rgba(79,209,232,.6)" strokeWidth={0.8} />)}
          {base.rivers.map((r, i) => <path key={i} d={linePath(r.line)} fill="none" stroke="rgba(79,209,232,.45)" strokeWidth={r.name === "Jordan" ? 1.6 : 0.9} />)}
          {base.regions.filter((r) => (r.min_zoom ?? 5) <= 3.4 + Math.log2(k) * 1.6 + (r.kind === "Desert" || r.kind === "Geoarea" ? 1 : 0)).map((r) => {
            const [x, y] = P([r.lon, r.lat]);
            return <text key={r.name} x={x} y={y} textAnchor="middle" fill="rgba(160,190,210,.32)" fontFamily="var(--hud)" fontSize={11} fontWeight={600} letterSpacing="0.35em">{(r[`name_${lang}`] ?? r.name).toUpperCase()}</text>;
          })}
          {journey && stops.length > 1 && (
            <g>
              <path d={linePath(stops.map((s) => [placeById[s.place].lon, placeById[s.place].lat] as LonLat))} fill="none"
                    stroke="var(--amber)" strokeWidth={2.2} strokeDasharray="8 6" filter="url(#glow)">
                <animate attributeName="stroke-dashoffset" from="28" to="0" dur="1.2s" repeatCount="indefinite" />
              </path>
              {stops.map((s, i) => {
                const [x, y] = P([placeById[s.place].lon, placeById[s.place].lat]);
                return (
                  <g key={`${s.event_id}${i}`} transform={`translate(${x + 10},${y - 14 - (i % 2) * 14})`}>
                    <circle r={8} fill="#1a1006" stroke="var(--amber)" />
                    <text y={3.5} textAnchor="middle" fontSize="9" fontFamily="var(--mono)" fill="var(--amber)">{i + 1}</text>
                  </g>
                );
              })}
            </g>
          )}
          {data.places.map((p) => {
            const [x, y] = P([p.lon, p.lat]);
            const r = 5 + 7 * (p.events.length / maxEvents);
            const status = ledger[`entity:${p.entity_id}`]?.status;
            const color = status === "approved" ? "var(--green)" : status === "changes_requested" ? "var(--red)" : "var(--cyan)";
            const conf = p.confidence ?? 0.5;
            const on = p.entity_id === selected;
            return (
              <g key={p.entity_id} transform={`translate(${x},${y})`} style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); go("atlas", p.entity_id); }}>
                <circle r={r + 10 + (1 - conf) * 18} fill={color} fillOpacity={0.06} stroke={color} strokeOpacity={0.5}
                        strokeDasharray={conf < 0.7 ? "3 4" : undefined}><title>{t("atlas.confidence_title", { pct: pct(conf), source: p.source ?? "" })}</title></circle>
                <circle r={r} fill={color} fillOpacity={on ? 0.9 : 0.55} stroke={on ? "#fff" : color} filter="url(#glow)" />
                {(labelAt.get(p.entity_id)?.dy ?? 0) !== 0 && (
                  <line x1={r} y1={0} x2={r + 6} y2={labelAt.get(p.entity_id)!.dy} stroke="var(--dim)" strokeWidth={0.8} />
                )}
                <text x={r + 8} y={4 + (labelAt.get(p.entity_id)?.dy ?? 0)} fill="var(--text)" fontFamily="var(--hud)" fontWeight={700} fontSize={13} letterSpacing="0.06em"
                      style={{ paintOrder: "stroke", stroke: "#03070b", strokeWidth: 4 }}>{p.name}</text>
              </g>
            );
          })}
          {token && (
            <g transform={`translate(${token.x},${token.y})`}>
              <circle r={9} fill="var(--amber)" filter="url(#glow)" />
              <circle r={16} fill="none" stroke="var(--amber)" strokeOpacity={0.6}>
                <animate attributeName="r" from="9" to="24" dur="0.9s" repeatCount="indefinite" />
                <animate attributeName="stroke-opacity" from="0.7" to="0" dur="0.9s" repeatCount="indefinite" />
              </circle>
            </g>
          )}
        </svg>
        {token && journey && (
          <div className="panel" style={{ position: "absolute", left: 20, bottom: 20, padding: "10px 14px", minWidth: 320 }}>
            <div className="hud upper" style={{ fontSize: 10, color: "var(--amber)" }}>{t("atlas.token_stop", { journey: journey.name, n: token.stop + 1, total: stops.length })}</div>
            <div className="hud" style={{ fontSize: 17, fontWeight: 700 }}>{stops[token.stop].title}</div>
            <div className="mono muted">{stops[token.stop].label} · {placeById[stops[token.stop].place].name}</div>
          </div>
        )}
        <div className="muted mono" style={{ position: "absolute", right: 12, bottom: 8, fontSize: 10 }}>{t("atlas.credits")}</div>
      </div>
      <div style={{ borderLeft: "1px solid var(--line)", overflow: "auto", padding: 16 }} className="grid">
        <Panel title={t("atlas.journeys")} count={data.journeys.length}>
          <div className="grid" style={{ gap: 6 }}>
            {data.journeys.map((j) => (
              <div key={j.entity_id} className={`chip click ${j.entity_id === journeyId ? "on" : ""}`} style={{ justifyContent: "space-between" }} onClick={() => setJourneyId(j.entity_id)}>
                <span>♟ {j.name}</span><span className="n">{t("atlas.stops", { count: j.stops.length })}</span>
              </div>
            ))}
            {journey && <button className="btn amber" onClick={play} disabled={progress !== null}>▶ {t("atlas.play_route", { name: journey.name })}</button>}
          </div>
          {journey && (
            <ol style={{ margin: "12px 0 0", paddingLeft: 20, fontSize: 12 }}>
              {stops.map((s, i) => (
                <li key={i} style={{ marginBottom: 4, color: token?.stop === i ? "var(--amber)" : undefined }}>
                  <a href={href("chronicle", s.event_id)}>{s.title}</a>
                  <div className="muted mono" style={{ fontSize: 10 }}>{placeById[s.place].name} · {s.label}</div>
                </li>
              ))}
            </ol>
          )}
        </Panel>
        {place && (
          <Panel title={t("atlas.place")} className="cyan" right={<ReviewBar itemKey={`entity:${place.entity_id}`} />}>
            <h2>{place.name}</h2>
            <dl className="kv" style={{ margin: "8px 0" }}>
              <dt>{t("atlas.position")}</dt><dd className="mono">{place.lat.toFixed(3)}, {place.lon.toFixed(3)}</dd>
              <dt>{t("atlas.source")}</dt><dd>{place.source}</dd>
              <dt>{t("atlas.confidence")}</dt><dd>
                <div style={{ height: 6, width: 160, background: "#132230", borderRadius: 3 }}>
                  <div style={{ height: "100%", width: `${(place.confidence ?? 0) * 100}%`, background: "var(--cyan)", borderRadius: 3, boxShadow: "var(--glow-cyan)" }} />
                </div>
                <span className="mono muted">{place.confidence != null ? pct(place.confidence) : t("atlas.confidence_unknown")}</span>
              </dd>
            </dl>
            <div className="hud upper muted" style={{ fontSize: 10 }}>{t("atlas.events_here")}</div>
            {place.events.map((id) => <div key={id} style={{ fontSize: 13 }}><a href={href("chronicle", id)}>{data.events[id]?.title}</a> <span className="mono muted">{data.events[id]?.label}</span></div>)}
            <a href={href("dossiers", place.entity_id)} style={{ display: "block", marginTop: 8 }}>{t("atlas.open_dossier")} →</a>
          </Panel>
        )}
        <Panel title={t("atlas.places")} count={data.places.length}>
          {data.places.map((p) => (
            <div key={p.entity_id} className="row" style={{ fontSize: 13, cursor: "pointer", padding: "3px 0" }} onClick={() => go("atlas", p.entity_id)}>
              <span style={{ color: "var(--cyan)" }}>⌖</span><span style={{ flex: 1 }}>{p.name}</span>
              <span className="mono muted">{t("atlas.events_short", { count: p.events.length })}</span>
              <span className="mono" style={{ width: 38, textAlign: "right", color: (p.confidence ?? 0) < 0.7 ? "var(--amber)" : "var(--dim)" }}>{p.confidence != null ? pct(p.confidence) : "—"}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}
