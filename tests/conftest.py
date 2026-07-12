from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import pytest


@pytest.fixture
def scratch_path(request) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    root = Path(tempfile.gettempdir()) / "retrofetch-test-scratch"
    path = root / f"{int(time.time() * 1000)}-{safe_name}"
    path.mkdir(parents=True, exist_ok=False)
    return path
