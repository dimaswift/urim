// Typed access to the review API (urim/review/server.py).

export type Status = "draft" | "changes_requested" | "approved";
export interface Coded { code: string; label: string | null }
export interface EntityRef { entity_id: string; entity_type: string; name: string }

export interface EventView {
  event_id: string; parent_event_id: string | null; title: string | null;
  narrative_summary: string | null; temporal_reasoning_note: string | null;
  verse_start: string; verse_end: string; utes_start: number; utes_end: number;
  duration_seconds: number; utes_margin_seconds: number; relative_margin_seconds: number;
  precision_tier: Coded; start_label: string; end_label: string;
  anchor_id: string; anchor_point: string; relative_offset_seconds: number;
  time_of_day: Coded | null; ancient_year_marker: string | null;
  ancient_season_marker: string | null; ancient_diurnal_marker: string | null;
  location: EntityRef | null; text_lang: string | null;
}
export interface CausalLink {
  causal_id: string; cause_event_id: string; effect_event_id: string; causal_type: Coded;
  elapsed_seconds: number; confidence: number; explanation: string | null;
}
export interface ComponentView {
  component_id: string; entity_id: string; category: string; component_key: string;
  value_code: string | null; target: EntityRef | null; supersedes_component_id: string | null;
  label_key: string | null; label_value: string | null; evidence_explanation: string | null;
  acquired_at_verse: string; expired_at_verse: string | null; utes_start: number; utes_end: number | null;
}
export interface EdgeView {
  edge_id: string; source: EntityRef; target: EntityRef; interaction_type: string;
  interaction_label: string | null; description: string | null; verse_id: string; event_id: string;
  utes_timestamp: number;
}
export interface InstanceView {
  instance_id: string; system_id: string; system_name: string | null; event_id: string;
  verse_start: string; verse_end: string; utes_timestamp: number; initiator: EntityRef;
  targets: EntityRef[]; artifacts: EntityRef[]; location: EntityRef | null; tags: string[];
  outcome_summary: string | null; significance_note: string | null;
}
export interface Token {
  pos: number; surface: string; translit?: string | null; lemma?: string | null;
  strongs?: string | null; morph?: string | null; name_ref?: string | null;
  reading?: string | null; gloss?: string | null;
}
export interface PhilNote { term: string; translit?: string; root?: string; note: string; sources?: string[] }
export interface VerseMatrix {
  verse_id: string; book_code: string; book_name: string | null; chapter: number; verse: number;
  aliases: string[]; source_language: string; source_text: string; tokens: Token[];
  baseline_translation: string | null; traditional_baseline: string | null;
  translation_literal: string | null; translation_dramatic: string | null;
  directors_commentary: string | null; philological_notes: PhilNote[];
  baseline_lang: string | null; layers_lang: string | null; utes: number | null;
  events: EventView[];
  ecs: { entities: EntityRef[]; components: ComponentView[]; system_instances: InstanceView[]; edges: EdgeView[] } | null;
}
export interface Dossier {
  entity_id: string; entity_type: string; tipnr_id: string | null; source_script_name: string | null;
  transliterated_name: string | null; canonical_name: string | null; phonetic_name: string | null;
  aliases: string[]; etymology_meaning: string | null; summary_bio: string | null;
  first_mention_verse: string;
  geo: { lat: number; lon: number; elevation_m: number | null; source: string | null; confidence: number | null } | null;
  components: ComponentView[]; interactions: EdgeView[]; events: EventView[]; text_lang: string | null;
}
export interface Codex {
  system_id: string; category: string; name: string | null; ancient_near_east_context: string | null;
  rules_and_mechanics: string[]; first_occurrence_verse: string | null; instances: InstanceView[];
}
export interface Player {
  level: number; rank: string; xp: number; level_floor: number; level_ceiling: number;
  streak_days: number; reviews: number;
}
export interface Badge { id: string; name: string; description: string; progress: number; goal: number; earned: boolean }
export interface ChapterTile {
  chapter: number; ref: string; ingested: boolean; verses?: number; events?: number;
  ontology?: boolean; philology?: number; completion?: number; approved?: number;
  drafts?: number; requests?: number; approval?: number;
}
export interface Overview {
  player: Player; badges: Badge[];
  totals: Record<string, number>;
  sections: { name: string; first: number; last: number }[];
  books: { book_code: string; osis: string; testament: string; book_id: number; chapters: ChapterTile[] }[];
  next_steps: string[];
}
export interface Card {
  key: string; kind: string; id: string; chapter: string; status: Status;
  produced_by: { model: string; skill: string; run: string }; produced_at: string;
  agent_notes: string[]; history: { status: Status; at: string; note: string | null }[];
  title: string; missing: boolean; payload: any;
}
export interface LedgerEntry { status: Status; chapter: string; model: string; notes: number }
export interface Place {
  entity_id: string; name: string; lat: number; lon: number; source: string | null;
  confidence: number | null; events: string[];
}
export interface Journey {
  entity_id: string; name: string;
  stops: { event_id: string; title: string | null; place: string; utes: number; label: string }[];
}
export interface EntityRow {
  entity_id: string; name: string; entity_type: string; tipnr_id: string | null;
  first_mention_verse: string; events: number; interactions: number; states: number; located: boolean;
}
export interface SearchHit {
  kind: string; id: string; title: string; snippet: string; score: number;
  via?: ("keyword" | "meaning")[];
  similarity?: number | null; // cosine similarity, for hits found by meaning
}

export class ApiError extends Error {}

/** Built for GitHub Pages (`npm run build:site`): no server, read-only, the API from files. */
export const STATIC = import.meta.env.VITE_URIM_STATIC === "1";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (STATIC) return (await import("./static")).answer<T>(path, init);
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not json */ }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export interface ReviewResult {
  changed: string[]; player: Player; xp_gained: number; level_up: boolean; badges: Badge[];
}

// --- autonomous runs (urim run) ----------------------------------------------------------------
export interface LayerRow {
  phase: "unwritten" | "partial" | "requested" | "drafts" | "done" | "failed";
  approved: number; drafts: number; requested: number; escalated: number; unwritten: number; rounds: number;
}
export interface RunStep {
  id: string; action: "write" | "revise" | "critique"; layer: string; chapter: string; scope: string;
  round: number; final: boolean; model: string;
  status: "running" | "done" | "failed" | "limited" | "unavailable" | "stopped";
  started: string; ended: string | null; activity: string | null; summary: string; error: string | null;
  verdict: Record<string, number> | null; turns: number; duration_s: number; cost_usd: number;
  tokens_in: number; tokens_out: number; cache_read: number;
}
export interface RunState {
  name: string; scope: string; layers: string[]; models: Record<string, string>;
  parallel: number; max_rounds: number;
  status: "running" | "waiting" | "finished" | "stopped" | "interrupted";
  started: string; updated: string; finished: string | null;
  waiting_until: string | null; waiting_for: string | null;
  chapters: { chapter: string; verses: number; layers: Record<string, LayerRow> }[];
  totals: { sessions: number; cost_usd: number; tokens: number };
  running: RunStep[];
  steps?: RunStep[]; log?: string[];
  escalated?: { key: string; chapter: string; note: string | null }[];
}

// --- learning (urim/learn) ----------------------------------------------------------------------
export interface QuizChoice { id: string; label: string; hebrew: boolean }
export interface Question {
  id: string; kind: string; family: string; chapter: string; item: string;
  format: "choice" | "order" | "map" | "number" | "text";
  prompt: string; context: string | null; hebrew: string | null; choices: QuizChoice[];
  frame: { west: number; south: number; east: number; north: number } | null;
  unit: string | null; verse: string | null;
}
export interface Judged {
  correct: boolean; score: number; answer: string; explanation: string; verse: string | null;
  point: [number, number] | null; card: { interval_days: number; due: string };
}
export interface LearnChapter {
  chapter: string; book: string; verses: number; translated: number; events: number; facts: number;
  seen?: number; known?: number; due?: number; mastery: number; proven: boolean;
  best_exam?: number; exams?: number; retell_score?: number | null; accuracy?: number; answers?: number;
}
export interface LearnOverview {
  chapters: LearnChapter[]; families: Record<string, string[]>; pass_mark: number;
  exam_size: number; known_days: number;
}
export interface RetellResult {
  score: number; covered: string[]; missed: string[];
  errors: { claim: string; correction: string; verse: string | null }[];
  order_ok: boolean; feedback: string; titles: Record<string, string>;
}
