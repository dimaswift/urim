// The apps on GitHub Pages, where no server answers /api: `urim site` (urim/review/site.py)
// writes every answer that can be listed in advance as a file, and what depends on words a
// reader types runs here instead. Keyword search over the exported index follows the engine's
// FTS5 BM25 (names and titles ten times bodies, the last word as a prefix, names first);
// similar items compare the exported vectors; the review deck is filtered from each chapter's
// whole deck; SQL runs in sql.js over the exported bundles. Writes need `urim review`.

import type { Database } from "sql.js";
import type { Card, SearchHit } from "./api";
import { ApiError } from "./api";
import { tr } from "./i18n";

const SHARED = new Set(["meta", "overview", "ledger", "i18n/progress", "sql/schema"]);
const KINDS: Record<string, string[]> = {
  verses: ["verse"], entities: ["entity"], systems: ["system"], events: ["event"],
  all: ["verse", "entity", "system", "event"],
};
const KIND_SCOPE: Record<string, string> = { verse: "verses", entity: "entities", system: "systems", event: "events" };
const SERVER_ONLY = /^(learn\/|runs$|run\/|review$|causal\/)/;

/** What a GET or POST to the review API would answer, from files and in-browser work. */
export async function answer<T>(path: string, init?: RequestInit): Promise<T> {
  const url = new URL(path, "http://urim");
  const route = url.pathname.replace(/^\/api\//, "");
  const p = url.searchParams;
  const lang = p.get("lang") ?? "en";
  if (init?.method === "POST") {
    if (route === "sql") return (await sql(JSON.parse(String(init.body)).query)) as T;
    throw new ApiError(tr("site.server_only"));
  }
  if (SERVER_ONLY.test(route)) throw new ApiError(tr("site.server_only"));
  if (route === "search") {
    return (await search(p.get("q") ?? "", lang, p.get("scope") ?? "all", int(p.get("top_k"), 20), p.get("mode") ?? "hybrid")) as T;
  }
  if (route.startsWith("similar/")) {
    const [, kind, id] = route.split("/").map(decodeURIComponent);
    return (await similar(kind, id, lang, p.get("scope"), int(p.get("top_k"), 12), p.get("same_type") === "true")) as T;
  }
  if (route === "queue") return (await queue(p, lang)) as T;
  const file = route.split("/").map((s) => encodeURIComponent(decodeURIComponent(s))).join("/");
  return json<T>(SHARED.has(route) ? `api/${file}.json` : `api/${lang}/${file}.json`);
}

const int = (v: string | null, fallback: number) => Math.max(1, Math.min(Number(v ?? fallback) || fallback, 100));

const files = new Map<string, Promise<unknown>>();

function json<T>(rel: string): Promise<T> {
  let got = files.get(rel);
  if (!got) {
    got = fetch(rel).then((r) => {
      if (!r.ok) throw new ApiError(tr("site.missing", { path: rel }));
      return r.json();
    });
    got.catch(() => files.delete(rel));
    files.set(rel, got);
  }
  return got as Promise<T>;
}

// --- the review deck -----------------------------------------------------------------------------

/** /api/queue: the server's filters over each chapter's whole deck, already in deck order. */
async function queue(p: URLSearchParams, lang: string) {
  const status = p.get("status") ?? "draft";
  const chapter = p.get("chapter");
  const kind = p.get("kind");
  const limit = Number(p.get("limit") ?? 40);
  const chapters = chapter ? [chapter] : (await json<{ chapters: string[] }>("api/queue.json")).chapters;
  const decks = await Promise.all(chapters.map((c) => json<Card[]>(`api/${lang}/queue/${c}.json`).catch(() => [])));
  const scoped = decks.flat().filter((c) => status === "all" || c.status === status);
  const byKind: Record<string, number> = {};
  for (const c of scoped) byKind[c.key.split(":")[0]] = (byKind[c.key.split(":")[0]] ?? 0) + 1;
  const picked = scoped.filter((c) => !kind || c.key.startsWith(kind + ":"));
  return { total: picked.length, by_kind: byKind, cards: picked.slice(0, limit) };
}

// --- keyword search ------------------------------------------------------------------------------

interface Tok { s: number; e: number; f: string } // offsets in the text, folded form
interface Doc { kind: string; id: string; title: string; body: string; t: Tok[]; b: Tok[] }
interface Index { docs: Doc[]; avgdl: number; at: Map<string, Doc>; names: Map<string, [string, string][]> }

// unicode61 with remove_diacritics: letters and digits make words, case folds, and Latin letters
// lose their accents (é is e) while Cyrillic keeps its own (й, ё). Of the combining marks, those
// in SQLite's diacritic table (sqlite3Fts5UnicodeIsdiacritic) stay inside a word and drop out,
// like a stress mark in Russian; any other mark splits words, like Hebrew points.
const DIACRITIC = "\\u0300-\\u0304\\u0306-\\u030C\\u030F\\u0311\\u031B\\u0323-\\u0328\\u032D-\\u032E\\u0330-\\u0331";
const WORD = new RegExp(`[\\p{L}\\p{N}\\p{Co}${DIACRITIC}]+`, "gu");
const MARKS = new RegExp(`[${DIACRITIC}]`, "gu");
const LATIN = /[À-ɏḀ-ỿ]/u;

function fold(word: string): string {
  const low = word.toLowerCase().replace(MARKS, "");
  if (!LATIN.test(low)) return low;
  return [...low].map((c) => (LATIN.test(c) ? c.normalize("NFD").replace(/\p{M}/gu, "") : c)).join("");
}

function tokens(text: string): Tok[] {
  return [...text.matchAll(WORD)]
    .map((m) => ({ s: m.index, e: m.index + m[0].length, f: fold(m[0]) }))
    .filter((t) => t.f); // a mark on its own is no word
}

const indexes = new Map<string, Promise<Index>>();

function index(lang: string): Promise<Index> {
  let got = indexes.get(lang);
  if (!got) {
    got = json<{ docs: [string, string, string, string][]; names: [string, string, string][] }>(`api/${lang}/search.json`).then((raw) => {
      const docs = raw.docs.map(([kind, id, title, body]) => ({ kind, id, title, body, t: tokens(title), b: tokens(body) }));
      const names = new Map<string, [string, string][]>();
      for (const [name, kind, id] of raw.names) names.set(name, [...(names.get(name) ?? []), [kind, id]]);
      const total = docs.reduce((n, d) => n + d.t.length + d.b.length, 0);
      return { docs, avgdl: total / Math.max(docs.length, 1), at: new Map(docs.map((d) => [d.kind + "\0" + d.id, d])), names };
    });
    indexes.set(lang, got);
  }
  return got;
}

interface Phrase { words: string[]; prefix: boolean }

/** Where a phrase starts in a token list. */
function hits(toks: Tok[], ph: Phrase): number[] {
  const out: number[] = [];
  const n = ph.words.length;
  if (!n) return out;
  for (let i = 0; i + n <= toks.length; i++) {
    let ok = true;
    for (let j = 0; j < n && ok; j++) {
      const f = toks[i + j].f;
      ok = j === n - 1 && ph.prefix ? f.startsWith(ph.words[j]) : f === ph.words[j];
    }
    if (ok) out.push(i);
  }
  return out;
}

/** FTS5's snippet(…, '[', ']', '…', 16), as fts5_aux.c picks it: a window scores 1000 for
 * each phrase it holds and 1 for each repeat, and is centred on its matches; a window that
 * starts a sentence before the match scores 100 more (120 at the very start). */
function snippet(d: Doc, phrases: Phrase[], size = 16): string {
  const toks = d.b, n = toks.length, body = d.body;
  if (!n) return "";
  const inst: { p: number; s: number; e: number }[] = [];
  phrases.forEach((ph, p) => hits(toks, ph).forEach((s) => inst.push({ p, s, e: s + ph.words.length })));
  inst.sort((a, b) => a.s - b.s || a.p - b.p);
  // A sentence starts at the first word, and at a word after a space that follows "." or ":".
  const firsts = [0];
  for (let i = 1; i < n; i++) {
    let j = toks[i].s - 1;
    while (j >= 0 && " \t\n\r".includes(body[j])) j--;
    if (j !== toks[i].s - 1 && j >= 0 && (body[j] === "." || body[j] === ":")) firsts.push(i);
  }
  const score = (from: number) => {
    const seen = new Set<number>();
    let s = 0, first = -1, last = 0;
    for (const x of inst) {
      if (x.s < from || x.s >= from + size) continue;
      s += seen.has(x.p) ? 1 : 1000;
      seen.add(x.p);
      if (first < 0) first = x.s;
      last = x.e;
    }
    return { s, first, last };
  };
  let best = 0, bestScore = 0;
  for (const x of inst) {
    const { s, first, last } = score(x.s);
    if (s > bestScore) {
      bestScore = s;
      best = Math.max(0, Math.min(first - Math.trunc((size - (last - first)) / 2), n - size));
    }
    if (n > size) {
      let jj = 0;
      while (jj < firsts.length - 1 && firsts[jj + 1] <= x.s) jj++;
      if (firsts[jj] < x.s) {
        const sentence = score(firsts[jj]).s + (firsts[jj] === 0 ? 120 : 100);
        if (sentence > bestScore) { bestScore = sentence; best = firsts[jj]; }
      }
    }
  }
  // Matches that overlap merge into one highlight; those starting before the window are dropped.
  const marks: [number, number][] = [];
  for (const x of inst) {
    if (x.s < best) continue;
    const m = marks.at(-1);
    if (m && x.s <= m[1]) m[1] = Math.max(m[1], x.e - 1);
    else marks.push([x.s, x.e - 1]);
  }
  const rangeEnd = best + size - 1;
  let out = best > 0 ? "…" : "";
  let off = best > 0 ? toks[best].s : 0;
  let open: [number, number] | undefined;
  for (let i = best; i <= Math.min(rangeEnd, n - 1); i++) {
    const m = marks.find(([a]) => a === i);
    if (m) { out += body.slice(off, toks[i].s) + "["; off = toks[i].s; open = m; }
    if (open && open[1] === i) { out += body.slice(off, toks[i].e) + "]"; off = toks[i].e; open = undefined; }
    if (i === rangeEnd) { out += body.slice(off, toks[i].e) + (open ? "]" : ""); off = toks[i].e; }
  }
  return rangeEnd >= n - 1 ? out + body.slice(off) : out + "…";
}

const K1 = 1.2, B = 0.75, TITLE = 10, BODY = 1;

/** The engine's keyword ranking: BM25 as FTS5 computes it, titles weighted ten to one. */
function keyword(ix: Index, terms: string[], kinds: string[], k: number) {
  const phrases: Phrase[] = terms.map((term, i) => ({
    words: tokens(term).map((x) => x.f),
    prefix: i === terms.length - 1 && term.length >= 3,
  }));
  const found = ix.docs.map((d) => phrases.map((ph) => [hits(d.t, ph).length, hits(d.b, ph).length]));
  const n = ix.docs.length;
  const idf = phrases.map((_, i) => {
    const nHit = found.filter((f) => f[i][0] + f[i][1] > 0).length;
    const v = Math.log((n - nHit + 0.5) / (nHit + 0.5));
    return v > 0 ? v : 1e-6;
  });
  const ranked: { d: Doc; score: number }[] = [];
  ix.docs.forEach((d, at) => {
    if (!kinds.includes(d.kind)) return;
    const len = d.t.length + d.b.length;
    let score = 0, any = false;
    phrases.forEach((_, i) => {
      const f = TITLE * found[at][i][0] + BODY * found[at][i][1];
      if (f > 0) any = true;
      score += idf[i] * ((f * (K1 + 1)) / (f + K1 * (1 - B + (B * len) / ix.avgdl)));
    });
    if (any) ranked.push({ d, score });
  });
  return { phrases, ranked: ranked.sort((a, b) => b.score - a.score).slice(0, k) };
}

/** Entities and systems the query names, exactly, then by a name being typed (engine `_named`). */
function named(ix: Index, query: string): [string, string][] {
  const q = query.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  const typed = q.length >= 3
    ? [...ix.names.keys()]
      .filter((n) => n.length > q.length && n.startsWith(q) && /[\p{L}\p{N}]/u.test(n[q.length]))
      .sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0))
    : [];
  const out = new Map<string, [string, string]>();
  for (const n of [q, ...typed]) for (const key of ix.names.get(n) ?? []) out.set(key.join("\0"), key);
  return [...out.values()];
}

/** Title and opening words, for hits found by name or by meaning. */
function fill(ix: Index, h: SearchHit): SearchHit {
  const d = ix.at.get(h.kind + "\0" + h.id);
  if (!d) return h;
  const words = d.body.split(/\s+/).filter(Boolean);
  return { ...h, title: d.title, snippet: words.slice(0, 24).join(" ") + (words.length > 24 ? "…" : "") };
}

async function search(query: string, lang: string, scope: string, topK: number, mode: string): Promise<SearchHit[]> {
  if (mode === "meaning") throw new ApiError(tr("site.no_meaning"));
  const terms = query.match(/[\p{L}\p{N}_]+/gu) ?? [];
  if (!terms.length) return [];
  const kinds = KINDS[scope] ?? KINDS.all;
  const ix = await index(lang);
  const { phrases, ranked } = keyword(ix, terms, kinds, Math.max(3 * topK, 30));
  const found = new Map<string, SearchHit>();
  for (const { d, score } of ranked) {
    found.set(d.kind + "\0" + d.id, { kind: d.kind, id: d.id, title: d.title, snippet: snippet(d, phrases), score, via: ["keyword"] });
  }
  const names = named(ix, query).filter(([kind]) => kinds.includes(kind));
  for (const [kind, id] of names) {
    if (!found.has(kind + "\0" + id)) found.set(kind + "\0" + id, { kind, id, title: "", snippet: "", score: 0, via: ["keyword"] });
  }
  const first = new Map(names.map(([kind, id], i) => [kind + "\0" + id, i]));
  const rank = (h: SearchHit) => first.get(h.kind + "\0" + h.id) ?? first.size;
  return [...found.values()]
    .sort((a, b) => rank(a) - rank(b) || b.score - a.score)
    .slice(0, topK)
    .map((h) => (h.snippet ? h : fill(ix, h)));
}

// --- similar items -------------------------------------------------------------------------------

interface Vectors { dims: number; docs: [string, string][]; at: Map<string, number>; rows: Int8Array; norms: Float64Array; types: Record<string, string> }

const vectorSets = new Map<string, Promise<Vectors | null>>();

function vectors(lang: string): Promise<Vectors | null> {
  let got = vectorSets.get(lang);
  if (!got) {
    got = (async () => {
      const [meta, bin] = await Promise.all([
        fetch(`api/${lang}/vectors.json`).then((r) => (r.ok ? r.json() : null)),
        fetch(`api/${lang}/vectors.bin`).then((r) => (r.ok ? r.arrayBuffer() : null)),
      ]);
      if (!meta || !bin) return null;
      const rows = new Int8Array(bin);
      const dims: number = meta.dims;
      const norms = new Float64Array(meta.docs.length);
      for (let i = 0; i < norms.length; i++) {
        let s = 0;
        for (let j = i * dims; j < (i + 1) * dims; j++) s += rows[j] * rows[j];
        norms[i] = Math.sqrt(s) || 1;
      }
      const docs: [string, string][] = meta.docs;
      return { dims, docs, rows, norms, types: meta.entity_types, at: new Map(docs.map(([k, id], i) => [k + "\0" + id, i])) };
    })();
    vectorSets.set(lang, got);
  }
  return got;
}

/** /api/similar: the engine's find_similar over the exported vectors (int8, so the fourth
 * decimal of a similarity may differ from the server's). */
async function similar(kind: string, id: string, lang: string, scope: string | null, topK: number, sameType: boolean): Promise<SearchHit[]> {
  const kinds = sameType ? ["entity"] : KINDS[scope ?? KIND_SCOPE[kind]] ?? KINDS.all;
  let source: { code: string; v: Vectors; row: number } | null = null;
  let anyVectors = false;
  for (const code of lang === "en" ? ["en"] : [lang, "en"]) {
    const v = await vectors(code);
    if (!v) continue;
    anyVectors = true;
    const row = v.at.get(kind + "\0" + id);
    if (row !== undefined) { source = { code, v, row }; break; }
  }
  if (!source) throw new ApiError(anyVectors ? tr("site.missing", { path: `${kind} ${id}` }) : tr("site.no_vectors"));
  const { v, row, code } = source;
  const scored: { i: number; sim: number }[] = [];
  for (let i = 0; i < v.docs.length; i++) {
    if (i === row || !kinds.includes(v.docs[i][0])) continue;
    let dot = 0;
    for (let a = row * v.dims, b = i * v.dims, end = a + v.dims; a < end; a++, b++) dot += v.rows[a] * v.rows[b];
    scored.push({ i, sim: dot / (v.norms[row] * v.norms[i]) });
  }
  scored.sort((a, b) => b.sim - a.sim);
  const pool = sameType
    ? scored.slice(0, Math.max(3 * topK, 30)).filter(({ i }) => v.types[v.docs[i][1]] === v.types[id])
    : scored;
  const ix = await index(code);
  return pool.slice(0, topK).map(({ i, sim }) => {
    const similarity = Math.round(sim * 10000) / 10000;
    return fill(ix, { kind: v.docs[i][0], id: v.docs[i][1], title: "", snippet: "", score: similarity, via: ["meaning"], similarity });
  });
}

// --- the SQL console -----------------------------------------------------------------------------

const ROW_LIMIT = 500;
let consoleDb: Promise<Database> | null = null;

function openConsole() {
  consoleDb ??= (async () => {
    const [{ default: initSqlJs }, { default: wasm }, meta] = await Promise.all([
      import("sql.js"),
      import("sql.js/dist/sql-wasm-browser.wasm?url"),
      json<{ languages: { lang_code: string }[] }>("api/meta.json"),
    ]);
    const SQL = await initSqlJs({ locateFile: () => wasm });
    const bytes = async (rel: string) => new Uint8Array(await (await fetch(rel)).arrayBuffer());
    const core = new SQL.Database(await bytes("db/core.sqlite"));
    for (const { lang_code } of meta.languages) {
      // sql.js keeps each database's bytes in its own file, named on the object: attach that.
      const lang = new SQL.Database(await bytes(`db/lang_${lang_code}.sqlite`));
      core.exec(`ATTACH DATABASE '${(lang as unknown as { filename: string }).filename}' AS lang_${lang_code}`);
    }
    core.exec("PRAGMA query_only = 1");
    return core;
  })();
  consoleDb.catch(() => { consoleDb = null; });
  return consoleDb;
}

async function sql(query: string) {
  const db = await openConsole();
  const started = performance.now();
  try {
    const stmt = db.prepare(query);
    const columns = stmt.getColumnNames();
    const rows: unknown[][] = [];
    while (rows.length <= ROW_LIMIT && stmt.step()) {
      rows.push(stmt.get().map((v) => (v instanceof Uint8Array ? `<${v.length} bytes>` : v)));
    }
    stmt.free();
    return { columns, rows: rows.slice(0, ROW_LIMIT), truncated: rows.length > ROW_LIMIT, ms: Math.round((performance.now() - started) * 10) / 10 };
  } catch (e) {
    throw new ApiError(String((e as Error).message ?? e));
  }
}
