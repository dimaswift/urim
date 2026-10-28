"""Learning: quiz questions built from the gold bundles, judging, spaced repetition, exams,
retellings graded by a (fake) model, and the review app's learn API."""

import json
import random
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from urim.config import load_paths
from urim.i18n.messages import Translator
from urim.learn.coach import candidates, facts_count, session
from urim.learn.quiz import (
    KINDS,
    Key,
    Question,
    _distinct,
    chapter_facts,
    judge,
    make,
    mask,
    mask_numbers,
    parse_id,
    subjects,
)
from urim.learn.retell import RetellError, grade, grading_prompt
from urim.learn.store import KNOWN_DAYS, Learner
from urim.review.server import create_review_app


@pytest.fixture(scope="module")
def facts(engine):
    return chapter_facts(engine, "1KGS.18")


def right_answer(q: Question, key: Key):
    match q.format:
        case "choice":
            return key.correct[0]
        case "order":
            return key.correct
        case "map":
            return list(key.point)
        case "number":
            return key.value
        case "text":
            return key.accept[0]


def test_every_kind_asks_from_the_corpus_and_accepts_its_own_answer(facts):
    made_kinds = set()
    for kind in KINDS:
        for subject in subjects(facts, kind)[:5]:
            made = make(facts, kind, subject, 11)
            if made is None:
                continue
            q, key = made
            made_kinds.add(kind)
            assert q.chapter == "1KGS.18" and q.prompt and key.answer
            assert judge(q, key, right_answer(q, key)).correct
            if q.format == "choice":
                assert len(q.choices) >= 3 and len({c.label for c in q.choices}) == len(q.choices)
                wrong = next(c.id for c in q.choices if c.id not in key.correct)
                assert not judge(q, key, wrong).correct
            # The id alone rebuilds the same question, which is how answers are checked.
            assert make(facts, *parse_id(q.id)[0:1], *parse_id(q.id)[2:]) == made
    assert {
        "who",
        "scene",
        "cause",
        "deed",
        "where",
        "place",
        "order",
        "gloss",
        "word",
        "cloze",
    } <= made_kinds


def test_names_are_masked_where_they_would_give_the_answer_away(facts):
    q, key = make(facts, "who", subjects(facts, "who")[0], 3)
    assert key.answer not in (q.context or "")


def test_partial_credit_for_order_distance_and_estimates(facts):
    q, key = make(facts, "order", subjects(facts, "order")[0], 5)
    swapped = key.correct[:]
    swapped[0], swapped[1] = swapped[1], swapped[0]
    j = judge(q, key, swapped)
    assert not j.correct and 0.5 < j.score < 1

    q, key = make(facts, "where", subjects(facts, "where")[0], 5)
    lat, lon = key.point
    assert judge(q, key, [lat + 0.1, lon]).correct  # about 11 km off
    far = judge(q, key, [lat + 5, lon])
    assert not far.correct and far.score == 0 and "km from your pin" in far.answer

    number_q = Question(
        id="x", kind="span", family="time_place", chapter="c", item="i", format="number", prompt="p"
    )
    number_key = Key(value=10, tolerance=2, answer="10", explanation="")
    assert judge(number_q, number_key, 11.5).correct
    assert 0 < judge(number_q, number_key, 14).score < 1

    text_q = number_q.model_copy(update={"format": "text"})
    text_key = Key(accept=["Obadiah"], answer="Obadiah", explanation="")
    assert (
        judge(text_q, text_key, "obadiah!").correct and judge(text_q, text_key, "Obadaih").correct
    )
    assert not judge(text_q, text_key, "Ahab").correct


RUSSIAN = Translator(
    "ru",
    {
        "quiz.scene.prompt": "Какую сцену описывает {ref}?",
        "quiz.where.prompt": "Где это происходит? Нажмите на карту.",
        "quiz.where.distance": {
            "one": "{answer} ({count} километр от вашей метки)",
            "few": "{answer} ({count} километра от вашей метки)",
            "many": "{answer} ({count} километров от вашей метки)",
            "other": "{answer} ({count} километра от вашей метки)",
        },
        "quiz.unit.years.count": {
            "one": "{count} год",
            "few": "{count} года",
            "many": "{count} лет",
            "other": "{count} года",
        },
    },
)


def test_questions_speak_the_learners_language_and_still_judge_their_answers(facts):
    ru = replace(facts, t=RUSSIAN)
    q, key = make(ru, "scene", subjects(ru, "scene")[0], 4)
    assert q.prompt.startswith("Какую сцену описывает 1 Kgs 18:") and q.prompt.endswith("?")
    assert judge(q, key, right_answer(q, key), ru.t).correct
    assert not judge(q, key, next(c.id for c in q.choices if c.id not in key.correct)).correct

    q, key = make(ru, "where", subjects(ru, "where")[0], 4)
    assert q.prompt == "Где это происходит? Нажмите на карту."
    assert judge(q, key, right_answer(q, key), ru.t).correct
    far = judge(q, key, [key.point[0] + 5, key.point[1]], ru.t)
    assert "от вашей метки" in far.answer and far.answer.startswith(key.answer)
    # A message with no translation yet stays English, so a language can go live piecemeal.
    q, _ = make(ru, "order", subjects(ru, "order")[0], 4)
    assert q.prompt == "Put these in the order they happened, first at the top."


def test_plural_messages_take_the_languages_form(facts):
    ru = replace(facts, t=RUSSIAN)
    assert [ru.duration(n, "years") for n in (1, 3, 5, 11, 21, 2.5)] == [
        "1 год",
        "3 года",
        "5 лет",
        "11 лет",
        "21 год",
        "2.5 года",
    ]
    assert facts.duration(1, "years") == "1 year" and facts.duration(17, "years") == "17 years"


def test_masking_and_matching_follow_inflected_names():
    text = "Братья продали Иосифа, и Иосифу было семнадцать лет; семья не знала"
    assert (
        mask(text, ["Иосиф"], inflects=True)
        == "Братья продали …, и … было семнадцать лет; семья не знала"
    )
    assert mask(text, ["Иосиф"]) == text  # English names match only whole
    assert mask("Илия и Илии", ["Илия"], inflects=True) == "… и Илии"  # four letters: exact
    assert mask_numbers(text) == "Братья продали Иосифа, и Иосифу было … лет; семья не знала"
    assert mask_numbers("на третий день, в 17 лет") == "на … день, в … лет"

    pool = [("e1", "Фамари"), ("e2", "Иуда"), ("e3", "Онан"), ("e4", "Ир")]
    picked = _distinct(random.Random(0), pool, {"Фамарь"}, inflects=True)
    assert [label for _, label in picked] == ["Иуда", "Онан", "Ир"]

    text_q = Question(
        id="x", kind="cloze", family="hebrew", chapter="c", item="i", format="text", prompt="p"
    )
    key = Key(accept=["Иосифа", "Иосиф"], answer="Иосифа", explanation="")
    assert judge(text_q, key, "иосиф!").correct and judge(text_q, key, "Иосифа").correct
    assert judge(text_q, Key(accept=["Пётр"], answer="Пётр", explanation=""), "петр").correct


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 28, 9, tzinfo=UTC)

    def __call__(self):
        return self.now


def test_spaced_repetition_and_mastery(tmp_path):
    clock = Clock()
    learner = Learner(tmp_path / "l.sqlite", clock=clock)
    record = dict(question_id="q", kind="who", chapter="1KGS.18", item="evt.x", score=1.0)
    intervals = []
    for _ in range(4):
        card = learner.record(**record, correct=True)
        intervals.append(card["interval_days"])
        clock.now += timedelta(days=card["interval_days"])
    assert intervals[:2] == [1.0, 3.0] and intervals[3] > intervals[2] > 3
    missed = learner.record(**record | {"score": 0.0}, correct=False)
    assert missed["interval_days"] == 0 and len(learner.due("1KGS.18")) == 0
    clock.now += timedelta(minutes=11)
    assert [r["card_id"] for r in learner.due("1KGS.18")] == ["who:1KGS.18:evt.x"]

    for _ in range(6):
        card = learner.record(**record, correct=True)
        clock.now += timedelta(days=card["interval_days"])
    progress = learner.progress({"1KGS.18": 4})["1KGS.18"]
    assert card["interval_days"] >= KNOWN_DAYS and progress["known"] == 1
    assert progress["mastery"] == 0.25 and not progress["proven"]

    exam = learner.start_exam("1KGS.18", 2)
    learner.record(**record, correct=True, mode="exam", exam_id=exam)
    learner.record(**record | {"score": 0.7}, correct=True, mode="exam", exam_id=exam)
    assert learner.finish_exam(exam) == {
        "exam_id": exam,
        "chapter": "1KGS.18",
        "score": 0.85,
        "passed": True,
    }
    assert learner.progress({})["1KGS.18"]["proven"]


def test_practice_asks_what_is_due_first_and_exams_mix_every_kind(facts, tmp_path):
    clock = Clock()
    learner = Learner(tmp_path / "l.sqlite", clock=clock)
    first = session(facts, learner, n=6, seed=1)
    assert len(first) == 6 and len({q.kind for q, _ in first}) >= 4
    q, _ = first[0]
    learner.record(
        question_id=q.id, kind=q.kind, chapter=q.chapter, item=q.item, correct=False, score=0
    )
    clock.now += timedelta(minutes=15)
    again = session(facts, learner, n=6, seed=2)
    assert (again[0][0].kind, again[0][0].item) == (q.kind, q.item)

    exam = session(facts, None, mode="exam", n=40, seed=3)
    assert len(exam) == 15 and len({q.family for q, _ in exam}) == 3
    story = session(facts, None, families=("story",), n=8, seed=4)
    assert {q.family for q, _ in story} == {"story"}
    assert facts_count(facts) == len({c.card("1KGS.18") for c in candidates(facts, KINDS)})


def test_retellings_are_graded_against_the_chapter_events(facts):
    event_ids = [e.event_id for e in facts.events]

    def model(prompt: str) -> str:
        assert all(i in prompt for i in event_ids) and "Elijah mocked" in prompt
        reply = {
            "score": 64,
            "covered": [event_ids[0], "evt.not.real", event_ids[0]],
            "missed": [],
            "errors": [
                {"claim": "Ahab built the altar", "correction": "Elijah did", "verse": "1KGS.18.32"}
            ],
            "order_ok": True,
            "feedback": "Good start.",
        }
        return "Here you go:\n" + json.dumps(reply)

    text = (
        "Elijah mocked the prophets of Baal on Carmel, Ahab built the altar and fire fell "
        "from heaven, then the rain came after a long drought and Elijah ran before the chariot."
    )
    result = grade(facts, text, run=model)
    assert result.score == 64 and result.covered == [event_ids[0]]
    assert set(result.missed) == set(event_ids[1:]) and result.errors[0].verse == "1KGS.18.32"
    with pytest.raises(RetellError, match="few sentences"):
        grade(facts, "Elijah won.", run=model)
    with pytest.raises(RetellError, match="not readable"):
        grade(facts, text, run=lambda _: "I cannot grade this.")

    # In another language the grader is asked to answer in it, and to accept a retelling in it.
    assert 'Write "feedback"' not in grading_prompt(facts, text)
    prompt = grading_prompt(facts, "Илия посрамил пророков Ваала на Кармиле.", lang="ru")
    assert re.search(r'Write "feedback", every "claim" and every "correction" in .*\bru\b', prompt)
    assert "Илия посрамил" in prompt and all(i in prompt for i in event_ids)


def test_review_app_serves_quizzes_exams_and_retellings(bundles, tmp_path):
    paths = replace(
        load_paths(), bundles=bundles, runs=tmp_path / "runs", learner=tmp_path / "l.sqlite"
    )
    reply = {
        "score": 80,
        "covered": [],
        "missed": [],
        "errors": [],
        "order_ok": True,
        "feedback": "ok",
    }
    client = TestClient(create_review_app(paths, grader=lambda _: json.dumps(reply)))

    overview = client.get("/api/learn/overview").json()
    row = next(c for c in overview["chapters"] if c["chapter"] == "1KGS.18")
    assert (
        row["facts"] > 50
        and row["mastery"] == 0
        and set(overview["families"]) == {"story", "time_place", "hebrew"}
    )

    exam = client.get("/api/learn/session", params={"chapter": "1KGS.18", "mode": "exam"}).json()
    assert exam["exam_id"] and len(exam["questions"]) == 15
    q = exam["questions"][0]
    wrong = {"choice": "nope", "order": [], "map": [0, 0], "number": -1, "text": "zzz"}[q["format"]]
    answered = client.post(
        "/api/learn/answer",
        json={
            "question_id": q["id"],
            "response": wrong,
            "mode": "exam",
            "exam_id": exam["exam_id"],
        },
    ).json()
    assert (
        answered["correct"] is False
        and answered["answer"]
        and answered["card"]["interval_days"] == 0
    )
    done = client.post(f"/api/learn/exam/{exam['exam_id']}/finish").json()
    assert done["passed"] is False and done["score"] == 0

    bad = client.post("/api/learn/answer", json={"question_id": "nope|1KGS.18|x|1", "response": 1})
    assert bad.status_code == 400
    text = (
        "Elijah calls Israel to Carmel, the prophets of Baal fail, fire falls on the altar, "
        "and the rain returns at last."
    )
    retold = client.post("/api/learn/retell", json={"chapter": "1KGS.18", "text": text}).json()
    assert retold["score"] == 80 and len(retold["missed"]) == len(retold["titles"])
    after = client.get("/api/learn/overview").json()
    row = next(c for c in after["chapters"] if c["chapter"] == "1KGS.18")
    assert row["retell_score"] == 80 and row["exams"] == 1 and row["seen"] == 1
