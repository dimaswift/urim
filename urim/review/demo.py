"""A demo corpus for the review app, built from the gold fixture through the real workbench.

It lives under runs/demo/ and never touches corpus/. Chapter 17 is fully approved, part of 18 is
approved, one item carries a change request, and the rest waits in the review deck.
"""

from __future__ import annotations

import shutil

from urim.compiler.link import link_all
from urim.config import Paths
from urim.ir.load import read_model, write_model
from urim.ir.models import I18nChapterIR
from urim.workbench import gold
from urim.workbench.fragments import ReviewerNote
from urim.workbench.ledger import load_ledger, set_status
from urim.workbench.merge import merge_fragment

CHAPTERS = ("1KGS.17", "1KGS.18", "1KGS.19")


def demo_paths(paths: Paths) -> Paths:
    root = paths.runs / "demo"
    return Paths(
        corpus=root / "corpus",
        inputs=paths.fixtures,
        bundles=root / "bundles",
        sources=paths.sources,
        lockfile=paths.lockfile,
        work=root / "work",
        runs=paths.runs,
        fixtures=paths.fixtures,
    )


def build_demo(paths: Paths) -> Paths:
    demo = demo_paths(paths)
    if demo.corpus.exists():
        shutil.rmtree(demo.corpus)
    demo.corpus.mkdir(parents=True)
    shutil.copy(paths.fixtures / "chronology.json", demo.corpus / "chronology.json")
    for lang in ("en", "ru"):
        (demo.corpus / "i18n" / lang).mkdir(parents=True)
        shutil.copy(
            paths.fixtures / "i18n" / lang / "_bundle.json",
            demo.corpus / "i18n" / lang / "_bundle.json",
        )

    fragments = [gold.chronology(c, paths.fixtures) for c in CHAPTERS]
    fragments += [gold.ontology(c, paths.fixtures) for c in CHAPTERS]
    fragments += [gold.philology(c, paths.fixtures) for c in ("1KGS.18", "1KGS.19")]
    fragments[1].reviewer_notes = [
        ReviewerNote(
            item="evt.1kgs_18.chariot_run_to_jezreel",
            note="2.5 h assumes ~10-12 km/h through mud; a dry road would be ~2 h.",
        ),
        ReviewerNote(
            item="evt.1kgs_18.carmel_contest",
            note="Dawn start inferred from 'from morning until noon' (18:26).",
        ),
    ]
    fragments[5].reviewer_notes = [
        ReviewerNote(
            item="loc.mount_horeb",
            note="Location disputed: Jebel Musa vs north-west Arabia; kept TIPNR/OpenBible.",
        ),
    ]
    for f in fragments:
        result = merge_fragment(f, demo.corpus, demo.inputs)
        if not result.ok:
            raise RuntimeError(f"demo merge failed for {f.agent} {f.chapter_ref}: {result.errors}")

    # Russian texts ride along as-is (localization is a later phase).
    for c in CHAPTERS:
        src = paths.fixtures / "i18n" / "ru" / f"{c}.json"
        if src.exists():
            write_model(demo.corpus / "i18n" / "ru" / f"{c}.json", read_model(src, I18nChapterIR))

    set_status(demo.corpus, list(load_ledger(demo.corpus, "1KGS.17").items), "approved")
    chapter18 = load_ledger(demo.corpus, "1KGS.18").items
    set_status(
        demo.corpus, [k for k in chapter18 if k.startswith(("event:", "causal:"))], "approved"
    )
    set_status(
        demo.corpus,
        ["entity:loc.kishon_brook"],
        "changes_requested",
        "OpenBible puts Kishon at the river mouth; the executions were near Carmel's "
        "foot. Consider an IR override.",
    )
    link_all(demo.corpus, demo.bundles, inputs_dir=demo.inputs)
    return demo


def ensure_demo(paths: Paths, rebuild: bool = False) -> Paths:
    demo = demo_paths(paths)
    if rebuild or not (demo.corpus / "ledger").exists():
        return build_demo(paths)
    return demo
