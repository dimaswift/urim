"""Read an IR directory into validated models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from urim.ir.models import (
    ChronologyIR,
    CoreChapterIR,
    I18nBundleIR,
    I18nChapterIR,
    RegistryIR,
    SourceBookIR,
)


class IRLoadError(ValueError):
    pass


def read_model[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        return model.model_validate_json(path.read_bytes())
    except ValidationError as e:
        raise IRLoadError(f"{path}: {e}") from e


@dataclass
class CoreCorpus:
    sources: list[SourceBookIR]
    chronology: ChronologyIR
    chapters: list[CoreChapterIR]
    registry: RegistryIR | None = None


def inputs_root(ir_dir: Path, inputs_dir: Path | None = None) -> Path:
    """Where ingest output (source/, registry/, commentary/) lives.

    A self-contained IR directory (the gold fixture) carries its own; the working corpus reads
    them from the regenerated ingest directory instead.
    """
    ir_dir = Path(ir_dir)
    if inputs_dir is None or (ir_dir / "source").is_dir():
        return ir_dir
    return Path(inputs_dir)


def load_sources(root: Path) -> list[SourceBookIR]:
    return [read_model(p, SourceBookIR) for p in sorted((Path(root) / "source").glob("*.json"))]


def load_registry(root: Path) -> RegistryIR | None:
    path = Path(root) / "registry" / "entities.json"
    return read_model(path, RegistryIR) if path.exists() else None


def load_core_corpus(ir_dir: Path, inputs_dir: Path | None = None) -> CoreCorpus:
    ir_dir = Path(ir_dir)
    if not (ir_dir / "chronology.json").exists():
        raise IRLoadError(f"{ir_dir} has no chronology.json; is it an IR directory?")
    root = inputs_root(ir_dir, inputs_dir)
    return CoreCorpus(
        sources=load_sources(root),
        chronology=read_model(ir_dir / "chronology.json", ChronologyIR),
        chapters=[read_model(p, CoreChapterIR) for p in sorted((ir_dir / "core").glob("*.json"))],
        registry=load_registry(root),
    )


def available_langs(ir_dir: Path) -> list[str]:
    root = Path(ir_dir) / "i18n"
    return sorted(p.name for p in root.iterdir() if (p / "_bundle.json").exists())


def load_i18n(ir_dir: Path, lang: str) -> tuple[I18nBundleIR, list[I18nChapterIR]]:
    root = Path(ir_dir) / "i18n" / lang
    if not (root / "_bundle.json").exists():
        raise IRLoadError(f"no language bundle IR at {root}")
    bundle = read_model(root / "_bundle.json", I18nBundleIR)
    if bundle.lang_code != lang:
        raise IRLoadError(f"{root}/_bundle.json declares lang_code {bundle.lang_code!r}")
    chapters = [
        read_model(p, I18nChapterIR)
        for p in sorted(root.glob("*.json"))
        if p.name != "_bundle.json"
    ]
    return bundle, chapters


def write_model(path: Path, model: BaseModel) -> None:
    """Write IR as stable, diff-friendly JSON (no nulls, one-space indent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = model.model_dump(mode="json", exclude_none=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
