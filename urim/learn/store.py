"""Your answers and what they say you know: spaced repetition per fact, exams per chapter.

This is your data, not the corpus: it lives in `data/learner.sqlite` and is never committed.
A card is a fact (a scene's cast, a causal link, a word), not a question: each time it comes
due it is asked with a fresh seed, so you meet it from new angles. Scheduling is SM-2 in
miniature. A fact counts as known once its interval reaches three weeks; a chapter is
mastered by the share of its facts you know, and proven by a passed exam.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

KNOWN_DAYS = 21.0
PASS_MARK = 0.8
_SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    answer_id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    question_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    chapter TEXT NOT NULL,
    item TEXT NOT NULL,
    mode TEXT NOT NULL,
    exam_id INTEGER,
    correct INTEGER NOT NULL,
    score REAL NOT NULL,
    ms INTEGER
) STRICT;
CREATE TABLE IF NOT EXISTS cards (
    card_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    chapter TEXT NOT NULL,
    item TEXT NOT NULL,
    reps INTEGER NOT NULL,
    lapses INTEGER NOT NULL,
    ease REAL NOT NULL,
    interval_days REAL NOT NULL,
    due TEXT NOT NULL,
    last TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS exams (
    exam_id INTEGER PRIMARY KEY,
    chapter TEXT NOT NULL,
    started TEXT NOT NULL,
    finished TEXT,
    questions INTEGER NOT NULL,
    score REAL,
    passed INTEGER
) STRICT;
CREATE TABLE IF NOT EXISTS retells (
    retell_id INTEGER PRIMARY KEY,
    chapter TEXT NOT NULL,
    at TEXT NOT NULL,
    text TEXT NOT NULL,
    score REAL,
    result TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS cards_chapter ON cards (chapter, due);
"""


def card_id(kind: str, chapter: str, item: str) -> str:
    return f"{kind}:{chapter}:{item}"


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


class Learner:
    def __init__(self, path: Path, clock=lambda: datetime.now(UTC)):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- answering -----------------------------------------------------------------------------

    def record(
        self,
        *,
        question_id: str,
        kind: str,
        chapter: str,
        item: str,
        correct: bool,
        score: float,
        mode: str = "practice",
        exam_id: int | None = None,
        ms: int | None = None,
    ) -> dict:
        """Store an answer and reschedule its card; returns the card."""
        now = self.clock()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO answers (at, question_id, kind, chapter, item, mode, exam_id,"
                " correct, score, ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _iso(now),
                    question_id,
                    kind,
                    chapter,
                    item,
                    mode,
                    exam_id,
                    int(correct),
                    score,
                    ms,
                ),
            )
            cid = card_id(kind, chapter, item)
            row = conn.execute("SELECT * FROM cards WHERE card_id = ?", (cid,)).fetchone()
            reps, lapses, ease, interval = (
                (row["reps"], row["lapses"], row["ease"], row["interval_days"])
                if row
                else (0, 0, 2.5, 0.0)
            )
            if correct:
                reps += 1
                interval = 1.0 if reps == 1 else 3.0 if reps == 2 else round(interval * ease, 2)
                ease = min(3.0, ease + 0.1 * (score - 0.6))
                due = now + timedelta(days=interval)
            else:
                reps, lapses, interval = 0, lapses + 1, 0.0
                ease = max(1.3, ease - 0.2)
                due = now + timedelta(minutes=10)
            conn.execute(
                "INSERT OR REPLACE INTO cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, kind, chapter, item, reps, lapses, ease, interval, _iso(due), _iso(now)),
            )
            return {"card_id": cid, "reps": reps, "interval_days": interval, "due": _iso(due)}

    def due(self, chapter: str) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM cards WHERE chapter = ? AND due <= ? ORDER BY due",
                (chapter, _iso(self.clock())),
            ).fetchall()

    def seen(self, chapter: str) -> set[str]:
        with self._conn() as conn:
            return {
                r[0]
                for r in conn.execute("SELECT card_id FROM cards WHERE chapter = ?", (chapter,))
            }

    # --- exams and retellings ------------------------------------------------------------------

    def start_exam(self, chapter: str, questions: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO exams (chapter, started, questions) VALUES (?, ?, ?)",
                (chapter, _iso(self.clock()), questions),
            )
            return int(cur.lastrowid)

    def finish_exam(self, exam_id: int) -> dict:
        with self._conn() as conn:
            exam = conn.execute("SELECT * FROM exams WHERE exam_id = ?", (exam_id,)).fetchone()
            if exam is None:
                raise KeyError(f"no exam {exam_id}")
            total = conn.execute(
                "SELECT coalesce(sum(score), 0) FROM answers WHERE exam_id = ?", (exam_id,)
            ).fetchone()[0]
            score = round(total / max(exam["questions"], 1), 3)
            passed = score >= PASS_MARK
            conn.execute(
                "UPDATE exams SET finished = ?, score = ?, passed = ? WHERE exam_id = ?",
                (_iso(self.clock()), score, int(passed), exam_id),
            )
            return {
                "exam_id": exam_id,
                "chapter": exam["chapter"],
                "score": score,
                "passed": passed,
            }

    def record_retell(self, chapter: str, text: str, result: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO retells (chapter, at, text, score, result) VALUES (?, ?, ?, ?, ?)",
                (chapter, _iso(self.clock()), text, result.get("score"), json.dumps(result)),
            )
            return int(cur.lastrowid)

    # --- what you know -------------------------------------------------------------------------

    def progress(self, facts: dict[str, int]) -> dict[str, dict]:
        """Per chapter: facts known, seen and due, mastery 0-1, best exam, last retelling.

        `facts` is how many facts each chapter offers, so mastery counts the unseen ones too.
        """
        now = _iso(self.clock())
        out: dict[str, dict] = defaultdict(
            lambda: {"seen": 0, "known": 0, "due": 0, "strength": 0.0}
        )
        with self._conn() as conn:
            for r in conn.execute("SELECT chapter, interval_days, due FROM cards"):
                row = out[r["chapter"]]
                row["seen"] += 1
                row["known"] += r["interval_days"] >= KNOWN_DAYS
                row["due"] += r["due"] <= now
                row["strength"] += min(1.0, r["interval_days"] / KNOWN_DAYS)
            exams = conn.execute(
                "SELECT chapter, max(score) AS best, max(passed) AS proven, count(*) AS n"
                " FROM exams WHERE finished IS NOT NULL GROUP BY chapter"
            ).fetchall()
            retells = conn.execute(
                "SELECT chapter, score, at FROM retells r WHERE at ="
                " (SELECT max(at) FROM retells WHERE chapter = r.chapter)"
            ).fetchall()
            answered = conn.execute(
                "SELECT chapter, count(*) AS n, avg(correct) AS accuracy FROM answers"
                " GROUP BY chapter"
            ).fetchall()
        for e in exams:
            out[e["chapter"]] |= {
                "best_exam": e["best"],
                "proven": bool(e["proven"]),
                "exams": e["n"],
            }
        for r in retells:
            out[r["chapter"]] |= {"retell_score": r["score"], "retold_at": r["at"]}
        for a in answered:
            out[a["chapter"]] |= {"answers": a["n"], "accuracy": round(a["accuracy"], 3)}
        result = {}
        for chapter in set(facts) | set(out):
            row = dict(out[chapter])
            total = max(facts.get(chapter, 0), row["seen"], 1)
            row["facts"] = facts.get(chapter, 0)
            row["mastery"] = round(row.pop("strength") / total, 3)
            row.setdefault("proven", False)
            result[chapter] = row
        return result
