import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from urim.compiler.link import link_all
from urim.runtime.engine import UrimEngine

FIXTURE_IR = Path(__file__).resolve().parent.parent / "fixtures" / "ir"


@pytest.fixture(scope="session")
def bundles(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bundles")
    link_all(FIXTURE_IR, out)
    return out


@pytest.fixture(scope="session")
def engine(bundles) -> UrimEngine:
    return UrimEngine(bundles)


@pytest.fixture
def ir_copy(tmp_path) -> Path:
    dst = tmp_path / "ir"
    shutil.copytree(FIXTURE_IR, dst)
    return dst


def edit_json(path: Path, fn: Callable[[dict], None]) -> None:
    doc = json.loads(path.read_text())
    fn(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False))
