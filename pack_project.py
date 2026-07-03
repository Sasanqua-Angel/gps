"""Create the final zip package for submission."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


EXCLUDE_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".zip"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def pack(output_name: str) -> Path:
    root = Path(__file__).resolve().parent
    output = root / output_name
    if output.suffix.lower() != ".zip":
        output = output.with_suffix(".zip")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path == output or not path.is_file() or not should_include(path.relative_to(root)):
                continue
            archive.write(path, path.relative_to(root))

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pack project files into a submission zip.")
    parser.add_argument("name", help="zip name, e.g. 物联网考核-学号1-姓名1-学号2-姓名2.zip")
    args = parser.parse_args()
    print(pack(args.name))
