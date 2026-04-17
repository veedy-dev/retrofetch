import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "retrofetch", "--version"],
    capture_output=True,
    text=True,
    check=True,
)
version = (result.stdout or result.stderr).strip()

if version != "retrofetch 0.1.0":
    print(f"expected retrofetch 0.1.0, got {version}", file=sys.stderr)
    raise SystemExit(1)

print("sample version-check: OK")
