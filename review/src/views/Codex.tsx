import type { Codex as CodexEntry } from "../api";
import { EntityChip, Loading, Panel, ReviewBar } from "../components";
import { num, useT, type TFunc } from "../i18n";
import { useApi, useApp } from "../state";
import { go, href, range, type Route } from "../util";

const CATEGORY: Record<string, { color: string; glyph: string }> = {
  LITURGICAL_RITUAL: { color: "var(--gold)", glyph: "🜂" },
  SUPERNATURAL_ACT: { color: "var(--violet)", glyph: "✶" },
  LEGAL_CUSTOM: { color: "var(--cyan)", glyph: "⚖" },
  SOCIAL_CUSTOM: { color: "var(--cyan)", glyph: "⚑" },
  PROPHETIC_ORACLE: { color: "var(--amber)", glyph: "☍" },
  THEOPHANY: { color: "var(--violet)", glyph: "☼" },
  MILITARY_PROTOCOL: { color: "var(--red)", glyph: "⚔" },
};

function categoryLabel(t: TFunc, category: string): string {
  switch (category) {
    case "LITURGICAL_RITUAL": return t("codexview.category.liturgical_ritual");
    case "SUPERNATURAL_ACT": return t("codexview.category.supernatural_act");
    case "LEGAL_CUSTOM": return t("codexview.category.legal_custom");
    case "SOCIAL_CUSTOM": return t("codexview.category.social_custom");
    case "PROPHETIC_ORACLE": return t("codexview.category.prophetic_oracle");
    case "THEOPHANY": return t("codexview.category.theophany");
    case "MILITARY_PROTOCOL": return t("codexview.category.military_protocol");
    default: return category;
  }
}

export default function Codex({ route }: { route: Route }) {
  const t = useT();
  const { lang, ledger } = useApp();
  const { data } = useApi<CodexEntry[]>(`/api/systems?lang=${lang}`);
  if (!data) return <Loading what={t("codexview.loading")} />;
  const open = route.arg ? data.find((s) => s.system_id === route.arg) : null;
  const verified = data.filter((s) => ledger[`system:${s.system_id}`]?.status === "approved").length;
  return (
    <div className="view">
      <style>{`
        .codex-card { position: relative; padding: 16px; border-radius: 6px; cursor: pointer; min-height: 210px;
          background: linear-gradient(160deg, rgba(20,32,44,.95), rgba(8,13,19,.95)); border: 1px solid var(--line-2); transition: transform .15s, box-shadow .15s; }
        .codex-card:hover { transform: translateY(-3px); }
        .codex-card .glyph { font-size: 40px; line-height: 1; }
        .codex-card .count { position: absolute; top: 12px; right: 14px; font: 700 20px var(--mono); }
      `}</style>
      <div className="row" style={{ marginBottom: 14 }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("codexview.kicker")}</div>
          <h1>{t("codexview.title")} <span className="muted" style={{ fontSize: 16 }}>· {t("codexview.discovered", { count: data.length })} · {t("codexview.verified_count", { count: verified })}</span></h1>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 14 }}>
        {data.map((s) => {
          const c = CATEGORY[s.category] ?? { color: "var(--text)", glyph: "◇" };
          const status = ledger[`system:${s.system_id}`]?.status;
          return (
            <div key={s.system_id} className="codex-card" onClick={() => go("codex", s.system_id)}
                 style={{ borderColor: status === "approved" ? "var(--green)" : c.color, boxShadow: `0 0 18px color-mix(in srgb, ${status === "approved" ? "var(--green)" : c.color} 22%, transparent)` }}>
              <div className="count" style={{ color: c.color }}>×{num(s.instances.length)}</div>
              <div className="glyph" style={{ color: c.color, textShadow: `0 0 14px ${c.color}` }}>{c.glyph}</div>
              <div className="hud upper" style={{ fontSize: 10, color: c.color, marginTop: 10, letterSpacing: "0.25em" }}>{categoryLabel(t, s.category)}</div>
              <h3 style={{ fontSize: 18, margin: "4px 0 8px" }}>{s.name}</h3>
              <div className="muted" style={{ fontSize: 12, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{s.ancient_near_east_context}</div>
              <div className="mono faint" style={{ fontSize: 10, marginTop: 10 }}>{t("codexview.first_seen", { verse: s.first_occurrence_verse ?? "—" })}{status === "approved" && <span className="st-approved"> · {t("codexview.verified")} ✦</span>}</div>
            </div>
          );
        })}
      </div>
      {open && (
        <Panel title={open.name ?? open.system_id} className="cyan" right={<ReviewBar itemKey={`system:${open.system_id}`} />}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginTop: 4 }}>
            <div>
              <p style={{ marginTop: 0 }}>{open.ancient_near_east_context}</p>
              <div className="hud upper muted" style={{ fontSize: 10 }}>{t("codexview.how_it_works")}</div>
              <ol style={{ paddingLeft: 18 }}>{open.rules_and_mechanics.map((r) => <li key={r} style={{ marginBottom: 4 }}>{r}</li>)}</ol>
            </div>
            <div className="grid" style={{ gap: 10 }}>
              <div className="hud upper muted" style={{ fontSize: 10 }}>{t("codexview.occurrences")}</div>
              {open.instances.map((i) => (
                <div key={i.instance_id} className="panel" style={{ padding: 10 }}>
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    <a className="mono" href={href("xray", i.verse_start)}>{range(i.verse_start, i.verse_end)}</a>
                    <EntityChip entity={i.initiator} />
                    {i.targets.map((tg) => <EntityChip key={tg.entity_id} entity={tg} />)}
                  </div>
                  <p style={{ margin: "6px 0 0", fontSize: 13 }}>{i.outcome_summary}</p>
                  <div className="muted" style={{ fontSize: 12 }}>{i.significance_note}</div>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
