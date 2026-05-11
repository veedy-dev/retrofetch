from __future__ import annotations

import importlib.resources
from pathlib import Path


def find_data_file(name: str) -> Path:
    """Resolve a bundled data file or directory by name.

    Tries three locations in order:
      1. importlib.resources (post-wheel-install: file is INSIDE the
         installed retrofetch/ package via hatch force-include).
      2. Package directory sibling (defensive: in case files/dirs
         ended up in retrofetch/ during a hybrid build).
      3. Repo root sibling (editable install: files live at
         <repo>/<name>, sibling of the retrofetch/ package).

    Does NOT check CWD. Caller handles user-override layer.
    Works for both files (consoles.yml, *.example, .env.example) and
    directories (dats).
    Raises FileNotFoundError if no tier resolves.
    """
    try:
        traversable = importlib.resources.files("retrofetch") / name
        if traversable.is_file() or traversable.is_dir():
            return Path(str(traversable))
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    package_dir = Path(__file__).resolve().parent
    in_package = package_dir / name
    if in_package.is_file() or in_package.is_dir():
        return in_package
    repo_candidate = package_dir.parent / name
    if repo_candidate.is_file() or repo_candidate.is_dir():
        return repo_candidate
    raise FileNotFoundError(
        f"Could not locate bundled data {name!r}. "
        f"Tried (1) importlib.resources.files('retrofetch') / {name!r}, "
        f"(2) {in_package}, "
        f"(3) {repo_candidate}."
    )
