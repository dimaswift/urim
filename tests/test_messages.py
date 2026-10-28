"""Interface messages: the English catalog is whole and every key the apps ask for exists, so a
translator can rely on it and no screen shows a bare key."""

import re
from pathlib import Path

from urim.i18n.messages import ENGLISH, Translator, english, fill

SRC = Path(__file__).resolve().parent.parent / "review" / "src"
_USE = re.compile(
    r"""(?:\bt|\btr)\(\s*["']([a-z][a-z0-9_.]+)["']|<Msg\s+k=["']([a-z][a-z0-9_.]+)["']"""
)


def used_keys() -> dict[str, str]:
    out = {}
    for path in SRC.rglob("*.ts*"):
        for m in _USE.finditer(path.read_text(encoding="utf-8")):
            out[m[1] or m[2]] = path.name
    return out


def test_every_key_the_apps_use_has_english():
    catalog = english()
    missing = {k: f for k, f in used_keys().items() if k not in catalog}
    assert not missing, missing


def test_plural_forms_are_whole_and_agree_on_placeholders():
    for k, s in english().items():
        assert k.startswith(s.namespace + ".") or s.namespace in ("common", "morph", "server"), k
        if s.forms is None:
            assert s.text is not None, k
            continue
        assert "other" in s.forms, k
        texts = list(s.forms.values())
        names = [set(re.findall(r"\{(\w+)\}", t)) - {"count"} for t in texts]
        assert all(n == names[0] for n in names), k


def test_translators_fall_back_to_english_and_fill_placeholders():
    plural = next(k for k, s in english().items() if s.forms)
    assert Translator("ru", {})(plural, count=2) == ENGLISH(plural, count=2)
    assert fill("{a} and {b}", {"a": 1}) == "1 and {b}"
    assert ENGLISH("no.such.message") == "no.such.message"
