from __future__ import annotations

import sys

from retrofetch.config import user_config_path


def executable_argv(argv: list[str]) -> list[str]:
    if len(argv) == 1:
        return [argv[0], "tui", "--config", str(user_config_path())]
    return argv


def main() -> None:
    sys.argv[:] = executable_argv(sys.argv)
    from retrofetch.cli import app

    app()


if __name__ == "__main__":
    main()
