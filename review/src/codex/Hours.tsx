import * as d3 from "d3";
import { useMemo } from "react";
import type { ReactNode } from "react";
import type { CausalLink, EventView } from "../api";
import { useApi } from "../hooks";
import { Msg, useI18n } from "../i18n";
import type { TFunc } from "../i18n";
import { duration, go, href, range, toDate, yearLabel, type Route } from "../util";
import { Corners, LangMark, Ornament, dayMonth, useLang } from "./parts";

interface Data { events: EventView[]; links: CausalLink[] }
interface Group { key: string; daily: boolean; start: number; end: number; events: EventView[] }

/** The ancient hours: when, the name in the interface language, the name in its own tongue. */
const hoursOf = (t: TFunc): [number, string, string][] => [
  [2, t("codex.hours.hour.morning_watch"), "אַשְׁמֹרֶת הַבֹּקֶר"], [5.5, t("codex.hours.hour.dawn"), "שַׁחַר"],
  [6, t("codex.hours.hour.morning"), "בֹּקֶר"], [9, t("codex.hours.hour.third"), "hora tertia"],
  [12, t("codex.hours.hour.noon"), "צָהֳרַיִם"], [15, t("codex.hours.hour.minchah"), "מִנְחָה"],
  [17.5, t("codex.hours.hour.between_evenings"), "בֵּין הָעַרְבַּיִם"], [18, t("codex.hours.hour.evening"), "עֶרֶב"],
  [22, t("codex.hours.hour.middle_watch"), "אַשְׁמֹרֶת הַתִּיכוֹנָה"],
];

function passage(t: TFunc, seconds: number): string {
  const days = seconds / 86400;
  if (days < 0.5) return t("codex.hours.same_day");
  if (days < 1.5) return t("codex.hours.next_day");
  if (days < 45) return t("codex.hours.days_pass", { count: Math.round(days) });
  if (days < 700) return t("codex.hours.months_pass", { count: Math.round(days / 30.4) });
  return t("codex.hours.years_pass", { count: Math.round((days / 365.2425) * 10) / 10 });
}

/** What a cause leads to, in words, before the effect's title. */
function Because({ code, event }: { code: string; event: ReactNode }) {
  switch (code) {
    case "FULFILLS_PROPHECY": return <Msg k="codex.hours.because.fulfills" vars={{ event }} />;
    case "RETALIATES_FOR": return <Msg k="codex.hours.because.avenges" vars={{ event }} />;
    case "ENABLES": return <Msg k="codex.hours.because.enables" vars={{ event }} />;
    default: return <Msg k="codex.hours.because.other" vars={{ event }} />;
  }
}

function Horologium({ day, events, selected }: { day: number; events: EventView[]; selected?: string }) {
  const { t, lang } = useI18n();
  const S = 300, c = S / 2, R = 116;
  const arc = (h0: number, h1: number, r0: number, r1: number) =>
    d3.arc()({ innerRadius: r0, outerRadius: r1, startAngle: (h0 / 24) * 2 * Math.PI, endAngle: (h1 / 24) * 2 * Math.PI }) ?? "";
  const pt = (h: number, r: number) => [c + r * Math.sin((h / 24) * 2 * Math.PI), c - r * Math.cos((h / 24) * 2 * Math.PI)];
  const todays = events.filter((e) => e.utes_end > day && e.utes_start < day + 86400 && e.duration_seconds < 86400 * 2);
  return (
    <svg width={S} height={S + 10} viewBox={`0 0 ${S} ${S + 10}`}>
      <g transform={`translate(${c},${c})`}>
        <circle r={R + 18} fill="var(--page)" stroke="var(--gold)" strokeWidth="2" />
        <circle r={R + 13} fill="none" stroke="var(--gold)" strokeOpacity="0.5" />
        <path d={arc(18, 30, 30, R)} fill="rgba(36,71,111,.16)" />
        <path d={arc(6, 18, 30, R)} fill="rgba(216,181,90,.28)" />
        {todays.map((e, i) => {
          const h0 = Math.max(0, (e.utes_start - day) / 3600), h1 = Math.min(24, Math.max((e.utes_end - day) / 3600, h0 + 0.2));
          const r0 = 40 + (i % 5) * 14;
          return (
            <path key={e.event_id} d={arc(h0, h1, r0, r0 + 10)} fill="var(--rubric)" fillOpacity={e.event_id === selected ? 0.95 : 0.55}
                  style={{ cursor: "pointer" }} onClick={() => go("hours", e.event_id)}><title>{e.title}</title></path>
          );
        })}
        <circle r={30} fill="var(--page)" stroke="var(--gold)" />
        <text y={-2} textAnchor="middle" fontFamily="var(--caps)" fontWeight={700} fontSize={12} fill="var(--rubric)">{dayMonth(t, lang, toDate(day))}</text>
        <text y={12} textAnchor="middle" fontFamily="var(--serif)" fontStyle="italic" fontSize={11} fill="var(--faded)">{yearLabel(toDate(day))}</text>
      </g>
      {d3.range(24).map((h) => {
        const [x0, y0] = pt(h, R), [x1, y1] = pt(h, R + (h % 3 === 0 ? 9 : 5));
        return <line key={h} x1={x0} y1={y0} x2={x1} y2={y1} stroke="var(--ink-2)" strokeOpacity="0.6" />;
      })}
      {hoursOf(t).map(([h, name]) => {
        const [x, y] = pt(h, R - 6);
        return <circle key={name} cx={x} cy={y} r={3} fill="var(--gold)" stroke="var(--ink-2)" strokeWidth="0.6"><title>{name}</title></circle>;
      })}
      {[0, 6, 12, 18].map((h) => {
        const [x, y] = pt(h, R + 26);
        return <text key={h} x={x} y={y + 4} textAnchor="middle" fontFamily="var(--caps)" fontSize={11} fill="var(--faded)">{["XXIV", "VI", "XII", "XVIII"][h / 6]}</text>;
      })}
    </svg>
  );
}

export default function Hours({ route }: { route: Route }) {
  const { t, lang: uiLang } = useI18n();
  const { lang } = useLang();
  const { data } = useApi<Data>(`/api/events?lang=${lang}`);
  const groups = useMemo(() => {
    const out: Group[] = [];
    const events = [...(data?.events ?? [])].sort((a, b) => a.utes_start - b.utes_start || b.duration_seconds - a.duration_seconds);
    // A day-scale event: hour- or day-level precision, a stated hour, or a parent of such events
    // (the contest on Carmel is dated only to the year, but it is one day, dawn to dusk).
    const dailyIds = new Set(events.filter((e) => e.precision_tier.code === "DIURNAL_HOUR"
      || e.precision_tier.code === "DAY_SEQUENCE" || e.time_of_day).map((e) => e.event_id));
    events.forEach((e) => { if (e.parent_event_id && dailyIds.has(e.event_id)) dailyIds.add(e.parent_event_id); });
    for (const e of events) {
      const daily = dailyIds.has(e.event_id) && e.duration_seconds < 2 * 86400;
      const key = daily ? `d${Math.floor(e.utes_start / 86400)}` : `e${e.event_id}`;
      const last = out.at(-1);
      if (last && last.key === key) { last.events.push(e); last.end = Math.max(last.end, e.utes_end); }
      else out.push({ key, daily, start: e.utes_start, end: e.utes_end, events: [e] });
    }
    return out;
  }, [data]);
  if (!data) return <div className="loading">{t("codex.hours.loading")}</div>;
  const selected = route.arg || data.events.find((e) => e.time_of_day?.code === "MINCHAH")?.event_id;
  const sel = data.events.find((e) => e.event_id === selected);
  const firstDaily = groups.find((g) => g.daily);
  const day = sel && sel.duration_seconds < 2 * 86400 ? Math.floor(sel.utes_start / 86400) * 86400 : firstDaily ? Math.floor(firstDaily.start / 86400) * 86400 : 0;
  const titles = Object.fromEntries(data.events.map((e) => [e.event_id, e.title]));

  return (
    <article className="folio">
      <Corners />
      <div className="heading">
        <div className="book">{t("codex.hours.latin")}</div>
        <h1>{t("codex.hours.title")}</h1>
        <div className="sub">{t("codex.hours.subtitle")}</div>
        <Ornament />
      </div>
      <div className="hours">
        <div>
          {groups.map((g, gi) => {
            const prev = groups[gi - 1];
            const head = g.daily ? (
              <div className="day-head">
                <div className="date">{dayMonth(t, uiLang, toDate(g.start), true)}</div>
                <div className="era">{yearLabel(toDate(g.start))}</div>
              </div>
            ) : (
              <div className="day-head"><div className="date">{g.events[0].start_label}</div><div className="era">{g.events[0].precision_tier.label}</div></div>
            );
            return (
              <section key={g.key}>
                {prev && <div className="interlude"><span>{passage(t, g.start - prev.end)}</span></div>}
                {head}
                {g.events.map((e) => {
                  const effects = data.links.filter((l) => l.cause_event_id === e.event_id);
                  const clock = e.precision_tier.code === "DIURNAL_HOUR" || e.time_of_day
                    ? d3.utcFormat("%H:%M")(toDate(e.utes_start))
                    : e.duration_seconds >= 86400 ? duration(e.duration_seconds, 1) : "";
                  return (
                    <div key={e.event_id} className={`entry ${e.parent_event_id ? "child" : ""}`} id={e.event_id}
                         style={{ background: e.event_id === selected ? "rgba(216,181,90,.16)" : undefined, cursor: "pointer" }}
                         onClick={() => go("hours", e.event_id)}>
                      <div className="time">{clock}</div>
                      <div>
                        <h3><a href={href("read", e.verse_start.split(".").slice(0, 2).join(".")) + `?v=${e.verse_start}`} onClick={(ev) => ev.stopPropagation()}>{e.title}</a><LangMark from={e.text_lang} /></h3>
                        <p>{e.narrative_summary}</p>
                        <div className="meta">
                          {range(e.verse_start, e.verse_end)}
                          {e.location && <> · <a href={href("people", e.location.entity_id)} onClick={(ev) => ev.stopPropagation()}>{e.location.name}</a></>}
                          {e.ancient_diurnal_marker && <> · {e.ancient_diurnal_marker}</>}
                          {e.ancient_season_marker && <> · {e.ancient_season_marker}</>}
                        </div>
                        {effects.map((l) => (
                          <div key={l.causal_id} className="because">
                            ⤷ <Because code={l.causal_type.code} event={<a href={href("hours", l.effect_event_id)} onClick={(ev) => ev.stopPropagation()}>{titles[l.effect_event_id]}</a>} />
                            <span className="muted"> ({l.elapsed_seconds <= 0 ? t("codex.hours.at_once") : t("codex.hours.later", { duration: duration(l.elapsed_seconds, 1) })})</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </section>
            );
          })}
        </div>
        <aside className="sticky">
          <div className="section-title" style={{ marginTop: 0 }}>{t("codex.hours.horologium")}</div>
          <div style={{ display: "grid", placeItems: "center" }}><Horologium day={day} events={data.events} selected={selected} /></div>
          {sel && (
            <div style={{ marginTop: 12 }}>
              <div className="small-caps rubric-text">{t("codex.hours.chosen_hour")}</div>
              <div style={{ fontSize: 19, fontWeight: 600 }}>{sel.title}<LangMark from={sel.text_lang} /></div>
              <div className="muted">{sel.start_label} → {sel.end_label}</div>
              {sel.temporal_reasoning_note && <p style={{ fontSize: 15.5 }}><i>{t("codex.hours.how_we_know")}</i> {sel.temporal_reasoning_note}</p>}
            </div>
          )}
          <div className="section-title">{t("codex.hours.the_hours")}</div>
          {hoursOf(t).map(([h, name, heb]) => (
            <div key={name} style={{ display: "grid", gridTemplateColumns: "48px 1fr auto", fontSize: 15, padding: "2px 0" }}>
              <span className="small-caps rubric-text">{String(Math.floor(h)).padStart(2, "0")}:{h % 1 ? "30" : "00"}</span>
              <span>{name}</span>
              <span style={{ fontFamily: heb.startsWith("hora") ? "var(--serif)" : "var(--hebrew)", fontStyle: heb.startsWith("hora") ? "italic" : undefined, color: "var(--ink-2)" }}>{heb}</span>
            </div>
          ))}
        </aside>
      </div>
    </article>
  );
}
