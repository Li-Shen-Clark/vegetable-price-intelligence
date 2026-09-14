#!/usr/bin/env python3
"""Verify that the GitHub Pages payload is a small, data-free static site."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "portfolio-site"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BUNDLE_BYTES = 10 * 1024 * 1024

REQUIRED_FILES = {
    ".nojekyll",
    "index.html",
    "og.png",
    "robots.txt",
    "sitemap.xml",
    "styles.css",
}
ALLOWED_SUFFIXES = {".html", ".css", ".png", ".txt", ".xml"}
TEXT_SUFFIXES = {".html", ".css", ".txt", ".xml"}
FORBIDDEN_TEXT = {
    "/Users/",
    "/Volumes/",
    "C:\\Users\\",
    "localhost",
    "web/public/data",
    "artifacts/",
    ".csv",
    ".parquet",
    ".json",
    "执行日志",
}


def site_files() -> list[Path]:
    if not SITE.is_dir():
        raise AssertionError("portfolio-site directory is missing")
    return sorted(path for path in SITE.rglob("*") if path.is_file())


def verify() -> dict[str, int | str]:
    files = site_files()
    relative_files = {path.relative_to(SITE).as_posix() for path in files}
    missing = sorted(REQUIRED_FILES - relative_files)
    if missing:
        raise AssertionError(f"missing Pages files: {missing}")

    invalid: list[str] = []
    oversized: list[str] = []
    text_violations: list[str] = []
    total_bytes = 0

    for path in files:
        relative = path.relative_to(SITE).as_posix()
        if path.is_symlink():
            invalid.append(f"symlink:{relative}")
        if relative != ".nojekyll" and path.suffix.lower() not in ALLOWED_SUFFIXES:
            invalid.append(relative)
        if any(part.startswith(".") for part in path.relative_to(SITE).parts) and relative != ".nojekyll":
            invalid.append(f"hidden:{relative}")

        size = path.stat().st_size
        total_bytes += size
        if size > MAX_FILE_BYTES:
            oversized.append(relative)

        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in FORBIDDEN_TEXT):
                text_violations.append(relative)

    if invalid:
        raise AssertionError(f"invalid Pages payload files: {sorted(set(invalid))}")
    if oversized:
        raise AssertionError(f"Pages files over 5 MiB: {oversized}")
    if total_bytes > MAX_BUNDLE_BYTES:
        raise AssertionError(f"Pages payload exceeds 10 MiB: {total_bytes}")
    if text_violations:
        raise AssertionError(f"forbidden text in Pages payload: {sorted(set(text_violations))}")

    index = (SITE / "index.html").read_text(encoding="utf-8")
    for forbidden_markup in ("<script", "fetch(", "<form", "<iframe"):
        if forbidden_markup in index:
            raise AssertionError(f"forbidden active markup: {forbidden_markup}")

    return {
        "status": "pass",
        "files": len(files),
        "bytes": total_bytes,
        "maximum_file_bytes": MAX_FILE_BYTES,
        "maximum_bundle_bytes": MAX_BUNDLE_BYTES,
    }


def main() -> None:
    print(json.dumps(verify(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
