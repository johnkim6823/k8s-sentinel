"""Summarize baseline MTTR results: per-scenario mean and standard deviation.

Usage:
    python experiments/baseline/summarize.py [results_file]

Defaults to results.jsonl next to this script.
"""

import json
import statistics
import sys
from pathlib import Path

SCENARIO_NAMES = {1: "OOMKilled", 2: "CrashLoopBackOff", 3: "ImagePullBackOff"}


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "results.jsonl"
    )
    if not path.exists():
        raise SystemExit(f"no results file: {path}")

    by_scenario: dict[int, list[int]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        by_scenario.setdefault(record["scenario"], []).append(record["mttr_seconds"])

    print(f"{'scenario':<22} {'n':>3} {'mean_s':>8} {'stdev_s':>8} {'runs (s)'}")
    for scenario in sorted(by_scenario):
        values = by_scenario[scenario]
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        name = SCENARIO_NAMES.get(scenario, str(scenario))
        print(
            f"{scenario}. {name:<19} {len(values):>3} {mean:>8.1f} {stdev:>8.1f} "
            f"{values}"
        )


if __name__ == "__main__":
    main()
