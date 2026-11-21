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

REFUSE = re.compile(r"don'?t (?:have|know|remember)|do not (?:have|know)|no (?:record|memory|info)|not (?:sure|aware)|"
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


COLORS = ["amber", "azure", "coral", "indigo", "ivory", "jade", "khaki", "lilac", "maroon", "olive",
          "plum", "rust", "sable", "teal", "umber", "violet", "wheat", "zinc", "crimson", "slate"]
ANIMALS = ["otter", "heron", "lynx", "marmot", "ibis", "kestrel", "badger", "gecko", "puffin", "walrus",
           "tapir", "ocelot", "newt", "bison", "egret", "lemur", "mole", "pika", "stoat", "viper"]
FIRST = ["Priya", "Tomas", "Hana", "Luis", "Mira", "Dev", "Ana", "Jonas", "Keiko", "Omar", "Sven", "Lena",
         "Ravi", "Zoe", "Ivan", "Nia", "Hugo", "Amara", "Felix", "Yuki"]
LAST = ["Raman", "Ekwueme", "Kobayashi", "Ferreira", "Okafor", "Patel", "Lindqvist", "Moreau", "Haddad", "Novak"]


def scenarios_scale(seed: int = 42) -> dict:
    """200 facts told (120 direct, 40 paraphrase, 20 preference, 20 updates); ~100 questions asked."""
    r = random.Random(seed)
    names = [f"{c}-{a}" for c in COLORS for a in ANIMALS]
    r.shuffle(names)
    people = [f"{f} {l}" for f in FIRST for l in LAST]
    r.shuffle(people)
    port = lambda: str(r.randint(1000, 9899))
    S = []

    def add(kind, tell, ask, expect, forbid=(), later=None, asked=True):
        S.append(dict(id=len(S), kind=kind, tell=tell, ask=ask, expect=list(expect), forbid=list(forbid),
                      later=later, asked=asked))

    D = [
        "my {n} database listens on port {v}.|What port does my {n} database listen on?|{v}",
        "my {n} build server sits at 10.{b}.{c}.{d}.|What is the IP address of my {n} build server?|10.{b}.{c}.{d}",
        "the {n} nightly backup job runs at {h}:{m} AM.|What time does the {n} nightly backup job run?|{h}:{m}",
        "our {n} service is pinned to API version {a}.{b}.{c}.|Which API version is our {n} service pinned to?|{a}.{b}.{c}",
        "the ticket prefix for the {n} project is {k}.|What is the ticket prefix for the {n} project?|{k}",
        "our {n} cold backups go to the bucket {n}-archive-{v}.|Which bucket do the {n} cold backups go to?|{n}-archive-{v}",
        "my {n} software licence number is {k}.|What is my {n} software licence number?|{k}",
        "the {n} staging site is served from the hostname {n}.stage.example.net.|What hostname serves the {n} staging site?|{n}.stage.example.net",
        "our {n} worker pool is capped at {v} concurrent jobs.|How many concurrent jobs is the {n} worker pool capped at?|{v}",
        "the {n} cache TTL is set to {v} seconds.|How many seconds is the {n} cache TTL?|{v}",
    ]
    for i in range(120):
        t, q, e = D[i % len(D)].split("|")
        n = names.pop()
        kw = dict(n=n, v=port(), b=r.randint(2, 200), c=r.randint(2, 200), d=r.randint(2, 250),
                  h=r.randint(1, 5), m=r.randint(10, 55), a=r.randint(2, 9), k=n[:3].upper() + str(r.randint(10, 99)))
        add("direct", t.format(**kw), q.format(**kw), [e.format(**kw)], asked=(i % 3 == 0))
    P = [
        "the {n} on-call engineer this quarter is {p}.|Who do I page when {n} goes down?|{f}",
        "{p} owns the {n} payments migration.|Who is responsible for moving {n} payments over?|{f}",
        "if the {n} build breaks, {p} is the person to ask.|Who should I ask when {n} is red?|{f}",
        "the {n} release train leaves every {d}.|On what day of the week does {n} ship?|{d}",
        "all {n} infrastructure lives in the {g} region.|Where, geographically, is the {n} stack hosted?|{g}",
        "the {n} incident channel is #inc-{n}.|Where should I raise an alarm about {n}?|inc-{n}",
        "{p} approves every {n} schema change.|Whose sign-off do I need before altering {n} tables?|{f}",
        "we agreed the {n} retro is held on the {o} Friday of each month.|Which Friday does the {n} team look back on its sprint?|{o}",
    ]
    for i in range(40):
        t, q, e = P[i % len(P)].split("|")
        n = names.pop(); p_ = people.pop()
        kw = dict(n=n, p=p_, f=p_.split()[0], d=r.choice(["Monday", "Tuesday", "Wednesday", "Thursday"]),
                  g=r.choice(["eu-west-3", "ap-south-2", "us-east-2", "sa-east-1"]), o=r.choice(["first", "second", "third", "last"]))
        add("para", t.format(**kw), q.format(**kw), [e.format(**kw)], asked=(i % 2 == 0))
    PR = ["for my {n} project I prefer {a} over {b}.|What do I prefer to use on my {n} project instead of {b}?",
          "on {n} work I always use {a} rather than {b}.|On {n} work, what do I use rather than {b}?"]
    PAIRS = [("pnpm", "npm"), ("Zig", "Rust"), ("Helix", "vim"), ("fish", "bash"), ("Postgres", "MySQL"), ("Caddy", "nginx"),
             ("uv", "pip"), ("Bun", "Node"), ("Ruff", "flake8"), ("Podman", "Docker")]
    for i in range(20):
        t, q = PR[i % 2].split("|")
        a_, b_ = PAIRS[i % len(PAIRS)]
        n = names.pop()
        add("pref", t.format(n=n, a=a_, b=b_), q.format(n=n, b=b_), [a_], asked=(i % 2 == 0))
    for i in range(20):
        n = names.pop(); old, new = port(), port()
        add("update", f"my {n} queue listens on port {old}.", f"What port does my {n} queue listen on right now?", [new], [old],
            later=f"update: my {n} queue moved, it now listens on port {new}.")
    for q in ["What is the name of my dentist?", "What is my mother's maiden name?", "Which airline did I fly to Lisbon?",
              "What is the serial number of my laptop?", "What is my passport number?", "What is the name of my first pet?",
              "Which hospital was I born in?", "What is my landlord's phone number?", "What car do I drive?",
              "What is my gym membership number?"]:
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
    ans = re.sub(r"(?<=\d),(?=\d{3}\b)", "", ans.replace("\u2019", "'"))  # "4,249" == "4249"
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
    ap.add_argument("--scale", action="store_true", help="200-fact run, ~100 questions, batched ingest")
    ap.add_argument("--batch", type=int, default=5, help="statements per ingest session (scale mode)")
    a = ap.parse_args()
    S = scenarios_scale(a.seed)["S"] if a.scale else scenarios(a.seed)["S"]
    if a.limit:
        S = S[: a.limit]
    r = random.Random(a.seed + 1)
    first = [s for s in S if s["tell"]]
    r.shuffle(first)
    if a.scale:
        def batches(items):
            return [items[i:i + a.batch] for i in range(0, len(items), a.batch)]
        stm = [s["tell"] for s in first]
        upd = [s["later"] for s in S if s["later"]]
        ingest = [(0, "Remember these for later, each is a separate fact: " + " ".join(b) + " Reply with just 'ok'.")
                  for b in batches(stm) + batches(upd)]
    else:
        ingest = [(s["id"], f"Remember this for later: {s['tell']} Reply with just 'ok'.") for s in first]
        ingest += [(s["id"], f"Remember this for later: {s['later']} Reply with just 'ok'.") for s in S if s["later"]]
    ingest_errs = 0
    for i, (sid, prompt) in enumerate(ingest):
        _, secs, err = hermes(a.profile, prompt)
        ingest_errs += bool(err)
        print(f"[{a.arm}] ingest {i + 1}/{len(ingest)} {secs:.0f}s {err}", flush=True)
    order = [s for s in S if s.get("asked", True)]
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
    Path(a.out, f"hermes-live-{'scale-' if a.scale else ''}{a.arm}.json").write_text(json.dumps(dict(summary=summary, rows=rows), indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
