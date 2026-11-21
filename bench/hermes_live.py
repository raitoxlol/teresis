"""Live end-to-end benchmark: a real Hermes agent, real model, one fresh process per session.

Phase 1 (ingest): each statement is told to the agent in its own session.
Phase 2 (ask): each question is asked in a new session with no restating.
Graded by deterministic string match (no LLM judge). 30 scenarios, fixed seed:
10 direct facts, 6 preferences/rules, 6 paraphrased questions, 4 updates (newest value must win),
4 abstention (never told; the agent must say it does not know).

    python bench/hermes_live.py --profile bench-teresis --arm teresis
    python bench/hermes_live.py --profile bench-base --arm builtin
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
import time
from pathlib import Path

REFUSE = re.compile(r"don'?t (?:have|know)|do not (?:have|know)|no (?:record|memory|info)|not (?:sure|aware)|"
                    r"haven'?t (?:told|shared|mentioned)|unknown|can'?t (?:find|recall)|couldn'?t|no idea|"
                    r"not (?:in|stored)|isn'?t (?:in|something)", re.I)

NAMES = ["falcon", "otter", "juniper", "basalt", "marmot", "cobalt", "tundra", "saffron", "heron", "quartz",
         "lynx", "ember", "willow", "ibis", "garnet", "sparrow", "onyx", "fennel", "kestrel", "moss"]
PEOPLE = ["Priya Raman", "Tomas Ekwueme", "Hana Kobayashi", "Luis Ferreira", "Mira Okafor", "Dev Patel"]


def scenarios(seed: int = 42) -> dict:
    r = random.Random(seed)
    nm = NAMES[:]
    r.shuffle(nm)
    ppl = PEOPLE[:]
    r.shuffle(ppl)
    ip = lambda: f"10.{r.randint(2, 200)}.{r.randint(2, 200)}.{r.randint(2, 250)}"
    port = lambda: str(r.randint(2000, 9800))
    S = []

    def add(kind, tell, ask, expect, forbid=(), later=None):
        S.append(dict(id=len(S), kind=kind, tell=tell, ask=ask, expect=list(expect), forbid=list(forbid), later=later))

    # direct facts (10)
    n = nm.pop(); p = port()
    add("direct", f"my staging database is called {n}-staging and listens on port {p}.", f"What port does my {n}-staging database listen on?", [p])
    n = nm.pop(); a = ip()
    add("direct", f"my build server is called {n}-7 and sits at {a}.", f"What is the IP address of my {n}-7 build server?", [a])
    n = nm.pop(); c = f"{r.randint(1, 5)}:{r.randint(10, 55)}"
    add("direct", f"the nightly {n} backup job runs at {c} AM.", f"What time does the nightly {n} backup job run?", [c])
    n = nm.pop(); v = f"{r.randint(2, 9)}.{r.randint(10, 40)}.{r.randint(0, 9)}"
    add("direct", f"our {n} service is pinned to API version {v}.", f"Which API version is our {n} service pinned to?", [v])
    n = nm.pop(); k = n[:3].upper() + str(r.randint(10, 99))
    add("direct", f"the ticket prefix for the {n} project is {k}.", f"What is the ticket prefix for the {n} project?", [k])
    n = nm.pop(); b = f"{n}-archive-{r.randint(100, 999)}"
    add("direct", f"our cold backups go to the bucket {b}.", "Which bucket do our cold backups go to?", [b])
    n = nm.pop(); wf = f"{n.capitalize()}Net-{r.randint(10, 99)}"
    add("direct", f"my home wifi network is called {wf}.", "What is my home wifi network called?", [wf])
    n = nm.pop(); lic = f"{n[:2].upper()}-{r.randint(10000, 99999)}"
    add("direct", f"my {n} software licence number is {lic}.", f"What is my {n} software licence number?", [lic])
    n = nm.pop(); pet = n.capitalize()
    add("direct", f"my cat is named {pet}.", "What is my cat's name?", [pet])
    n = nm.pop(); bk = f"{n.capitalize()} {r.choice(['Gravel', 'Roadster', 'Trail'])}"
    add("direct", f"I ride a {bk} bike.", "What bike do I ride?", [bk])
    # preferences / rules (6)
    add("pref", "I prefer pnpm over npm for every JavaScript project.", "Which package manager should you use when setting up my JS project?", ["pnpm"])
    add("pref", "I prefer tabs over spaces in all my Go code.", "Should the Go code you write for me use tabs or spaces?", ["tab"])
    add("pref", "I prefer Zig over Rust for small command-line tools.", "Which language should you pick for a new small CLI tool of mine?", ["zig"])
    add("pref", "my default shell is fish.", "Which shell do I use by default?", ["fish"])
    add("pref", "always run the linter before you commit anything.", "What should you always do before committing for me?", ["lint"])
    add("pref", "my favourite editor is Helix.", "What is my favourite editor?", ["helix"])
    # paraphrased question (6)
    x = ppl.pop(); n = nm.pop()
    add("para", f"the on-call engineer this quarter is {x}.", "Who do I page if production goes down?", [x.split()[0]])
    n = nm.pop(); p = port()
    add("para", f"we deploy the {n} dashboard behind port {p}.", f"Which network port should I open to reach the {n} dashboard?", [p])
    x = ppl.pop()
    add("para", f"{x} owns the payments migration.", "Who is responsible for moving the payments system over?", [x.split()[0]])
    n = nm.pop(); d = r.choice(["Thursday", "Tuesday", "Wednesday"])
    add("para", f"the {n} release train leaves every {d}.", f"On what day of the week does {n} ship?", [d])
    n = nm.pop(); rg = r.choice(["eu-west-3", "ap-south-2", "us-east-2"])
    add("para", f"all {n} infrastructure lives in the {rg} region.", f"Where, geographically, is the {n} stack hosted?", [rg])
    x = ppl.pop()
    add("para", f"if the build breaks, {x} is the person to ask.", "Who should I ask when the build is red?", [x.split()[0]])
    # updates (4): newest value must win
    for _ in range(4):
        n = nm.pop(); old, new = port(), port()
        add("update", f"my {n} cache listens on port {old}.", f"What port does my {n} cache listen on right now?", [new], [old],
            later=f"update: my {n} cache moved, it now listens on port {new}.")
    # abstention (4)
    for q in ["What is the name of my dentist?", "What is my mother's maiden name?",
              "Which airline did I fly on my last trip to Lisbon?", "What is the serial number of my laptop?"]:
        add("abstain", None, q, [], [])
    return {"S": S}


def hermes(profile: str, prompt: str, timeout: int = 240) -> tuple[str, float, str]:
    t = time.time()
    try:
        p = subprocess.run(["hermes", "-p", profile, "chat", "-Q", "--reasoning", "medium", "-q", prompt],
                           capture_output=True, text=True, timeout=timeout)
        out = p.stdout
        err = "" if p.returncode == 0 else f"rc={p.returncode}"
    except subprocess.TimeoutExpired:
        out, err = "", "timeout"
    lines = [l for l in out.splitlines() if l.strip() and "1Password" not in l and not l.startswith("session_id")]
    return "\n".join(lines).strip(), time.time() - t, err


def grade(sc: dict, ans: str) -> bool:
    ans = ans.replace("\u2019", "'")
    a = ans.casefold()
    if sc["kind"] == "abstain":
        return bool(REFUSE.search(ans))
    return any(e.casefold() in a for e in sc["expect"]) and not any(f.casefold() in a for f in sc["forbid"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    S = scenarios(a.seed)["S"]
    if a.limit:
        S = S[: a.limit]
    r = random.Random(a.seed + 1)
    first = [s for s in S if s["tell"]]
    r.shuffle(first)
    ingest = [(s["id"], f"Remember this for later: {s['tell']} Reply with just 'ok'.") for s in first]
    ingest += [(s["id"], f"Remember this for later: {s['later']} Reply with just 'ok'.") for s in S if s["later"]]
    ingest_errs = 0
    for i, (sid, prompt) in enumerate(ingest):
        _, secs, err = hermes(a.profile, prompt)
        ingest_errs += bool(err)
        print(f"[{a.arm}] ingest {i + 1}/{len(ingest)} {secs:.0f}s {err}", flush=True)
    order = S[:]
    r.shuffle(order)
    rows = []
    for i, s in enumerate(order):
        prompt = ("Answer in one short sentence, from what you already know or remember about me and my work. "
                  f"Do not run commands or search files. Question: {s['ask']}")
        ans, secs, err = hermes(a.profile, prompt)
        ok = grade(s, ans) and not err
        rows.append(dict(id=s["id"], kind=s["kind"], ask=s["ask"], expect=s["expect"], forbid=s["forbid"],
                         answer=ans, ok=ok, secs=round(secs, 1), error=err))
        print(f"[{a.arm}] ask {i + 1}/{len(order)} {'PASS' if ok else 'FAIL'} {s['kind']} {secs:.0f}s", flush=True)
    by = {}
    for k in sorted({x["kind"] for x in rows}):
        sub = [x for x in rows if x["kind"] == k]
        by[k] = dict(n=len(sub), acc=round(sum(x["ok"] for x in sub) / len(sub), 3))
    summary = dict(benchmark="hermes-live", arm=a.arm, profile=a.profile, n=len(rows),
                   acc=round(sum(x["ok"] for x in rows) / len(rows), 3), by_kind=by,
                   ask_p50_s=round(statistics.median(x["secs"] for x in rows), 1),
                   errors=sum(bool(x["error"]) for x in rows) + ingest_errs, seed=a.seed)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    Path(a.out, f"hermes-live-{a.arm}.json").write_text(json.dumps(dict(summary=summary, rows=rows), indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
