"""Rich console wrappers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console: Console = Console()


@contextmanager
def progress_context() -> Iterator[Progress]:
    progress = Progress(
        TextColumn("[bold cyan]{task.fields[console]:<12}"),
        TextColumn("{task.fields[game]:<40}"),
        BarColumn(bar_width=30),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )
    with progress:
        yield progress
