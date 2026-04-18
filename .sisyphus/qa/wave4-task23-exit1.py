"""T23 exit1: uncaught exception in a screen yields exit != 0 and != 130.

Approach: subprocess runs a crash-fixture script that monkey-patches
HomeScreen.on_mount to raise RuntimeError. Textual 8.x catches the exception
via App._handle_exception, sets `_return_code = 1`, and shows its crash
screen. We propagate that code to the process with `sys.exit(app.return_code
or 1)` so the subprocess exit reflects the crash, matching the pattern
cli.py::tui uses (`raise typer.Exit(return_code if return_code is not None
else 0)`).

We assert `rc != 0 AND rc != 130` rather than hard-coding `rc == 1` to stay
robust if Textual maps future panics to different non-zero codes.
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, textwrap


def main() -> None:
    repo = os.path.abspath(".")
    cfg = os.path.abspath("config.yml.example")
    consoles = os.path.abspath("consoles.yml")
    crash_script = textwrap.dedent(f"""
    import pathlib, sys
    sys.path.insert(0, {repo!r})
    from retrofetch.tui.app import RetrofetchApp
    from retrofetch.tui.screens.home import HomeScreen
    from retrofetch.config import load_config, _yaml_rt
    def boom(self):
        raise RuntimeError("fixture crash for exit-code test")
    HomeScreen.on_mount = boom
    config = load_config(pathlib.Path({cfg!r}))
    consoles = _yaml_rt.load(pathlib.Path({consoles!r}).read_text(encoding='utf-8'))
    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path({cfg!r}),
        consoles_yml=consoles,
        overrides={{}},
    )
    app.run()
    sys.exit(app.return_code if app.return_code is not None else 1)
    """)
    fd, path = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(crash_script)
        r = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        assert r.returncode != 0, \
            f"expected non-zero for crashed app, got {r.returncode}"
        assert r.returncode != 130, \
            f"crash shouldn't be SIGINT-coded, got {r.returncode}"
        print(f"T23 exit1: OK (rc={r.returncode})")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


main()
