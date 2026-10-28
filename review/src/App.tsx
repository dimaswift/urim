import type { ReactNode } from "react";
import { STATIC } from "./api";
import { Icon } from "./components";
import type { TFunc } from "./i18n";
import { num, useT } from "./i18n";
import { rankLabel, useApp } from "./state";
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
import Campaign from "./views/Campaign";
import Learn from "./views/Learn";
import Languages from "./views/Languages";

// Learn and Campaign keep state on the server: the static copy (GitHub Pages) goes without.
const SERVER_VIEWS = ["learn", "campaign"];
const NAV = ["command", "learn", "campaign", "languages", "review", "xray", "chronicle", "causal", "atlas", "dossiers", "codex", "query"]
  .filter((id) => !STATIC || !SERVER_VIEWS.includes(id));

function navLabel(t: TFunc, id: string): string {
  switch (id) {
    case "command": return t("shell.nav.command");
    case "learn": return t("shell.nav.learn");
    case "campaign": return t("shell.nav.campaign");
    case "languages": return t("shell.nav.languages");
    case "review": return t("shell.nav.review");
    case "xray": return t("shell.nav.xray");
    case "chronicle": return t("shell.nav.chronicle");
    case "causal": return t("shell.nav.causal");
    case "atlas": return t("shell.nav.atlas");
    case "dossiers": return t("shell.nav.dossiers");
    case "codex": return t("shell.nav.codex");
    case "query": return t("shell.nav.query");
    default: return id;
  }
}

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
  const t = useT();
  const p = overview?.player;
  const totals = overview?.totals;
  const pct = p ? (p.xp - p.level_floor) / Math.max(p.level_ceiling - p.level_floor, 1) : 0;
  return (
    <header className="topbar">
      <div className="brand">
        <svg width="26" height="26" viewBox="0 0 32 32"><path d="M16 2 30 16 16 30 2 16Z" fill="none" stroke="var(--amber)" strokeWidth="2" /><circle cx="16" cy="16" r="4" fill="var(--amber)" /></svg>
        <b>URIM</b><small>{t("shell.war_room")}</small>
      </div>
      {demo && <span className="pill" style={{ color: "var(--violet)" }}>{t("shell.demo_corpus")}</span>}
      {STATIC && <span className="pill" style={{ color: "var(--cyan)" }} title={t("site.static_title")}>{t("site.static")}</span>}
      <div className="spacer" />
      {totals && (
        <>
          <div className="stat-inline">{t("shell.totals.drafts")}<b style={{ color: "var(--amber)" }}>{num(totals.drafts)}</b></div>
          <div className="stat-inline">{t("shell.totals.sent_back")}<b style={{ color: "var(--red)" }}>{num(totals.requests)}</b></div>
          <div className="stat-inline">{t("shell.totals.approved")}<b style={{ color: "var(--green)" }}>{num(totals.approved)}</b></div>
        </>
      )}
      {p && (
        <div className="stat-inline" title={t("shell.streak_title")}>
          {t("shell.streak")}<b style={{ color: p.streak_days ? "var(--amber)" : "var(--faint)" }}>
            <span style={{ verticalAlign: "-3px" }}><Icon name="flame" size={16} /></span>{p.streak_days}
          </b>
        </div>
      )}
      {p && (
        <div className="rank">
          <Insignia level={p.level} />
          <div className="xpbar">
            <div className="label"><span style={{ color: "var(--amber)" }}>{rankLabel(p.rank)}</span><span className="mono">{t("shell.xp", { xp: p.xp })}</span></div>
            <div className="track"><div className="fill" style={{ width: `${pct * 100}%` }} /></div>
            <div className="label"><span>{t("shell.level", { level: p.level })}</span><span>{t("shell.next_level", { xp: p.level_ceiling })}</span></div>
          </div>
        </div>
      )}
      <a className="btn small ghost" href="codex.html" title={t("shell.codex_title")}>{t("shell.codex_link")} ↗</a>
      <select value={lang} onChange={(e) => setLang(e.target.value)} title={t("shell.language_title")}>
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
  const t = useT();
  const views: Record<string, ReactNode> = {
    command: <Command />, review: <Review route={route} />, xray: <Xray route={route} />,
    chronicle: <Chronicle route={route} />, causal: <Causal route={route} />, atlas: <Atlas route={route} />,
    dossiers: <Dossiers route={route} />, codex: <Codex route={route} />, query: <Query />,
    campaign: <Campaign route={route} />, learn: <Learn route={route} />, languages: <Languages />,
  };
  if (STATIC) for (const id of SERVER_VIEWS) views[id] = <div className="intel">{t("site.server_only")}</div>;
  const pending = (overview?.totals.drafts ?? 0) + (overview?.totals.requests ?? 0);
  return (
    <div className="app">
      <TopBar />
      <nav className="rail">
        {NAV.map((id) => (
          <a key={id} href={href(id)} className={route.view === id ? "active" : ""}>
            <Icon name={id} />{navLabel(t, id)}
            {id === "review" && pending > 0 && <span className="badge-dot">{num(pending)}</span>}
          </a>
        ))}
      </nav>
      <main className="main">{views[route.view] ?? views.command}</main>
    </div>
  );
}
