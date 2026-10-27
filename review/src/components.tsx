import { useState } from "react";
import type { ReactNode } from "react";
import type { CausalLink, EntityRef, EventView, Status } from "./api";
import { useApp } from "./state";
import { ENTITY_COLOR, ENTITY_GLYPH, STATUS_LABEL, duration, href, range } from "./util";

const ICONS: Record<string, ReactNode> = {
  command: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><path d="M12 12 18 6M12 3v2M12 19v2M3 12h2M19 12h2" /></>,
  review: <><rect x="4" y="6" width="13" height="15" rx="1" /><path d="M7 3h13v15" /><path d="m8 13 2.5 2.5L15 11" /></>,
  xray: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3" /></>,
  chronicle: <><path d="M3 12h18M6 8v8M11 6v12M16 9v6M20 7v10" /></>,
  causal: <><circle cx="5" cy="6" r="2.5" /><circle cx="5" cy="18" r="2.5" /><circle cx="19" cy="12" r="2.5" /><path d="M7.5 6.5 16.5 11M7.5 17.5l9-5" /></>,
  atlas: <><path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3Z" /><path d="M9 3v15M15 6v15" /></>,
  dossiers: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4.5 4.5-7 8-7s7 2.5 8 7" /></>,
  codex: <><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3Z" /><path d="M5 17a3 3 0 0 1 3-3h11M9 8h6" /></>,
  query: <><rect x="3" y="4" width="18" height="16" rx="1" /><path d="m7 10 3 2-3 2M12 15h5" /></>,
  flame: <><path d="M12 22c4 0 7-3 7-7 0-5-5-7-5-12-3 2-4 5-4 7-1-1-2-2-2-4-2 2-3 5-3 9 0 4 3 7 7 7Z" /></>,
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
         strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">{ICONS[name]}</svg>
  );
}

export function Panel({ title, count, children, className = "", right }: {
  title?: string; count?: ReactNode; children: ReactNode; className?: string; right?: ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <h4 className="panel-title">
          {title}{count !== undefined && <span className="count">{count}</span>}
          {right && <span style={{ order: 3, marginLeft: 8 }}>{right}</span>}
        </h4>
      )}
      {children}
    </section>
  );
}

export function StatusPill({ status }: { status?: Status | null }) {
  if (!status) return <span className="pill faint">Unreviewed</span>;
  return <span className={`pill st-${status}`}>{STATUS_LABEL[status]}</span>;
}

export function EntityChip({ entity, onClick }: { entity: EntityRef; onClick?: () => void }) {
  const color = ENTITY_COLOR[entity.entity_type] ?? "var(--text)";
  return (
    <a className="chip click" href={onClick ? undefined : href("dossiers", entity.entity_id)}
       onClick={onClick} style={{ borderColor: `color-mix(in srgb, ${color} 40%, transparent)` }}>
      <span style={{ color }}>{ENTITY_GLYPH[entity.entity_type] ?? "•"}</span>{entity.name}
    </a>
  );
}

export function EventBrief({ event, compact = false }: { event: EventView; compact?: boolean }) {
  return (
    <div className="grid" style={{ gap: 6 }}>
      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="chip mono">{range(event.verse_start, event.verse_end)}</span>
        <span className="chip"><b className="mono" style={{ color: "var(--amber)" }}>{event.start_label}</b></span>
        {event.time_of_day && <span className="chip" style={{ color: "var(--cyan)" }}>☼ {event.time_of_day.label ?? event.time_of_day.code}</span>}
        <span className="chip">⧗ {duration(event.duration_seconds)}</span>
        <span className="chip muted">± {duration(event.relative_margin_seconds, 1)} rel.</span>
        {event.location && <EntityChip entity={event.location} />}
      </div>
      {!compact && event.narrative_summary && <p style={{ margin: 0 }}>{event.narrative_summary}</p>}
      {!compact && event.temporal_reasoning_note && (
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          <b className="hud upper" style={{ fontSize: 10, color: "var(--cyan)" }}>Timing&nbsp;</b>
          {event.temporal_reasoning_note}
        </p>
      )}
    </div>
  );
}

export function CausalRow({ link, titles, from }: { link: CausalLink; titles: Record<string, string | null>; from?: string }) {
  const other = link.cause_event_id === from ? link.effect_event_id : link.cause_event_id;
  const arrow = link.cause_event_id === from ? "→" : "←";
  return (
    <div className="row" style={{ alignItems: "flex-start", gap: 8, fontSize: 13 }}>
      <span className="chip" style={{ color: "var(--gold)" }}>{link.causal_type.label ?? link.causal_type.code}</span>
      <div style={{ flex: 1 }}>
        <a href={href("chronicle", other)}>{arrow} {titles[other] ?? other}</a>
        <span className="muted mono" style={{ marginLeft: 8 }}>
          {link.elapsed_seconds < 0 ? "overlaps" : link.elapsed_seconds === 0 ? "immediately" : `after ${duration(link.elapsed_seconds)}`}
        </span>
        {link.explanation && <div className="muted" style={{ fontSize: 12 }}>{link.explanation}</div>}
      </div>
    </div>
  );
}

/** Approve / send back controls for one ledger key, used inside the reading views. */
export function ReviewBar({ itemKey }: { itemKey: string }) {
  const { ledger, review } = useApp();
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const status = ledger[itemKey]?.status;
  if (!ledger[itemKey]) return <span className="pill faint">Not in ledger</span>;
  return (
    <div className="row" style={{ flexWrap: "wrap" }}>
      <StatusPill status={status} />
      {status !== "approved" && <button className="btn green small" onClick={() => review([itemKey], "approved")}>Approve</button>}
      {status === "approved" && <button className="btn small ghost" onClick={() => review([itemKey], "draft")}>Reopen</button>}
      {!asking && status !== "changes_requested" && <button className="btn red small" onClick={() => setAsking(true)}>Send back</button>}
      {asking && (
        <>
          <input autoFocus value={note} placeholder="What should change?" onChange={(e) => setNote(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter" && note) { review([itemKey], "changes_requested", note); setAsking(false); setNote(""); } }}
                 style={{ minWidth: 260 }} />
          <button className="btn red small" disabled={!note} onClick={() => { review([itemKey], "changes_requested", note); setAsking(false); setNote(""); }}>Send</button>
        </>
      )}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="loading">{what}…</div>;
}

export function ProgressRing({ value, size = 64, stroke = 6, color = "var(--amber)", label, sub }: {
  value: number; size?: number; stroke?: number; color?: string; label?: ReactNode; sub?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#132230" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
                strokeDasharray={`${c * Math.min(Math.max(value, 0), 1)} ${c}`} strokeLinecap="round"
                style={{ filter: `drop-shadow(0 0 4px ${color})`, transition: "stroke-dasharray .6s" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
        <div>
          <div className="mono" style={{ fontSize: size / 4.2, fontWeight: 700, color }}>{label}</div>
          {sub && <div className="hud upper" style={{ fontSize: 9, color: "var(--dim)" }}>{sub}</div>}
        </div>
      </div>
    </div>
  );
}
