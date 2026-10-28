import { useEffect, useState } from "react";
import type { ChapterTile, LearnChapter, LearnOverview, Overview } from "../api";
import { STATIC, api } from "../api";
import { Icon, Loading, Panel, ProgressRing } from "../components";
import { has, num, tr, useT } from "../i18n";
import type { TFunc } from "../i18n";
import { badgeDescription, badgeName, rankLabel, useApp } from "../state";
import { go } from "../util";

const pct = (v: number) => num(v, { style: "percent", maximumFractionDigits: 0 });

/** A section of the canon in words; the names arrive from the server in English (progress.py). */
function sectionLabel(name: string): string {
  const key = `command.section.${name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")}`;
  return has(key) ? tr(key) : name;
}

function tileStyle(t: ChapterTile): React.CSSProperties {
  if (!t.ingested) return {};
  const c = t.completion ?? 0;
  const held = (t.approval ?? 0) >= 0.999 && (t.approved ?? 0) > 0;
  return {
    background: held
      ? "linear-gradient(135deg, rgba(69,224,138,.9), rgba(69,224,138,.55))"
      : `rgba(255, 179, 71, ${0.18 + 0.75 * c})`,
    borderColor: held ? "var(--green)" : "rgba(255,179,71,.8)",
    boxShadow: held ? "0 0 8px rgba(69,224,138,.7)" : `0 0 ${4 + 8 * c}px rgba(255,179,71,${0.25 + 0.4 * c})`,
  };
}

// Knowing: the same territory coloured by what you have learned (violet) and proven (gold).
function masteryStyle(m?: LearnChapter): React.CSSProperties {
  if (!m) return {};
  if (m.proven) return { background: "linear-gradient(135deg, #f3d77a, #c9982e)", borderColor: "#f3d77a", boxShadow: "0 0 8px rgba(243,215,122,.75)" };
  const v = m.mastery;
  return v > 0
    ? { background: `rgba(165, 139, 250, ${0.2 + 0.75 * v})`, borderColor: "rgba(165,139,250,.85)", boxShadow: `0 0 ${3 + 8 * v}px rgba(165,139,250,.5)` }
    : { background: "rgba(165,139,250,.06)", borderColor: "rgba(165,139,250,.35)" };
}

function Theatre({ overview, onHover, mastery }: {
  overview: Overview; onHover: (t: ChapterTile | null, e?: React.MouseEvent) => void;
  mastery: Record<string, LearnChapter> | null;
}) {
  return (
    <div className="grid" style={{ gap: 18 }}>
      {overview.sections.map((s) => (
        <div key={s.name}>
          <div className="hud upper muted" style={{ fontSize: 11, marginBottom: 8, letterSpacing: "0.3em" }}>{sectionLabel(s.name)}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "14px 18px" }}>
            {overview.books.filter((b) => b.book_id >= s.first && b.book_id <= s.last).map((b) => {
              const revealed = b.chapters.some((c) => c.ingested);
              return (
                <div key={b.book_code} style={{ maxWidth: 25 * 12 }}>
                  <div className="mono" style={{ fontSize: 10, color: revealed ? "var(--amber)" : "var(--faint)", marginBottom: 4 }}>{b.osis}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                    {b.chapters.map((c) => (
                      <div key={c.ref} className={`tile ${c.ingested ? "on" : ""}`} style={mastery ? masteryStyle(mastery[c.ref]) : tileStyle(c)}
                           onMouseEnter={(e) => onHover(c, e)} onMouseMove={(e) => onHover(c, e)} onMouseLeave={() => onHover(null)}
                           onClick={() => c.ingested && (mastery ? go("learn", c.ref) : go("review", "", { chapter: c.ref }))}>
                        {(c.requests ?? 0) > 0 && <i />}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** A next step in words: the server sends English sentences for review steps, slash commands
 * for agents (which stay as they are). */
function missionText(t: TFunc, step: string): string {
  const requests = /^(\S+): (\d+) change request/.exec(step);
  if (requests) return t("command.mission.requests_waiting", { chapter: requests[1], count: Number(requests[2]) });
  const drafts = /^(\S+): review (\d+) draft/.exec(step);
  if (drafts) return t("command.mission.drafts_waiting", { chapter: drafts[1], count: Number(drafts[2]) });
  return step;
}

function Mission({ step }: { step: string }) {
  const { toast } = useApp();
  const t = useT();
  const agent = step.startsWith("/urim-");
  return (
    <div className="mission" onClick={() => {
      if (agent) { navigator.clipboard?.writeText(step); toast(t("command.mission.copied")); }
      else { const ch = step.split(":")[0]; go("review", "", { chapter: ch, status: step.includes("change") ? "changes_requested" : "draft" }); }
    }}>
      <span className="mission-tag" style={{ color: agent ? "var(--cyan)" : "var(--amber)" }}>{agent ? t("command.mission.agent") : t("command.mission.review")}</span>
      <span className={agent ? "mono" : ""}>{missionText(t, step)}</span>
      <span className="spacer" />
      <span className="muted hud upper" style={{ fontSize: 10 }}>{agent ? `${t("command.mission.copy")} ⧉` : `${t("command.mission.open")} →`}</span>
    </div>
  );
}

export default function Command() {
  const { overview, lang } = useApp();
  const t = useT();
  const [hover, setHover] = useState<{ t: ChapterTile; x: number; y: number } | null>(null);
  const [knowing, setKnowing] = useState(() => { try { return !STATIC && localStorage.getItem("urim.command.layer") === "knowing"; } catch { return false; } });
  const [mastery, setMastery] = useState<Record<string, LearnChapter> | null>(null);
  useEffect(() => {
    try { localStorage.setItem("urim.command.layer", knowing ? "knowing" : "writing"); } catch { /* storage unavailable */ }
    if (knowing && !mastery) api<LearnOverview>(`/api/learn/overview?lang=${lang}`).then((o) => setMastery(Object.fromEntries(o.chapters.map((c) => [c.chapter, c]))));
  }, [knowing, mastery, lang]);
  if (!overview) return <Loading what={t("command.loading")} />;
  const totals = overview.totals;
  const p = overview.player;
  return (
    <div className="view">
      <style>{`
        .tile { width: 10px; height: 10px; border: 1px solid #142230; background: #0a121a; border-radius: 1px; position: relative; }
        .tile.on { cursor: pointer; }
        .tile.on:hover { outline: 1px solid var(--text); outline-offset: 1px; }
        .tile i { position: absolute; top: -3px; right: -3px; width: 5px; height: 5px; border-radius: 50%; background: var(--red); box-shadow: 0 0 5px var(--red); }
        .mission { display: flex; gap: 10px; align-items: center; padding: 9px 10px; border: 1px solid var(--line); border-radius: 4px; cursor: pointer; background: rgba(255,255,255,.015); }
        .mission:hover { border-color: var(--amber); background: rgba(255,179,71,.05); }
        .mission-tag { font: 700 10px/1 var(--hud); letter-spacing: .2em; padding: 3px 6px; border: 1px solid currentColor; border-radius: 3px; }
        .badge { display: grid; grid-template-columns: 42px 1fr; gap: 10px; align-items: center; padding: 8px; border: 1px solid var(--line); border-radius: 4px; }
        .badge.earned { border-color: rgba(69,224,138,.45); background: rgba(69,224,138,.05); }
        .hex { width: 42px; height: 42px; display: grid; place-items: center; clip-path: polygon(25% 3%, 75% 3%, 100% 50%, 75% 97%, 25% 97%, 0 50%); background: #101c26; color: var(--faint); font: 700 16px var(--hud); }
        .badge.earned .hex { background: linear-gradient(135deg, var(--green), #1f8a52); color: #031; }
        .bar { height: 4px; background: #132230; border-radius: 2px; overflow: hidden; margin-top: 5px; }
        .bar div { height: 100%; background: var(--amber); }
      `}</style>
      <div className="row" style={{ marginBottom: 16, alignItems: "flex-end" }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("command.theatre")}</div>
          <h1>{t("command.title")} <span className="muted" style={{ fontWeight: 500, fontSize: 18 }}>· {t("command.chapters_revealed", { revealed: totals.chapters_ingested, count: totals.chapters_in_canon })}</span></h1>
        </div>
        <div className="spacer" />
        <div className="row muted hud upper" style={{ fontSize: 10, gap: 14 }}>
          <span className="row" style={{ gap: 6 }}><span className="tile" /> {t("command.legend.fog")}</span>
          <span className="row" style={{ gap: 6 }}><span className="tile" style={{ background: "rgba(255,179,71,.3)", borderColor: "rgba(255,179,71,.8)" }} /> {t("command.legend.revealed")}</span>
          <span className="row" style={{ gap: 6 }}><span className="tile" style={{ background: "rgba(255,179,71,.9)", borderColor: "var(--amber)" }} /> {t("command.legend.written")}</span>
          <span className="row" style={{ gap: 6 }}><span className="tile" style={{ background: "var(--green)", borderColor: "var(--green)" }} /> {t("command.legend.held")}</span>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 380px", gap: 16, alignItems: "start" }}>
        <Panel title={t("command.territory")} right={!STATIC && (
          <span className="row" style={{ gap: 4 }}>
            <span className={`chip click ${knowing ? "" : "on"}`} onClick={() => setKnowing(false)}>{t("command.layer.writing")}</span>
            <span className={`chip click ${knowing ? "on" : ""}`} onClick={() => setKnowing(true)} style={knowing ? { color: "var(--violet)" } : undefined}>{t("command.layer.knowing")}</span>
          </span>
        )}>
          <Theatre overview={overview} mastery={knowing ? mastery : null} onHover={(tile, e) => setHover(tile && e ? { t: tile, x: e.clientX, y: e.clientY } : null)} />
        </Panel>
        <div className="grid">
          <Panel title={t("command.commander")}>
            <div className="row" style={{ gap: 16 }}>
              <ProgressRing value={(p.xp - p.level_floor) / Math.max(p.level_ceiling - p.level_floor, 1)} size={84} label={t("command.level", { level: p.level })} sub={rankLabel(p.rank)} />
              <div className="grid" style={{ gap: 4 }}>
                <div className="mono" style={{ fontSize: 22, color: "var(--amber)" }}>{num(p.xp)} <span className="muted" style={{ fontSize: 12 }}>{t("command.xp")}</span></div>
                <div className="muted" style={{ fontSize: 12 }}>{t("command.xp_to_next", { xp: p.level_ceiling - p.xp })}</div>
                <div className="row" style={{ gap: 6, color: p.streak_days ? "var(--amber)" : "var(--faint)" }}>
                  <Icon name="flame" size={16} /> <span className="hud upper" style={{ fontSize: 11 }}>{t("command.streak", { count: p.streak_days })} · {t("command.decisions", { count: p.reviews })}</span>
                </div>
              </div>
            </div>
          </Panel>
          <Panel title={t("command.front_lines")}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <ProgressRing value={totals.verses_with_layers / Math.max(totals.verses, 1)} label={num(totals.verses_with_layers)} sub={t("command.ring.of_verses", { total: totals.verses })} color="var(--cyan)" />
              <ProgressRing value={totals.approved / Math.max(totals.items, 1)} label={num(totals.approved)} sub={t("command.ring.of_held", { total: totals.items })} color="var(--green)" />
              <ProgressRing value={totals.events ? 1 : 0} label={num(totals.events)} sub={t("command.ring.events", { count: totals.events })} color="var(--amber)" />
              <ProgressRing value={totals.requests ? 1 : 0} label={num(totals.requests)} sub={t("command.ring.sent_back", { count: totals.requests })} color="var(--red)" />
            </div>
          </Panel>
          <Panel title={t("command.missions")} count={overview.next_steps.length}>
            <div className="grid" style={{ gap: 6 }}>
              {overview.next_steps.length ? overview.next_steps.map((s) => <Mission key={s} step={s} />) : <div className="empty">{t("command.no_missions")}</div>}
            </div>
          </Panel>
          <Panel title={t("command.honours")} count={`${overview.badges.filter((b) => b.earned).length}/${overview.badges.length}`}>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {overview.badges.map((b) => (
                <div key={b.id} className={`badge ${b.earned ? "earned" : ""}`} title={badgeDescription(b)}>
                  <div className="hex">{b.earned ? "✦" : "?"}</div>
                  <div>
                    <div className="hud" style={{ fontWeight: 700, fontSize: 13, color: b.earned ? "var(--green)" : "var(--text)" }}>{badgeName(b)}</div>
                    <div className="muted" style={{ fontSize: 11 }}>{badgeDescription(b)}</div>
                    {!b.earned && <div className="bar"><div style={{ width: `${(b.progress / b.goal) * 100}%` }} /></div>}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
      {hover && (
        <div className="tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="hud" style={{ fontWeight: 700, fontSize: 14 }}>{hover.t.ref.replace(".", " ")}</div>
          {hover.t.ingested ? (
            <dl className="kv" style={{ marginTop: 6 }}>
              <dt>{t("command.tip.verses")}</dt><dd>{num(hover.t.verses ?? 0)}</dd>
              <dt>{t("command.tip.written")}</dt>
              <dd>{pct(hover.t.completion ?? 0)} · {t("command.tip.events", { count: hover.t.events ?? 0 })} · {t("command.tip.layered", { count: hover.t.philology ?? 0 })}</dd>
              <dt>{t("command.tip.review")}</dt>
              <dd>
                <span className="st-approved">{t("command.tip.held", { count: hover.t.approved ?? 0 })}</span> · <span className="st-draft">{t("command.tip.drafts", { count: hover.t.drafts ?? 0 })}</span> · <span className="st-changes_requested">{t("command.tip.sent_back", { count: hover.t.requests ?? 0 })}</span>
              </dd>
              {knowing && mastery?.[hover.t.ref] && (() => {
                const m = mastery[hover.t.ref];
                return (
                  <>
                    <dt>{t("command.tip.known")}</dt>
                    <dd style={{ color: "var(--violet)" }}>
                      {pct(m.mastery)} · {t("command.tip.facts", { known: m.known ?? 0, count: m.facts })}
                      {m.proven ? ` · ${t("command.tip.proven")} ★` : ""}{m.due ? ` · ${t("command.tip.due", { count: m.due })}` : ""}
                    </dd>
                  </>
                );
              })()}
            </dl>
          ) : <div className="muted">{t("command.tip.fog")}</div>}
        </div>
      )}
    </div>
  );
}
