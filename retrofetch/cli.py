"""Typer CLI entrypoint. Full subcommands added in T12."""

import typer

from retrofetch import __version__

app = typer.Typer(name="retrofetch", add_completion=False)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"retrofetch {__version__}")
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    pass
