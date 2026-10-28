import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, post } from "./api";
import { I18nProvider, has, tr, useI18n, useT } from "./i18n";
import type { Badge, LedgerEntry, Overview, ReviewResult, Status } from "./api";

interface Toast { id: number; text: string; tone: "amber" | "green" | "red" }

interface AppState {
  lang: string;
  setLang: (lang: string) => void;
  languages: { lang_code: string; lang_name: string }[];
  demo: boolean;
  overview: Overview | null;
  ledger: Record<string, LedgerEntry>;
  refresh: () => Promise<void>;
  toast: (text: string, tone?: Toast["tone"]) => void;
  review: (keys: string[], status: Status, note?: string) => Promise<ReviewResult | null>;
}

const Ctx = createContext<AppState | null>(null);

// Ranks and badges arrive from the server in English (urim/review/progress.py); the words are
// translated here by rank name and badge id, and fall back to the server's English.

/** A rank in words: Scout, Runner, Scribe… */
export function rankLabel(rank: string): string {
  const key = `shell.rank.${rank.toLowerCase()}`;
  return has(key) ? tr(key) : rank;
}

export const badgeName = (b: Badge) => (has(`shell.badge.${b.id}.name`) ? tr(`shell.badge.${b.id}.name`) : b.name);
export const badgeDescription = (b: Badge) =>
  has(`shell.badge.${b.id}.description`) ? tr(`shell.badge.${b.id}.description`) : b.description;

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp outside AppProvider");
  return ctx;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem("urim.lang") ?? "en"; } catch { return "en"; }
  });
  const [languages, setLanguages] = useState<AppState["languages"]>([]);
  const [demo, setDemo] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [ledger, setLedger] = useState<Record<string, LedgerEntry>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [levelUp, setLevelUp] = useState<string | null>(null);
  const nextId = useRef(1);

  const setLang = (l: string) => {
    setLangState(l);
    try { localStorage.setItem("urim.lang", l); } catch { /* storage unavailable */ }
  };

  const toast = useCallback((text: string, tone: Toast["tone"] = "amber") => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2600);
  }, []);

  const refresh = useCallback(async () => {
    const [o, l] = await Promise.all([api<Overview>("/api/overview"), api<Record<string, LedgerEntry>>("/api/ledger")]);
    setOverview(o);
    setLedger(l);
  }, []);

  useEffect(() => {
    api<{ demo: boolean; languages: AppState["languages"] }>("/api/meta").then((m) => {
      setDemo(m.demo);
      setLanguages(m.languages);
    });
    refresh();
  }, [refresh]);

  const review = useCallback(async (keys: string[], status: Status, note?: string) => {
    const before = overview?.badges.filter((b) => b.earned).map((b) => b.id) ?? [];
    try {
      const r = await post<ReviewResult>("/api/review", { keys, status, note: note || null });
      if (r.xp_gained > 0) toast(tr("shell.toast.xp", { xp: r.xp_gained }), status === "approved" ? "green" : "amber");
      if (status === "changes_requested") toast(tr("shell.toast.sent_back"), "red");
      if (r.level_up) {
        setLevelUp(r.player.rank);
        setTimeout(() => setLevelUp(null), 2700);
      }
      r.badges.filter((b) => b.earned && !before.includes(b.id)).forEach((b) => toast(tr("shell.toast.badge", { name: badgeName(b) }), "green"));
      await refresh();
      return r;
    } catch (e) {
      toast(String((e as Error).message), "red");
      return null;
    }
  }, [overview, refresh, toast]);

  return (
    <Ctx.Provider value={{ lang, setLang, languages, demo, overview, ledger, refresh, toast, review }}>
      <I18nProvider lang={lang}>
        {children}
        <div className="toasts">
          {toasts.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.text}</div>)}
        </div>
        {levelUp && <LevelUp rank={levelUp} />}
      </I18nProvider>
    </Ctx.Provider>
  );
}

function LevelUp({ rank }: { rank: string }) {
  const t = useT();
  const { lang } = useI18n();
  return <div className="levelup"><div>{t("shell.rank_up")}<small>{rankLabel(rank).toLocaleUpperCase(lang)}</small></div></div>;
}

export { useApi } from "./hooks";
