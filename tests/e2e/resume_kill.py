import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

URL = (
    "https://archive.org/download/BigBuckBunny_124/"
    "Content/big_buck_bunny_720p_surround.ogv"
)
EXPECTED_SIZE = 46935223
DEST = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "tmp" / "resume-test.ogv"


def child() -> None:
    from retrofetch.downloader import stream_http_download

    result = stream_http_download(URL, DEST, source_name="e2e-resume", timeout=60)
    print(f"resumed={result.resumed} bytes_written={result.bytes_written}")


def parent() -> int:
    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        lines.append(msg)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.unlink(missing_ok=True)
    part = DEST.with_suffix(DEST.suffix + ".part")
    part.unlink(missing_ok=True)

    proc = subprocess.Popen(
        [sys.executable, __file__, "child", str(DEST)], cwd=str(ROOT)
    )
    killed = False
    for _ in range(600):
        time.sleep(0.2)
        if part.exists() and part.stat().st_size > 5_000_000:
            proc.kill()
            proc.wait()
            killed = True
            break
        if proc.poll() is not None:
            break
    if not killed:
        log("FAIL: never reached 5MB before child exited")
        return 1
    part_size = part.stat().st_size
    log(f"killed child at part_size={part_size}")
    log(f"part exists={part.exists()} final exists={DEST.exists()}")
    if DEST.exists():
        log("FAIL: final file exists after kill")
        return 1

    rerun = subprocess.run(
        [sys.executable, __file__, "child", str(DEST)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    log(f"rerun stdout: {rerun.stdout.strip()}")
    final_size = DEST.stat().st_size if DEST.exists() else 0
    log(f"final exists={DEST.exists()} size={final_size} expected={EXPECTED_SIZE}")
    log(f"stale part remains={part.exists()}")
    ok = (
        DEST.exists()
        and final_size == EXPECTED_SIZE
        and "resumed=True" in rerun.stdout
        and not part.exists()
    )
    log("PASS" if ok else "FAIL")
    evidence = ROOT / ".omo" / "evidence" / "task-20-resume.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "Kill-and-resume integrity (real network, archive.org Range-supporting URL)\n"
        f"url={URL}\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    DEST.unlink(missing_ok=True)
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child()
    else:
        raise SystemExit(parent())
