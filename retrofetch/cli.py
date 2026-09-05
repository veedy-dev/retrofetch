from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

import typer
from rich.console import Console

from retrofetch import __version__, _resources
from retrofetch.config import (
    Config,
    ConfigError,
    _yaml_rt,
    default_library_root,
    load_config,
    load_overrides,
)
from retrofetch.dat import parse_dat, verify_file
from retrofetch.dat_fetch import bootstrap_dats, find_dat_for_console
from retrofetch.events import (
    CloudflareBlockEvent,
    DatLoadDoneEvent,
    DatLoadStartEvent,
    EventBus,
    ExtractionDoneEvent,
    ExtractionStartEvent,
    GameDoneEvent,
    GameFailedEvent,
    GameStartEvent,
    ProgressEvent,
    RateLimitEvent,
    SourceDeadEvent,
)
from retrofetch.handheld import app as handheld_app
from retrofetch.logging_setup import setup_logging
from retrofetch.orchestrator import run_console
from retrofetch.ranker import get_wantlist, resolve_download_set
from retrofetch.report import generate_coverage_report
from retrofetch.signals import install_signal_handlers
from retrofetch.sources import SourceUnavailable
from retrofetch.sources.bios import BiosSource
from retrofetch.state import load_state, save_state, update_game
from retrofetch.ui import console

_log = logging.getLogger(__name__)

app = typer.Typer(name="retrofetch", add_completion=False)
app.add_typer(handheld_app, name="handheld")

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_DIR = _PACKAGE_DIR.parent


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"retrofetch {__version__}")
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _load_consoles(consoles_path: Path) -> dict[str, Any]:
    if not consoles_path.exists():
        raise ConfigError(
            f"consoles.yml not found at {consoles_path}. "
            "Ensure you are running from the retrofetch project root or run 'retrofetch init'."
        )
    data = _yaml_rt.load(consoles_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(
            f"consoles.yml root must be a mapping, got {type(data).__name__}"
        )
    return data


def _resolve_config(config_path: Path) -> Config:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(2) from exc


def _resolve_console_entry(
    consoles: dict[str, Any], shortname: str
) -> dict[str, Any] | None:
    entries: list[dict[str, Any]] = consoles.get("consoles", []) or []
    for entry in entries:
        if entry.get("shortname") == shortname:
            return entry
    return None


def _verbose_formatter(cons: Console) -> Callable[[ProgressEvent], None]:
    def _on(event: ProgressEvent) -> None:
        if isinstance(event, GameStartEvent):
            cons.print(f"[cyan]-> Starting {event.game} from {event.source}[/cyan]")
        elif isinstance(event, GameDoneEvent):
            sha1_str = f"{event.sha1[:8]}..." if event.sha1 else "sha1=?"
            cons.print(
                f"[green][OK] Acquired {event.game} "
                f"({event.size} bytes, {sha1_str})[/green]"
            )
        elif isinstance(event, GameFailedEvent):
            cons.print(f"[red][X] Failed {event.game}: {event.reason}[/red]")
        elif isinstance(event, SourceDeadEvent):
            cons.print(f"[yellow]! Source {event.source} dead: {event.reason}[/yellow]")
        elif isinstance(event, RateLimitEvent):
            cons.print(
                f"[yellow]! Rate-limited on {event.source}, "
                f"retry in {event.retry_after}s[/yellow]"
            )
        elif isinstance(event, CloudflareBlockEvent):
            cons.print(
                f"[yellow]! Cloudflare blocked {event.source} "
                f"(status={event.status})[/yellow]"
            )
        elif isinstance(event, DatLoadStartEvent):
            cons.print(
                f"[dim]... Loading DAT for {event.console}: {event.dat_name}[/dim]"
            )
        elif isinstance(event, DatLoadDoneEvent):
            if event.detail:
                cons.print(f"[yellow]... {event.detail}[/yellow]")
            else:
                cons.print(
                    f"[dim]... DAT loaded for {event.console}: "
                    f"{event.games_loaded} games[/dim]"
                )
        elif isinstance(event, ExtractionStartEvent):
            cons.print(f"[dim]... Extracting {event.filename} ({event.format})[/dim]")
        elif isinstance(event, ExtractionDoneEvent):
            cons.print(f"[dim]... Extracted to {event.extracted_to}[/dim]")

    return _on


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files"),
) -> None:
    """Create config.yml, overrides.yml, .env.example, and bootstrap dats/ layout."""

    targets = {
        "config.yml": _resources.find_data_file("config.yml.example"),
        "overrides.yml": _resources.find_data_file("overrides.yml.example"),
        ".env.example": _resources.find_data_file(".env.example"),
    }
    for dest_name, example_path in targets.items():
        dest = Path.cwd() / dest_name
        if dest.exists() and not force:
            console.print(f"[yellow]skip[/yellow] {dest_name} already exists")
            continue
        if not example_path.exists():
            console.print(
                f"[yellow]warn[/yellow] {example_path} not found; skipping {dest_name}"
            )
            continue
        shutil.copyfile(example_path, dest)
        console.print(f"[green]created[/green] {dest_name}")

    dats_dir = Path.cwd() / "dats"
    bootstrap_dats(dats_dir)
    console.print(f"[green]ensured[/green] {dats_dir}/ structure")

    consoles_src = _resources.find_data_file("consoles.yml")
    consoles_dst = Path.cwd() / "consoles.yml"
    if consoles_src.exists() and not consoles_dst.exists():
        shutil.copyfile(consoles_src, consoles_dst)
        console.print("[green]created[/green] consoles.yml")


@app.command()
def download(
    console_name: Optional[str] = typer.Option(
        None,
        "--console",
        help="Single console shortname (e.g. virtualboy). Omit to process all.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Max games per console (overrides config.default_limit)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print game list without downloading"
    ),
    no_torrent: bool = typer.Option(
        False, "--no-torrent", help="Skip qBittorrent/torrent sources for this run"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print per-game event lines during download (uses event bus).",
    ),
    config_path: Path = typer.Option(
        Path("config.yml"), "--config", help="Path to config.yml"
    ),
) -> None:
    """Download ROMs for one or all consoles."""

    config = _resolve_config(config_path)
    config.dry_run = dry_run
    setup_logging(config.log_file)
    consoles_yml_path = Path.cwd() / "consoles.yml"
    if not consoles_yml_path.exists():
        consoles_yml_path = _resources.find_data_file("consoles.yml")
    try:
        consoles_yml = _load_consoles(consoles_yml_path)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    try:
        overrides = load_overrides(Path("overrides.yml"))
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    entries: list[dict[str, Any]]
    if console_name:
        entry = _resolve_console_entry(consoles_yml, console_name)
        if entry is None:
            console.print(f"[red]Unknown console: {console_name}[/red]")
            raise typer.Exit(2)
        entries = [entry]
    else:
        entries = list(consoles_yml.get("consoles", []) or [])

    bus: EventBus | None = None
    if verbose:
        bus = EventBus()
        bus.subscribe(_verbose_formatter(console))

    exit_code = 0
    for entry in entries:
        short: str = str(entry.get("shortname", "?"))
        klass: str = str(entry.get("class", "?"))
        if klass in ("D", "E", "F"):
            console.print(
                f"[dim]SKIPPED: {short} (Class {klass}: "
                f"{entry.get('skip_reason') or 'out of scope'})[/dim]"
            )
            continue

        override = overrides.get(short)
        per_limit = limit
        if per_limit is None and override is not None and override.limit is not None:
            per_limit = override.limit
        if per_limit is None:
            per_limit = config.default_limit

        ranked_titles = get_wantlist(
            console_entry=entry,
            overrides=override,
            config=config,
            limit=per_limit,
        )
        wantlist = resolve_download_set(ranked_titles, override, per_limit)

        console.print(
            f"[cyan]Console:[/cyan] {short} (Class {klass}) - selected: {len(wantlist)} games"
        )
        for title in wantlist[:5]:
            console.print(f"  - {title}")
        if len(wantlist) > 5:
            console.print(f"  ... and {len(wantlist) - 5} more")

        coordinator = install_signal_handlers()
        report = run_console(
            console_entry=entry,
            wantlist=wantlist,
            config=config,
            allow_torrent=not no_torrent,
            consoles_yml=consoles_yml,
            stop_event=coordinator.stop_event,
            event_bus=bus,
            dry_run=config.dry_run,
        )
        if not dry_run:
            if report.error:
                console.print(f"[red]{short} error:[/red] {report.error}")
                exit_code = 1
            else:
                console.print(
                    f"[green]{short}:[/green] attempted={report.attempted} "
                    f"acquired={report.acquired} failed={report.failed} "
                    f"unverified={report.unverified} cancelled={report.cancelled}"
                )
                if report.failed:
                    exit_code = 1
        if coordinator.stop_event.is_set():
            console.print("[yellow]stopped by signal; rerun to resume[/yellow]")
            exit_code = 130
            break

    if not dry_run:
        coverage = generate_coverage_report(
            consoles_yml_path, config.roms_root, Path.cwd() / "coverage.md"
        )
        console.print(f"[green]Report:[/green] {coverage}")
        if exit_code:
            raise typer.Exit(exit_code)


@app.command()
def bios(
    console_name: str = typer.Option(
        ..., "--console", help="Console shortname (e.g. psx, ps2, saturn)"
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Limit BIOS files for a small probe run; default downloads all listed files.",
    ),
    config_path: Path = typer.Option(Path("config.yml"), "--config"),
) -> None:
    """Opt-in BIOS download to BIOS/{console}."""

    config = _resolve_config(config_path)
    setup_logging(config.log_file)
    source = BiosSource()
    try:
        catalog = source.list_files(console_name)
    except SourceUnavailable as exc:
        console.print(f"[red]BIOS unavailable for {console_name}:[/red] {exc}")
        raise typer.Exit(2) from exc
    files = catalog.files[:limit] if limit is not None and limit > 0 else catalog.files
    if not files:
        console.print(f"[yellow]No BIOS files found for {catalog.console}[/yellow]")
        raise typer.Exit(1)
    target = Path(config.bios_root) / catalog.console
    console.print(
        f"[cyan]BIOS:[/cyan] {catalog.console} - {len(files)} file(s) -> {target}"
    )
    for bios_file in files[:10]:
        console.print(f"  - {bios_file.filename} [{bios_file.source}]")
    if len(files) > 10:
        console.print(f"  ... and {len(files) - 10} more")
    try:
        paths = source.download(catalog.console, config.bios_root, limit=limit)
    except SourceUnavailable as exc:
        console.print(f"[red]BIOS download failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]BIOS complete:[/green] {len(paths)} file(s) in {target}")


@app.command()
def verify(
    console_name: Optional[str] = typer.Option(
        None, "--console", help="Single console shortname"
    ),
    config_path: Path = typer.Option(Path("config.yml"), "--config"),
) -> None:
    """Rescan existing ROM files and update state with verification results."""

    config = _resolve_config(config_path)
    setup_logging(config.log_file)
    consoles_yml_path = Path.cwd() / "consoles.yml"
    if not consoles_yml_path.exists():
        consoles_yml_path = _resources.find_data_file("consoles.yml")
    consoles_yml = _load_consoles(consoles_yml_path)
    dats_dir = Path.cwd() / "dats"
    if not dats_dir.exists():
        dats_dir = _resources.find_data_file("dats")

    verify_entries: list[dict[str, Any]] = list(consoles_yml.get("consoles", []) or [])
    if console_name:
        verify_entries = [
            c for c in verify_entries if c.get("shortname") == console_name
        ]

    for entry in verify_entries:
        short = str(entry.get("shortname", "?"))
        if entry.get("class") in ("D", "E", "F"):
            continue
        target_dir = Path(config.roms_root) / short
        if not target_dir.exists():
            continue
        dat_path = find_dat_for_console(short, consoles_yml, dats_dir)
        if dat_path is None:
            console.print(f"[dim]{short}: no DAT available, skipping verify[/dim]")
            continue
        dat = parse_dat(dat_path)
        index = {rom.name: rom for game in dat.games for rom in game.roms}
        state = load_state(short, config.roms_root)
        verified = 0
        mismatched = 0
        for file in target_dir.iterdir():
            if not file.is_file() or file.name.startswith("."):
                continue
            rom = index.get(file.name)
            if rom is None or not (rom.sha1 or rom.crc32):
                continue
            result = verify_file(file, rom)
            if result.matched:
                verified += 1
                update_game(
                    state,
                    rom.name,
                    status="acquired",
                    filename=file.name,
                    sha1=rom.sha1,
                )
            else:
                mismatched += 1
                update_game(
                    state,
                    rom.name,
                    status="unverified",
                    filename=file.name,
                )
        save_state(state, config.roms_root)
        console.print(
            f"[cyan]{short}:[/cyan] verified {verified}, mismatched {mismatched}"
        )


@app.command()
def report(
    config_path: Path = typer.Option(Path("config.yml"), "--config"),
    output: Path = typer.Option(Path("coverage.md"), "--output"),
) -> None:
    """Generate the coverage.md report from state files."""

    config = _resolve_config(config_path)
    consoles_yml_path = Path.cwd() / "consoles.yml"
    if not consoles_yml_path.exists():
        consoles_yml_path = _resources.find_data_file("consoles.yml")
    path = generate_coverage_report(consoles_yml_path, config.roms_root, output)
    console.print(f"[green]Report written:[/green] {path}")


@app.command()
def tui(
    config_path: Path = typer.Option(
        Path("config.yml"), "--config", help="Path to config.yml"
    ),
) -> None:
    """Launch the interactive TUI command center."""
    import os
    import sys as _sys

    if not _sys.stdout.isatty():
        console.print("[red]retrofetch tui requires an interactive terminal[/red]")
        raise typer.Exit(2)
    if os.environ.get("MSYSTEM"):
        console.print(
            "[red]MSYS2 / MinGW is not supported. Use Windows Terminal or a native POSIX shell.[/red]"
        )
        raise typer.Exit(2)
    if os.environ.get("PSEDIT"):
        console.print(
            "[red]PowerShell ISE is not supported. Use Windows Terminal.[/red]"
        )
        raise typer.Exit(2)

    config_path = config_path.expanduser().resolve()
    consoles_yml_path = Path.cwd() / "consoles.yml"
    if not consoles_yml_path.exists():
        consoles_yml_path = _resources.find_data_file("consoles.yml")
    if not consoles_yml_path.exists():
        console.print(
            f"[red]consoles.yml not found at {consoles_yml_path} or repo dir[/red]"
        )
        raise typer.Exit(2)
    try:
        consoles_yml = _load_consoles(consoles_yml_path)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    overrides_path = config_path.with_name("overrides.yml")
    try:
        overrides = load_overrides(overrides_path)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    first_run = not config_path.exists()
    if first_run:
        library_root = default_library_root()
        minimal_config = Config(
            roms_root=library_root,
            bios_root=library_root.parent / "BIOS",
            cache_dir=config_path.parent / "cache",
            log_file=config_path.parent / "retrofetch.log",
        )
    else:
        try:
            minimal_config = load_config(config_path)
        except ConfigError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2) from exc

    from retrofetch.tui.app import RetrofetchApp

    tui_app = RetrofetchApp(
        config=minimal_config,
        config_path=config_path,
        overrides_path=overrides_path,
        consoles_yml=consoles_yml,
        overrides=overrides,
        first_run=first_run,
    )
    return_code = tui_app.run()
    if return_code == 2 and first_run:
        console.print("Setup cancelled. Run `retrofetch tui` again when ready.")
    # Clamp App[int] return value to the repo's allowed CLI exit codes (0, 1, 2).
    # Anything unexpected is treated as exit 1.
    if return_code not in (0, 1, 2):
        return_code = 0 if return_code is None else 1
    raise typer.Exit(return_code)
