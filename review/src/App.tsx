import type { ReactNode } from "react";
import { Icon } from "./components";
import { useApp } from "./state";
import { href, useRoute } from "./util";
import Command from "./views/Command";
import Review from "./views/Review";
import Xray from "./views/Xray";
import Chronicle from "./views/Chronicle";
import Causal from "./views/Causal";
import Atlas from "./views/Atlas";
import Dossiers from "./views/Dossiers";
import Codex from "./views/Codex";
import Query from "./views/Query";

const NAV: { id: string; label: string }[] = [
  { id: "command", label: "Command" }, { id: "review", label: "Review" }, { id: "xray", label: "X-Ray" },
  { id: "chronicle", label: "Chronicle" }, { id: "causal", label: "Causal" }, { id: "atlas", label: "Atlas" },
  { id: "dossiers", label: "Dossiers" }, { id: "codex", label: "Codex" }, { id: "query", label: "Query" },
];

function Insignia({ level }: { level: number }) {
  return (
    <div className="insignia">
      <svg viewBox="0 0 34 34"><path d="M17 1 32 9v16l-15 8L2 25V9Z" fill="rgba(255,179,71,.08)" stroke="var(--amber)" strokeWidth="1.5" /></svg>
      {level}
    </div>
  );
}

function TopBar() {
  const { overview, lang, setLang, languages, demo } = useApp();
  const p = overview?.player;
  const t = overview?.totals;
  const pct = p ? (p.xp - p.level_floor) / Math.max(p.level_ceiling - p.level_floor, 1) : 0;
  return (
    <header className="topbar">
      <div className="brand">
        <svg width="26" height="26" viewBox="0 0 32 32"><path d="M16 2 30 16 16 30 2 16Z" fill="none" stroke="var(--amber)" strokeWidth="2" /><circle cx="16" cy="16" r="4" fill="var(--amber)" /></svg>
        <b>URIM</b><small>WAR ROOM</small>
      </div>
      {demo && <span className="pill" style={{ color: "var(--violet)" }}>Demo corpus</span>}
      <div className="spacer" />
      {t && (
        <>
          <div className="stat-inline">Drafts<b style={{ color: "var(--amber)" }}>{t.drafts}</b></div>
          <div className="stat-inline">Sent back<b style={{ color: "var(--red)" }}>{t.requests}</b></div>
          <div className="stat-inline">Approved<b style={{ color: "var(--green)" }}>{t.approved}</b></div>
        </>
      )}
      {p && (
        <div className="stat-inline" title="Days in a row with at least one review">
          Streak<b style={{ color: p.streak_days ? "var(--amber)" : "var(--faint)" }}>
            <span style={{ verticalAlign: "-3px" }}><Icon name="flame" size={16} /></span>{p.streak_days}
          </b>
        </div>
      )}
      {p && (
        <div className="rank">
          <Insignia level={p.level} />
          <div className="xpbar">
            <div className="label"><span style={{ color: "var(--amber)" }}>{p.rank}</span><span className="mono">{p.xp} XP</span></div>
            <div className="track"><div className="fill" style={{ width: `${pct * 100}%` }} /></div>
            <div className="label"><span>Lv {p.level}</span><span>next {p.level_ceiling}</span></div>
          </div>
        </div>
      )}
      <a className="btn small ghost" href="/codex.html" title="Read without review: the Illuminated Codex">Codex ↗</a>
      <select value={lang} onChange={(e) => setLang(e.target.value)} title="Language bundle">
        {(languages.length ? languages : [{ lang_code: "en", lang_name: "English" }]).map((l) => (
          <option key={l.lang_code} value={l.lang_code}>{l.lang_code.toUpperCase()} · {l.lang_name}</option>
        ))}
      </select>
    </header>
  );
}

export default function App() {
  const route = useRoute();
  const { overview } = useApp();
  const views: Record<string, ReactNode> = {
    command: <Command />, review: <Review route={route} />, xray: <Xray route={route} />,
    chronicle: <Chronicle route={route} />, causal: <Causal route={route} />, atlas: <Atlas route={route} />,
    dossiers: <Dossiers route={route} />, codex: <Codex route={route} />, query: <Query />,
  };
  const pending = (overview?.totals.drafts ?? 0) + (overview?.totals.requests ?? 0);
  return (
    <div className="app">
      <TopBar />
      <nav className="rail">
        {NAV.map((n) => (
          <a key={n.id} href={href(n.id)} className={route.view === n.id ? "active" : ""}>
            <Icon name={n.id} />{n.label}
            {n.id === "review" && pending > 0 && <span className="badge-dot">{pending}</span>}
          </a>
        ))}
      </nav>
      <main className="main">{views[route.view] ?? views.command}</main>
    </div>
  );
}
