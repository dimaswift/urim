"""Project paths, configurable under [tool.urim] in pyproject.toml.

corpus   committed IR written by agents and reviewed by you
inputs   regenerated ingest output (source/, registry/, commentary/)
bundles  linked SQLite bundles
sources  download cache; lockfile pins it
cache    regenerable caches (embedding vectors by text hash)
work     task packets and fragments (scratch, not committed)
runs     comparison runs, one corpus per model; also the review demo
fixtures the hand-written gold IR (benchmark)
review   the review app (frontend sources; built into review/dist)
learner  your quiz answers and mastery (personal, not committed)

Each can also be set with an environment variable, URIM_CORPUS, URIM_BUNDLES and so on, which
wins over pyproject.toml: a run's sessions inherit it, so a whole run can target a scratch
corpus.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    corpus: Path = Path("corpus")
    inputs: Path = Path("build/ir")
    bundles: Path = Path("data/bundles")
    sources: Path = Path("data/sources")
    cache: Path = Path("data/cache")
    lockfile: Path = Path("sources.lock.json")
    work: Path = Path("work")
    runs: Path = Path("runs")
    fixtures: Path = Path("fixtures/ir")
    review: Path = Path("review")
    learner: Path = Path("data/learner.sqlite")


def load_paths(start: Path | None = None) -> Paths:
    """Paths from the nearest pyproject.toml with a [tool.urim] table, relative to it."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        pyproject = directory / "pyproject.toml"
        if not pyproject.exists():
            continue
        table = tomllib.loads(pyproject.read_text()).get("tool", {}).get("urim")
        if table is None:
            continue
        values = {
            f.name: directory / table.get(f.name, getattr(Paths, f.name)) for f in fields(Paths)
        }
        return _from_env(Paths(**values))
    return _from_env(Paths())


def _from_env(paths: Paths) -> Paths:
    env = {f.name: os.environ.get(f"URIM_{f.name.upper()}") for f in fields(Paths)}
    return replace(paths, **{k: Path(v).resolve() for k, v in env.items() if v})
