import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { Token } from "../api";
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

export const TYPE_NAME: Record<string, string> = {
  PERSON: "Person", DEITY: "The Divine", SPIRIT_BEING: "Heavenly being", LOCATION: "Place",
  GROUP: "People", ARTIFACT: "Object", SUBSTANCE: "Substance",
};

// --- words ------------------------------------------------------------------------------------------
export function WordCard({ t }: { t: Token }) {
  const grammar = decodeMorph(t.morph).slice(1);
  const hebrewLemma = t.lemma && /[֐-׿]/.test(t.lemma);
  return (
    <div>
      <div className="he">{t.surface}</div>
      {t.translit && <div className="muted" style={{ fontStyle: "italic" }}>{t.translit}</div>}
      {t.gloss && <div style={{ fontSize: 17, margin: "2px 0 6px" }}>“{t.gloss}”</div>}
      <dl className="kv">
        {hebrewLemma && <><dt>From</dt><dd style={{ fontFamily: "var(--hebrew)", fontSize: 18 }}>{t.lemma}</dd></>}
        {grammar.length > 0 && <><dt>Form</dt><dd>{grammar.join("; ")}</dd></>}
        {t.strongs && <><dt>Strong’s</dt><dd style={{ fontFamily: "var(--mono)", fontSize: 13 }}>{t.strongs}</dd></>}
        {t.reading && <><dt>Reading</dt><dd>{t.reading.startsWith("Q") ? "Qere (read aloud), Ketiv written differently" : t.reading}</dd></>}
        {t.name_ref && <><dt>Names</dt><dd className="rubric-text">{t.name_ref.split("@")[0].replace("|", " / ")}</dd></>}
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
