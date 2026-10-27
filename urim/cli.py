"""urim command line. Paths default to [tool.urim] in pyproject.toml (see urim.config)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from urim.compiler.link import LinkError, Report, link_all, link_core, link_lang, validate
from urim.config import Paths, load_paths

app = typer.Typer(no_args_is_help=True, help="URIM compiler, workbench and runtime.")
link_app = typer.Typer(no_args_is_help=True, help="Link IR into SQLite bundles (no LLM calls).")
ir_app = typer.Typer(no_args_is_help=True, help="Merge session output into the corpus.")
app.add_typer(link_app, name="link")
app.add_typer(ir_app, name="ir")

IrDir = Annotated[Path | None, typer.Option("--ir", help="IR directory [default: corpus]")]
InputsDir = Annotated[
    Path | None, typer.Option("--inputs", help="Ingest output, when the IR has none of its own")
]
BundlesDir = Annotated[Path | None, typer.Option("--bundles", help="Bundles directory")]
Scheme = Annotated[str | None, typer.Option("--chronology", help="Chronology scheme")]
Agent = Annotated[str, typer.Argument(help="chronology, ontology or philology")]


def _paths(
    ir: Path | None = None, inputs: Path | None = None, bundles: Path | None = None
) -> Paths:
    p = load_paths()
    return Paths(
        corpus=ir or p.corpus,
        inputs=inputs or p.inputs,
        bundles=bundles or p.bundles,
        sources=p.sources,
        lockfile=p.lockfile,
        work=p.work,
        runs=p.runs,
        fixtures=p.fixtures,
        review=p.review,
    )


def _fail(message: str) -> typer.Exit:
    typer.secho(f"error: {message}", fg=typer.colors.RED)
    return typer.Exit(1)


def _print_report(name: str, report: Report) -> None:
    for w in report.warnings:
        typer.secho(f"  warn  {name}: {w}", fg=typer.colors.YELLOW)
    typer.secho(f"{name}: ok ({len(report.warnings)} warnings)", fg=typer.colors.GREEN)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LinkError as e:
        for w in e.report.warnings:
            typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
        for err in e.report.errors:
            typer.secho(f"  error {err}", fg=typer.colors.RED)
        raise typer.Exit(1) from e


# --- linking ----------------------------------------------------------------------------------


@link_app.command("core")
def link_core_cmd(
    ir: IrDir = None,
    inputs: InputsDir = None,
    bundles: BundlesDir = None,
    chronology: Scheme = None,
) -> None:
    """Build urim-core.sqlite."""
    p = _paths(ir, inputs, bundles)
    _print_report("core", _run(link_core, p.corpus, p.bundles, chronology, inputs_dir=p.inputs))


@link_app.command("lang")
def link_lang_cmd(
    lang: str, ir: IrDir = None, inputs: InputsDir = None, bundles: BundlesDir = None
) -> None:
    """Build one language bundle against the existing core (core is opened read-only)."""
    p = _paths(ir, inputs, bundles)
    _print_report(lang, _run(link_lang, p.corpus, lang, p.bundles, inputs_dir=p.inputs))


@link_app.command("all")
def link_all_cmd(
    ir: IrDir = None,
    inputs: InputsDir = None,
    bundles: BundlesDir = None,
    chronology: Scheme = None,
) -> None:
    """Build the core and every language bundle found in the IR."""
    p = _paths(ir, inputs, bundles)
    for name, report in _run(
        link_all, p.corpus, p.bundles, chronology, inputs_dir=p.inputs
    ).items():
        _print_report(name, report)


@app.command("validate")
def validate_cmd(ir: IrDir = None, inputs: InputsDir = None, chronology: Scheme = None) -> None:
    """Run the linker's checks without writing anything."""
    p = _paths(ir, inputs)
    report = validate(p.corpus, chronology, inputs_dir=p.inputs)
    for w in report.warnings:
        typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
    for err in report.errors:
        typer.secho(f"  error {err}", fg=typer.colors.RED)
    if report.errors:
        raise typer.Exit(1)
    typer.secho("ok", fg=typer.colors.GREEN)


# --- ingest -----------------------------------------------------------------------------------


@app.command()
def ingest(
    scope: Annotated[str, typer.Argument(help="Book or chapters, e.g. 1KGS.17-19")],
    out: Annotated[Path | None, typer.Option("--out", help="[default: build/ir]")] = None,
    refresh: Annotated[bool, typer.Option(help="Re-download and re-pin sources")] = False,
    commentary: Annotated[bool, typer.Option(help="Fetch Sefaria commentaries")] = True,
) -> None:
    """Fetch pinned sources and write source IR, entity registry and commentary for a scope."""
    from urim.compiler.ingest.build import IngestError
    from urim.compiler.ingest.build import ingest as run_ingest
    from urim.compiler.ingest.fetch import SourceChanged

    p = _paths()
    target = out or p.inputs
    try:
        r = run_ingest(
            scope, target, p.sources, p.lockfile, refresh=refresh, commentaries=commentary
        )
    except (IngestError, SourceChanged) as e:
        raise _fail(str(e)) from e
    for w in r.warnings:
        typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
    typer.echo(f"{r.scope}: {r.verses} verses, {r.tokens} words, {r.verse_map_rows} verse-map rows")
    typer.echo("  baselines:    " + ", ".join(f"{k} {v}" for k, v in r.baselines.items()))
    if r.commentaries:
        typer.echo("  commentaries: " + ", ".join(f"{k} {v}" for k, v in r.commentaries.items()))
    typer.echo(f"  registry:     {r.entities} entities, {r.geocoded} with coordinates")
    typer.secho(f"wrote {target}", fg=typer.colors.GREEN)


# --- workbench --------------------------------------------------------------------------------


@app.command()
def task(
    agent: Agent,
    scope: Annotated[str, typer.Argument(help="1KGS.18 or 1KGS.18.1-12")],
    ir: IrDir = None,
    inputs: InputsDir = None,
) -> None:
    """Write the work packet for one session task."""
    from urim.workbench.packets import TaskError, build_packet, display_path

    try:
        packet = build_packet(agent, scope, _paths(ir, inputs))
    except TaskError as e:
        raise _fail(str(e)) from e
    for w in packet.warnings:
        typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
    typer.echo(f"packet:   {display_path(packet.packet_path)} ({len(packet.text):,} chars)")
    typer.echo(f"fragment: {display_path(packet.fragment_path)}")
    typer.echo(f"schema:   urim schema {agent}")
    typer.echo(f"then:     urim ir merge {display_path(packet.fragment_path)}")


@app.command()
def schema(agent: Agent) -> None:
    """Print the JSON schema of an agent's fragment."""
    from urim.workbench.fragments import FRAGMENT_MODELS

    if agent not in FRAGMENT_MODELS:
        raise _fail(f"unknown agent {agent!r}")
    typer.echo(json.dumps(FRAGMENT_MODELS[agent].model_json_schema(), indent=1))


@ir_app.command("merge")
def ir_merge(
    fragment: Annotated[Path, typer.Argument(help="Fragment JSON written by a session")],
    ir: IrDir = None,
    inputs: InputsDir = None,
    bundles: BundlesDir = None,
    dry_run: Annotated[bool, typer.Option(help="Check only; write nothing")] = False,
    link: Annotated[bool, typer.Option(help="Relink the bundles afterwards")] = True,
) -> None:
    """Check a fragment (schema, ownership, locks, full link) and merge it into the corpus."""
    from urim.workbench.fragments import FragmentError, load_fragment
    from urim.workbench.merge import merge_fragment

    p = _paths(ir, inputs, bundles)
    try:
        frag = load_fragment(fragment)
    except FragmentError as e:
        raise _fail(str(e)) from e
    r = merge_fragment(frag, p.corpus, p.inputs, dry_run=dry_run)
    for w in r.warnings:
        typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
    for err in r.errors:
        typer.secho(f"  error {err}", fg=typer.colors.RED)
    if not r.ok:
        raise typer.Exit(1)
    typer.echo(
        f"{r.agent} {r.chapter_ref}: {len(r.added)} added, {len(r.changed)} changed, "
        f"{len(r.unchanged)} unchanged, {len(r.removed)} removed, "
        f"{len(r.kept_locked)} kept (approved)"
    )
    if r.timeline:
        _print_timeline(r.chapter_ref, r.timeline, r.causes)
    if dry_run:
        typer.secho("dry run: nothing written", fg=typer.colors.GREEN)
        return
    for path in r.written:
        typer.echo(f"  wrote {path}")
    if link:
        _run(link_all, p.corpus, p.bundles, inputs_dir=p.inputs)
        typer.echo(f"  relinked {p.bundles}")
    typer.secho(
        f"merged; review with `urim status` and `urim ledger {r.chapter_ref}`",
        fg=typer.colors.GREEN,
    )


def _print_timeline(chapter: str, rows, causes) -> None:
    from urim.workbench.timeline import span

    typer.echo(f"\ntimeline {chapter} (as linked; check it reads the way the text does):")
    depth: dict[str, int] = {}
    for t in rows:
        depth[t.event_id] = depth.get(t.parent_event_id, -1) + 1 if t.parent_event_id else 0
        pad = "  " * depth[t.event_id]
        typer.echo(
            f"  {pad}{t.start} → {t.end}  {span(t.duration_seconds)} ± {span(t.margin_seconds)}"
            f" (abs ± {span(t.absolute_margin_seconds)})  {t.precision_tier}  {t.verses}"
            f"  {t.event_id}"
        )
        typer.secho(f"  {pad}    from {t.anchor}", dim=True)
    for c in causes:
        typer.echo(f"  {c.causal_id} {c.causal_type}: {span(c.elapsed_seconds)} after the cause")


@app.command()
def timeline(
    chapter: Annotated[str, typer.Argument(help="Chapter, e.g. 1KGS.17")],
    bundles: BundlesDir = None,
) -> None:
    """A chapter's events with the dates the linker gave them."""
    from urim.bundles import core_path
    from urim.workbench.timeline import chapter_timeline

    path = core_path(_paths(bundles=bundles).bundles)
    if not path.exists():
        raise _fail(f"{path} not found: run `urim link all`")
    rows, causes = chapter_timeline(path, chapter)
    if not rows:
        raise _fail(f"no events in {chapter} yet")
    _print_timeline(chapter, rows, causes)


@app.command()
def travel(
    places: Annotated[list[str], typer.Argument(help="Two or more places: loc.carmel, Jezreel")],
    mode: Annotated[str | None, typer.Option(help="Only this mode")] = None,
    detour: Annotated[float, typer.Option(help="Road length over straight line")] = 1.25,
    ir: IrDir = None,
    inputs: InputsDir = None,
) -> None:
    """Journey times between places, for each way of travelling."""
    from urim.workbench.travel import MODES, TravelError, find_place, journey

    p = _paths(ir, inputs)
    if len(places) < 2:
        raise _fail("give at least two places")
    try:
        stops = [find_place(q, p.corpus, p.inputs) for q in places]
        legs = [journey(stops, m, detour) for m in ([mode] if mode else MODES)]
    except TravelError as e:
        raise _fail(str(e)) from e
    route = " → ".join(f"{s.name} ({s.entity_id})" for s in stops)
    first = legs[0]
    typer.echo(f"{route}: {first.straight_km:.0f} km straight, ~{first.route_km:.0f} km by road")
    for leg in legs:
        m = MODES[leg.mode]
        d = leg.ir_duration
        warn = (
            "  (longer than one stint)"
            if leg.mode in ("run", "chariot") and (leg.moving_hours > m.hours_per_day)
            else ""
        )
        typer.echo(
            f"  {leg.mode:8} {m.kmh:>4g} km/h  {leg.moving_hours:5.1f} h moving  "
            f"elapsed ≈ {d['value']:g} {d['unit']}  ({m.note}){warn}"
        )
    typer.echo('IR: "duration": {"value": N, "unit": "hours" | "days"} from the elapsed column')


@app.command()
def status(ir: IrDir = None, inputs: InputsDir = None) -> None:
    """Progress per chapter, and what to do next."""
    from urim.workbench.status import corpus_status, next_steps

    rows = corpus_status(_paths(ir, inputs))
    header = (
        f"{'chapter':10} {'verses':>6} {'events':>6} {'linked':>6} {'onto':>5} "
        f"{'philo':>7} {'✓':>4} {'draft':>5} {'asks':>4} {'notes':>5}"
    )
    typer.echo(header)
    for r in rows:
        typer.echo(
            f"{r.chapter:10} {len(r.verses):>6} {r.events:>6} {r.linked_events:>6} "
            f"{r.ontology_items:>5} {r.philology:>3}/{len(r.verses):<3} {r.approved:>4} "
            f"{r.drafts:>5} {r.requests:>4} {r.notes:>5}"
        )
    steps = next_steps(rows)
    if steps:
        typer.echo("\nnext:")
        for s in steps:
            typer.echo(f"  {s}")


@app.command()
def ledger(chapter: str, ir: IrDir = None) -> None:
    """Every reviewable item of a chapter, with status, producer and agent notes."""
    from urim.workbench.ledger import load_ledger

    led = load_ledger(_paths(ir).corpus, chapter)
    colors = {"approved": typer.colors.GREEN, "changes_requested": typer.colors.RED}
    for k, item in led.items.items():
        typer.secho(f"{item.status:17} {k}", fg=colors.get(item.status))
        typer.echo(
            f"{'':17} by {item.produced_by.model} ({item.produced_by.skill}) at {item.produced_at}"
        )
        for n in item.agent_notes:
            typer.echo(f"{'':17} agent: {n}")
        if note := item.review_note():
            typer.echo(f"{'':17} you {note}")
    for n in led.notes:
        typer.echo(f"note ({n.produced_by.model}, {n.at}): {n.note}")


def _review(keys: list[str], new_status: str, note: str | None, ir: Path | None) -> None:
    from urim.workbench.ledger import LedgerError, set_status

    try:
        changed = set_status(_paths(ir).corpus, keys, new_status, note)
    except LedgerError as e:
        raise _fail(str(e)) from e
    typer.secho(f"{len(changed)} item(s) now {new_status}", fg=typer.colors.GREEN)


@app.command()
def approve(
    keys: Annotated[list[str] | None, typer.Argument(help="Ledger keys, e.g. event:evt.…")] = None,
    chapter: Annotated[str | None, typer.Option(help="Approve every draft in a chapter")] = None,
    kind: Annotated[str | None, typer.Option(help="With --chapter: only this kind")] = None,
    note: str | None = None,
    ir: IrDir = None,
) -> None:
    """Approve items; approved items are locked against later merges."""
    from urim.workbench.ledger import load_ledger

    selected = list(keys or [])
    if chapter:
        led = load_ledger(_paths(ir).corpus, chapter)
        selected += [
            k
            for k, i in led.items.items()
            if i.status == "draft" and (kind is None or k.startswith(f"{kind}:"))
        ]
    if not selected:
        raise _fail("nothing to approve: pass keys or --chapter")
    _review(selected, "approved", note, ir)


@app.command("request-changes")
def request_changes(
    key: str, note: Annotated[str, typer.Option(help="What should change")], ir: IrDir = None
) -> None:
    """Send an item back; the next packet for its chapter shows your note first."""
    _review([key], "changes_requested", note, ir)


@app.command()
def reopen(key: str, note: str | None = None, ir: IrDir = None) -> None:
    """Unlock an approved item so a session may change it again."""
    _review([key], "draft", note, ir)


# --- review app -------------------------------------------------------------------------------


@app.command()
def review(
    demo: Annotated[
        bool, typer.Option(help="Use a demo corpus built from the gold fixture")
    ] = False,
    rebuild_demo: Annotated[bool, typer.Option(help="Rebuild the demo corpus first")] = False,
    host: str = "127.0.0.1",
    port: int = 8765,
    ir: IrDir = None,
    inputs: InputsDir = None,
    bundles: BundlesDir = None,
) -> None:
    """Open the review game: link the corpus, then serve the API and the built frontend."""
    import uvicorn

    from urim.review.demo import ensure_demo
    from urim.review.server import create_review_app

    p = _paths(ir, inputs, bundles)
    if demo or rebuild_demo:
        p = ensure_demo(p, rebuild=rebuild_demo)
        typer.echo(f"demo corpus: {p.corpus}")
    else:
        _run(link_all, p.corpus, p.bundles, inputs_dir=p.inputs)
    dist = p.review / "dist"
    if not dist.exists():
        typer.secho(
            f"no frontend build at {dist}: run `npm --prefix {p.review} install` and "
            f"`npm --prefix {p.review} run build` (API only for now)",
            fg=typer.colors.YELLOW,
        )
    typer.secho(f"War Room (review):   http://{host}:{port}", fg=typer.colors.GREEN)
    typer.secho(f"Illuminated Codex:   http://{host}:{port}/codex", fg=typer.colors.GREEN)
    uvicorn.run(
        create_review_app(p, static_dir=dist, demo=demo or rebuild_demo),
        host=host,
        port=port,
        log_level="warning",
    )


@app.command()
def basemap() -> None:
    """Rebuild the Atlas basemap from pinned Natural Earth data."""
    from urim.compiler.ingest.fetch import Fetcher
    from urim.review.basemap import build_basemap

    p = _paths()
    out = p.review / "public" / "geo" / "near_east.json"
    with Fetcher(p.sources, p.lockfile) as fetcher:
        stats = build_basemap(fetcher, out)
    typer.secho(f"wrote {out}: {stats}", fg=typer.colors.GREEN)


# --- runtime ----------------------------------------------------------------------------------


@app.command()
def verse(ref: str, lang: str = "en", bundles: BundlesDir = None, ecs: bool = False) -> None:
    """Print one verse matrix as JSON."""
    from urim.runtime.engine import UrimEngine

    m = UrimEngine(_paths(bundles=bundles).bundles).get_verse_matrix(
        ref, lang=lang, include_ecs=ecs
    )
    typer.echo(json.dumps(m.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command()
def serve(bundles: BundlesDir = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the REST API."""
    import uvicorn

    from urim.interfaces.rest_api import create_app

    uvicorn.run(create_app(_paths(bundles=bundles).bundles), host=host, port=port)


@app.command()
def mcp(bundles: BundlesDir = None) -> None:
    """Run the MCP server over stdio."""
    from urim.interfaces.mcp_server import create_server

    create_server(_paths(bundles=bundles).bundles).run()
