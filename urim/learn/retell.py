"""Retelling a chapter in your own words, checked by Claude against the chapter's events.

The one kind of quiz that needs a model while you study: free recall has no key a program
can match. The grader sees the events the corpus holds for the chapter (titles, summaries,
verses) and your text, and says which scenes you told, which you missed, and which of your
claims the text contradicts. It runs as a headless Claude Code session on your subscription.
You retell in the language you study in, and the grader answers in it.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable

from pydantic import BaseModel, Field, ValidationError

from urim.learn.quiz import Facts

GRADER_MODEL = "claude-sonnet-5-5"
NO_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Task")


class Contradiction(BaseModel):
    claim: str = Field(description="What the retelling says, quoted or paraphrased")
    correction: str = Field(description="What the text says instead")
    verse: str | None = Field(default=None, description="Verse id, e.g. GEN.37.28")


class RetellResult(BaseModel):
    score: int = Field(ge=0, le=100)
    covered: list[str] = []
    missed: list[str] = []
    errors: list[Contradiction] = []
    order_ok: bool = True
    feedback: str = ""


class RetellError(RuntimeError):
    pass


def _language(f: Facts, lang: str) -> str:
    """The language's name for the grader, as its bundle gives it: "Русский (ru)"."""
    if lang == "en":
        return "English"
    name = next((x.lang_name for x in f.engine.languages() if x.lang_code == lang), None)
    return f"{name} ({lang})" if name else lang


def grading_prompt(f: Facts, text: str, lang: str | None = None) -> str:
    lang = lang or f.lang
    language = _language(f, lang)
    events = "\n".join(
        f"- {e.event_id} ({f.ref(e.verse_start, e.verse_end)}): {e.title}. "
        f"{e.narrative_summary or ''}"
        for e in sorted(f.events, key=lambda e: e.verse_start)
    )
    chapter = f.ref(f.chapter + ".1").rsplit(":", 1)[0]
    in_language = (
        ""
        if lang == "en"
        else f"""
The student studies in {language} and writes the retelling in it. Some events may be given in \
English where the corpus has no {language} text yet; judge the retelling against them all \
the same. Write "feedback", every "claim" and every "correction" in {language}.
"""
    )
    return f"""You grade a student's retelling of {chapter} from memory. Judge it only against \
these events, which are the chapter's content in the order the text tells them:

{events}
{in_language}
The student's retelling:
<<<
{text.strip()}
>>>

Answer with one JSON object and nothing else:
{{"score": 0-100, "covered": [event ids the retelling tells, even briefly or in other words],
"missed": [event ids it leaves out], "errors": [{{"claim": "...", "correction": "...",
"verse": "GEN.37.28"}}], "order_ok": true if the scenes come in the text's order,
"feedback": "two or three sentences to the student, plain and encouraging"}}

Score coverage of the important scenes most, then accuracy (names, places, who did what),
then order. Paraphrase is fine; a wrong name or a reversed deed is an error. Do not count
interpretation or style against the student."""


def _claude(prompt: str, *, claude: str = "claude", model: str = GRADER_MODEL) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE")}
    try:
        done = subprocess.run(
            [
                claude,
                "-p",
                prompt,
                "--model",
                model,
                "--output-format",
                "json",
                "--disallowedTools",
                *NO_TOOLS,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RetellError(f"the grader did not run: {e}") from e
    try:
        out = json.loads(done.stdout)
    except json.JSONDecodeError as e:
        raise RetellError((done.stderr or done.stdout or "no output").strip()[-500:]) from e
    if out.get("is_error"):
        raise RetellError(str(out.get("result") or "the grader failed")[-500:])
    return out.get("result") or ""


def grade(
    f: Facts, text: str, run: Callable[[str], str] | None = None, lang: str | None = None
) -> RetellResult:
    """Grade a retelling written in `lang` (the facts' language by default); the feedback
    comes back in it."""
    if len(text.split()) < 15:
        raise RetellError(f.t("quiz.retell.too_short"))
    reply = (run or _claude)(grading_prompt(f, text, lang))
    start, end = reply.find("{"), reply.rfind("}")
    try:
        result = RetellResult.model_validate_json(reply[start : end + 1])
    except ValidationError as e:
        raise RetellError(f.t("quiz.retell.unreadable", reply=reply[:300])) from e
    known = {e.event_id for e in f.events}
    result.covered = [i for i in dict.fromkeys(result.covered) if i in known]
    result.missed = [i for i in known - set(result.covered)]
    result.missed.sort(key=lambda i: next(e.verse_start for e in f.events if e.event_id == i))
    return result
