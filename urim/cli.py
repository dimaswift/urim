"""urim command line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from urim.compiler.link import LinkError, Report, link_all, link_core, link_lang, validate

app = typer.Typer(no_args_is_help=True, help="URIM compiler and runtime.")
link_app = typer.Typer(no_args_is_help=True, help="Link IR into SQLite bundles (no LLM calls).")
app.add_typer(link_app, name="link")

IrDir = Annotated[Path, typer.Option("--ir", help="IR directory")]
BundlesDir = Annotated[Path, typer.Option("--bundles", help="Bundles directory")]
Scheme = Annotated[str | None, typer.Option("--chronology", help="Chronology scheme")]


def _print_report(name: str, report: Report) -> None:
    for w in report.warnings:
        typer.secho(f"  warn  {name}: {w}", fg=typer.colors.YELLOW)
    typer.secho(f"{name}: ok ({len(report.warnings)} warnings)", fg=typer.colors.GREEN)


def _run(fn, *args):
    try:
        return fn(*args)
    except LinkError as e:
        for w in e.report.warnings:
            typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
        for err in e.report.errors:
            typer.secho(f"  error {err}", fg=typer.colors.RED)
        raise typer.Exit(1) from e


@link_app.command("core")
def link_core_cmd(
    ir: IrDir = Path("fixtures/ir"),
    bundles: BundlesDir = Path("data/bundles"),
    chronology: Scheme = None,
) -> None:
    """Build urim-core.sqlite."""
    _print_report("core", _run(link_core, ir, bundles, chronology))


@link_app.command("lang")
def link_lang_cmd(
    lang: str, ir: IrDir = Path("fixtures/ir"), bundles: BundlesDir = Path("data/bundles")
) -> None:
    """Build one language bundle against the existing core (core is opened read-only)."""
    _print_report(lang, _run(link_lang, ir, lang, bundles))


@link_app.command("all")
def link_all_cmd(
    ir: IrDir = Path("fixtures/ir"),
    bundles: BundlesDir = Path("data/bundles"),
    chronology: Scheme = None,
) -> None:
    """Build the core and every language bundle found in the IR."""
    for name, report in _run(link_all, ir, bundles, chronology).items():
        _print_report(name, report)


@app.command("validate")
def validate_cmd(ir: IrDir = Path("fixtures/ir"), chronology: Scheme = None) -> None:
    """Run the linker's checks without writing anything."""
    report = validate(ir, chronology)
    for w in report.warnings:
        typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
    for err in report.errors:
        typer.secho(f"  error {err}", fg=typer.colors.RED)
    if report.errors:
        raise typer.Exit(1)
    typer.secho("ok", fg=typer.colors.GREEN)


@app.command()
def ingest(
    scope: Annotated[str, typer.Argument(help="Book or chapters, e.g. 1KGS.17-19")],
    ir: IrDir = Path("build/ir"),
    sources: Annotated[Path, typer.Option("--sources", help="Download cache")] = Path(
        "data/sources"
    ),
    lockfile: Annotated[Path, typer.Option("--lock", help="Source pins")] = Path(
        "sources.lock.json"
    ),
    refresh: Annotated[bool, typer.Option(help="Re-download and re-pin sources")] = False,
    commentary: Annotated[bool, typer.Option(help="Fetch Sefaria commentaries")] = True,
) -> None:
    """Fetch pinned sources and write source IR, entity registry and commentary for a scope."""
    from urim.compiler.ingest.build import IngestError
    from urim.compiler.ingest.build import ingest as run_ingest
    from urim.compiler.ingest.fetch import SourceChanged

    try:
        r = run_ingest(scope, ir, sources, lockfile, refresh=refresh, commentaries=commentary)
    except (IngestError, SourceChanged) as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e
    for w in r.warnings:
        typer.secho(f"  warn  {w}", fg=typer.colors.YELLOW)
    typer.echo(f"{r.scope}: {r.verses} verses, {r.tokens} words, {r.verse_map_rows} verse-map rows")
    typer.echo("  baselines:    " + ", ".join(f"{k} {v}" for k, v in r.baselines.items()))
    if r.commentaries:
        typer.echo("  commentaries: " + ", ".join(f"{k} {v}" for k, v in r.commentaries.items()))
    typer.echo(f"  registry:     {r.entities} entities, {r.geocoded} with coordinates")
    typer.secho(f"wrote {ir}", fg=typer.colors.GREEN)


@app.command()
def verse(
    ref: str, lang: str = "en", bundles: BundlesDir = Path("data/bundles"), ecs: bool = False
) -> None:
    """Print one verse matrix as JSON."""
    from urim.runtime.engine import UrimEngine

    m = UrimEngine(bundles).get_verse_matrix(ref, lang=lang, include_ecs=ecs)
    typer.echo(json.dumps(m.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command()
def serve(
    bundles: BundlesDir = Path("data/bundles"), host: str = "127.0.0.1", port: int = 8000
) -> None:
    """Serve the REST API."""
    import uvicorn

    from urim.interfaces.rest_api import create_app

    uvicorn.run(create_app(bundles), host=host, port=port)


@app.command()
def mcp(bundles: BundlesDir = Path("data/bundles")) -> None:
    """Run the MCP server over stdio."""
    from urim.interfaces.mcp_server import create_server

    create_server(bundles).run()
