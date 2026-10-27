import { useState } from "react";
import type { ChapterTile, Overview } from "../api";
import { Icon, Loading, Panel, ProgressRing } from "../components";
import { useApp } from "../state";
import { go } from "../util";

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

function Theatre({ overview, onHover }: { overview: Overview; onHover: (t: ChapterTile | null, e?: React.MouseEvent) => void }) {
  return (
    <div className="grid" style={{ gap: 18 }}>
      {overview.sections.map((s) => (
        <div key={s.name}>
          <div className="hud upper muted" style={{ fontSize: 11, marginBottom: 8, letterSpacing: "0.3em" }}>{s.name}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "14px 18px" }}>
            {overview.books.filter((b) => b.book_id >= s.first && b.book_id <= s.last).map((b) => {
              const revealed = b.chapters.some((c) => c.ingested);
              return (
                <div key={b.book_code} style={{ maxWidth: 25 * 12 }}>
                  <div className="mono" style={{ fontSize: 10, color: revealed ? "var(--amber)" : "var(--faint)", marginBottom: 4 }}>{b.osis}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                    {b.chapters.map((c) => (
                      <div key={c.ref} className={`tile ${c.ingested ? "on" : ""}`} style={tileStyle(c)}
                           onMouseEnter={(e) => onHover(c, e)} onMouseMove={(e) => onHover(c, e)} onMouseLeave={() => onHover(null)}
                           onClick={() => c.ingested && go("review", "", { chapter: c.ref })}>
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

function Mission({ step }: { step: string }) {
  const { toast } = useApp();
  const agent = step.startsWith("/urim-");
  return (
    <div className="mission" onClick={() => {
      if (agent) { navigator.clipboard?.writeText(step); toast("Command copied: paste it into a new chat"); }
      else { const ch = step.split(":")[0]; go("review", "", { chapter: ch, status: step.includes("change") ? "changes_requested" : "draft" }); }
    }}>
      <span className="mission-tag" style={{ color: agent ? "var(--cyan)" : "var(--amber)" }}>{agent ? "AGENT" : "REVIEW"}</span>
      <span className={agent ? "mono" : ""}>{step}</span>
      <span className="spacer" />
      <span className="muted hud upper" style={{ fontSize: 10 }}>{agent ? "copy ⧉" : "open →"}</span>
    </div>
  );
}

export default function Command() {
  const { overview } = useApp();
  const [hover, setHover] = useState<{ t: ChapterTile; x: number; y: number } | null>(null);
  if (!overview) return <Loading what="Raising the war room" />;
  const t = overview.totals;
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
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>Theatre of operations</div>
          <h1>The Canon <span className="muted" style={{ fontWeight: 500, fontSize: 18 }}>· {t.chapters_ingested} of {t.chapters_in_canon} chapters revealed</span></h1>
        </div>
        <div className="spacer" />
        <div className="row muted hud upper" style={{ fontSize: 10, gap: 14 }}>
          <span className="row" style={{ gap: 6 }}><span className="tile" /> Fog</span>
          <span className="row" style={{ gap: 6 }}><span className="tile" style={{ background: "rgba(255,179,71,.3)", borderColor: "rgba(255,179,71,.8)" }} /> Revealed</span>
          <span className="row" style={{ gap: 6 }}><span className="tile" style={{ background: "rgba(255,179,71,.9)", borderColor: "var(--amber)" }} /> Written</span>
          <span className="row" style={{ gap: 6 }}><span className="tile" style={{ background: "var(--green)", borderColor: "var(--green)" }} /> Held</span>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 380px", gap: 16, alignItems: "start" }}>
        <Panel title="Territory">
          <Theatre overview={overview} onHover={(tile, e) => setHover(tile && e ? { t: tile, x: e.clientX, y: e.clientY } : null)} />
        </Panel>
        <div className="grid">
          <Panel title="Commander">
            <div className="row" style={{ gap: 16 }}>
              <ProgressRing value={(p.xp - p.level_floor) / Math.max(p.level_ceiling - p.level_floor, 1)} size={84} label={`L${p.level}`} sub={p.rank} />
              <div className="grid" style={{ gap: 4 }}>
                <div className="mono" style={{ fontSize: 22, color: "var(--amber)" }}>{p.xp} <span className="muted" style={{ fontSize: 12 }}>XP</span></div>
                <div className="muted" style={{ fontSize: 12 }}>{p.level_ceiling - p.xp} XP to next rank</div>
                <div className="row" style={{ gap: 6, color: p.streak_days ? "var(--amber)" : "var(--faint)" }}>
                  <Icon name="flame" size={16} /> <span className="hud upper" style={{ fontSize: 11 }}>{p.streak_days}-day streak · {p.reviews} decisions</span>
                </div>
              </div>
            </div>
          </Panel>
          <Panel title="Front lines">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <ProgressRing value={t.verses_with_layers / Math.max(t.verses, 1)} label={t.verses_with_layers} sub={`of ${t.verses} vv`} color="var(--cyan)" />
              <ProgressRing value={t.approved / Math.max(t.items, 1)} label={t.approved} sub={`of ${t.items} held`} color="var(--green)" />
              <ProgressRing value={t.events ? 1 : 0} label={t.events} sub="events" color="var(--amber)" />
              <ProgressRing value={t.requests ? 1 : 0} label={t.requests} sub="sent back" color="var(--red)" />
            </div>
          </Panel>
          <Panel title="Missions" count={overview.next_steps.length}>
            <div className="grid" style={{ gap: 6 }}>
              {overview.next_steps.length ? overview.next_steps.map((s) => <Mission key={s} step={s} />) : <div className="empty">No missions</div>}
            </div>
          </Panel>
          <Panel title="Honours" count={`${overview.badges.filter((b) => b.earned).length}/${overview.badges.length}`}>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {overview.badges.map((b) => (
                <div key={b.id} className={`badge ${b.earned ? "earned" : ""}`} title={b.description}>
                  <div className="hex">{b.earned ? "✦" : "?"}</div>
                  <div>
                    <div className="hud" style={{ fontWeight: 700, fontSize: 13, color: b.earned ? "var(--green)" : "var(--text)" }}>{b.name}</div>
                    <div className="muted" style={{ fontSize: 11 }}>{b.description}</div>
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
              <dt>Verses</dt><dd>{hover.t.verses}</dd>
              <dt>Written</dt><dd>{Math.round((hover.t.completion ?? 0) * 100)}% · {hover.t.events} events · {hover.t.philology} vv layered</dd>
              <dt>Review</dt><dd><span className="st-approved">{hover.t.approved} held</span> · <span className="st-draft">{hover.t.drafts} drafts</span> · <span className="st-changes_requested">{hover.t.requests} sent back</span></dd>
            </dl>
          ) : <div className="muted">Fog of war: not ingested yet</div>}
        </div>
      )}
    </div>
  );
}
