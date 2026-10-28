import { useEffect, useMemo, useRef, useState } from "react";
import type { Card, CausalLink, ComponentView, Dossier, EdgeView, EventView, InstanceView, Status, VerseMatrix } from "../api";
import { CausalRow, EntityChip, EventBrief, Loading, Panel, StatusPill } from "../components";
import { useApi, useApp } from "../state";
import { KIND_COLOR, KIND_LABEL, ENTITY_COLOR, ENTITY_GLYPH, ago, duration, go, href, range, short, type Route } from "../util";

interface Queue { total: number; by_kind: Record<string, number>; cards: Card[] }

function Verses({ verses }: { verses: { verse_id: string; text: string; translation: string }[] }) {
  return (
    <div className="grid" style={{ gap: 4 }}>
      {verses.map((v) => (
        <div key={v.verse_id} style={{ fontSize: 13 }}>
          <a className="mono" href={href("xray", v.verse_id)} style={{ marginRight: 8 }}>{short(v.verse_id)}</a>
          <span className="muted">{v.text}</span>
        </div>
      ))}
    </div>
  );
}

function EventBody({ p }: { p: { event: EventView; causes: CausalLink[]; effects: CausalLink[]; neighbours: Record<string, string>; verses: any[] } }) {
  return (
    <div className="grid">
      <EventBrief event={p.event} />
      {(p.causes.length > 0 || p.effects.length > 0) && (
        <div className="grid" style={{ gap: 6 }}>
          <div className="hud upper muted" style={{ fontSize: 10 }}>Causality</div>
          {p.causes.map((l) => <CausalRow key={l.causal_id} link={l} titles={p.neighbours} from={p.event.event_id} />)}
          {p.effects.map((l) => <CausalRow key={l.causal_id} link={l} titles={p.neighbours} from={p.event.event_id} />)}
        </div>
      )}
      <Verses verses={p.verses} />
    </div>
  );
}

function EntityBody({ d }: { d: Dossier }) {
  const color = ENTITY_COLOR[d.entity_type];
  return (
    <div className="grid">
      <div className="row" style={{ gap: 14 }}>
        <div style={{ fontSize: 34, color, textShadow: `0 0 12px ${color}` }}>{ENTITY_GLYPH[d.entity_type]}</div>
        <div>
          <div className="row"><h2>{d.canonical_name}</h2><span className="muted">{d.phonetic_name}</span>
            {d.source_script_name && <span className="hebrew" style={{ fontSize: 22, color: "var(--gold)" }}>{d.source_script_name}</span>}</div>
          <div className="mono muted">{d.entity_type} · {d.tipnr_id ?? "no TIPNR id"} · first at {d.first_mention_verse}</div>
        </div>
      </div>
      <p style={{ margin: 0 }}>{d.summary_bio}</p>
      <dl className="kv">
        <dt>Meaning</dt><dd>{d.etymology_meaning}</dd>
        {d.aliases.length > 0 && <><dt>Also</dt><dd>{d.aliases.join(" · ")}</dd></>}
        {d.geo && <><dt>Position</dt><dd className="mono">{d.geo.lat.toFixed(3)}, {d.geo.lon.toFixed(3)} <span className="muted">via {d.geo.source}{d.geo.confidence != null && ` · confidence ${Math.round(d.geo.confidence * 100)}%`}</span></dd></>}
      </dl>
    </div>
  );
}

function ComponentBody({ c, who }: { c: ComponentView; who: string }) {
  return (
    <div className="grid">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <span className="chip">{who}</span><span className="chip" style={{ color: "var(--green)" }}>{c.category}</span>
        <span className="chip mono">{short(c.acquired_at_verse)} → {c.expired_at_verse ? short(c.expired_at_verse) : "…"}</span>
      </div>
      <div className="hud" style={{ fontSize: 22 }}><span className="muted">{c.label_key}: </span><b style={{ color: "var(--green)" }}>{c.label_value}</b></div>
      {c.target && <div>Target: <EntityChip entity={c.target} /></div>}
      <p style={{ margin: 0 }}>{c.evidence_explanation}</p>
      {c.supersedes_component_id && <div className="muted mono">supersedes {c.supersedes_component_id}</div>}
    </div>
  );
}

function InstanceBody({ i }: { i: InstanceView }) {
  return (
    <div className="grid">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <EntityChip entity={i.initiator} /><span className="muted">→</span>
        {i.targets.map((t) => <EntityChip key={t.entity_id} entity={t} />)}
        {i.artifacts.map((t) => <EntityChip key={t.entity_id} entity={t} />)}
        <span className="chip mono">{range(i.verse_start, i.verse_end)}</span>
        {i.location && <EntityChip entity={i.location} />}
      </div>
      <p style={{ margin: 0 }}>{i.outcome_summary}</p>
      <div className="intel" style={{ borderColor: "rgba(165,139,250,.4)", background: "rgba(165,139,250,.06)", color: "#d9cfff" }}>
        <b style={{ color: "var(--violet)" }}>SIGNIFICANCE</b>{i.significance_note}
      </div>
      {i.tags.length > 0 && <div className="row">{i.tags.map((t) => <span key={t} className="chip mono">#{t}</span>)}</div>}
    </div>
  );
}

function EdgeBody({ e }: { e: EdgeView }) {
  return (
    <div className="grid">
      <div className="row" style={{ fontSize: 18, gap: 12 }}>
        <EntityChip entity={e.source} />
        <span className="hud upper" style={{ color: "var(--cyan)", letterSpacing: "0.2em" }}>— {e.interaction_label ?? e.interaction_type} →</span>
        <EntityChip entity={e.target} />
      </div>
      <div className="muted">{e.description}</div>
      <div><a className="mono" href={href("xray", e.verse_id)}>{e.verse_id}</a></div>
    </div>
  );
}

function VerseBody({ m }: { m: VerseMatrix }) {
  return (
    <div className="grid">
      <div className="hebrew" style={{ fontSize: 24, lineHeight: 1.9, color: "var(--gold)" }}>{m.source_text}</div>
      {[["Literal", m.translation_literal], ["Dramatic", m.translation_dramatic], ["Commentary", m.directors_commentary], [m.baseline_translation ?? "Baseline", m.traditional_baseline]].map(([label, text]) => text && (
        <div key={label}><div className="hud upper muted" style={{ fontSize: 10 }}>{label}</div><div>{text}</div></div>
      ))}
      <a href={href("xray", m.verse_id)}>Open in X-Ray →</a>
    </div>
  );
}

function CardBody({ card }: { card: Card }) {
  const p = card.payload;
  if (card.missing || !p) return <div className="empty">This item is not in the linked bundles</div>;
  switch (card.kind) {
    case "event": return <EventBody p={p} />;
    case "event_links":
      return (
        <div className="grid">
          <EventBrief event={p.event} compact />
          <div className="row" style={{ flexWrap: "wrap" }}>
            {p.participants.map((x: any) => (
              <span key={x.entity.entity_id} className="row" style={{ gap: 4 }}>
                <EntityChip entity={x.entity} /><span className="mono muted" style={{ fontSize: 10 }}>{x.role}</span>
              </span>
            ))}
          </div>
          <Verses verses={p.verses} />
        </div>
      );
    case "causal":
      return (
        <div className="grid">
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 12, alignItems: "center" }}>
            <div className="panel" style={{ padding: 10 }}><h3>{p.cause.title}</h3><div className="mono muted">{p.cause.start_label}</div></div>
            <div style={{ textAlign: "center" }}>
              <div className="hud upper" style={{ color: "var(--gold)", fontSize: 12 }}>{p.link.causal_type.label}</div>
              <div style={{ fontSize: 26, color: "var(--gold)" }}>⟶</div>
              <div className="mono muted">{p.link.elapsed_seconds < 0 ? "overlaps" : duration(p.link.elapsed_seconds)}</div>
            </div>
            <div className="panel" style={{ padding: 10 }}><h3>{p.effect.title}</h3><div className="mono muted">{p.effect.start_label}</div></div>
          </div>
          <p style={{ margin: 0 }}>{p.link.explanation}</p>
          <div className="muted mono">confidence {Math.round(p.link.confidence * 100)}%</div>
        </div>
      );
    case "entity": return <EntityBody d={p.dossier} />;
    case "system":
      return (
        <div className="grid">
          <div className="row"><span className="chip" style={{ color: "var(--violet)" }}>{p.codex.category}</span><span className="muted">first at {p.codex.first_occurrence_verse ?? "—"} · {p.codex.instances.length} occurrence(s)</span></div>
          <p style={{ margin: 0 }}>{p.codex.ancient_near_east_context}</p>
          <ol style={{ margin: 0, paddingLeft: 18 }}>{p.codex.rules_and_mechanics.map((r: string) => <li key={r}>{r}</li>)}</ol>
        </div>
      );
    case "component": case "closure": return <ComponentBody c={p.component} who={p.entity_name} />;
    case "instance": return <InstanceBody i={p.instance} />;
    case "edge": return <EdgeBody e={p.edge} />;
    case "verse.en": return <VerseBody m={p.verse} />;
  }
  return <pre className="mono">{JSON.stringify(p, null, 1)}</pre>;
}

function openTarget(card: Card) {
  if (card.kind === "verse.en") return go("xray", card.id);
  if (card.kind === "event" || card.kind === "event_links") return go("chronicle", card.id);
  if (card.kind === "entity") return go("dossiers", card.id);
  if (card.kind === "system") return go("codex", card.id);
  if (card.kind === "causal") return go("causal", card.payload?.link?.effect_event_id ?? "");
  if (card.kind === "component" || card.kind === "closure") return go("dossiers", card.payload?.component?.entity_id ?? "");
}

export default function Review({ route }: { route: Route }) {
  const { overview, review, lang } = useApp();
  const status = (route.params.get("status") ?? "draft") as Status;
  const chapter = route.params.get("chapter") ?? undefined;
  const kind = route.params.get("kind") ?? undefined;
  const q = new URLSearchParams({ status, limit: "500", lang });
  if (chapter) q.set("chapter", chapter);
  if (kind) q.set("kind", kind);
  const { data, error, reload } = useApi<Queue>(`/api/queue?${q}`);
  const [index, setIndex] = useState(0);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [leaving, setLeaving] = useState<"approved" | "changes_requested" | null>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { setIndex(0); setGone(new Set()); }, [status, chapter, kind]);
  const cards = useMemo(() => (data?.cards ?? []).filter((c) => !gone.has(c.key)), [data, gone]);
  // The queue counts kinds as fetched; take off the cards decided since.
  const byKind = useMemo(() => {
    const out = { ...(data?.by_kind ?? {}) };
    data?.cards.forEach((c) => { if (gone.has(c.key)) out[c.key.split(":")[0]] -= 1; });
    return out;
  }, [data, gone]);
  const card = cards[Math.min(index, Math.max(cards.length - 1, 0))];

  const decide = async (decision: "approved" | "changes_requested") => {
    if (!card) return;
    if (decision === "changes_requested" && !note.trim()) { setAsking(true); setTimeout(() => noteRef.current?.focus()); return; }
    setLeaving(decision);
    const r = await review([card.key], decision, decision === "changes_requested" ? note : undefined);
    setTimeout(() => {
      setLeaving(null);
      if (r && card.status !== decision) setGone((g) => new Set(g).add(card.key));
      setAsking(false); setNote("");
    }, 220);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA" || (e.target as HTMLElement).tagName === "INPUT") {
        if (e.key === "Escape") { setAsking(false); (e.target as HTMLElement).blur(); }
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && asking) decide("changes_requested");
        return;
      }
      if (e.key === "a" && card && card.status !== "approved") decide("approved");
      else if (e.key === "r" && card) { setAsking(true); setTimeout(() => noteRef.current?.focus()); e.preventDefault(); }
      else if (e.key === "ArrowRight" || e.key === "s") setIndex((i) => Math.min(i + 1, cards.length - 1));
      else if (e.key === "ArrowLeft") setIndex((i) => Math.max(i - 1, 0));
      else if (e.key === "o" && card) openTarget(card);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const ingested = overview?.books.flatMap((b) => b.chapters.filter((c) => c.ingested)) ?? [];
  const tally = chapter ? ingested.find((c) => c.ref === chapter) : overview?.totals;
  const counts: Record<string, number | undefined> = {
    draft: tally?.drafts, changes_requested: tally?.requests, approved: tally?.approved,
  };
  const set = (k: string, v?: string) => go("review", "", { status, chapter, kind, [k]: v });

  return (
    <div className="view">
      <style>{`
        .deck-card { transition: transform .22s ease, opacity .22s ease; }
        .deck-card.leave-approved { transform: translateX(60px) rotate(2deg); opacity: 0; }
        .deck-card.leave-changes_requested { transform: translateX(-60px) rotate(-2deg); opacity: 0; }
        .tabs { display: flex; gap: 4px; }
        .tab { padding: 8px 14px; border: 1px solid var(--line); border-radius: 4px; cursor: pointer; font: 700 12px/1 var(--hud); letter-spacing: .16em; text-transform: uppercase; color: var(--dim); background: transparent; }
        .tab.on { color: var(--text); border-color: currentColor; }
        .stack-shadow { position: absolute; inset: 8px -8px -8px 8px; border: 1px solid var(--line); border-radius: 4px; background: rgba(10,17,24,.8); z-index: -1; }
      `}</style>
      <div className="row" style={{ marginBottom: 14, flexWrap: "wrap" }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>Intelligence review</div>
          <h1>Review deck</h1>
        </div>
        <div className="spacer" />
        <div className="tabs">
          {(["draft", "changes_requested", "approved"] as Status[]).map((s) => (
            <button key={s} className={`tab ${status === s ? "on" : ""} st-${s}`} onClick={() => go("review", "", { status: s, chapter, kind })}>
              {s === "draft" ? "Drafts" : s === "changes_requested" ? "Sent back" : "Approved"} <span className="mono">{counts[s] ?? ""}</span>
            </button>
          ))}
        </div>
        <select value={chapter ?? ""} onChange={(e) => set("chapter", e.target.value || undefined)}>
          <option value="">All chapters</option>
          {ingested.map((c) => <option key={c.ref} value={c.ref}>{c.ref.replace(".", " ")}</option>)}
        </select>
      </div>
      <div className="row" style={{ marginBottom: 14, flexWrap: "wrap", gap: 6 }}>
        <span className={`chip click ${!kind ? "on" : ""}`} onClick={() => set("kind", undefined)}>All <span className="n">{data ? Object.values(byKind).reduce((a, b) => a + b, 0) : ""}</span></span>
        {Object.entries(byKind).map(([k, n]) => (
          <span key={k} className={`chip click ${kind === k ? "on" : ""}`} onClick={() => set("kind", k)}>
            <span style={{ color: KIND_COLOR[k] }}>■</span>{KIND_LABEL[k] ?? k} <span className="n">{n}</span>
          </span>
        ))}
      </div>
      {error && <div className="intel red"><b>ERROR</b>{error}</div>}
      {!data && !error && <Loading what="Pulling the deck" />}
      {data && !card && (
        <Panel><div className="empty">Deck cleared. {status === "draft" ? "No drafts waiting: send an agent on a mission from Command." : "Nothing here."}</div></Panel>
      )}
      {card && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 16, alignItems: "start" }}>
          <div style={{ position: "relative" }}>
            {cards.length > 1 && <div className="stack-shadow" />}
            <section className={`panel deck-card ${leaving ? "leave-" + leaving : ""}`} style={{ minHeight: 360 }}>
              <div className="row" style={{ marginBottom: 10 }}>
                <span className="pill" style={{ color: KIND_COLOR[card.kind] }}>{KIND_LABEL[card.kind] ?? card.kind}</span>
                <span className="mono muted">{card.chapter}</span>
                <span className="spacer" />
                <span className="mono muted">{Math.min(index, cards.length - 1) + 1} / {cards.length}</span>
              </div>
              <h2 style={{ marginBottom: 4 }}>{card.title}</h2>
              <div className="mono faint" style={{ marginBottom: 14 }}>{card.key}</div>
              {card.agent_notes.length > 0 && (
                <div className="intel" style={{ marginBottom: 12 }}>
                  <b>AGENT INTEL</b>{card.agent_notes.map((n) => <div key={n}>{n}</div>)}
                </div>
              )}
              {card.status === "changes_requested" && (
                <div className="intel red" style={{ marginBottom: 12 }}><b>YOUR ORDERS</b>{card.history.at(-1)?.note}</div>
              )}
              <CardBody card={card} />
            </section>
            <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
              <button className="btn ghost" onClick={() => setIndex((i) => Math.max(i - 1, 0))}><span className="kbd">←</span> Back</button>
              <button className="btn" onClick={() => setIndex((i) => Math.min(i + 1, cards.length - 1))}>Skip <span className="kbd">S</span></button>
              <button className="btn ghost" onClick={() => openTarget(card)}>Open <span className="kbd">O</span></button>
              <div className="spacer" />
              <button className="btn red" onClick={() => decide("changes_requested")}>Send back <span className="kbd">R</span></button>
              <button className="btn green" disabled={card.status === "approved"} onClick={() => decide("approved")}>Approve <span className="kbd">A</span></button>
            </div>
            {asking && (
              <div className="panel" style={{ marginTop: 12, borderColor: "rgba(255,90,95,.5)" }}>
                <div className="panel-title" style={{ color: "var(--red)" }}>Orders for the next session</div>
                <textarea ref={noteRef} rows={3} style={{ width: "100%" }} value={note} onChange={(e) => setNote(e.target.value)}
                          placeholder="What should the agent change? It will see this first in its packet." />
                <div className="row" style={{ marginTop: 8 }}>
                  <span className="muted" style={{ fontSize: 12 }}><span className="kbd">⌘↵</span> send · <span className="kbd">Esc</span> cancel</span>
                  <div className="spacer" />
                  <button className="btn red" disabled={!note.trim()} onClick={() => decide("changes_requested")}>Send back</button>
                </div>
              </div>
            )}
          </div>
          <div className="grid">
            <Panel title="Provenance">
              <dl className="kv">
                <dt>Status</dt><dd><StatusPill status={card.status} /></dd>
                <dt>Model</dt><dd className="mono">{card.produced_by.model}</dd>
                <dt>Skill</dt><dd className="mono">{card.produced_by.skill}</dd>
                <dt>Written</dt><dd>{ago(card.produced_at)}</dd>
              </dl>
            </Panel>
            <Panel title="History" count={card.history.length}>
              {card.history.length === 0 && <div className="muted">No decisions yet.</div>}
              <div className="grid" style={{ gap: 6 }}>
                {card.history.slice().reverse().map((h, i) => (
                  <div key={i} style={{ fontSize: 12 }}>
                    <StatusPill status={h.status} /> <span className="muted">{ago(h.at)}</span>
                    {h.note && <div className="muted" style={{ marginTop: 3 }}>{h.note}</div>}
                  </div>
                ))}
              </div>
            </Panel>
            <Panel title="Up next" count={Math.max(cards.length - index - 1, 0)}>
              <div className="grid" style={{ gap: 4 }}>
                {cards.slice(index + 1, index + 8).map((c, i) => (
                  <div key={c.key} className="row" style={{ fontSize: 12, cursor: "pointer" }} onClick={() => setIndex(index + 1 + i)}>
                    <span style={{ color: KIND_COLOR[c.kind] }}>■</span>
                    <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.title}</span>
                  </div>
                ))}
              </div>
              <button className="btn small ghost" style={{ marginTop: 10 }} onClick={reload}>Refresh deck</button>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
