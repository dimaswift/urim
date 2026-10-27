"""On-disk bundle layout, shared by the linker and the runtime.

{bundles_dir}/urim-core.sqlite
{bundles_dir}/lang-{iso}/i18n_{iso}.sqlite
{bundles_dir}/lang-{iso}/manifest.json
"""

from __future__ import annotations

from pathlib import Path

CORE_FILENAME = "urim-core.sqlite"


def core_path(bundles_dir: Path) -> Path:
    return Path(bundles_dir) / CORE_FILENAME


def lang_bundle_path(bundles_dir: Path, lang: str) -> Path:
    return Path(bundles_dir) / f"lang-{lang}" / f"i18n_{lang}.sqlite"


def discover_langs(bundles_dir: Path) -> dict[str, Path]:
    found = {}
    for d in sorted(Path(bundles_dir).glob("lang-*")):
        lang = d.name.removeprefix("lang-")
        if (p := lang_bundle_path(bundles_dir, lang)).exists():
            found[lang] = p
    return found


def sqlite_uri(path: Path, *, immutable: bool = False) -> str:
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    return uri + "&immutable=1" if immutable else uri
