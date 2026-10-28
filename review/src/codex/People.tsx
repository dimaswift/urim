import type { Dossier, EntityRow, SearchHit } from "../api";
import { useApi } from "../hooks";
import { Msg, num, useT } from "../i18n";
import { href, short, type Route } from "../util";
import { Corners, LangMark, Ornament, Roundel, Section, typeName, useLang } from "./parts";

interface Row extends EntityRow { source_script_name: string | null; summary_bio: string | null }
interface Entity { dossier: Dossier; mentions: { verse_id: string; pos: number }[] }

const degrees = (x: number) => num(x, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Index() {
  const t = useT();
  const { lang } = useLang();
  const { data } = useApi<Row[]>(`/api/entities?lang=${lang}`);
  if (!data) return <div className="loading">{t("codex.people.loading")}</div>;
  const groups: [string, string[]][] = [
    [t("codex.people.group.persons"), ["PERSON"]],
    [t("codex.people.group.divine"), ["DEITY", "SPIRIT_BEING"]],
    [t("codex.people.group.places"), ["LOCATION"]],
    [t("codex.people.group.peoples"), ["GROUP"]],
    [t("codex.people.group.things"), ["ARTIFACT", "SUBSTANCE"]],
  ];
  return (
    <article className="folio">
      <Corners />
      <div className="heading">
        <div className="book">{t("codex.people.latin")}</div>
        <h1>{t("codex.people.title")}</h1>
        <div className="sub">{t("codex.people.subtitle")}</div>
        <Ornament />
      </div>
      {groups.map(([title, types]) => {
        const rows = data.filter((r) => types.includes(r.entity_type)).sort((a, b) => b.events - a.events || a.name.localeCompare(b.name));
        if (!rows.length) return null;
        return (
          <Section key={title} title={title}>
            <div className="cards">
              {rows.map((r) => (
                <a key={r.entity_id} className="card" href={href("people", r.entity_id)}>
                  <Roundel name={r.name} type={r.entity_type} />
                  <div>
                    <h3>{r.name}</h3>
                    {r.source_script_name && <div className="heb">{r.source_script_name}</div>}
                    <p>{(r.summary_bio ?? "").length > 150 ? r.summary_bio!.slice(0, 148) + "…" : r.summary_bio}</p>
                  </div>
                </a>
              ))}
            </div>
          </Section>
        );
      })}
    </article>
  );
}

/** Others of the same kind whose description is nearest in meaning; silent without vectors. */
function Kindred({ id, name }: { id: string; name: string }) {
  const t = useT();
  const { lang } = useLang();
  const { data, error } = useApi<SearchHit[]>(`/api/similar/entity/${encodeURIComponent(id)}?lang=${lang}&top_k=6&same_type=true`);
  if (error || !data?.length) return null;
  return (
    <Section title={t("codex.people.like", { name })}>
      <p style={{ margin: "4px 0" }}>
        {data.map((h, i) => (
          <span key={h.id}>{i > 0 && " · "}<a href={href("people", h.id)} title={h.snippet}>{h.title}</a></span>
        ))}
      </p>
    </Section>
  );
}

function Page({ id }: { id: string }) {
  const t = useT();
  const { lang } = useLang();
  const { data } = useApi<Entity>(`/api/entity/${encodeURIComponent(id)}?lang=${lang}`);
  if (!data) return <div className="loading">{t("codex.people.opening")}</div>;
  const d = data.dossier;
  const byChapter = new Map<string, string[]>();
  data.mentions.forEach((m) => {
    const ch = m.verse_id.split(".").slice(0, 2).join(".");
    const list = byChapter.get(ch) ?? [];
    if (!list.includes(m.verse_id)) list.push(m.verse_id);
    byChapter.set(ch, list);
  });
  return (
    <article className="folio" style={{ maxWidth: 920 }}>
      <Corners />
      <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 26, alignItems: "center" }}>
        <Roundel name={d.canonical_name ?? id} type={d.entity_type} size={110} />
        <div>
          <div className="small-caps muted">{typeName(t, d.entity_type)}</div>
          <h1 style={{ font: "700 40px/1.1 var(--caps)", margin: "4px 0" }}>{d.canonical_name}</h1>
          <div style={{ fontSize: 19 }}>
            {d.source_script_name && <span style={{ fontFamily: "var(--hebrew)", fontSize: 30, color: "var(--rubric)", marginRight: 14 }}>{d.source_script_name}</span>}
            <i className="muted">{d.phonetic_name}{d.transliterated_name && `, ${d.transliterated_name}`}</i>
          </div>
          {d.aliases.length > 0 && <div className="muted">{t("codex.people.also_called", { names: d.aliases.join(", ") })}</div>}
        </div>
      </div>
      <Ornament />
      <p style={{ fontSize: 20, lineHeight: 1.6 }}>{d.summary_bio}<LangMark from={d.text_lang} /></p>
      <p><span className="small-caps rubric-text">{t("codex.people.name_means")} </span>{d.etymology_meaning}</p>
      {d.geo && (
        <p className="muted">
          {t("codex.people.located", { lat: degrees(d.geo.lat), lon: degrees(d.geo.lon) })}
          {d.geo.confidence != null && d.geo.confidence < 0.7 && ` ${t("codex.people.approximate")}`} · <a href={href("map", d.entity_id)}>{t("codex.people.see_on_map")}</a>
        </p>
      )}

      {d.events.length > 0 && (
        <Section title={t("codex.people.in_story")}>
          <div className="story">
            {d.events.map((e) => (
              <div key={e.event_id} className="story-item">
                <a href={href("hours", e.event_id)} style={{ fontSize: 19, color: "var(--ink)" }}>{e.title}</a>
                {e.text_lang !== d.text_lang && <LangMark from={e.text_lang} />}
                <div className="muted" style={{ fontSize: 15 }}>
                  {e.start_label} · <a href={href("read", e.verse_start.split(".").slice(0, 2).join("."), )}>{short(e.verse_start)}</a>
                  {e.location && e.location.entity_id !== id && <> · <Msg k="codex.people.at_place" vars={{ place: <a href={href("people", e.location.entity_id)}>{e.location.name}</a> }} /></>}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {d.components.length > 0 && (
        <Section title={t("codex.people.through_narrative")}>
          {d.components.map((c) => (
            <div key={c.component_id} style={{ margin: "6px 0" }}>
              <span className="ribbon">{c.label_value}</span>{" "}
              <span className="muted">{c.expired_at_verse
                ? t("codex.people.state_until", { state: c.label_key?.toLocaleLowerCase(lang) ?? "", from: short(c.acquired_at_verse), until: short(c.expired_at_verse) })
                : t("codex.people.state_onward", { state: c.label_key?.toLocaleLowerCase(lang) ?? "", from: short(c.acquired_at_verse) })}</span>
              {c.evidence_explanation && <div style={{ fontSize: 15.5, color: "var(--ink-2)", marginLeft: 4 }}>{c.evidence_explanation}</div>}
            </div>
          ))}
        </Section>
      )}

      {d.interactions.length > 0 && (
        <Section title={t("codex.people.deeds")}>
          {d.interactions.map((x) => (
            <p key={x.edge_id} style={{ margin: "4px 0" }}>
              <a href={href("people", x.source.entity_id)}>{x.source.name}</a> {x.interaction_label ?? x.interaction_type.toLowerCase()}{" "}
              <a href={href("people", x.target.entity_id)}>{x.target.name}</a>
              <span className="muted"> ({short(x.verse_id)})</span>
            </p>
          ))}
        </Section>
      )}

      <Kindred id={id} name={d.canonical_name ?? id} />

      {byChapter.size > 0 && (
        <Section title={t("codex.people.named_in")}>
          {[...byChapter.entries()].map(([ch, verses]) => (
            <p key={ch} style={{ margin: "4px 0" }}>
              <span className="small-caps muted">{ch.replace(".", " ")} </span>
              {verses.map((v) => <a key={v} className="chip" href={href("read", ch) + `?v=${v}`}>{short(v)}</a>)}
            </p>
          ))}
        </Section>
      )}
      <div className="pager"><a href={href("people")}>{t("codex.people.all")}</a><span /></div>
    </article>
  );
}

export default function People({ route }: { route: Route }) {
  return route.arg ? <Page id={route.arg} /> : <Index />;
}
