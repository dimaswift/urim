import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Journey, Place } from "../api";
import { useApi } from "../hooks";
import { go, href, type Route } from "../util";
import { useLang } from "./parts";

type LonLat = [number, number];
interface Basemap {
  bbox: [number, number, number, number];
  land: { rings: LonLat[][] }[];
  lakes: { rings: LonLat[][] }[];
  rivers: { line: LonLat[]; name: string | null }[];
  regions: { name: string; name_ru: string | null; kind: string; lon: number; lat: number; min_zoom: number | null }[];
}
interface Atlas { places: Place[]; journeys: Journey[]; events: Record<string, { title: string | null; label: string }> }

function Compass({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x},${y})`} fill="none" stroke="var(--ink-2)" strokeWidth="1">
      <circle r="34" strokeOpacity="0.5" /><circle r="28" strokeOpacity="0.3" />
      <path d="M0 -40 L6 0 L0 40 L-6 0 Z" fill="var(--ink-2)" fillOpacity="0.15" />
      <path d="M0 -40 L6 0 L0 0 Z" fill="var(--rubric)" stroke="none" />
      <path d="M-40 0 L0 -5 L40 0 L0 5 Z" fill="var(--ink-2)" fillOpacity="0.12" />
      <text y="-46" textAnchor="middle" fill="var(--rubric)" stroke="none" fontFamily="var(--caps)" fontSize="13" fontWeight="700">N</text>
    </g>
  );
}

export default function Mappa({ route }: { route: Route }) {
  const { lang } = useLang();
  const { data } = useApi<Atlas>(`/api/atlas?lang=${lang}`);
  const [base, setBase] = useState<Basemap | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 1100, h: 720 });
  const [t, setT] = useState(d3.zoomIdentity);
  const [who, setWho] = useState<string | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const selected = route.arg || null;

  useEffect(() => { fetch("/geo/near_east.json").then((r) => r.json()).then(setBase); }, []);
  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const ro = new ResizeObserver(() => setSize({ w: svg.clientWidth, h: svg.clientHeight }));
    ro.observe(svg);
    d3.select(svg).call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.6, 40]).on("zoom", (e) => setT(e.transform)));
    return () => ro.disconnect();
  }, [base, data]);
  useEffect(() => { if (data && !who && data.journeys[0]) setWho(data.journeys[0].entity_id); }, [data, who]);

  const projection = useMemo(() => {
    const pts = data?.places.map((p) => [p.lon, p.lat] as LonLat) ?? [[34, 29], [37, 34]];
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    const frame: GeoJSON.Feature = { type: "Feature", properties: {}, geometry: { type: "MultiPoint", coordinates: [
      [Math.min(...lons) - 1.6, Math.min(...lats) - 1.2], [Math.max(...lons) + 1.6, Math.max(...lats) + 1.2]] } };
    return d3.geoMercator().fitExtent([[60, 60], [size.w - 60, size.h - 60]], frame);
  }, [data, size]);

  if (!data || !base) return <div className="loading">Unrolling the chart…</div>;
  const P = (p: LonLat) => { const q = projection(p)!; return [t.applyX(q[0]), t.applyY(q[1])]; };
  const ring = (r: LonLat[]) => r.map((p, i) => { const [x, y] = P(p); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("") + "Z";
  const line = (l: LonLat[]) => l.map((p, i) => { const [x, y] = P(p); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("");
  const places = Object.fromEntries(data.places.map((p) => [p.entity_id, p]));
  const journey = data.journeys.find((j) => j.entity_id === who);
  const stops = (journey?.stops ?? []).filter((s) => places[s.place]);
  const shown = step === null ? stops.length : step + 1;
  const place = selected ? places[selected] : null;
  const landPath = base.land.map((l) => l.rings.map(ring).join("")).join("");

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", height: "calc(100vh - 62px)" }}>
      <div style={{ position: "relative", margin: 16, border: "1px solid var(--rule)", boxShadow: "0 12px 30px rgba(90,60,20,.15)", background: "#dfe3d3" }}>
        <svg ref={ref} style={{ width: "100%", height: "100%", display: "block", cursor: "grab" }}>
          <defs>
            <pattern id="waves" width="22" height="10" patternUnits="userSpaceOnUse">
              <path d="M0 6 Q5.5 2 11 6 T22 6" fill="none" stroke="rgba(36,71,111,.13)" strokeWidth="0.8" />
            </pattern>
            <filter id="ink"><feTurbulence baseFrequency="0.9" numOctaves="2" seed="3" /><feDisplacementMap in="SourceGraphic" scale="1.2" /></filter>
          </defs>
          <rect width="100%" height="100%" fill="url(#waves)" />
          {d3.range(base.bbox[0], base.bbox[2] + 0.1, 2).map((lon) => <path key={`o${lon}`} d={line([[lon, base.bbox[1]], [lon, base.bbox[3]]])} stroke="rgba(78,59,40,.12)" fill="none" strokeDasharray="2 4" />)}
          {d3.range(base.bbox[1], base.bbox[3] + 0.1, 2).map((lat) => <path key={`a${lat}`} d={line([[base.bbox[0], lat], [base.bbox[2], lat]])} stroke="rgba(78,59,40,.12)" fill="none" strokeDasharray="2 4" />)}
          <path d={landPath} fill="none" stroke="rgba(78,59,40,.18)" strokeWidth="7" />
          <path d={landPath} fill="#f1e3c0" fillRule="evenodd" stroke="#6b4f2a" strokeWidth="1.1" filter="url(#ink)" />
          {base.lakes.map((l, i) => <path key={i} d={l.rings.map(ring).join("")} fill="#cfdccf" stroke="#4e6b78" strokeWidth="0.8" />)}
          {base.rivers.map((r, i) => <path key={i} d={line(r.line)} fill="none" stroke="#3c6488" strokeOpacity={0.7} strokeWidth={r.name === "Jordan" ? 1.6 : 0.9} />)}
          {base.regions.filter((r) => (r.min_zoom ?? 5) <= 4 + Math.log2(t.k) * 1.6).map((r) => {
            const [x, y] = P([r.lon, r.lat]);
            const name = lang === "ru" && r.name_ru ? r.name_ru : r.name;
            return <text key={r.name} x={x} y={y} textAnchor="middle" fill="rgba(78,59,40,.45)" fontFamily="var(--serif)" fontStyle="italic" fontSize={14} letterSpacing="0.25em">{name.toUpperCase()}</text>;
          })}
          {journey && shown > 1 && (
            <path d={line(stops.slice(0, shown).map((s) => [places[s.place].lon, places[s.place].lat] as LonLat))}
                  fill="none" stroke="var(--rubric)" strokeWidth={2.2} strokeDasharray="7 5" strokeLinecap="round" />
          )}
          {journey && stops.slice(0, shown).map((s, i) => {
            const [x, y] = P([places[s.place].lon, places[s.place].lat]);
            return (
              <g key={i} transform={`translate(${x - 14 - (i % 2) * 12},${y - 12})`}>
                <circle r={8.5} fill="var(--page)" stroke="var(--rubric)" strokeWidth={1.2} />
                <text y={4} textAnchor="middle" fontFamily="var(--caps)" fontSize={10} fontWeight={700} fill="var(--rubric)">{i + 1}</text>
              </g>
            );
          })}
          {data.places.map((p) => {
            const [x, y] = P([p.lon, p.lat]);
            const on = p.entity_id === selected;
            const approx = (p.confidence ?? 1) < 0.7;
            return (
              <g key={p.entity_id} transform={`translate(${x},${y})`} style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); go("map", p.entity_id); }}>
                {approx && <circle r={14} fill="none" stroke="var(--ink-2)" strokeOpacity={0.35} strokeDasharray="2 3" />}
                <circle r={on ? 6 : 4.5} fill={on ? "var(--rubric)" : "var(--ink)"} stroke="var(--page)" strokeWidth={1.5} />
                <text x={9} y={4} fontFamily="var(--caps)" fontWeight={700} fontSize={on ? 15 : 13} fill={on ? "var(--rubric)" : "var(--ink)"}
                      style={{ paintOrder: "stroke", stroke: "#f1e3c0", strokeWidth: 4 }}>{p.name}{approx ? " ?" : ""}</text>
              </g>
            );
          })}
          <Compass x={size.w - 70} y={size.h - 80} />
          <g transform="translate(26, 24)">
            <rect width="250" height="54" fill="var(--page)" stroke="var(--gold)" />
            <rect x="4" y="4" width="242" height="46" fill="none" stroke="var(--gold)" strokeOpacity="0.5" />
            <text x="125" y="26" textAnchor="middle" fontFamily="var(--caps)" fontWeight={700} fontSize={15} fill="var(--rubric)" letterSpacing="0.12em">TABVLA TERRAE</text>
            <text x="125" y="42" textAnchor="middle" fontFamily="var(--serif)" fontStyle="italic" fontSize={13} fill="var(--ink-2)">the lands of the story</text>
          </g>
        </svg>
        <div className="muted" style={{ position: "absolute", left: 10, bottom: 6, fontSize: 12 }}>Natural Earth (public domain) · places after OpenBible.info · “?” marks an uncertain site</div>
      </div>
      <aside style={{ padding: "16px 22px 16px 6px", overflow: "auto" }}>
        <div className="section-title" style={{ marginTop: 6 }}>Journeys</div>
        {data.journeys.map((j) => (
          <div key={j.entity_id} style={{ margin: "4px 0" }}>
            <a href="#" onClick={(e) => { e.preventDefault(); setWho(j.entity_id); setStep(null); }}
               style={{ fontWeight: who === j.entity_id ? 700 : 400, color: who === j.entity_id ? "var(--rubric)" : undefined }}>
              {j.name}
            </a> <span className="muted">· {j.stops.length} stages</span>
          </div>
        ))}
        {journey && (
          <>
            <div style={{ display: "flex", gap: 8, margin: "10px 0" }}>
              <button className="select" onClick={() => setStep((s) => (s === null ? 0 : Math.max(s - 1, 0)))}>← stage</button>
              <button className="select" onClick={() => setStep((s) => (s === null ? 0 : Math.min(s + 1, stops.length - 1)))}>stage →</button>
              <button className="select" onClick={() => setStep(null)}>whole road</button>
            </div>
            <ol style={{ paddingLeft: 22, margin: 0 }}>
              {stops.map((s, i) => (
                <li key={i} style={{ marginBottom: 6, opacity: step !== null && i > step ? 0.4 : 1, cursor: "pointer" }} onClick={() => setStep(i)}>
                  <a href={href("hours", s.event_id)} onClick={(e) => e.stopPropagation()}>{s.title}</a>
                  <div className="muted" style={{ fontSize: 14 }}>{places[s.place].name} · {s.label}</div>
                </li>
              ))}
            </ol>
          </>
        )}
        {place && (
          <>
            <div className="section-title">{place.name}</div>
            {place.events.map((id) => (
              <p key={id} style={{ margin: "4px 0" }}><a href={href("hours", id)}>{data.events[id]?.title}</a> <span className="muted">· {data.events[id]?.label}</span></p>
            ))}
            {place.events.length === 0 && <p className="muted">Named, but nothing happens here in these chapters.</p>}
            <p><a href={href("people", place.entity_id)}>Read about {place.name} →</a></p>
          </>
        )}
      </aside>
    </div>
  );
}
