"""Offline diagnostic of the evidence Hermes would receive, not answer accuracy.

    PYTHONPATH=src python bench/hermes_packet.py

Both arms use the native provider and identical synthetic stores. The labels below
are the exact rows useful for a question. A missing row AND an unnecessary row are
both errors. Red rows are research targets, not a CI gate or a leaderboard.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass

from teresis.hermes import TeresisMemoryProvider
from teresis.store import Weights
from teresis.text import estimate_tokens


SCOPE = "hermes/replay"


@dataclass(frozen=True)
class Row:
    label: str
    content: str
    scope: str = SCOPE
    kind: str = "fact"
    source: str = "hermes:memory-tool"
    key: str | None = None


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    rows: tuple[Row, ...]
    required: tuple[str, ...]
    budget: int = 700
    k: int = 6


OWNER = Row("owner", "Priya owns the billing service.")
LEAVE = Row("leave", "Priya is on leave through October.")
HOBBY = Row("hobby", "Priya collects vintage fountain pens.")
ASK = "Is the billing service owner available?"
ENDPOINT = Row("current", "The Kestrel worker now listens on port 6600.", key="kestrel.port")
EPISODE = Row("obsolete_turn", "User: The Kestrel worker listens on port 4400.\nAssistant: Noted.",
              kind="episode", source="hermes:cli")
CASES = (
    Case("two facts needed", ASK, (OWNER, LEAVE), ("owner", "leave")),
    Case("same person, irrelevant property", ASK, (OWNER, HOBBY), ("owner",)),
    Case("sibling must not supply the bridge", ASK,
         (OWNER, Row("other_user", LEAVE.content, scope="hermes/other")), ("owner",)),
    Case("unreviewed evidence", ASK,
         (OWNER, Row("unreviewed", LEAVE.content, source="hermes:auto-extract")), ("owner",)),
    Case("abstain without an anchor", "Who designed the aquarium?", (OWNER, LEAVE), ()),
    Case("current value after correction", "Which port does the Kestrel worker use now?",
         (Row("former", "The Kestrel worker listens on port 4400.", key="kestrel.port"), ENDPOINT),
         ("current",)),
    Case("current fact versus stale conversation", "Which port does the Kestrel worker use now?",
         (EPISODE, ENDPOINT), ("current",)),
    Case("budget includes conversation and headers", "Which port does the Kestrel worker use now?",
         (ENDPOINT, EPISODE), ("current",), budget=40),
)


def run(case: Case, linked: bool) -> dict:
    provider = TeresisMemoryProvider({"db_path": ":memory:", "scope": SCOPE, "extra_scopes": "",
                                     "embed": "", "rerank": "", "prefetch_linked": linked,
                                     "prefetch_k": case.k, "prefetch_budget_tokens": case.budget})
    provider.initialize("synthetic", platform="cli")
    try:
        store = provider._store
        assert store is not None
        store.w = Weights()  # Do not tune this replay via the caller's TERESIS_WEIGHTS.
        store.clock = lambda: 1_700_000_000.0
        labels = {}
        for row in case.rows:
            mid = store.remember(row.content, scope=row.scope, kind=row.kind,
                                 key=row.key, source=row.source).id
            if mid in labels:
                raise ValueError(f"{case.name}: fixture rows unexpectedly reconciled")
            labels[mid] = row.label
        context = provider.prefetch(case.question)
        returned = [labels[mid] for mid in re.findall(r" \(id ([0-9a-f]{16})(?:; linked from [0-9a-f]{16})?\)$",
                                                      context, flags=re.M)]
        if context and (not returned or len(returned) != provider._last_count):
            raise ValueError(f"{case.name}: unrecognized provider citation format")
        missing = sorted(set(case.required) - set(returned))
        extra = sorted(set(returned) - set(case.required))
        cost = estimate_tokens(context) if context else 0
        within_limits = cost <= case.budget and len(returned) <= case.k
        return {"case": case.name, "arm": "linked" if linked else "direct", "returned": returned,
                "missing": missing, "extra": extra, "estimated_tokens": cost, "budget": case.budget,
                "within_limits": within_limits, "pass": not missing and not extra and within_limits}
    finally:
        provider.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=["both", "direct", "linked"], default="both")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    arms = [False, True] if args.arm == "both" else [args.arm == "linked"]
    rows = [run(case, arm) for case in CASES for arm in arms]
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        state = "pass" if r["pass"] else "miss"
        print(f"{r['arm']:6} {state:4} {r['case']:<41} missing={r['missing']} extra={r['extra']} "
              f"budget={r['estimated_tokens']}/{r['budget']}")


if __name__ == "__main__":
    main()
