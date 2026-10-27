"""The game layer: territory, experience, rank, streaks and badges, all derived from the ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from urim.canon import BOOKS
from urim.config import Paths
from urim.workbench.ledger import all_ledgers
from urim.workbench.status import corpus_status, next_steps

XP_PER_APPROVAL = {
    "verse.en": 10,
    "event": 8,
    "entity": 6,
    "system": 6,
    "component": 5,
    "instance": 5,
    "causal": 4,
    "edge": 3,
    "event_links": 3,
    "closure": 3,
}
XP_PER_REQUEST = 2
RANKS = [
    "Scout",
    "Runner",
    "Scribe",
    "Watchman",
    "Herald",
    "Captain",
    "Seer",
    "Prophet",
    "Judge",
    "Sanhedrin",
]

SECTIONS = [
    ("Torah", 1, 5),
    ("Former Prophets", 6, 12),
    ("Writings: History", 13, 17),
    ("Writings: Poetry", 18, 22),
    ("Latter Prophets", 23, 27),
    ("The Twelve", 28, 39),
    ("Gospels & Acts", 40, 44),
    ("Letters", 45, 65),
    ("Revelation", 66, 66),
]


def level_for(xp: int) -> dict[str, Any]:
    level = int((xp / 50) ** 0.5) + 1
    floor, ceiling = 50 * (level - 1) ** 2, 50 * level**2
    return {
        "level": level,
        "rank": RANKS[min(level, len(RANKS)) - 1],
        "xp": xp,
        "level_floor": floor,
        "level_ceiling": ceiling,
    }


def _streak(days: set[date]) -> int:
    today = datetime.now(UTC).date()
    day = today if today in days else today - timedelta(days=1)
    n = 0
    while day in days:
        n += 1
        day -= timedelta(days=1)
    return n


def overview(paths: Paths) -> dict[str, Any]:
    ledgers = all_ledgers(paths.corpus)
    rows = {r.chapter: r for r in corpus_status(paths)}
    items = [(led.chapter_ref, k, item) for led in ledgers for k, item in led.items.items()]
    approved = [(c, k) for c, k, i in items if i.status == "approved"]
    requests_made = sum(h.status == "changes_requested" for _, _, i in items for h in i.history)
    xp = sum(XP_PER_APPROVAL.get(k.split(":")[0], 2) for _, k in approved)
    xp += requests_made * XP_PER_REQUEST
    review_days = {datetime.fromisoformat(h.at).date() for _, _, i in items for h in i.history}

    def count(kind: str, status: str = "approved") -> int:
        return sum(1 for _, k, i in items if k.startswith(kind + ":") and i.status == status)

    by_chapter: dict[str, dict[str, int]] = {}
    for c, _, i in items:
        stats = by_chapter.setdefault(c, {"approved": 0, "draft": 0, "changes_requested": 0})
        stats[i.status] += 1
    cleared = [
        c
        for c, s in by_chapter.items()
        if s["approved"] >= 10 and not s["draft"] and not s["changes_requested"]
    ]

    badges = [
        ("first_seal", "First Seal", "Approve your first item", count_all := len(approved), 1),
        ("sharp_eye", "Sharp Eye", "Send 5 items back with a note", requests_made, 5),
        ("chronicler", "Chronicler", "Approve 25 events", count("event"), 25),
        ("lexicographer", "Lexicographer", "Approve 25 verses", count("verse.en"), 25),
        ("cartographer", "Cartographer", "Approve 10 entities", count("entity"), 10),
        (
            "conqueror",
            "Territory Held",
            "Clear a chapter: 10+ items, all approved",
            len(cleared),
            1,
        ),
        ("vigil", "Seven Watches", "Review on 7 days in a row", _streak(review_days), 7),
    ]

    books = []
    for b in BOOKS:
        chapters = []
        for n in range(1, b.chapters + 1):
            ref = f"{b.code}.{n}"
            row = rows.get(ref)
            stats = by_chapter.get(ref, {"approved": 0, "draft": 0, "changes_requested": 0})
            total = sum(stats.values())
            if row is None:
                chapters.append({"chapter": n, "ref": ref, "ingested": False})
                continue
            onto = bool(row.linked_events or row.ontology_items)
            completion = (
                0.3 * bool(row.events)
                + 0.3 * onto
                + 0.4 * (row.philology / max(len(row.verses), 1))
            )
            chapters.append(
                {
                    "chapter": n,
                    "ref": ref,
                    "ingested": True,
                    "verses": len(row.verses),
                    "events": row.events,
                    "ontology": onto,
                    "philology": row.philology,
                    "completion": round(completion, 3),
                    "approved": stats["approved"],
                    "drafts": stats["draft"],
                    "requests": stats["changes_requested"],
                    "approval": round(stats["approved"] / total, 3) if total else 0.0,
                }
            )
        books.append(
            {
                "book_code": b.code,
                "osis": b.osis,
                "testament": b.testament,
                "book_id": b.book_id,
                "chapters": chapters,
            }
        )

    ingested = [r for r in rows.values()]
    return {
        "player": level_for(xp)
        | {"streak_days": _streak(review_days), "reviews": len(approved) + requests_made},
        "badges": [
            {
                "id": i,
                "name": n,
                "description": d,
                "progress": min(v, goal),
                "goal": goal,
                "earned": v >= goal,
            }
            for i, n, d, v, goal in badges
        ],
        "totals": {
            "chapters_ingested": len(ingested),
            "chapters_in_canon": sum(b.chapters for b in BOOKS),
            "verses": sum(len(r.verses) for r in ingested),
            "verses_with_layers": sum(r.philology for r in ingested),
            "events": sum(r.events for r in ingested),
            "items": len(items),
            "approved": count_all,
            "drafts": sum(i.status == "draft" for _, _, i in items),
            "requests": sum(i.status == "changes_requested" for _, _, i in items),
        },
        "sections": [{"name": n, "first": a, "last": z} for n, a, z in SECTIONS],
        "books": books,
        "next_steps": next_steps(list(rows.values()), limit=8),
    }
