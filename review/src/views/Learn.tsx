import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Judged, LearnChapter, LearnOverview, Question, RetellResult } from "../api";
import { api, post } from "../api";
import { Loading, Panel, ProgressRing } from "../components";
import type { TFunc } from "../i18n";
import { num, useT } from "../i18n";
import { useApp } from "../state";
import type { Route } from "../util";
import { go, short } from "../util";

// Learn: quizzes built from the corpus, spaced repetition, chapter exams, and retellings
// graded by Claude. The server keeps the answers; this view only asks and shows.

const FAMILY: Record<string, { color: string }> = {
  story: { color: "var(--amber)" },
  time_place: { color: "var(--cyan)" },
  hebrew: { color: "var(--violet)" },
};

function familyLabel(t: TFunc, family: string): string {
  switch (family) {
    case "story": return t("learn.family.story");
    case "time_place": return t("learn.family.time_place");
    case "hebrew": return t("learn.family.hebrew");
    default: return family;
  }
}

/** A question kind in words, for the card's title. */
function questionKind(t: TFunc, kind: string): string {
  switch (kind) {
    case "who": return t("learn.kind.who");
    case "scene": return t("learn.kind.scene");
    case "cause": return t("learn.kind.cause");
    case "state": return t("learn.kind.state");
    case "deed": return t("learn.kind.deed");
    case "order": return t("learn.kind.order");
    case "where": return t("learn.kind.where");
    case "place": return t("learn.kind.place");
    case "span": return t("learn.kind.span");
    case "age": return t("learn.kind.age");
    case "gloss": return t("learn.kind.gloss");
    case "word": return t("learn.kind.word");
    case "cloze": return t("learn.kind.cloze");
    default: return kind;
  }
}

/** The unit a number question asks in (urim/learn/quiz.py: hours, days, months, years). */
function unitLabel(t: TFunc, unit: string): string {
  switch (unit) {
    case "hours": return t("learn.unit.hours");
    case "days": return t("learn.unit.days");
    case "months": return t("learn.unit.months");
    case "years": return t("learn.unit.years");
    default: return unit;
  }
}

function modeLabel(t: TFunc, mode: string): string {
  switch (mode) {
    case "practice": return t("learn.mode.practice");
    case "exam": return t("learn.mode.exam");
    case "retell": return t("learn.mode.retell");
    default: return mode;
  }
}

const pct = (v: number) => num(v, { style: "percent", maximumFractionDigits: 0 });

function useFamilies(): [string[], (f: string[]) => void] {
  const [fams, setFams] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("urim.learn.families") ?? "null") ?? Object.keys(FAMILY); }
    catch { return Object.keys(FAMILY); }
  });
  const set = (f: string[]) => {
    setFams(f);
    try { localStorage.setItem("urim.learn.families", JSON.stringify(f)); } catch { /* storage unavailable */ }
  };
  return [fams, set];
}

// --- the map ----------------------------------------------------------------------------------------
type LonLat = [number, number];
interface Basemap {
  land: { rings: LonLat[][] }[]; lakes: { rings: LonLat[][] }[];
  rivers: { line: LonLat[]; scalerank: number | null }[];
  regions: { name: string; kind: string; lon: number; lat: number; [k: `name_${string}`]: string | undefined }[];
}
let basemap: Promise<Basemap> | null = null;

function MapPick({ q, pin, setPin, judged }: {
  q: Question; pin: [number, number] | null; setPin: (p: [number, number]) => void; judged: Judged | null;
}) {
  const [base, setBase] = useState<Basemap | null>(null);
  const { lang } = useApp();
  const ref = useRef<SVGSVGElement>(null);
  const W = 720, H = 420;
  useEffect(() => {
    basemap ??= fetch("/geo/near_east.json").then((r) => r.json());
    basemap.then(setBase);
  }, []);
  const projection = useMemo(() => {
    const f = q.frame!;
    const frame: GeoJSON.Feature = { type: "Feature", properties: {}, geometry: { type: "MultiPoint", coordinates: [[f.west, f.south], [f.east, f.north]] } };
    return d3.geoMercator().fitExtent([[10, 10], [W - 10, H - 10]], frame);
  }, [q.frame]);
  const path = (rings: LonLat[][]) => rings.map((r) => r.map((p, i) => { const [x, y] = projection(p)!; return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("") + "Z").join("");
  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    if (judged) return;
    const box = ref.current!.getBoundingClientRect();
    const [lon, lat] = projection.invert!([(e.clientX - box.left) * (W / box.width), (e.clientY - box.top) * (H / box.height)])!;
    setPin([lat, lon]);
  };
  const P = (p: [number, number]) => projection([p[1], p[0]])!;
  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="quiz-map" onClick={click}>
      <rect width={W} height={H} fill="#040a10" />
      {base && base.land.map((l, i) => <path key={i} d={path(l.rings)} fill="#1a3142" fillRule="evenodd" stroke="#3d6f8a" />)}
      {base && base.lakes.map((l, i) => <path key={`k${i}`} d={path(l.rings)} fill="#040a10" stroke="#3d6f8a" />)}
      {base && base.rivers.filter((r) => (r.scalerank ?? 9) <= 8).map((r, i) => (
        <path key={`r${i}`} d={r.line.map((p, j) => { const [x, y] = projection(p)!; return `${j ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join("")}
              fill="none" stroke="#3d7fa3" strokeWidth={1.2} opacity={0.8} />
      ))}
      {base && base.regions.map((r, i) => {
        const [x, y] = projection([r.lon, r.lat])!;
        return x > 0 && x < W && y > 0 && y < H
          ? <text key={`g${i}`} x={x} y={y} textAnchor="middle" fill="#6f8ea3" fontSize={11} letterSpacing="0.15em" style={{ textTransform: "uppercase", pointerEvents: "none" }}>{r[`name_${lang}`] ?? r.name}</text>
          : null;
      })}
      {pin && <circle cx={P(pin)[0]} cy={P(pin)[1]} r={6} fill="var(--amber)" stroke="#000" />}
      {judged?.point && pin && <line x1={P(pin)[0]} y1={P(pin)[1]} x2={P(judged.point)[0]} y2={P(judged.point)[1]} stroke="var(--dim)" strokeDasharray="4 3" />}
      {judged?.point && <circle cx={P(judged.point)[0]} cy={P(judged.point)[1]} r={7} fill="none" stroke="var(--green)" strokeWidth={3} />}
    </svg>
  );
}

// --- one question ---------------------------------------------------------------------------------
function Hebrew({ line }: { line: string }) {
  return (
    <div className="hebrew quiz-hebrew">
      {line.split(" ").map((w, i) => w.startsWith("[") ? <mark key={i}>{w.slice(1, -1)} </mark> : <span key={i}>{w} </span>)}
    </div>
  );
}

function OrderList({ q, order, setOrder, locked }: { q: Question; order: string[]; setOrder: (o: string[]) => void; locked: boolean }) {
  const label = Object.fromEntries(q.choices.map((c) => [c.id, c.label]));
  const [drag, setDrag] = useState<number | null>(null);
  const move = (from: number, to: number) => {
    if (locked || to < 0 || to >= order.length) return;
    const next = [...order];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setOrder(next);
  };
  return (
    <div className="grid" style={{ gap: 6 }}>
      {order.map((id, i) => (
        <div key={id} className="order-item" draggable={!locked}
             onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()}
             onDrop={() => { if (drag !== null) move(drag, i); setDrag(null); }}>
          <span className="mono muted">{i + 1}</span>
          <span style={{ flex: 1 }}>{label[id]}</span>
          {!locked && <><button className="btn small ghost" onClick={() => move(i, i - 1)}>↑</button>
            <button className="btn small ghost" onClick={() => move(i, i + 1)}>↓</button></>}
        </div>
      ))}
    </div>
  );
}

function QuestionCard({ q, n, total, onAnswered, mode, examId }: {
  q: Question; n: number; total: number; mode: string; examId: number | null;
  onAnswered: (j: Judged) => void;
}) {
  const { toast, lang } = useApp();
  const t = useT();
  const [choice, setChoice] = useState<string | null>(null);
  const [order, setOrder] = useState<string[]>(q.choices.map((c) => c.id));
  const [pin, setPin] = useState<[number, number] | null>(null);
  const [text, setText] = useState("");
  const [judged, setJudged] = useState<Judged | null>(null);
  const started = useRef(Date.now());
  const fam = FAMILY[q.family];

  const response = () => {
    switch (q.format) {
      case "choice": return choice;
      case "order": return order;
      case "map": return pin;
      case "number": return text.trim() === "" ? null : Number(text);
      case "text": return text.trim() || null;
    }
  };
  const submit = async (override?: unknown) => {
    const r = override ?? response();
    if (judged || r === null || r === undefined || (typeof r === "number" && Number.isNaN(r))) return;
    try {
      const j = await post<Judged>("/api/learn/answer", {
        question_id: q.id, response: r, mode, exam_id: examId, ms: Date.now() - started.current, lang,
      });
      setJudged(j);
    } catch (e) { toast(String((e as Error).message), "red"); }
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" && e.key !== "Enter") return;
      if (judged && e.key === "Enter") { e.preventDefault(); onAnswered(judged); return; }
      if (!judged && q.format === "choice" && /^[1-9]$/.test(e.key)) {
        const c = q.choices[Number(e.key) - 1];
        if (c) { setChoice(c.id); submit(c.id); }
      } else if (!judged && e.key === "Enter") { e.preventDefault(); submit(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <Panel className="quiz-card" title={`${questionKind(t, q.kind)} · ${familyLabel(t, q.family)}`} count={`${n}/${total}`}>
      <div className="quiz-prompt" style={{ borderColor: fam?.color }}>{q.prompt}</div>
      {q.context && <div className="quiz-context">{q.context}</div>}
      {q.hebrew && <Hebrew line={q.hebrew} />}
      {q.format === "choice" && (
        <div className="grid" style={{ gap: 8, marginTop: 12 }}>
          {q.choices.map((c, i) => {
            const state = judged ? (judged.answer === c.label || (judged.correct && choice === c.id) ? "right" : choice === c.id ? "wrong" : "") : choice === c.id ? "picked" : "";
            return (
              <button key={c.id} className={`quiz-choice ${state}`} disabled={!!judged}
                      onClick={() => { setChoice(c.id); submit(c.id); }}>
                <span className="mono muted">{i + 1}</span>
                <span className={c.hebrew ? "hebrew" : ""} style={c.hebrew ? { fontSize: 26 } : undefined}>{c.label}</span>
              </button>
            );
          })}
        </div>
      )}
      {q.format === "order" && <OrderList q={q} order={order} setOrder={setOrder} locked={!!judged} />}
      {q.format === "map" && <MapPick q={q} pin={pin} setPin={setPin} judged={judged} />}
      {(q.format === "number" || q.format === "text") && (
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <input autoFocus value={text} disabled={!!judged} onChange={(e) => setText(e.target.value)}
                 type={q.format === "number" ? "number" : "text"} step="any" style={{ width: 220 }}
                 placeholder={q.format === "number" ? t("learn.answer.in_unit", { unit: unitLabel(t, q.unit ?? "") }) : t("learn.answer.word")} />
          {q.unit && <span className="muted">{unitLabel(t, q.unit)}</span>}
        </div>
      )}
      {!judged && q.format !== "choice" && (
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn amber" onClick={() => submit()}>{t("learn.check")} ⏎</button>
          {q.format === "map" && !pin && <span className="muted" style={{ fontSize: 12 }}>{t("learn.map_hint")}</span>}
        </div>
      )}
      {judged && (
        <div className={`intel ${judged.correct ? "" : "red"} quiz-feedback`} style={judged.correct ? { borderColor: "rgba(69,224,138,.4)", background: "rgba(69,224,138,.07)" } : undefined}>
          <b style={judged.correct ? { color: "var(--green)" } : undefined}>
            {judged.correct ? t("learn.feedback.right") : judged.score > 0 ? t("learn.feedback.close", { score: pct(judged.score) }) : t("learn.feedback.wrong")}
          </b>
          <div><span className="muted">{t("learn.feedback.answer")}</span> {judged.answer}</div>
          {judged.explanation && <div className="muted" style={{ marginTop: 4 }}>{judged.explanation}</div>}
          <div className="row" style={{ marginTop: 8, gap: 12 }}>
            {judged.verse && <a href={`/codex.html#/read/${judged.verse.split(".").slice(0, 2).join(".")}`} target="_blank" rel="noreferrer">{t("learn.feedback.read", { ref: short(judged.verse) })} ↗</a>}
            <span className="muted mono" style={{ fontSize: 11 }}>
              {judged.card.interval_days ? t("learn.feedback.next_in", { count: judged.card.interval_days }) : t("learn.feedback.again_soon")}
            </span>
            <span className="spacer" />
            <button className="btn amber" autoFocus onClick={() => onAnswered(judged)}>{t("learn.next")} ⏎</button>
          </div>
        </div>
      )}
    </Panel>
  );
}

// --- a round --------------------------------------------------------------------------------------
function Quiz({ chapter, mode, families }: { chapter: string; mode: "practice" | "exam"; families: string[] }) {
  const { lang } = useApp();
  const t = useT();
  const [qs, setQs] = useState<Question[] | null>(null);
  const [examId, setExamId] = useState<number | null>(null);
  const [i, setI] = useState(0);
  const [results, setResults] = useState<{ q: Question; j: Judged }[]>([]);
  const [exam, setExam] = useState<{ score: number; passed: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    setQs(null); setI(0); setResults([]); setExam(null);
    api<{ exam_id: number | null; questions: Question[] }>(
      `/api/learn/session?chapter=${chapter}&mode=${mode}&families=${families.join(",")}&n=10&lang=${lang}`,
    ).then((s) => { setQs(s.questions); setExamId(s.exam_id); }).catch((e) => setError(String(e.message)));
  }, [chapter, mode, families.join(","), round, lang]);

  useEffect(() => {
    if (qs && examId && results.length === qs.length && !exam) {
      post<{ score: number; passed: boolean }>(`/api/learn/exam/${examId}/finish`, {}).then(setExam);
    }
  }, [results, qs, examId, exam]);

  if (error) return <div className="intel red"><b>{t("learn.quiz")}</b>{error}</div>;
  if (!qs) return <Loading what={t("learn.loading_questions")} />;
  if (!qs.length) return <div className="intel"><b>{t("learn.nothing.title")}</b>{t("learn.nothing.text")}</div>;
  if (i < qs.length) {
    return <QuestionCard key={qs[i].id} q={qs[i]} n={i + 1} total={qs.length} mode={mode} examId={examId}
                         onAnswered={(j) => { setResults((r) => [...r, { q: qs[i], j }]); setI(i + 1); }} />;
  }
  const score = results.reduce((s, r) => s + r.j.score, 0) / results.length;
  const byFam = Object.keys(FAMILY).map((f) => {
    const rs = results.filter((r) => r.q.family === f);
    return { f, n: rs.length, s: rs.length ? rs.reduce((a, r) => a + r.j.score, 0) / rs.length : 0 };
  }).filter((x) => x.n);
  return (
    <Panel title={mode === "exam" ? t("learn.result.exam") : t("learn.result.round")}>
      <div className="row" style={{ gap: 24 }}>
        <ProgressRing value={score} size={96} label={pct(score)}
                      sub={mode === "exam" ? (exam ? (exam.passed ? t("learn.result.passed") : t("learn.result.not_yet")) : "…") : t("learn.result.score")}
                      color={mode === "exam" && exam?.passed ? "var(--green)" : "var(--amber)"} />
        <div className="grid" style={{ gap: 6 }}>
          {byFam.map(({ f, n, s }) => (
            <div key={f} className="row" style={{ gap: 8 }}>
              <span style={{ color: FAMILY[f].color, width: 110 }} className="hud upper">{familyLabel(t, f)}</span>
              <span className="mono">{pct(s)}</span><span className="muted">{t("learn.of", { total: n })}</span>
            </div>
          ))}
          {mode === "exam" && exam && (
            <div className={exam.passed ? "" : "muted"} style={{ color: exam.passed ? "var(--green)" : undefined }}>
              {exam.passed ? t("learn.result.proven", { chapter }) : t("learn.result.try_again", { mark: pct(0.8) })}
            </div>
          )}
        </div>
      </div>
      <div className="grid" style={{ gap: 4, marginTop: 14 }}>
        {results.filter((r) => !r.j.correct).map((r) => (
          <div key={r.q.id} style={{ fontSize: 13 }}>
            <span className="mono" style={{ color: "var(--red)" }}>✗</span> {r.q.prompt} <span className="muted">→ {r.j.answer}</span>
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: 14, gap: 8 }}>
        <button className="btn amber" onClick={() => setRound(round + 1)}>{t("learn.another_round")}</button>
        <button className="btn ghost" onClick={() => go("learn")}>{t("learn.all_chapters")}</button>
      </div>
    </Panel>
  );
}

function Retell({ chapter }: { chapter: string }) {
  const { lang } = useApp();
  const t = useT();
  const [text, setText] = useState(() => { try { return localStorage.getItem(`urim.retell.${chapter}`) ?? ""; } catch { return ""; } });
  const [result, setResult] = useState<RetellResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const save = (v: string) => { setText(v); try { localStorage.setItem(`urim.retell.${chapter}`, v); } catch { /* storage unavailable */ } };
  const send = async () => {
    setBusy(true); setError(null);
    try { setResult(await post<RetellResult>("/api/learn/retell", { chapter, text, lang })); }
    catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(false); }
  };
  return (
    <div className="grid">
      <Panel title={t("learn.retell.title", { chapter })} count={t("learn.retell.words", { count: words })}>
        <p className="muted" style={{ marginTop: 0 }}>{t("learn.retell.intro")}</p>
        <textarea value={text} onChange={(e) => save(e.target.value)} rows={10} style={{ width: "100%" }} disabled={busy}
                  placeholder={t("learn.retell.placeholder")} />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn amber" disabled={busy || words < 15} onClick={send}>{busy ? t("learn.retell.busy") : t("learn.retell.check")}</button>
          {error && <span style={{ color: "var(--red)" }}>{error}</span>}
        </div>
      </Panel>
      {result && (
        <Panel title={t("learn.retell.feedback")}>
          <div className="row" style={{ gap: 20, alignItems: "flex-start" }}>
            <ProgressRing value={result.score / 100} size={90} label={num(result.score)} sub={t("learn.of", { total: 100 })} />
            <div className="grid" style={{ gap: 8, flex: 1 }}>
              <div>{result.feedback}</div>
              {!result.order_ok && <div style={{ color: "var(--amber)" }}>{t("learn.retell.order")}</div>}
              {result.errors.map((e, i) => (
                <div key={i} className="intel red"><b>{t("learn.retell.check_label")}</b>{t("learn.retell.error", { claim: e.claim, correction: e.correction })}{e.verse && <span className="muted"> ({short(e.verse)})</span>}</div>
              ))}
              <div className="row" style={{ gap: 24, alignItems: "flex-start" }}>
                <div><div className="hud upper" style={{ color: "var(--green)", fontSize: 10 }}>{t("learn.retell.told")}</div>
                  {result.covered.map((id) => <div key={id} style={{ fontSize: 13 }}>✓ {result.titles[id]}</div>)}</div>
                <div><div className="hud upper" style={{ color: "var(--red)", fontSize: 10 }}>{t("learn.retell.missed")}</div>
                  {result.missed.map((id) => <div key={id} style={{ fontSize: 13 }} className="muted">· {result.titles[id]}</div>)}</div>
              </div>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}

// --- chapters -----------------------------------------------------------------------------------------
function ChapterCard({ c, families }: { c: LearnChapter; families: string[] }) {
  const t = useT();
  const open = (mode: string) => go("learn", c.chapter, { mode, fam: families.join(",") });
  return (
    <div className={`learn-card ${c.proven ? "proven" : ""}`}>
      <div className="row" style={{ gap: 8 }}>
        <b className="mono">{c.chapter}</b>
        {c.proven && <span title={t("learn.card.proven")} style={{ color: "var(--gold, #e8c66a)" }}>★</span>}
        <span className="spacer" />
        {(c.due ?? 0) > 0 && <span className="pill" style={{ color: "var(--amber)" }}>{t("learn.card.due", { count: c.due ?? 0 })}</span>}
      </div>
      <div className="bar" style={{ margin: "6px 0" }}><div style={{ width: `${c.mastery * 100}%` }} /></div>
      <div className="muted mono" style={{ fontSize: 11 }}>
        {t("learn.card.known", { known: c.known ?? 0, count: c.facts })} · {t("learn.card.scenes", { count: c.events })}
        {c.best_exam !== undefined && ` · ${t("learn.card.exam", { score: pct(c.best_exam) })}`}
        {c.retell_score != null && ` · ${t("learn.card.retold", { score: c.retell_score })}`}
      </div>
      <div className="row" style={{ gap: 6, marginTop: 8 }}>
        <button className="btn small amber" onClick={() => open("practice")}>{t("learn.card.practice")}</button>
        <button className="btn small" onClick={() => open("exam")}>{t("learn.card.exam_button")}</button>
        <button className="btn small ghost" disabled={!c.events} onClick={() => open("retell")}>{t("learn.card.retell")}</button>
      </div>
    </div>
  );
}

export default function Learn({ route }: { route: Route }) {
  const { lang } = useApp();
  const t = useT();
  const [data, setData] = useState<LearnOverview | null>(null);
  const [families, setFamilies] = useFamilies();
  const [all, setAll] = useState(false);
  const chapter = route.arg;
  const mode = route.params.get("mode") ?? "practice";
  const fams = route.params.get("fam")?.split(",").filter((f) => FAMILY[f]) ?? families;

  useEffect(() => { if (!chapter) api<LearnOverview>(`/api/learn/overview?lang=${lang}`).then(setData); }, [chapter, lang]);

  const style = (
    <style>{`
      .learn-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
      .learn-card { border: 1px solid var(--line); border-radius: 4px; padding: 10px; background: rgba(255,255,255,.015); }
      .learn-card.proven { border-color: rgba(232,198,106,.6); box-shadow: 0 0 10px rgba(232,198,106,.15); }
      .bar { height: 4px; background: #132230; border-radius: 2px; overflow: hidden; }
      .bar div { height: 100%; background: linear-gradient(90deg, var(--violet), var(--green)); }
      .quiz-card { max-width: 820px; }
      .quiz-prompt { font-size: 20px; line-height: 1.35; border-left: 3px solid; padding-left: 10px; }
      .quiz-context { margin-top: 10px; color: var(--dim); font-size: 15px; }
      .quiz-hebrew { font-size: 28px; line-height: 1.9; text-align: right; margin-top: 10px; color: var(--text); }
      .quiz-hebrew mark { background: rgba(165,139,250,.25); color: var(--violet); border-radius: 3px; padding: 0 3px; }
      .quiz-choice { display: flex; gap: 12px; align-items: center; text-align: left; padding: 10px 12px; border: 1px solid var(--line); border-radius: 4px; background: rgba(255,255,255,.02); color: var(--text); cursor: pointer; font-size: 15px; }
      .quiz-choice:hover:not(:disabled) { border-color: var(--amber); }
      .quiz-choice.picked { border-color: var(--amber); }
      .quiz-choice.right { border-color: var(--green); background: rgba(69,224,138,.08); }
      .quiz-choice.wrong { border-color: var(--red); background: rgba(255,90,95,.08); }
      .quiz-map { width: 100%; max-width: 760px; margin-top: 12px; border: 1px solid var(--line); border-radius: 4px; cursor: crosshair; }
      .quiz-feedback { margin-top: 14px; }
      .order-item { display: flex; gap: 10px; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: 4px; cursor: grab; background: rgba(255,255,255,.02); }
    `}</style>
  );

  if (chapter) {
    return (
      <div className="view">
        {style}
        <div className="row" style={{ marginBottom: 14, gap: 12 }}>
          <a onClick={() => go("learn")} style={{ cursor: "pointer" }}>← {t("learn.chapters")}</a>
          <h1 style={{ margin: 0 }}>{chapter} <span className="muted hud upper" style={{ fontSize: 13 }}>· {modeLabel(t, mode)}</span></h1>
          <span className="spacer" />
          {mode !== "retell" && Object.entries(FAMILY).map(([f, v]) => (
            <span key={f} className={`chip click ${fams.includes(f) ? "on" : ""}`} style={{ color: fams.includes(f) ? v.color : undefined }}
                  onClick={() => {
                    const next = fams.includes(f) ? fams.filter((x) => x !== f) : [...fams, f];
                    if (next.length) { setFamilies(next); go("learn", chapter, { mode, fam: next.join(",") }); }
                  }}>{familyLabel(t, f)}</span>
          ))}
        </div>
        {mode === "retell" ? <Retell chapter={chapter} /> : <Quiz chapter={chapter} mode={mode as "practice" | "exam"} families={fams} />}
      </div>
    );
  }
  if (!data) return <Loading what={t("learn.loading_overview")} />;
  const withStory = data.chapters.filter((c) => c.events > 0 || c.translated > 0);
  const shown = all ? data.chapters : withStory;
  const books = [...new Set(shown.map((c) => c.book))];
  const known = data.chapters.reduce((s, c) => s + (c.known ?? 0), 0);
  const due = data.chapters.reduce((s, c) => s + (c.due ?? 0), 0);
  const proven = data.chapters.filter((c) => c.proven).length;
  return (
    <div className="view">
      {style}
      <div className="row" style={{ marginBottom: 14, alignItems: "flex-end" }}>
        <div>
          <div className="hud upper muted" style={{ fontSize: 11, letterSpacing: "0.3em" }}>{t("learn.kicker")}</div>
          <h1>
            {t("learn.title")}{" "}
            <span className="muted" style={{ fontWeight: 500, fontSize: 18 }}>
              · {t("learn.facts_known", { count: known })} · {t("learn.chapters_proven", { count: proven })} · {t("learn.due", { count: due })}
            </span>
          </h1>
        </div>
        <span className="spacer" />
        {Object.entries(FAMILY).map(([f, v]) => (
          <span key={f} className={`chip click ${families.includes(f) ? "on" : ""}`} style={{ color: families.includes(f) ? v.color : undefined }}
                onClick={() => { const next = families.includes(f) ? families.filter((x) => x !== f) : [...families, f]; if (next.length) setFamilies(next); }}>{familyLabel(t, f)}</span>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 0, maxWidth: 860 }}>
        {t("learn.intro", { count: data.known_days, size: data.exam_size, mark: pct(data.pass_mark) })}
      </p>
      {books.map((b) => (
        <Panel key={b} title={b} count={shown.filter((c) => c.book === b).length}>
          <div className="learn-grid">
            {shown.filter((c) => c.book === b).map((c) => <ChapterCard key={c.chapter} c={c} families={families} />)}
          </div>
        </Panel>
      ))}
      {!all && data.chapters.length > withStory.length && (
        <button className="btn ghost" onClick={() => setAll(true)}>
          {t("learn.show_text_only", { count: data.chapters.length - withStory.length })}
        </button>
      )}
    </div>
  );
}
