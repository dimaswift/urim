import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { Token } from "../api";
import { useT } from "../i18n";
import type { TFunc } from "../i18n";
import { decodeMorph } from "../util";

// --- language ---------------------------------------------------------------------------------
export const LangContext = createContext<{ lang: string; setLang: (l: string) => void }>({
  lang: "en", setLang: () => {},
});
export const useLang = () => useContext(LangContext);

// --- ornaments -----------------------------------------------------------------------------------
export function Corners() {
  const path = "M2 32 C2 14 14 2 32 2 M2 22 C4 12 12 4 22 2 M8 8 m-3 0 a3 3 0 1 0 6 0 a3 3 0 1 0 -6 0";
  return (
    <>
      {["tl", "tr", "bl", "br"].map((c) => (
        <svg key={c} className={`corner ${c}`} viewBox="0 0 34 34" fill="none" stroke="currentColor" strokeWidth="1.4">
          <path d={path} />
        </svg>
      ))}
    </>
  );
}

export function Ornament({ glyph = "❦" }: { glyph?: string }) {
  return <div className="ornament">{glyph}</div>;
}

const ROMAN: [number, string][] = [[1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"],
  [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
/** The chapter the reader opens on: the first one with a translation, else the first. */
export function defaultChapter(toc: { chapters: { ref: string; translated: number }[] }[]): string | undefined {
  const chapters = toc.flatMap((b) => b.chapters);
  return chapters.find((c) => c.translated > 0)?.ref ?? chapters[0]?.ref;
}

export function roman(n: number): string {
  let out = "";
  for (const [v, s] of ROMAN) while (n >= v) { out += s; n -= v; }
  return out;
}

export function initialOf(name: string): string {
  return name.replace(/^(the|a)\s+/i, "").trim().charAt(0).toUpperCase() || "·";
}

export function roundelClass(type: string): string {
  if (type === "LOCATION") return "roundel place";
  if (type === "DEITY" || type === "SPIRIT_BEING") return "roundel divine";
  if (type === "ARTIFACT" || type === "SUBSTANCE") return "roundel thing";
  return "roundel";
}

export function Roundel({ name, type, size = 54 }: { name: string; type: string; size?: number }) {
  return (
    <div className={roundelClass(type)} style={{ width: size, height: size, fontSize: size * 0.48 }}>{initialOf(name)}</div>
  );
}

/** An entity type as the codex names it (softer words than the War Room's). */
export function typeName(t: TFunc, type: string): string {
  switch (type) {
    case "PERSON": return t("codex.people.type.PERSON");
    case "DEITY": return t("codex.people.type.DEITY");
    case "SPIRIT_BEING": return t("codex.people.type.SPIRIT_BEING");
    case "LOCATION": return t("codex.people.type.LOCATION");
    case "GROUP": return t("codex.people.type.GROUP");
    case "ARTIFACT": return t("codex.people.type.ARTIFACT");
    case "SUBSTANCE": return t("codex.people.type.SUBSTANCE");
    default: return type;
  }
}

/** "14 September": the day and the month's name in the interface language. */
export function dayMonth(t: TFunc, lang: string, d: Date, long = false): string {
  const month = new Intl.DateTimeFormat(lang, { day: "numeric", month: long ? "long" : "short", timeZone: "UTC" })
    .formatToParts(d).find((p) => p.type === "month")?.value ?? "";
  return t("codex.hours.day_month", { day: String(d.getUTCDate()).padStart(2, "0"), month });
}

/** A small "EN" beside text that has no translation in the chosen language yet. */
export function LangMark({ from }: { from: string | null | undefined }) {
  const t = useT();
  const { lang } = useLang();
  if (!from || from === lang) return null;
  return (
    <span className="small-caps muted" title={t("codex.fallback.title")}
          style={{ fontSize: 10, fontStyle: "normal", fontWeight: 400, letterSpacing: "0.08em", marginLeft: 6, verticalAlign: "middle", cursor: "help" }}>
      {from.toUpperCase()}
    </span>
  );
}

// --- words ------------------------------------------------------------------------------------------
export function WordCard({ t: tok }: { t: Token }) {
  const t = useT();
  const grammar = decodeMorph(tok.morph).slice(1);
  const hebrewLemma = tok.lemma && /[֐-׿]/.test(tok.lemma);
  return (
    <div>
      <div className="he">{tok.surface}</div>
      {tok.translit && <div className="muted" style={{ fontStyle: "italic" }}>{tok.translit}</div>}
      {tok.gloss && <div style={{ fontSize: 17, margin: "2px 0 6px" }}>{t("codex.folio.word.gloss", { gloss: tok.gloss })}</div>}
      <dl className="kv">
        {hebrewLemma && <><dt>{t("codex.folio.word.from")}</dt><dd style={{ fontFamily: "var(--hebrew)", fontSize: 18 }}>{tok.lemma}</dd></>}
        {grammar.length > 0 && <><dt>{t("codex.folio.word.form")}</dt><dd>{grammar.join("; ")}</dd></>}
        {tok.strongs && <><dt>{t("codex.folio.word.strongs")}</dt><dd style={{ fontFamily: "var(--mono)", fontSize: 13 }}>{tok.strongs}</dd></>}
        {tok.reading && <><dt>{t("codex.folio.word.reading")}</dt><dd>{tok.reading.startsWith("Q") ? t("codex.folio.word.qere") : tok.reading}</dd></>}
        {tok.name_ref && <><dt>{t("codex.folio.word.names")}</dt><dd className="rubric-text">{tok.name_ref.split("@")[0].replace("|", " / ")}</dd></>}
      </dl>
    </div>
  );
}

export function Words({ tokens }: { tokens: Token[] }) {
  const [hover, setHover] = useState<{ t: Token; x: number; y: number } | null>(null);
  return (
    <>
      <div className="words">
        {tokens.map((t) => (
          <span key={t.pos} className={`word ${t.name_ref ? "name" : ""}`}
                onMouseEnter={(e) => setHover({ t, x: e.clientX, y: e.clientY })}
                onMouseMove={(e) => setHover({ t, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover(null)}>
            <span className="he">{t.surface}</span>
            <span className="tr">{t.translit}</span>
            <span className="gl">{t.gloss}</span>
          </span>
        ))}
      </div>
      {hover && (
        <div className="hovercard" style={{ left: Math.min(hover.x + 16, window.innerWidth - 320), top: Math.min(hover.y + 16, window.innerHeight - 260) }}>
          <WordCard t={hover.t} />
        </div>
      )}
    </>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <div className="section-title">{title}</div>
      {children}
    </section>
  );
}
