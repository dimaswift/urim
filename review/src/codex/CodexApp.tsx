import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SearchHit } from "../api";
import { useApi } from "../hooks";
import { go, href, useRoute } from "../util";
import Folio from "./Folio";
import Hours from "./Hours";
import Mappa from "./Mappa";
import People from "./People";
import { LangContext, defaultChapter, useLang } from "./parts";

export interface TocBook { book_code: string; osis: string; name: string; chapters: { chapter: number; ref: string; verses: number; translated: number }[] }

const TABS = [
  { id: "read", label: "Read" },
  { id: "people", label: "Persons & Places" },
  { id: "map", label: "Map" },
  { id: "hours", label: "Book of Hours" },
];

function Search() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const { lang } = useLang();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const id = setTimeout(() => api<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}&lang=${lang}&top_k=8`).then(setHits).catch(() => setHits([])), 200);
    return () => clearTimeout(id);
  }, [q, lang]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, []);
  const pick = (h: SearchHit) => {
    setOpen(false); setQ("");
    if (h.kind === "verse") go("read", h.id.split(".").slice(0, 2).join("."), { v: h.id });
    else if (h.kind === "entity") go("people", h.id);
    else if (h.kind === "event") go("hours", h.id);
    else go("people");
  };
  return (
    <div ref={box} style={{ position: "relative" }}>
      <input className="search" placeholder="Search the codex…" value={q} onFocus={() => setOpen(true)}
             onChange={(e) => { setQ(e.target.value); setOpen(true); }}
             onKeyDown={(e) => { if (e.key === "Enter" && hits[0]) pick(hits[0]); }} />
      {open && hits.length > 0 && (
        <div style={{ position: "absolute", right: 0, top: "110%", width: 420, background: "var(--page)", border: "1px solid var(--gold)", boxShadow: "0 12px 30px rgba(80,50,15,.2)", zIndex: 20 }}>
          {hits.map((h) => (
            <div key={h.kind + h.id} onMouseDown={() => pick(h)} style={{ padding: "8px 12px", borderBottom: "1px solid var(--rule)", cursor: "pointer" }}>
              <div>
                <span className="small-caps rubric-text">{h.kind}</span> <b>{h.title}</b>
                {h.via && !h.via.includes("keyword") && <i className="muted" style={{ fontSize: 13 }}> · by meaning</i>}
              </div>
              <div className="muted" style={{ fontSize: 14 }}>{h.snippet.replace(/[[\]]/g, "")}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CodexApp() {
  const route = useRoute();
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem("urim.lang") ?? "en"; } catch { return "en"; }
  });
  const setLang = (l: string) => { setLangState(l); try { localStorage.setItem("urim.lang", l); } catch { /* ignore */ } };
  const { data: toc } = useApi<TocBook[]>(`/api/toc?lang=${lang}`);
  const { data: meta } = useApi<{ languages: { lang_code: string; lang_name: string }[] }>("/api/meta");
  const view = TABS.some((t) => t.id === route.view) ? route.view : "read";

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      <div className="codex">
        <header className="masthead">
          <a className="title" href={href("read")} style={{ textDecoration: "none" }}><b>URIM</b><span>the illuminated codex</span></a>
          <nav className="tabs">
            {TABS.map((t) => <a key={t.id} href={href(t.id)} className={view === t.id ? "on" : ""}>{t.label}</a>)}
          </nav>
          <div className="spacer" />
          {toc && (
            <select className="select" value={view === "read" ? route.arg || defaultChapter(toc) || "" : ""} onChange={(e) => go("read", e.target.value)}>
              <option value="" disabled>Go to chapter…</option>
              {toc.map((b) => b.chapters.map((c) => (
                <option key={c.ref} value={c.ref}>
                  {b.name} {c.chapter}{c.translated === 0 ? " · not yet translated" : c.translated < c.verses ? ` · ${c.translated} of ${c.verses} translated` : ""}
                </option>
              )))}
            </select>
          )}
          <Search />
          <select className="select" value={lang} onChange={(e) => setLang(e.target.value)}>
            {(meta?.languages ?? [{ lang_code: "en", lang_name: "English" }]).map((l) => (
              <option key={l.lang_code} value={l.lang_code}>{l.lang_name}</option>
            ))}
          </select>
          <a href="/" className="small-caps muted" title="Review in the War Room">War Room ↗</a>
        </header>
        {view === "read" && <Folio route={route} toc={toc ?? []} />}
        {view === "people" && <People route={route} />}
        {view === "map" && <Mappa route={route} />}
        {view === "hours" && <Hours route={route} />}
      </div>
    </LangContext.Provider>
  );
}
