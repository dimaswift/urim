import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CausalLink, EventView } from "../api";
import { CausalRow, EventBrief, Loading, Panel, ReviewBar } from "../components";
import { useI18n, useT, type TFunc } from "../i18n";
import { useApi, useApp } from "../state";
import { chapterOf, go, href, range, toDate, yearLabel, type Route } from "../util";

interface Data { events: EventView[]; links: CausalLink[] }
const LANE = 30;
const DIURNAL: [number, string][] = [
  [2, "ashmoret_haboker"], [5.5, "shachar"], [6, "boker"], [9, "third_hour"], [12, "tzohorayim"],
  [15, "minchah"], [17.5, "bein_haarbayim"], [18, "erev"], [22, "middle_watch"],
];

function hourName(t: TFunc, code: string): string {
  switch (code) {
    case "ashmoret_haboker": return t("chronicle.hour.ashmoret_haboker");
    case "shachar": return t("chronicle.hour.shachar");
    case "boker": return t("chronicle.hour.boker");
    case "third_hour": return t("chronicle.hour.third_hour");
    case "tzohorayim": return t("chronicle.hour.tzohorayim");
    case "minchah": return t("chronicle.hour.minchah");
    case "bein_haarbayim": return t("chronicle.hour.bein_haarbayim");
    case "erev": return t("chronicle.hour.erev");
    case "middle_watch": return t("chronicle.hour.middle_watch");
  }
  return code;
}

// Month names come from Intl in the interface language. Ancient dates are proleptic Gregorian,
// which Intl may not honour, so only the month index is taken from them.
const mid = (date: Date) => new Date(Date.UTC(2000, date.getUTCMonth(), 15));
const monthName = (date: Date, lang: string) =>
  new Intl.DateTimeFormat(lang, { month: "short", timeZone: "UTC" }).format(mid(date));
const monthInDate = (date: Date, lang: string) =>
  new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", timeZone: "UTC" })
    .formatToParts(mid(date)).find((p) => p.type === "month")?.value ?? monthName(date, lang);
const dayMonth = (t: TFunc, lang: string, date: Date) =>
  t("chronicle.day_month", { day: d3.utcFormat("%d")(date), month: monthInDate(date, lang) });

function tickFormatFor(ticks: Date[], t: TFunc, lang: string) {
  const day = 86400e3;
  const step = ticks.length > 1 ? ticks[1].getTime() - ticks[0].getTime() : 365 * day;
  return (d: Date | d3.NumberValue) => {
    const date = d as Date;
    if (step >= 300 * day) return yearLabel(date);
    if (step >= 27 * day) return t("chronicle.month_year", { month: monthName(date, lang), year: yearLabel(date) });
    if (step >= day) return dayMonth(t, lang, date);
    return d3.utcFormat("%H:%M")(date);
  };
}

interface Slot { lane: number; label: boolean; inside: boolean; x0: number; x1: number }

/** Pack events into rows per chapter so bars and their labels never overlap on screen. */
function pack(events: EventView[], x: d3.ScaleTime<number, number>, allLabels: boolean, selected: string) {
  const slots = new Map<string, Slot>();
  let base = 0;
  for (const ch of [...new Set(events.map((e) => chapterOf(e.verse_start)))]) {
    const rows: number[] = [];
    const evs = events.filter((e) => chapterOf(e.verse_start) === ch)
      .map((e) => ({ e, x0: x(toDate(e.utes_start)), x1: Math.max(x(toDate(e.utes_end)), x(toDate(e.utes_start)) + 4) }))
      .sort((a, b) => a.x0 - b.x0);
    for (const { e, x0, x1 } of evs) {
      const text = Math.min((e.title ?? e.event_id).length, 48) * 6.3 + 12;
      const inside = x1 - x0 >= text + 4;
      const label = inside || allLabels || e.event_id === selected;
      const end = (inside ? x1 : x1 + (label ? text : 0)) + 8;
      let r = rows.findIndex((edge) => edge <= x0);
      if (r < 0) { r = rows.length; rows.push(0); }
      rows[r] = end;
      slots.set(e.event_id, { lane: base + r, label, inside, x0, x1 });
    }
    base += rows.length + 1;
  }
  return { slots, rows: base };
}

function DayClock({ day, events, selected }: { day: number; events: EventView[]; selected: string }) {
  const t = useT();
  const { lang } = useI18n();
  const size = 300, c = size / 2, R = 118;
  const angle = (h: number) => (h / 24) * 2 * Math.PI - Math.PI / 2;
  const pt = (h: number, r: number) => [c + r * Math.cos(angle(h)), c + r * Math.sin(angle(h))];
  const arc = (h0: number, h1: number, r0: number, r1: number) =>
    d3.arc()({ innerRadius: r0, outerRadius: r1, startAngle: (h0 / 24) * 2 * Math.PI, endAngle: (h1 / 24) * 2 * Math.PI }) ?? "";
  const todays = events.filter((e) => e.utes_end > day && e.utes_start < day + 86400 && e.duration_seconds < 86400 * 2);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <defs>
        <radialGradient id="sun"><stop offset="0%" stopColor="rgba(255,179,71,.18)" /><stop offset="100%" stopColor="rgba(255,179,71,0)" /></radialGradient>
      </defs>
      <g transform={`translate(${c},${c})`}>
        <path d={arc(0, 24, 40, R)} fill="#08111a" stroke="var(--line-2)" />
        <path d={arc(6, 18, 40, R)} fill="url(#sun)" />
        {todays.map((e, i) => {
          const h0 = Math.max(0, (e.utes_start - day) / 3600), h1 = Math.min(24, Math.max((e.utes_end - day) / 3600, h0 + 0.15));
          const r0 = 48 + (i % 5) * 13;
          const on = e.event_id === selected;
          return (
            <path key={e.event_id} d={arc(h0, h1, r0, r0 + 10)} fill={on ? "var(--amber)" : "rgba(255,179,71,.45)"}
                  style={{ cursor: "pointer", filter: on ? "drop-shadow(0 0 6px var(--amber))" : undefined }}
                  onClick={() => go("chronicle", e.event_id)}><title>{e.title}</title></path>
          );
        })}
      </g>
      {d3.range(24).map((h) => {
        const [x0, y0] = pt(h, R), [x1, y1] = pt(h, R + (h % 6 === 0 ? 8 : 4));
        return <line key={h} x1={x0} y1={y0} x2={x1} y2={y1} stroke="var(--dim)" />;
      })}
      {[0, 6, 12, 18].map((h) => {
        const [x, y] = pt(h, R + 18);
        return <text key={h} x={x} y={y + 4} textAnchor="middle" fill="var(--dim)" fontSize="10" fontFamily="var(--mono)">{String(h).padStart(2, "0")}</text>;
      })}
      {DIURNAL.map(([h, code]) => {
        const [x, y] = pt(h, 30);
        const [lx, ly] = pt(h, R - 3);
        const name = hourName(t, code);
        return (
          <g key={code}>
            <line x1={x} y1={y} x2={lx} y2={ly} stroke="rgba(79,209,232,.22)" strokeDasharray="2 3" />
            <circle cx={lx} cy={ly} r={2.5} fill="var(--cyan)"><title>{name} {h}:00</title></circle>
          </g>
        );
      })}
      <text x={c} y={c - 4} textAnchor="middle" fill="var(--amber)" fontFamily="var(--hud)" fontWeight="700" fontSize="13">{dayMonth(t, lang, toDate(day))}</text>
      <text x={c} y={c + 12} textAnchor="middle" fill="var(--dim)" fontFamily="var(--hud)" fontSize="10" letterSpacing="2">{yearLabel(toDate(day))}</text>
    </svg>
  );
}

export default function Chronicle({ route }: { route: Route }) {
  const { lang, ledger } = useApp();
  const t = useT();
  const { lang: uiLang } = useI18n();
  const { data } = useApi<Data>(`/api/events?lang=${lang}`);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(0);
  const focused = useRef(false);
  const [transform, setTransform] = useState(d3.zoomIdentity);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const selected = route.arg || data?.events.find((e) => e.time_of_day?.code === "MINCHAH")?.event_id || data?.events[0]?.event_id || "";

  const base = useMemo(() => {
    const ev = data?.events ?? [];
    if (!ev.length) return d3.scaleUtc().range([20, Math.max(width - 20, 40)]);
    const lo = d3.min(ev, (e) => e.utes_start)!, hi = d3.max(ev, (e) => e.utes_end)!;
    const pad = (hi - lo) * 0.04 + 3600;
    return d3.scaleUtc().domain([toDate(lo - pad), toDate(hi + pad)]).range([20, Math.max(width - 20, 40)]);
  }, [data, width]);
  const x = transform.rescaleX(base);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const ro = new ResizeObserver(() => setWidth(svg.clientWidth));
    setWidth(svg.clientWidth);
    ro.observe(svg);
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([1, 5e6])
      .translateExtent([[-Infinity, 0], [Infinity, 0]])
      .on("zoom", (e) => setTransform(e.transform));
    d3.select(svg).call(zoom).on("dblclick.zoom", null);
    zoomRef.current = zoom;
    return () => ro.disconnect();
  }, [data]);

  const focus = (t0: number, t1: number, animate = true) => {
    const svg = svgRef.current;
    if (!svg || !zoomRef.current) return;
    const [a, b] = [base(toDate(t0)), base(toDate(t1))];
    const k = Math.min((width - 80) / Math.max(b - a, 1e-6), 5e6);
    const target = d3.zoomIdentity.translate(width / 2 - k * (a + b) / 2, 0).scale(k);
    const sel = d3.select(svg);
    if (animate) sel.transition().duration(700).call(zoomRef.current.transform, target);
    else sel.call(zoomRef.current.transform, target);
  };

  // Open on the selected event's day (the Carmel day by default): the interesting zoom level.
  useEffect(() => {
    if (focused.current || !data || !width || !zoomRef.current) return;
    const first = data.events.find((e) => e.event_id === selected);
    if (!first) return;
    focused.current = true;
    if (first.duration_seconds < 2 * 86400) {
      const d0 = Math.floor(first.utes_start / 86400) * 86400;
      focus(d0, d0 + 86400, false);
    } else {
      focus(first.utes_start - first.duration_seconds * 0.3, first.utes_end + first.duration_seconds * 0.3, false);
    }
  });

  if (!data) return <Loading what={t("chronicle.loading")} />;
  const ev = data.events.find((e) => e.event_id === selected);
  const titles = Object.fromEntries(data.events.map((e) => [e.event_id, e.title]));
  const span = x.domain()[1].getTime() - x.domain()[0].getTime();
  const { slots, rows } = pack(data.events, x, span < 3 * 86400e3, selected);
  const height = rows * LANE + 60;
  const ticks = x.ticks(Math.max(width / 120, 2));
  const day = ev ? Math.floor(ev.utes_start / 86400) * 86400 : 0;
  const all = [d3.min(data.events, (e) => e.utes_start)!, d3.max(data.events, (e) => e.utes_end)!];

  return (
    <div className="view">
      <div className="row" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("chronicle.kicker")}</div>
          <h1>{t("chronicle.title")}</h1>
        </div>
        <div className="spacer" />
        <button className="btn small" onClick={() => focus(all[0], all[1])}>{t("chronicle.zoom.all")}</button>
        {ev && <button className="btn small amber" onClick={() => focus(day, day + 86400)}>{t("chronicle.zoom.day")}</button>}
        {ev && <button className="btn small" onClick={() => focus(ev.utes_start - ev.duration_seconds * 0.5 - 3600, ev.utes_end + ev.duration_seconds * 0.5 + 3600)}>{t("chronicle.zoom.event")}</button>}
      </div>
      <Panel>
        <svg ref={svgRef} className="svg-fill" style={{ height, cursor: "grab" }}>
          <g transform={`translate(0, ${height - 24})`} ref={(g) => { if (g) d3.select(g).call(d3.axisBottom(x).ticks(Math.max(width / 120, 2)).tickFormat(tickFormatFor(ticks, t, uiLang)) as any).call((s) => { s.selectAll("text").attr("fill", "var(--dim)").attr("font-family", "var(--mono)"); s.selectAll("line,path").attr("stroke", "var(--line-2)"); }); }} />
          {ticks.map((tick) => (
            <line key={tick.getTime()} x1={x(tick)} x2={x(tick)} y1={10} y2={height - 24} stroke="rgba(79,209,232,.06)" />
          ))}
          {data.events.map((e) => {
            const slot = slots.get(e.event_id)!;
            const y = 14 + slot.lane * LANE;
            const { x0, x1 } = slot;
            const m = x(toDate(e.utes_start + e.relative_margin_seconds)) - x0;
            const status = ledger[`event:${e.event_id}`]?.status;
            const color = status === "approved" ? "var(--green)" : status === "changes_requested" ? "var(--red)" : "var(--amber)";
            const on = e.event_id === selected;
            const label = e.title ?? e.event_id;
            if (x1 < -400 || x0 > width + 400) return null;
            const whisker = Math.min(m, width);
            const margin = e.relative_margin_seconds / 3600 < 48
              ? t("unit.h", { n: Math.round(e.relative_margin_seconds / 360) / 10 })
              : t("unit.d", { n: Math.round(e.relative_margin_seconds / 8640) / 10 });
            return (
              <g key={e.event_id} style={{ cursor: "pointer" }} onClick={() => go("chronicle", e.event_id)}>
                {whisker > 3 && (
                  <g stroke={color} strokeOpacity={0.45} strokeWidth={1.2}>
                    <line x1={x0 - whisker} x2={x0 + whisker} y1={y + 10} y2={y + 10} strokeDasharray="2 3" />
                    <line x1={x0 - whisker} x2={x0 - whisker} y1={y + 6} y2={y + 14} />
                    <line x1={x0 + whisker} x2={x0 + whisker} y1={y + 6} y2={y + 14} />
                  </g>
                )}
                <rect x={x0} y={y + 4} width={x1 - x0} height={12} rx={2} fill={color} fillOpacity={on ? 0.95 : 0.55}
                      stroke={on ? "#fff" : color} style={{ filter: on ? `drop-shadow(0 0 6px ${color})` : undefined }}>
                  <title>{t("chronicle.bar_title", { title: label, start: e.start_label, end: e.end_label, margin })}</title>
                </rect>
                {slot.label && (
                  <text x={slot.inside ? Math.max(x0, 4) + 6 : x1 + 6} y={y + 14} fill={slot.inside ? "#051018" : "var(--text)"}
                        fontSize="11" fontFamily="var(--hud)" fontWeight="600">{label.length > 48 ? label.slice(0, 46) + "…" : label}</text>
                )}
              </g>
            );
          })}
        </svg>
      </Panel>
      {ev && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: 16, marginTop: 16, alignItems: "start" }}>
          <Panel title={t("chronicle.event.title")} right={<ReviewBar itemKey={`event:${ev.event_id}`} />}>
            <h2 style={{ marginBottom: 8 }}>{ev.title}</h2>
            <EventBrief event={ev} />
            <dl className="kv" style={{ marginTop: 12 }}>
              <dt>{t("chronicle.event.starts")}</dt><dd className="mono">{ev.start_label}</dd>
              <dt>{t("chronicle.event.ends")}</dt><dd className="mono">{ev.end_label}</dd>
              <dt>{t("chronicle.event.anchor")}</dt><dd className="mono"><a href={ev.anchor_id.startsWith("evt.") ? href("chronicle", ev.anchor_id) : undefined}>{ev.anchor_id}</a> ({ev.anchor_point === "START" ? t("chronicle.anchor_point.start") : ev.anchor_point === "END" ? t("chronicle.anchor_point.end") : ev.anchor_point.toLowerCase()}) {ev.relative_offset_seconds ? `+${t("unit.h", { n: Math.round(ev.relative_offset_seconds / 3600) })}` : ""}</dd>
              <dt>{t("chronicle.event.precision")}</dt><dd>{ev.precision_tier.label ?? ev.precision_tier.code}</dd>
              {ev.ancient_year_marker && <><dt>{t("chronicle.event.text_says")}</dt><dd>{ev.ancient_year_marker}</dd></>}
              {ev.ancient_season_marker && <><dt>{t("chronicle.event.season")}</dt><dd>{ev.ancient_season_marker}</dd></>}
              {ev.ancient_diurnal_marker && <><dt>{t("chronicle.event.hour")}</dt><dd>{ev.ancient_diurnal_marker}</dd></>}
              <dt>{t("chronicle.event.verses")}</dt><dd><a className="mono" href={href("xray", ev.verse_start)}>{range(ev.verse_start, ev.verse_end)}</a></dd>
            </dl>
            <div className="grid" style={{ gap: 6, marginTop: 12 }}>
              {data.links.filter((l) => l.cause_event_id === ev.event_id || l.effect_event_id === ev.event_id).map((l) => (
                <CausalRow key={l.causal_id} link={l} titles={titles} from={ev.event_id} />
              ))}
            </div>
          </Panel>
          <Panel title={t("chronicle.dial.title")} className="cyan">
            <div style={{ display: "grid", placeItems: "center" }}><DayClock day={day} events={data.events} selected={ev.event_id} /></div>
            <div className="muted" style={{ fontSize: 12 }}>{t("chronicle.dial.note")}</div>
          </Panel>
        </div>
      )}
    </div>
  );
}
