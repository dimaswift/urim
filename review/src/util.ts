// Formatting, routing and the Hebrew morphology decoder.
import { useEffect, useState } from "react";

// --- routing (hash based: #/view/arg?x=y) -------------------------------------------------------
export interface Route { view: string; arg: string; params: URLSearchParams }

export function parseHash(hash = window.location.hash): Route {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const [view, ...rest] = path.split("/");
  return { view: view || "command", arg: decodeURIComponent(rest.join("/")), params: new URLSearchParams(query) };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parseHash());
  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(view: string, arg = "", params?: Record<string, string | undefined>) {
  const q = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([k, v]) => v !== undefined && v !== "" && q.set(k, v));
  const qs = q.toString();
  window.location.hash = `/${view}${arg ? "/" + encodeURIComponent(arg) : ""}${qs ? "?" + qs : ""}`;
}

export function href(view: string, arg = ""): string {
  return `#/${view}${arg ? "/" + encodeURIComponent(arg) : ""}`;
}

// --- formatting -----------------------------------------------------------------------------------
export function short(verseId: string): string {
  const [, ch, v] = verseId.split(".");
  return `${ch}:${v}`;
}

export function range(a: string, b: string): string {
  return a === b ? short(a) : `${short(a)}–${short(b)}`;
}

export function chapterOf(verseId: string): string {
  return verseId.split(".").slice(0, 2).join(".");
}

const UNITS: [number, string][] = [
  [31_556_952, "y"], [86_400, "d"], [3_600, "h"], [60, "m"], [1, "s"],
];

export function duration(seconds: number, parts = 2): string {
  if (seconds === 0) return "0";
  const sign = seconds < 0 ? "−" : "";
  let s = Math.abs(seconds);
  if (s >= 31_556_952 * 2) return `${sign}${(s / 31_556_952).toFixed(1)} y`;
  const out: string[] = [];
  for (const [size, unit] of UNITS) {
    if (s >= size && out.length < parts) {
      const n = Math.floor(s / size);
      out.push(`${n} ${unit}`);
      s -= n * size;
    }
  }
  return sign + out.join(" ");
}

export function ago(iso: string): string {
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", changes_requested: "Sent back", approved: "Approved",
};

export const KIND_LABEL: Record<string, string> = {
  event: "Event", causal: "Causal link", event_links: "Cast & place", entity: "Entity",
  system: "System", component: "State", closure: "State closed", instance: "Ritual instance",
  edge: "Interaction", "verse.en": "Verse",
};

export const KIND_COLOR: Record<string, string> = {
  event: "var(--amber)", causal: "var(--gold)", event_links: "var(--cyan)", entity: "var(--cyan)",
  system: "var(--violet)", component: "var(--green)", closure: "var(--green)",
  instance: "var(--violet)", edge: "var(--cyan)", "verse.en": "var(--text)",
};

export const ENTITY_COLOR: Record<string, string> = {
  PERSON: "var(--amber)", DEITY: "var(--violet)", SPIRIT_BEING: "var(--violet)",
  LOCATION: "var(--cyan)", GROUP: "var(--gold)", ARTIFACT: "var(--green)", SUBSTANCE: "var(--green)",
};

export const ENTITY_GLYPH: Record<string, string> = {
  PERSON: "♟", DEITY: "✶", SPIRIT_BEING: "✧", LOCATION: "⌖", GROUP: "⚑", ARTIFACT: "◈", SUBSTANCE: "◇",
};

// UTES seconds -> JS Date (proleptic Gregorian, astronomical years, UTC).
export const toDate = (utes: number) => new Date(utes * 1000);

export function yearLabel(d: Date): string {
  const y = d.getUTCFullYear();
  return y <= 0 ? `${1 - y} BCE` : `${y} CE`;
}

// --- Hebrew morphology (OSHB / STEPBible TAHOT codes) ----------------------------------------
const POS: Record<string, string> = {
  A: "adjective", C: "conjunction", D: "adverb", N: "noun", P: "pronoun", R: "preposition",
  S: "suffix", T: "particle", V: "verb",
};
const STEMS: Record<string, string> = {
  q: "qal", N: "niphal", p: "piel", P: "pual", h: "hiphil", H: "hophal", t: "hithpael",
  o: "polel", O: "polal", r: "hithpolel", m: "poel", M: "poal", k: "palel", K: "pulal",
  Q: "qal passive", l: "pilpel", L: "polpal", f: "hithpalpel", D: "nithpael", j: "pealal",
  i: "pilel", u: "hothpaal", c: "tiphil", v: "hishtaphel", w: "nithpalel", y: "nithpoel",
  z: "hithpoel",
};
const CONJ: Record<string, string> = {
  p: "perfect", q: "sequential perfect", i: "imperfect", w: "wayyiqtol", h: "cohortative",
  j: "jussive", v: "imperative", r: "active participle", s: "passive participle",
  a: "infinitive absolute", c: "infinitive construct",
};
const PERSON: Record<string, string> = { "1": "1st", "2": "2nd", "3": "3rd" };
const GENDER: Record<string, string> = { m: "masc.", f: "fem.", b: "both", c: "common" };
const NUMBER: Record<string, string> = { s: "sing.", p: "plur.", d: "dual" };
const STATE: Record<string, string> = { a: "absolute", c: "construct", d: "determined" };
const SUB: Record<string, Record<string, string>> = {
  N: { c: "common", g: "gentilic", p: "proper", x: "" },
  A: { a: "", c: "cardinal", g: "gentilic", o: "ordinal" },
  P: { d: "demonstrative", f: "indefinite", i: "interrogative", p: "personal", r: "relative" },
  S: { d: "directional ה", h: "paragogic ה", n: "paragogic נ", p: "pronominal" },
  T: { a: "affirmation", d: "article", e: "exhortation", i: "interrogative", j: "interjection",
       m: "demonstrative", n: "negative", o: "object marker", r: "relative", c: "conjunctive" },
  R: { d: "with article" },
};

function decodeSegment(seg: string): string {
  const pos = seg[0];
  const rest = seg.slice(1);
  const parts: string[] = [];
  if (pos === "V") {
    parts.push(STEMS[rest[0]] ?? rest[0], CONJ[rest[1]] ?? rest[1] ?? "");
    for (const c of rest.slice(2)) parts.push(PERSON[c] ?? GENDER[c] ?? NUMBER[c] ?? STATE[c] ?? c);
  } else {
    const sub = SUB[pos]?.[rest[0]];
    if (sub !== undefined) parts.push(sub);
    for (const c of rest.slice(sub !== undefined ? 1 : 0)) parts.push(PERSON[c] ?? GENDER[c] ?? NUMBER[c] ?? STATE[c] ?? c);
  }
  return [POS[pos] ?? pos, ...parts.filter(Boolean)].join(" ");
}

export function decodeMorph(code?: string | null): string[] {
  if (!code) return [];
  const lang = code[0] === "A" ? "Aramaic" : "Hebrew";
  const segs = code.slice(1).split("/");
  return [lang, ...segs.map(decodeSegment)];
}
