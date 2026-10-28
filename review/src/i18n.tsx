// Interface messages for both apps. English is the source, written with the code in
// urim/i18n/en/*.json and bundled here; translations come from the localizer through
// /api/messages and fall back to English per message. Placeholders are {name}; a message with
// plural forms picks one by {count} with Intl.PluralRules. Components call useT(); helpers
// outside React (util.ts) call tr(), which follows the language last rendered.
import { createContext, Fragment, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

type Entry = string | Record<string, string>;
type Catalog = Record<string, Entry>;
export type Vars = Record<string, string | number>;
export type TFunc = (key: string, vars?: Vars) => string;

const PLURALS = ["zero", "one", "two", "few", "many", "other"];
const files = import.meta.glob<Record<string, string | Record<string, string>>>(
  "../../urim/i18n/en/*.json", { eager: true, import: "default" },
);
export const ENGLISH: Catalog = {};
for (const file of Object.values(files)) {
  for (const [k, v] of Object.entries(file)) {
    if (typeof v === "string") ENGLISH[k] = v;
    else if (v.text !== undefined) ENGLISH[k] = v.text;
    else ENGLISH[k] = Object.fromEntries(Object.entries(v).filter(([p]) => PLURALS.includes(p)));
  }
}

/** Whether English has the message: for codes that may or may not have a word. */
export const has = (key: string) => ENGLISH[key] !== undefined;

const PLACEHOLDER = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

function pick(lang: string, translations: Catalog, key: string, count: unknown): string {
  let entry = translations[key];
  let from = lang;
  if (entry === undefined) { entry = ENGLISH[key]; from = "en"; }
  if (entry === undefined) {
    if (import.meta.env.DEV) console.warn(`missing message ${key}`);
    return key;
  }
  if (typeof entry === "string") return entry;
  const n = typeof count === "number" ? count : Number(count ?? 0);
  const cat = new Intl.PluralRules(from).select(Number.isFinite(n) ? n : 0);
  return entry[cat] ?? entry.other ?? Object.values(entry)[0] ?? key;
}

function makeT(lang: string, translations: Catalog): TFunc {
  return (key, vars = {}) =>
    pick(lang, translations, key, vars.count).replace(PLACEHOLDER, (m, name) =>
      name in vars ? fmtValue(lang, vars[name]) : m);
}

function fmtValue(lang: string, v: string | number): string {
  return typeof v === "number" ? new Intl.NumberFormat(lang).format(v) : v;
}

let current: { lang: string; t: TFunc } = { lang: "en", t: makeT("en", {}) };

/** The message in the language last rendered: for helpers that live outside components. */
export const tr: TFunc = (key, vars) => current.t(key, vars);
export const activeLang = () => current.lang;
/** A number in the active language's notation (1 234,5 in Russian). */
export const num = (n: number, opts?: Intl.NumberFormatOptions) =>
  new Intl.NumberFormat(current.lang, opts).format(n);

interface I18n { lang: string; t: TFunc; ready: boolean }
const Ctx = createContext<I18n>({ lang: "en", t: current.t, ready: true });

export function I18nProvider({ lang, children }: { lang: string; children: ReactNode }) {
  const [loaded, setLoaded] = useState<{ lang: string; messages: Catalog }>({ lang: "en", messages: {} });
  useEffect(() => {
    if (lang === "en") { setLoaded({ lang, messages: {} }); return; }
    let live = true;
    fetch(`/api/messages?lang=${encodeURIComponent(lang)}`)
      .then((r) => (r.ok ? r.json() : { messages: {} }))
      .then((d: { messages: Catalog }) => { if (live) setLoaded({ lang, messages: d.messages ?? {} }); })
      .catch(() => { if (live) setLoaded({ lang, messages: {} }); });
    return () => { live = false; };
  }, [lang]);
  const value = useMemo<I18n>(() => {
    const active = loaded.lang === lang ? lang : "en";
    const t = makeT(active, loaded.lang === lang ? loaded.messages : {});
    current = { lang: active, t };
    return { lang: active, t, ready: loaded.lang === lang };
  }, [lang, loaded]);
  useEffect(() => { document.documentElement.lang = value.lang; }, [value.lang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useT = (): TFunc => useContext(Ctx).t;
export const useI18n = (): I18n => useContext(Ctx);

/** A message with React nodes in its placeholders: <Msg k={key} vars={{ cmd: <code>…</code> }} />. */
export function Msg({ k, vars = {} }: { k: string; vars?: Record<string, ReactNode> }) {
  const t = useT();
  const plain: Vars = {};
  for (const [name, v] of Object.entries(vars)) if (typeof v === "string" || typeof v === "number") plain[name] = v;
  // Node placeholders survive the plain fill as {name}, then become the nodes themselves.
  const keep = Object.fromEntries(Object.keys(vars).filter((n) => !(n in plain)).map((n) => [n, `{${n}}`]));
  const parts = t(k, { ...plain, ...keep }).split(/(\{[a-zA-Z_][a-zA-Z0-9_]*\})/);
  return (
    <>
      {parts.map((p, i) => {
        const name = /^\{([a-zA-Z_][a-zA-Z0-9_]*)\}$/.exec(p)?.[1];
        return <Fragment key={i}>{name && name in keep ? vars[name] : p}</Fragment>;
      })}
    </>
  );
}
