"""Render bench/compare.py results as Markdown tables: python bench/report.py .data/results"""

from __future__ import annotations

import json
import sys
from pathlib import Path

METRICS = ["recall_any@5", "recall_any@10", "recall_all@10", "ndcg@10"]
SHORT = {
    "single-session-user": "ss-user", "single-session-assistant": "ss-asst",
    "single-session-preference": "ss-pref", "multi-session": "multi", "temporal-reasoning": "temporal",
    "knowledge-update": "update",
}


def main(path: str) -> int:
    runs = [json.loads(p.read_text())["summary"] for p in sorted(Path(path).glob("*.json"))]
    for n in sorted({r["n"] for r in runs}):
        group = sorted((r for r in runs if r["n"] == n), key=lambda r: -r["recall_any@5"])
        print(f"\n### n = {n} questions\n")
        print("| System | " + " | ".join(METRICS) + " | ingest units/s | query p50 ms |")
        print("|---" * (len(METRICS) + 3) + "|")
        for r in group:
            print(f"| {r['system']} | " + " | ".join(f"{r[m]:.3f}" for m in METRICS)
                  + f" | {r['ingest_units_per_s']} | {r['query_p50_ms']} |")
        types = sorted(group[0]["by_type"])
        print("\nrecall_any@5 by question type\n")
        print("| System | " + " | ".join(f"{SHORT.get(t, t)} (n={group[0]['by_type'][t]['n']})" for t in types) + " |")
        print("|---" * (len(types) + 1) + "|")
        for r in group:
            print(f"| {r['system']} | " + " | ".join(f"{r['by_type'][t]['recall_any@5']:.2f}" for t in types) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ".data/results"))
