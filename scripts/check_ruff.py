"""Run local Ruff checks, including the exact Python content about to be committed."""

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("monitor.py", "benchmark.py", "test_monitor.py", "scripts")


def ruff_command() -> list[str]:
    """Use the same locked environment as the hook, without relying on PATH."""
    return [sys.executable, "-m", "ruff", "check", "--no-cache", "--force-exclude"]


def check_staged(root: Path) -> int:
    """Check index blobs so partially staged files cannot hide lint failures."""
    changed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root, capture_output=True, check=True,
    )
    if b"pyproject.toml" in changed.stdout.split(b"\0"):
        result = subprocess.run([*ruff_command(), *SOURCE_ROOTS], cwd=root)
        if result.returncode:
            return result.returncode
    for raw_path in changed.stdout.split(b"\0"):
        if not raw_path:
            continue
        name = raw_path.decode("utf-8")
        path = PurePosixPath(name)
        if path.parts[0] not in SOURCE_ROOTS or path.suffix not in {".py", ".pyi"}:
            continue
        source = subprocess.run(
            ["git", "show", f":{name}"], cwd=root, capture_output=True, check=True,
        )
        result = subprocess.run(
            [*ruff_command(), "--stdin-filename", name, "-"],
            cwd=root, input=source.stdout, capture_output=True,
        )
        if result.returncode:
            print(f"Ruff rejected staged content: {name}", file=sys.stderr)
            sys.stderr.buffer.write(result.stdout + result.stderr)
            return result.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Check only commit content.")
    if parser.parse_args().staged:
        return check_staged(ROOT)
    result = subprocess.run([*ruff_command(), *SOURCE_ROOTS], cwd=ROOT)
    if result.returncode:
        return result.returncode
    return check_staged(ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
