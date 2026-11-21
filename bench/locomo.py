"""Head-to-head retrieval benchmark on LoCoMo (Maharana et al., ACL 2024).

Ingests each of the 10 multi-session conversations at turn granularity (`dia_id`) and evaluates
turn-level evidence retrieval across categories 1-4 (1,540 QA pairs; category 5 is adversarial /
unanswerable and is excluded from recall metrics per standard LoCoMo retrieval protocol).

    python bench/locomo.py --data .data/locomo10.json --system teresis --out bench/results
    systems: naive | teresis | teresis-emb | holographic | mem0
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

import compare as C  # noqa: E402

CAT_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
}


def parse_locomo_date(s: str) -> float:
    s = (s or "").strip()
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            pass
    return 1_700_000_000.0


def parse_evidence(ev_list: list[str]) -> set[str]:
    out: set[str] = set()
    for item in ev_list or []:
        for part in re.split(r"[;,]", str(item)):
            p = part.strip()
            if p:
                out.add(p)
    return out


def units_for_conv(conv: dict) -> tuple[list[tuple[str, str, float]], float]:
    sess_nums = sorted(
        int(m.group(1))
        for k in conv
        if (m := re.fullmatch(r"session_(\d+)", k))
    )
    units: list[tuple[str, str, float]] = []
    max_t = 1_700_000_000.0
    for sn in sess_nums:
        date_str = conv.get(f"session_{sn}_date_time", "")
        base_t = parse_locomo_date(date_str)
        turns = conv.get(f"session_{sn}") or []
        for idx, turn in enumerate(turns):
            dia_id = str(turn.get("dia_id") or f"D{sn}:{idx + 1}")
            speaker = turn.get("speaker", "Speaker")
            text = (turn.get("text") or "").strip()
            cap = (turn.get("blip_caption") or "").strip()
            if cap:
                text = f"{text} [shared image: {cap}]" if text else f"[shared image: {cap}]"
            if not text:
                continue
            body = f"[{date_str}] {speaker}: {text}" if date_str else f"{speaker}: {text}"
            t = base_t + idx * 10.0
            max_t = max(max_t, t)
            units.append((dia_id, body[:2000], t))
    return units, max_t + 86400.0


def run(data_path: Path, system: str, out_dir: Path, hermes: Path) -> dict:
    data = json.loads(data_path.read_text())
    rows = []
    total_units = 0
    ingest_s = 0.0
    qtimes: list[float] = []
    name = system

    for ci, item in enumerate(data):
        units, now_t = units_for_conv(item["conversation"])
        with tempfile.TemporaryDirectory() as td:
            adapter = C.make(system, Path(td), hermes)
            name = adapter.name
            t0 = time.perf_counter()
            adapter.add_all(units)
            ingest_s += time.perf_counter() - t0
            total_units += len(units)

            for qi, q in enumerate(item["qa"]):
                cat = int(q["category"])
                if cat not in CAT_NAMES:
                    continue
                gold = parse_evidence(q.get("evidence") or [])
                if not gold:
                    continue
                tq = time.perf_counter()
                raw_ids = adapter.search(q["question"], now_t)
                qtimes.append((time.perf_counter() - tq) * 1000.0)
                ranked = C.session_ranking(raw_ids)
                sc = C.score(ranked, gold)
                rows.append({"conv": ci, "id": f"c{ci}_q{qi}", "type": CAT_NAMES[cat], **sc})
            adapter.close()
        print(f"[{system}] conv {ci + 1}/{len(data)} done ({len(rows)} qas)", flush=True)

    metrics = ("recall_any@5", "recall_any@10", "recall_all@10", "ndcg@10")
    summary = {
        "benchmark": "locomo",
        "system": name,
        "key": system,
        "n": len(rows),
        **{m: round(statistics.mean(r[m] for r in rows), 4) for m in metrics},
        "by_type": {},
        "ingest_units_per_s": round(total_units / max(ingest_s, 1e-6), 1),
        "query_p50_ms": round(statistics.median(qtimes), 2) if qtimes else 0.0,
    }
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        summary["by_type"][t] = {**{m: round(statistics.mean(r[m] for r in sub), 4) for m in metrics}, "n": len(sub)}

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"locomo-{system}.json"
    out_file.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".data/locomo10.json")
    ap.add_argument("--system", required=True, choices=["naive", "teresis", "teresis-emb", "holographic", "mem0"])
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--hermes", default=os.path.expanduser("~/.hermes/hermes-agent"))
    args = ap.parse_args()
    run(Path(args.data), args.system, Path(args.out), Path(args.hermes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
