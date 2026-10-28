// How far each language has come: every chapter's texts and verses, the interface, the bundle,
// counted from the corpus (missing, stale, translated, approved), with the commands that do
// the rest. Polls while a run may be translating.
import { useEffect } from "react";
import { Panel } from "../components";
import { useApi } from "../hooks";
import { Msg, num, useT } from "../i18n";
import type { TFunc } from "../i18n";
import { href } from "../util";

interface Counts { total: number; missing: number; stale: number; requested: number; drafts: number; approved: number; translated: number }
interface LangProgress {
  lang: string; lang_name: string; baseline: string;
  chapters: { chapter: string; texts: Counts; verses: Counts }[];
  interface: Counts & { namespaces: Record<string, Counts> };
  bundle: Counts;
}

const sum = (rows: Counts[]): Counts => rows.reduce((a, c) => ({
  total: a.total + c.total, missing: a.missing + c.missing, stale: a.stale + c.stale,
  requested: a.requested + c.requested, drafts: a.drafts + c.drafts,
  approved: a.approved + c.approved, translated: a.translated + c.translated,
}), { total: 0, missing: 0, stale: 0, requested: 0, drafts: 0, approved: 0, translated: 0 });

const pct = (n: number, total: number) => (total ? Math.round((100 * n) / total) : 0);

function Bar({ c, height = 8 }: { c: Counts; height?: number }) {
  const t = useT();
  if (!c.total) return <span className="faint">—</span>;
  const parts: [number, string][] = [
    [c.approved, "var(--green)"], [c.drafts, "var(--amber)"], [c.requested, "var(--red)"],
    [c.stale, "var(--violet)"],
  ];
  return (
    <div title={tooltip(t, c)}>
      <div style={{ display: "flex", height, borderRadius: 3, overflow: "hidden", background: "#132230" }}>
        {parts.map(([n, color], i) => n > 0 && <div key={i} style={{ width: `${(100 * n) / c.total}%`, background: color }} />)}
      </div>
    </div>
  );
}

function tooltip(t: TFunc, c: Counts): string {
  return [
    t("languages.count.approved", { count: c.approved }),
    t("languages.count.drafts", { count: c.drafts }),
    t("languages.count.requested", { count: c.requested }),
    t("languages.count.stale", { count: c.stale }),
    t("languages.count.missing", { count: c.missing }),
  ].join(" · ");
}

function Cell({ c }: { c: Counts }) {
  const t = useT();
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <Bar c={c} />
      <div className="mono muted" style={{ fontSize: 11 }}>
        {c.total ? t("languages.of", { done: c.translated, total: c.total }) : ""}
        {c.stale > 0 && <span style={{ color: "var(--violet)" }}> · {t("languages.count.stale", { count: c.stale })}</span>}
        {c.requested > 0 && <span style={{ color: "var(--red)" }}> · {t("languages.count.requested", { count: c.requested })}</span>}
      </div>
    </div>
  );
}

function Language({ p }: { p: LangProgress }) {
  const t = useT();
  const texts = sum(p.chapters.map((c) => c.texts));
  const verses = sum(p.chapters.map((c) => c.verses));
  const all = sum([texts, verses, p.interface, p.bundle]);
  const books = [...new Set(p.chapters.map((c) => c.chapter.split(".")[0]))];
  const scope = books.length === 1 ? books[0] : "GEN";
  return (
    <div className="grid">
      <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("languages.kicker")}</div>
          <h1>{p.lang_name} <span className="mono muted" style={{ fontSize: 14 }}>{p.lang}</span></h1>
          <div className="muted">{t("languages.baseline", { name: p.baseline })}</div>
        </div>
        <div className="spacer" />
        <div className="mono" style={{ fontSize: 28, color: "var(--green)" }}>{num(pct(all.translated, all.total))}%</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>
        {([
          [t("languages.part.texts"), texts], [t("languages.part.verses"), verses],
          [t("languages.part.interface"), p.interface], [t("languages.part.bundle"), p.bundle],
        ] as [string, Counts][]).map(([label, c]) => (
          <div key={label} className="panel" style={{ padding: 12 }}>
            <div className="hud upper muted" style={{ fontSize: 11 }}>{label}</div>
            <div className="mono" style={{ fontSize: 20, margin: "4px 0 8px" }}>{num(pct(c.translated, c.total))}%</div>
            <Cell c={c} />
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", gap: 16, alignItems: "start" }}>
        <Panel title={t("languages.chapters")} count={num(p.chapters.length)}>
          <table className="table">
            <thead><tr><th>{t("languages.col.chapter")}</th><th>{t("languages.part.texts")}</th><th>{t("languages.part.verses")}</th><th /></tr></thead>
            <tbody>
              {p.chapters.map((c) => (
                <tr key={c.chapter}>
                  <td className="mono">{c.chapter}</td>
                  <td style={{ minWidth: 160 }}><Cell c={c.texts} /></td>
                  <td style={{ minWidth: 160 }}><Cell c={c.verses} /></td>
                  <td>
                    <a className="small" href={href("review", c.chapter)}>{t("languages.review")}</a>{" · "}
                    <a className="small" href={`/codex.html${href("read", c.chapter)}`}>{t("languages.read")}</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <div className="grid">
          <Panel title={t("languages.interface")} count={`${num(p.interface.translated)}/${num(p.interface.total)}`}>
            <div style={{ display: "grid", gap: 8 }}>
              {Object.entries(p.interface.namespaces).map(([ns, c]) => (
                <div key={ns} style={{ display: "grid", gridTemplateColumns: "110px minmax(0, 1fr)", gap: 8, alignItems: "center" }}>
                  <span className="mono muted" style={{ fontSize: 12 }}>{ns}</span>
                  <Cell c={c} />
                </div>
              ))}
            </div>
          </Panel>
          <Panel title={t("languages.how")}>
            <div className="muted" style={{ display: "grid", gap: 8, fontSize: 13 }}>
              <div><Msg k="languages.how.run" vars={{ cmd: <code className="mono">uv run urim run {scope} --lang {p.lang}</code> }} /></div>
              <div><Msg k="languages.how.one" vars={{ cmd: <code className="mono">/urim-localizer {p.lang} {p.chapters[0]?.chapter ?? "GEN.1"}</code> }} /></div>
              <div><Msg k="languages.how.status" vars={{ cmd: <code className="mono">uv run urim lang {p.lang}</code> }} /></div>
              <div className="row" style={{ gap: 10, flexWrap: "wrap", marginTop: 4 }}>
                {([
                  ["var(--green)", t("languages.legend.approved")], ["var(--amber)", t("languages.legend.drafts")],
                  ["var(--red)", t("languages.legend.requested")], ["var(--violet)", t("languages.legend.stale")],
                ] as [string, string][]).map(([color, label]) => (
                  <span key={label}><span style={{ color }}>■</span> {label}</span>
                ))}
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default function Languages() {
  const t = useT();
  const { data, error, reload } = useApi<LangProgress[]>("/api/i18n/progress");
  useEffect(() => {
    const id = setInterval(reload, 8000);
    return () => clearInterval(id);
  }, [reload]);
  if (error) return <div className="intel red">{error}</div>;
  if (!data) return <div className="muted">{t("languages.loading")}</div>;
  if (!data.length) {
    return (
      <div className="intel">
        <b>{t("languages.none.title")}</b>
        <Msg k="languages.none.body" vars={{ path: <code className="mono">corpus/i18n/&lt;lang&gt;/_bundle.json</code> }} />
      </div>
    );
  }
  return <div className="grid" style={{ gap: 28 }}>{data.map((p) => <Language key={p.lang} p={p} />)}</div>;
}
