"""Project paths, configurable under [tool.urim] in pyproject.toml.

corpus   committed IR written by agents and reviewed by you
inputs   regenerated ingest output (source/, registry/, commentary/)
bundles  linked SQLite bundles
sources  download cache; lockfile pins it
work     task packets and fragments (scratch, not committed)
runs     comparison runs, one corpus per model
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    corpus: Path = Path("corpus")
    inputs: Path = Path("build/ir")
    bundles: Path = Path("data/bundles")
    sources: Path = Path("data/sources")
    lockfile: Path = Path("sources.lock.json")
    work: Path = Path("work")
    runs: Path = Path("runs")


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
        return Paths(**values)
    return Paths()
