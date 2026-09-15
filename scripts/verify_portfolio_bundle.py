#!/usr/bin/env python3
"""Verify that the publishable Git bundle contains code and documentation only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_BYTES = 50 * 1024 * 1024

REQUIRED_PATHS = (
    ".gitignore",
    ".github/workflows/portfolio-ci.yml",
    ".github/workflows/pages.yml",
    "README.md",
    "PORTFOLIO_CASE_STUDY.md",
    "PROJECT_ROADMAP.md",
    "docs/economics_pricing_stage_gate.md",
    "docs/data_access_and_reproducibility.md",
    "docs/p6_evidence_matrix.md",
    "docs/pricing_integration_contract.md",
    "docs/p6_career_pack.md",
    "docs/p6_demo_script.md",
    "docs/p6_delivery_checklist.md",
    "docs/p7_delivery_checklist.md",
    "portfolio-site/index.html",
    "portfolio-site/styles.css",
    "portfolio-site/og.png",
    "scripts/verify_pages_bundle.py",
    "tests/test_p7_pages_site.py",
    "data/README.md",
    "config/p4_procurement.yaml",
    "web/package.json",
    "web/package-lock.json",
    "web/app/page.tsx",
    "web/app/forecast/page.tsx",
    "web/app/alerts/page.tsx",
    "web/app/procurement/page.tsx",
    "web/app/propagation/page.tsx",
    "web/app/case-study/page.tsx",
    "web/public/og.png",
)

REQUIRED_IGNORE_RULES = (
    "OneDrive_*.zip",
    "dataSource/",
    "data/*",
    "!data/README.md",
    "artifacts/",
    "baselines/",
    "web/public/data/",
    "reference/*.csv",
    "docs/**/*.csv",
    "docs/**/*.json",
    "docs/evidence/",
    "unmatched_markets.csv",
    "*.parquet",
    "*.csv",
    "*执行日志.md",
    "/GUIDEBOOK.md",
    "/GUIDEBOOK_可实施性评审.md",
    "/GUIDEBOOK_撤回执行计划.md",
    ".private-backups/",
    "/P[0-7]_执行计划.md",
    "/P5_前置执行计划.md",
    "/P7_状态评审.md",
    "/ROADMAP_迁移执行计划.md",
    "/EVIDENCE_DASHBOARD_P5_执行计划.md",
    "web/node_modules/",
    "web/.next/",
    "web/.vinext/",
    "web/dist/",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
)

FORBIDDEN_PREFIXES = (
    "artifacts/",
    "baselines/",
    "dataSource/",
    "docs/evidence/",
    "web/public/data/",
    "web/node_modules/",
    "web/.next/",
    "web/.vinext/",
    "web/dist/",
)

PUBLIC_TEXT_PATHS = (
    "README.md",
    "PORTFOLIO_CASE_STUDY.md",
    "PROJECT_ROADMAP.md",
    "docs/economics_pricing_stage_gate.md",
    "docs/p6_evidence_matrix.md",
    "docs/pricing_integration_contract.md",
    "docs/p6_career_pack.md",
    "docs/p6_demo_script.md",
    "docs/p6_delivery_checklist.md",
    "docs/p7_delivery_checklist.md",
    "portfolio-site/index.html",
    "web/app/page.tsx",
    "web/app/forecast/page.tsx",
    "web/app/alerts/page.tsx",
    "web/app/procurement/page.tsx",
    "web/app/propagation/page.tsx",
    "web/app/case-study/page.tsx",
)

PRIVATE_LOCAL_PATHS = (
    "GUIDEBOOK.md",
    "GUIDEBOOK_可实施性评审.md",
    "GUIDEBOOK_撤回执行计划.md",
    "P0_执行计划.md",
    "P1_执行计划.md",
    "P2_执行计划.md",
    "P3_执行计划.md",
    "P4_执行计划.md",
    "P5_前置执行计划.md",
    "P5_执行计划.md",
    "P6_执行计划.md",
    "P7_执行计划.md",
    "P7_状态评审.md",
    "ROADMAP_迁移执行计划.md",
    "EVIDENCE_DASHBOARD_P5_执行计划.md",
)

PRIVATE_HISTORY_PATHS = (
    "GUIDEBOOK.md",
    "GUIDEBOOK_可实施性评审.md",
    "GUIDEBOOK_撤回执行计划.md",
)


def assert_required_paths() -> None:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).is_file()]
    if missing:
        raise AssertionError(f"missing required portfolio files: {missing}")


def assert_ignore_contract() -> None:
    lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(set(REQUIRED_IGNORE_RULES) - lines)
    if missing:
        raise AssertionError(f"missing required ignore rules: {missing}")


def assert_public_text_is_portable() -> None:
    forbidden = ("/Users/", "/Volumes/", "C:\\Users\\")
    violations: list[str] = []
    for relative in PUBLIC_TEXT_PATHS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            violations.append(relative)
    if violations:
        raise AssertionError(f"absolute local paths in public-facing files: {violations}")


def assert_private_paths_absent(
    paths: list[str], private_paths: tuple[str, ...] = PRIVATE_LOCAL_PATHS
) -> None:
    leaked = sorted(set(private_paths).intersection(paths))
    if leaked:
        raise AssertionError(f"private local files in Git paths: {leaked}")


def git_candidate_paths() -> list[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    candidates = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in candidates.stdout.splitlines() if line]


def git_publishable_history_paths(ref: str = "HEAD") -> list[str]:
    """List every path reachable from the branch/ref that would be pushed."""
    result = subprocess.run(
        ["git", "rev-list", "--objects", ref],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        _, separator, path = line.partition(" ")
        if separator and path:
            paths.append(path)
    return paths


def assert_git_candidate_contract(paths: list[str]) -> tuple[int, int]:
    forbidden: list[str] = []
    oversized: list[str] = []
    total_bytes = 0
    for relative in paths:
        if relative == ".DS_Store" or relative.startswith(FORBIDDEN_PREFIXES):
            forbidden.append(relative)
        suffix = Path(relative).suffix.lower()
        if suffix in {".csv", ".parquet"}:
            forbidden.append(relative)
        if relative.startswith("data/") and relative != "data/README.md":
            forbidden.append(relative)
        if relative.startswith("docs/") and suffix == ".json":
            forbidden.append(relative)
        if relative == "unmatched_markets.csv":
            forbidden.append(relative)
        if Path(relative).name.endswith("执行日志.md"):
            forbidden.append(relative)
        if relative.startswith("OneDrive_") and relative.endswith(".zip"):
            forbidden.append(relative)
        if Path(relative).name.startswith(".env"):
            forbidden.append(relative)
        target = ROOT / relative
        if target.is_file():
            size = target.stat().st_size
            total_bytes += size
            if size > MAX_TRACKED_BYTES:
                oversized.append(relative)
    if forbidden:
        raise AssertionError(f"forbidden Git candidates: {sorted(set(forbidden))}")
    if oversized:
        raise AssertionError(f"Git candidates over 50 MiB: {oversized}")
    return len(paths), total_bytes


def verify() -> dict:
    assert_required_paths()
    assert_ignore_contract()
    assert_public_text_is_portable()
    candidates = git_candidate_paths()
    assert_private_paths_absent(candidates)
    candidate_count, candidate_bytes = assert_git_candidate_contract(candidates)
    history_paths = git_publishable_history_paths()
    assert_private_paths_absent(history_paths, PRIVATE_HISTORY_PATHS)
    assert_git_candidate_contract(history_paths)
    return {
        "status": "pass",
        "required_files": len(REQUIRED_PATHS),
        "git_initialized": bool(candidates),
        "git_candidate_files": candidate_count,
        "git_candidate_bytes": candidate_bytes,
        "publishable_history_paths": len(history_paths),
        "maximum_allowed_file_bytes": MAX_TRACKED_BYTES,
    }


def main() -> None:
    print(json.dumps(verify(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
