// Formatting, routing and the Hebrew morphology decoder. Words come from the message catalog
// (i18n.tsx), so every label here follows the interface language.
import { useEffect, useState } from "react";
import { has, num, tr } from "./i18n";

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
  if (s >= 31_556_952 * 2) {
    return sign + tr("unit.y", { n: num(s / 31_556_952, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) });
  }
  const out: string[] = [];
  for (const [size, unit] of UNITS) {
    if (s >= size && out.length < parts) {
      const n = Math.floor(s / size);
      out.push(tr(`unit.${unit}`, { n }));
      s -= n * size;
    }
  }
  return sign + out.join(" ");
}

export function ago(iso: string): string {
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 60) return tr("time.just_now");
  if (s < 3600) return tr("time.minutes_ago", { count: Math.floor(s / 60) });
  if (s < 86400) return tr("time.hours_ago", { count: Math.floor(s / 3600) });
  return tr("time.days_ago", { count: Math.floor(s / 86400) });
}

/** A review status in words: Draft, Sent back, Approved. */
export const statusLabel = (status: string) => (has(`status.${status}`) ? tr(`status.${status}`) : status);

/** A ledger kind in words; a translation's kind carries its language: "Event · RU". */
export function kindLabel(kind: string): string {
  const [base, lang] = kind.split(".");
  const word = has(`kind.${base}`) ? tr(`kind.${base}`) : base;
  return lang && lang !== "en" ? `${word} · ${lang.toUpperCase()}` : word;
}

const KIND_COLORS: Record<string, string> = {
  event: "var(--amber)", causal: "var(--gold)", event_links: "var(--cyan)", entity: "var(--cyan)",
  system: "var(--violet)", component: "var(--green)", closure: "var(--green)",
  instance: "var(--violet)", edge: "var(--cyan)", verse: "var(--text)",
};
export const kindColor = (kind: string) => KIND_COLORS[kind.split(".")[0]] ?? "var(--text)";

export const ENTITY_COLOR: Record<string, string> = {
  PERSON: "var(--amber)", DEITY: "var(--violet)", SPIRIT_BEING: "var(--violet)",
  LOCATION: "var(--cyan)", GROUP: "var(--gold)", ARTIFACT: "var(--green)", SUBSTANCE: "var(--green)",
};

export const ENTITY_GLYPH: Record<string, string> = {
  PERSON: "♟", DEITY: "✶", SPIRIT_BEING: "✧", LOCATION: "⌖", GROUP: "⚑", ARTIFACT: "◈", SUBSTANCE: "◇",
};

/** An entity type in words: Person, Place… */
export const entityTypeLabel = (type: string) => (has(`entity_type.${type}`) ? tr(`entity_type.${type}`) : type);

// UTES seconds -> JS Date (proleptic Gregorian, astronomical years, UTC).
export const toDate = (utes: number) => new Date(utes * 1000);

export function yearLabel(d: Date): string {
  const y = d.getUTCFullYear();
  return y <= 0 ? tr("time.bce", { year: String(1 - y) }) : tr("time.ce", { year: String(y) });
}

// --- Hebrew morphology (OSHB / STEPBible TAHOT codes) ----------------------------------------
// Every code has a message: morph.pos.V "verb", morph.stem.q "qal", morph.sub.T.o "object marker".
const SUB_BLANK = new Set(["N.x", "A.a"]);
const word = (group: string, code: string) => (has(`morph.${group}.${code}`) ? tr(`morph.${group}.${code}`) : code);
const feature = (c: string) => ["person", "gender", "number", "state"].map((g) => `morph.${g}.${c}`).find(has);

function decodeSegment(seg: string): string {
  const pos = seg[0];
  const rest = seg.slice(1);
  const parts: string[] = [];
  const features = (codes: string) => { for (const c of codes) { const k = feature(c); parts.push(k ? tr(k) : c); } };
  if (pos === "V") {
    parts.push(word("stem", rest[0]), rest[1] ? word("conj", rest[1]) : "");
    features(rest.slice(2));
  } else {
    const subKey = `${pos}.${rest[0]}`;
    const isSub = has(`morph.sub.${subKey}`) || SUB_BLANK.has(subKey);
    if (isSub && has(`morph.sub.${subKey}`)) parts.push(tr(`morph.sub.${subKey}`));
    features(rest.slice(isSub ? 1 : 0));
  }
  return [word("pos", pos), ...parts.filter(Boolean)].join(" ");
}

export function decodeMorph(code?: string | null): string[] {
  if (!code) return [];
  const lang = tr(code[0] === "A" ? "morph.lang.A" : "morph.lang.H");
  const segs = code.slice(1).split("/");
  return [lang, ...segs.map(decodeSegment)];
}
