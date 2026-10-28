import hashlib
import json
import math
import re
import shutil
import struct
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


class BagOfWords:
    """Words hashed into 64 dimensions: texts that share words point the same way."""

    dims = 64

    def __init__(self, model_id: str = "bag-of-words@1"):
        self.model_id = model_id
        self.embedded = 0

    def embed(self, texts):
        self.embedded += len(texts)
        out = []
        for text in texts:
            v = [0.0] * self.dims
            for word in re.findall(r"\w+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dims] += 1
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append(struct.pack(f"<{self.dims}f", *(x / norm for x in v)))
        return out
