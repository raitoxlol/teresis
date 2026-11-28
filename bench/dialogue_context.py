"""Paired, retrieval-only experiment on public LoCoMo transcripts.

The reference arms are captured Teresis rankings. The experimental index can
use neighboring turns to rank an individual turn but returns only its ID.
It is rebuilt per conversation from the active, redacted Teresis rows.
No question, answer, evidence label or dataset ID is indexed as content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import compare
import locomo
from teresis import provenance, text


CORPUS = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
REFERENCES = {
    "dev": ("529adeaa79c4aea04391df0b3d10924f16f2aab1f84ecc19eb5635adf77287a2", range(2)),
    "confirm": ("44f5986bb46a30894e5e47709fea320e29115a41e1b1aa4fe5ef0d32214ec292", range(2, 10)),
}
# Locked development candidates: (neighbor weight, author prior, reference fusion).
MODES = {"window": (0.45, 1.0, False), "author": (0.45, 1.4, False),
         "fusion": (0.45, 1.4, True)}


def pinned(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"input fingerprint mismatch: {path}")
    return json.loads(raw)


def index(conn, item):
    units, now = locomo.units_for_conv(item["conversation"])
    with tempfile.TemporaryDirectory() as td:
        adapter = compare.Teresis(Path(td))
        try:
            adapter.add_all(units)
            adapter.clock["t"] = now
            rows = adapter.s.recall("", scope="bench", inherit=False, k=len(units), touch=False)
            bodies = {adapter.sid[m.id]: m.content for m in rows
                      if provenance.injectable(m.kind, m.content, m.meta, m.source)[0]}
        finally:
            adapter.close()
    conn.execute("CREATE VIRTUAL TABLE passage USING fts5(body, prev, next, "
                 "turn UNINDEXED, speaker UNINDEXED, tokenize='porter unicode61')")
    speakers = set()
    for key, turns in item["conversation"].items():
        if not re.fullmatch(r"session_\d+", key):
            continue
        for i, turn in enumerate(turns):
            tid = turn["dia_id"]
            if tid not in bodies:
                continue
            speaker = turn["speaker"]
            speakers.add(speaker)
            # Keep an ineligible/missing turn as a gap; never skip across it.
            prev = bodies.get(turns[i-1]["dia_id"], "") if i else ""
            nxt = bodies.get(turns[i+1]["dia_id"], "") if i+1 < len(turns) else ""
            conn.execute("INSERT INTO passage VALUES (?, ?, ?, ?, ?)",
                         (bodies[tid], prev, nxt, tid, speaker))
    return bodies.keys(), speakers


def passages(conn, question, speakers, base, mode):
    weight, author_prior, fusion = MODES[mode]
    fq = text.fts_query(question)
    if not fq:
        return base[:10]
    mentioned = [s for s in speakers
                 if re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", question, re.I)]
    # Common conversation participants are poor topical cues, but who said a
    # thing is useful when a question names a single participant.
    author = mentioned[0] if len(mentioned) == 1 else None
    hits = conn.execute(
        "SELECT turn, speaker, -bm25(passage, 1, ?, ?) FROM passage WHERE passage MATCH ?",
        (weight, weight, fq))
    ranks = sorted(((t, sc * (author_prior if author == sp else 1)) for t, sp, sc in hits),
                   key=lambda x: (-x[1], x[0]))
    window = [t for t, _ in ranks[:50]]
    if not fusion:
        return list(dict.fromkeys(window + base))[:10]
    # Same 10-item output cap. Rank fusion avoids comparing scores from two
    # differently normalized rankers. The frozen reference supplies 10 ranks.
    votes = {}
    for ranked in (base, window):
        for pos, tid in enumerate(ranked, 1):
            votes[tid] = votes.get(tid, 0) + 1 / (8 + pos)
    return sorted(votes, key=votes.__getitem__, reverse=True)[:10]


def run(data, ref, split, modes):
    digest, conversations = REFERENCES[split]
    corpus = pinned(data, CORPUS)
    ref = pinned(ref, digest)
    assert ref["conversations"] == list(conversations) and ref["sha256"] == CORPUS
    results = []
    for ci in conversations:
        item = corpus[ci]
        with closing(sqlite3.connect(":memory:")) as conn:
            eligible, speakers = index(conn, item)
            expected = {qi for qi, q in enumerate(item["qa"])
                        if q["category"] in locomo.CAT_NAMES and locomo.parse_evidence(q.get("evidence"))}
            seen = set()
            for r in (r for r in ref["rows"] if r["conv"] == ci):
                qi = r["q"]
                q = item["qa"][qi]
                assert qi not in seen and set(r["gold"]) == locomo.parse_evidence(q["evidence"])
                seen.add(qi)
                base = r["base"]
                # If the captured baseline and this reconstruction disagree on
                # visible rows, refuse the comparison rather than edit either.
                assert set(base + r["trial"]) <= eligible, (ci, qi, "eligibility drift")
                arms = {"base": base, "nearby": r["trial"]}
                for mode in modes:
                    arms[mode] = passages(conn, q["question"], speakers, base, mode)
                assert all(len(ids) <= 10 and len(set(ids)) == len(ids) for ids in arms.values())
                results.append(dict(conv=ci, q=qi, kind=r["kind"], gold=r["gold"], arms=arms))
            assert seen == expected
    return results


def metrics(rows, arm):
    scores = [compare.score(r["arms"][arm], set(r["gold"])) for r in rows]
    return {m: sum(s[m] for s in scores) / len(scores)
            for m in ("recall_all@10", "recall_any@5", "ndcg@10")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ("data", "ref", "out"):
        ap.add_argument("--" + flag, type=Path, required=True)
    ap.add_argument("--split", choices=REFERENCES, required=True)
    ap.add_argument("--mode", choices=MODES, nargs="+", required=True)
    args = ap.parse_args()
    if args.split == "confirm" and len(args.mode) != 1:
        ap.error("confirm takes only the candidate chosen on dev")
    rows = run(args.data, args.ref, args.split, args.mode)
    summary = {group: {arm: metrics(sub, arm) for arm in rows[0]["arms"]}
               for group, sub in (("all", rows), ("multi-hop", [r for r in rows if r["kind"] == "multi-hop"]))}
    with args.out.open("x") as f:
        json.dump(dict(split=args.split, modes=args.mode, summary=summary, rows=rows), f)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
