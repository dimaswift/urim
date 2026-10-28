import { useEffect, useState } from "react";
import type { LayerRow, RunState, RunStep } from "../api";
import { api } from "../api";
import { Loading, Panel } from "../components";
import type { TFunc } from "../i18n";
import { Msg, num, useI18n, useT } from "../i18n";
import type { Route } from "../util";
import { ago, duration, go } from "../util";

// Campaign: an autonomous run (`urim run`) as it goes. Polls the run state the conductor writes.

const PHASE_COLOR: Record<LayerRow["phase"], string> = {
  unwritten: "var(--faint)", partial: "var(--amber)", drafts: "var(--amber)",
  requested: "var(--red)", done: "var(--green)", failed: "var(--red)",
};
const STATUS_COLOR: Record<string, string> = {
  running: "var(--cyan)", waiting: "var(--amber)", finished: "var(--green)", stopped: "var(--dim)",
  interrupted: "var(--red)", done: "var(--green)", failed: "var(--red)", limited: "var(--amber)",
  unavailable: "var(--amber)",
};

function phaseLabel(t: TFunc, phase: LayerRow["phase"]): string {
  switch (phase) {
    case "unwritten": return t("campaign.phase.unwritten");
    case "partial": return t("campaign.phase.partial");
    case "drafts": return t("campaign.phase.drafts");
    case "requested": return t("campaign.phase.requested");
    case "done": return t("campaign.phase.done");
    case "failed": return t("campaign.phase.failed");
    default: return phase;
  }
}

/** A run's or a session's status in words. */
function runStatusLabel(t: TFunc, status: string): string {
  switch (status) {
    case "running": return t("campaign.status.running");
    case "waiting": return t("campaign.status.waiting");
    case "finished": return t("campaign.status.finished");
    case "stopped": return t("campaign.status.stopped");
    case "interrupted": return t("campaign.status.interrupted");
    case "done": return t("campaign.status.done");
    case "failed": return t("campaign.status.failed");
    case "limited": return t("campaign.status.limited");
    case "unavailable": return t("campaign.status.unavailable");
    default: return status;
  }
}

function actionLabel(t: TFunc, action: string): string {
  switch (action) {
    case "write": return t("campaign.action.write");
    case "revise": return t("campaign.action.revise");
    case "critique": return t("campaign.action.critique");
    default: return action;
  }
}

function layerLabel(t: TFunc, layer: string): string {
  switch (layer) {
    case "chronology": return t("campaign.layer.chronology");
    case "ontology": return t("campaign.layer.ontology");
    case "philology": return t("campaign.layer.philology");
    default: return t("campaign.layer.language", { lang: layer.toUpperCase() });
  }
}

/** What a critique decided: "3 approved, 1 requested". */
function verdictLabel(t: TFunc, verdict: Record<string, number>): string {
  const parts: string[] = [];
  if (verdict.approved) parts.push(t("campaign.verdict.approved", { count: verdict.approved }));
  if (verdict.requested) parts.push(t("campaign.verdict.requested", { count: verdict.requested }));
  if (verdict.escalated) parts.push(t("campaign.verdict.escalated", { count: verdict.escalated }));
  if (verdict.kept) parts.push(t("campaign.verdict.kept", { count: verdict.kept }));
  return parts.join(", ");
}

const usd = (n: number) => num(n, { style: "currency", currency: "USD" });

function Cell({ row, step }: { row: LayerRow; step?: RunStep }) {
  const t = useT();
  const color = PHASE_COLOR[row.phase];
  const live = step?.status === "running";
  const title = [
    t("campaign.cell.approved", { count: row.approved }), t("campaign.cell.drafts", { count: row.drafts }),
    t("campaign.cell.sent_back", { count: row.requested }), t("campaign.cell.escalated", { count: row.escalated }),
    t("campaign.round", { round: row.rounds }),
  ].join(" · ");
  return (
    <div className={`cell ${live ? "live" : ""}`} style={{ borderColor: live ? "var(--cyan)" : color }} title={title}>
      <div className="hud upper" style={{ fontSize: 9, color: live ? "var(--cyan)" : color }}>
        {live ? `${actionLabel(t, step!.action)}${step!.round ? ` ${t("campaign.round_short", { round: step!.round })}` : ""}` : phaseLabel(t, row.phase)}
      </div>
      <div className="mono" style={{ fontSize: 11 }}>
        {row.approved + row.drafts + row.requested > 0 ? (
          <>
            <span style={{ color: "var(--green)" }}>{row.approved}✓</span>
            {row.drafts > 0 && <span className="muted"> {row.drafts}·</span>}
            {row.requested > 0 && <span style={{ color: "var(--red)" }}> {row.requested}↺</span>}
            {row.escalated > 0 && <span style={{ color: "var(--amber)" }}> {row.escalated}!</span>}
          </>
        ) : row.unwritten ? <span className="faint">{t("campaign.left", { count: row.unwritten })}</span> : <span className="faint">—</span>}
      </div>
    </div>
  );
}

function StepRow({ s }: { s: RunStep }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr onClick={() => setOpen(!open)} style={{ cursor: "pointer" }}>
        <td style={{ color: STATUS_COLOR[s.status] }} className="hud upper">{runStatusLabel(t, s.status)}</td>
        <td className="mono">
          {actionLabel(t, s.action)} {layerLabel(t, s.layer)} {s.scope}
          {s.round ? ` ${t("campaign.round_short", { round: s.round })}${s.final ? "!" : ""}` : ""}
        </td>
        <td className="muted">{s.model.replace("claude-", "")}</td>
        <td className="mono">{verdictLabel(t, s.verdict ?? {})}</td>
        <td className="mono muted">{s.turns ? num(s.turns) : ""}</td>
        <td className="mono muted">{s.duration_s ? duration(s.duration_s, 1) : ""}</td>
        <td className="mono muted">{s.cost_usd ? usd(s.cost_usd) : ""}</td>
      </tr>
      {open && (
        <tr><td colSpan={7}>
          {s.error && <div className="intel red"><b>{t("campaign.error")}</b>{s.error}</div>}
          <pre className="summary">{s.summary || t("campaign.no_report")}</pre>
        </td></tr>
      )}
    </>
  );
}

export default function Campaign({ route }: { route: Route }) {
  const t = useT();
  const { lang } = useI18n();
  const [runs, setRuns] = useState<RunState[] | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const name = route.arg || runs?.[0]?.name;

  useEffect(() => { api<RunState[]>("/api/runs").then(setRuns).catch((e) => setError(String(e.message))); }, []);
  useEffect(() => {
    if (!name) return;
    let live = true;
    const load = () => api<RunState>(`/api/run/${encodeURIComponent(name)}`)
      .then((r) => live && setRun(r)).catch((e) => live && setError(String(e.message)));
    load();
    const timer = setInterval(load, 4000);
    return () => { live = false; clearInterval(timer); };
  }, [name]);

  if (error) return <div className="view"><div className="intel red"><b>{t("campaign.title")}</b>{error}</div></div>;
  if (!runs) return <Loading what={t("campaign.loading_runs")} />;
  if (!name) {
    return (
      <div className="view">
        <h1>{t("campaign.title")}</h1>
        <Panel title={t("campaign.empty.title")}>
          <p>{t("campaign.empty.intro")}</p>
          <pre className="summary">
            {`uv run urim run GEN.38-40      # ${t("campaign.empty.pilot")}\n`}
            {`uv run urim run GEN            # ${t("campaign.empty.book")}\n`}
            {`uv run urim run GEN --plan     # ${t("campaign.empty.plan")}`}
          </pre>
          <p className="muted">{t("campaign.empty.resume")}</p>
        </Panel>
      </div>
    );
  }
  if (!run) return <Loading what={t("campaign.loading_run")} />;

  const running = new Map(run.running.map((s) => [`${s.chapter}:${s.layer}`, s]));
  const layerRows = run.chapters.flatMap((c) => Object.values(c.layers));
  const done = layerRows.filter((r) => r.phase === "done").length;
  const failed = layerRows.filter((r) => r.phase === "failed").length;
  const pct = layerRows.length ? done / layerRows.length : 0;
  const cmd = <span className="mono">uv run urim run {run.scope}</span>;
  return (
    <div className="view">
      <style>{`
        .camp-grid { display: grid; gap: 4px; }
        .cell { border: 1px solid; border-radius: 3px; padding: 4px 6px; min-height: 34px; background: rgba(255,255,255,.015); }
        .cell.live { animation: pulse 1.6s ease-in-out infinite; }
        @keyframes pulse { 50% { box-shadow: 0 0 10px rgba(79,209,232,.55); } }
        .summary { white-space: pre-wrap; font: 12px/1.5 var(--mono); color: var(--dim); max-height: 320px; overflow: auto; margin: 6px 0; }
        table.steps { width: 100%; border-collapse: collapse; font-size: 12px; }
        table.steps td { padding: 4px 6px; border-top: 1px solid var(--line); vertical-align: top; }
        .bigbar { height: 6px; background: #132230; border-radius: 3px; overflow: hidden; }
        .bigbar div { height: 100%; background: linear-gradient(90deg, var(--amber), var(--green)); }
      `}</style>
      <div className="row" style={{ marginBottom: 14, alignItems: "flex-end", gap: 16 }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("campaign.kicker")}</div>
          <h1>{run.name} <span className="hud upper" style={{ fontSize: 13, color: STATUS_COLOR[run.status] }}>· {runStatusLabel(t, run.status)}</span></h1>
        </div>
        <div className="spacer" />
        {runs.length > 1 && (
          <select value={run.name} onChange={(e) => go("campaign", e.target.value)}>
            {runs.map((r) => <option key={r.name} value={r.name}>{r.name} · {runStatusLabel(t, r.status)}</option>)}
          </select>
        )}
      </div>
      {run.status === "waiting" && run.waiting_until && (
        <div className="intel" style={{ marginBottom: 12 }}>
          <b>{!run.waiting_for || run.waiting_for === "usage limit" ? t("campaign.waiting.usage_limit") : t("campaign.waiting.api_failed")}</b>
          {t("campaign.waiting.until", { time: new Date(run.waiting_until).toLocaleString(lang) })}
          {run.waiting_for && run.waiting_for !== "usage limit" && <div className="mono muted" style={{ fontSize: 12, marginTop: 4 }}>{run.waiting_for}</div>}
        </div>
      )}
      {run.status === "finished" && failed > 0 && (
        <div className="intel red" style={{ marginBottom: 12 }}>
          <b>{t("campaign.failed.title")}</b><Msg k="campaign.failed.text" vars={{ count: failed, cmd }} />
        </div>
      )}
      {run.status === "interrupted" && (
        <div className="intel red" style={{ marginBottom: 12 }}>
          <b>{t("campaign.interrupted.title")}</b><Msg k="campaign.interrupted.text" vars={{ cmd }} />
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 400px", gap: 16, alignItems: "start" }}>
        <div className="grid">
          <Panel title={t("campaign.progress")} count={`${done}/${layerRows.length}`}>
            <div className="bigbar" style={{ marginBottom: 10 }}><div style={{ width: `${pct * 100}%` }} /></div>
            <div className="row muted mono" style={{ gap: 18, fontSize: 12, marginBottom: 12 }}>
              <span>{t("campaign.sessions_count", { count: run.totals.sessions })}</span>
              <span>{t("campaign.tokens", { millions: num(run.totals.tokens / 1e6, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) })}</span>
              <span>{t("campaign.cost", { cost: usd(run.totals.cost_usd) })}</span>
              <span>{t("campaign.started", { ago: ago(run.started) })}</span>
              <span>{t("campaign.parallel", { count: run.parallel })} · {t("campaign.max_rounds", { count: run.max_rounds })}</span>
            </div>
            <div className="camp-grid" style={{ gridTemplateColumns: `80px repeat(${run.layers.length}, minmax(0, 1fr))` }}>
              <div />
              {run.layers.map((l) => <div key={l} className="hud upper muted" style={{ fontSize: 10 }}>{layerLabel(t, l)} · {(run.models[l] ?? run.models.localization)?.replace("claude-", "")}</div>)}
              {run.chapters.map((c) => (
                <div key={c.chapter} style={{ display: "contents" }}>
                  <a className="mono" style={{ alignSelf: "center", fontSize: 12 }} onClick={() => go("review", "", { chapter: c.chapter, status: "all" })}>{c.chapter}</a>
                  {run.layers.map((l) => <Cell key={l} row={c.layers[l]} step={running.get(`${c.chapter}:${l}`)} />)}
                </div>
              ))}
            </div>
          </Panel>
          <Panel title={t("campaign.sessions")} count={run.steps?.length}>
            <table className="steps"><tbody>
              {[...(run.steps ?? [])].reverse().map((s, i) => <StepRow key={`${s.id}-${i}`} s={s} />)}
            </tbody></table>
          </Panel>
        </div>
        <div className="grid">
          <Panel title={t("campaign.now")} count={run.running.length}>
            {run.running.length === 0 && <div className="muted">{t("campaign.none_running")}</div>}
            {run.running.map((s) => (
              <div key={s.id} style={{ marginBottom: 10 }}>
                <div className="mono" style={{ color: "var(--cyan)" }}>
                  {actionLabel(t, s.action)} {layerLabel(t, s.layer)} {s.scope}{s.round ? ` · ${t("campaign.round", { round: s.round })}` : ""}
                </div>
                <div className="muted" style={{ fontSize: 12 }}>{s.model} · {ago(s.started)}</div>
                {s.activity && <div className="mono faint" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.activity}</div>}
              </div>
            ))}
          </Panel>
          <Panel title={t("campaign.escalated")} count={run.escalated?.length ?? 0}>
            {!run.escalated?.length && <div className="muted">{t("campaign.none_escalated")}</div>}
            {run.escalated?.slice(0, 30).map((e) => (
              <div key={e.key} className="click" style={{ marginBottom: 8, cursor: "pointer" }}
                   onClick={() => go("review", "", { chapter: e.chapter, status: "draft" })}>
                <div className="mono" style={{ fontSize: 12, color: "var(--amber)" }}>{e.key}</div>
                <div className="muted" style={{ fontSize: 12 }}>{e.note}</div>
              </div>
            ))}
          </Panel>
          <Panel title={t("campaign.log")}>
            <pre className="summary">{[...(run.log ?? [])].reverse().join("\n")}</pre>
          </Panel>
        </div>
      </div>
    </div>
  );
}
