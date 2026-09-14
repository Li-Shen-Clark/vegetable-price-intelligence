#!/usr/bin/env python3
"""Rebuild and verify the complete P0 data layer with one command."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STEPS = [
    ("T1 Bronze", [sys.executable, "src/ingest/build_bronze.py"]),
    ("T2 mapped Silver", [sys.executable, "src/mapping/build_market_mapping.py"]),
    ("T3 province audit", [sys.executable, "src/quality/audit_province_conflicts.py"]),
    ("T4 quality Silver", [sys.executable, "src/quality/build_market_price_quality.py"]),
    ("T5 market and city Gold", [sys.executable, "src/aggregate/build_city_price.py"]),
    ("T6 coverage tiers", [sys.executable, "src/quality/build_coverage_tiers.py"]),
    (
        "T7 data contracts",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    ),
]


def main() -> int:
    environment = os.environ.copy()
    environment.setdefault("PYTHONPYCACHEPREFIX", "/tmp/vegetable_price_p0_pycache")
    print(f"P0 rebuild root: {PROJECT_ROOT}", flush=True)
    for index, (name, command) in enumerate(STEPS, 1):
        print(f"[{index}/{len(STEPS)}] {name}", flush=True)
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            print(f"P0 rebuild stopped at {name} (exit {completed.returncode})", flush=True)
            return completed.returncode
    print("P0 rebuild and data-contract verification completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
