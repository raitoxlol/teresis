"""Command line interface: `mnemo <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .store import MemoryStore


def _print_mems(mems, as_json: bool) -> None:
    if as_json:
        print(json.dumps([m.to_dict(compact=True) for m in mems], indent=2))
        return
    if not mems:
        print("(no memories)")
    for m in mems:
        meta = f"{m.kind} · {m.scope}" + (f" · key={m.key}" if m.key else "")
        score = f" · {m.score:.3f}" if m.score is not None else ""
        state = " · SUPERSEDED" if m.superseded_by else (" · DELETED" if m.deleted_at else "")
        print(f"{m.id}  [{meta}{score}{state}]\n    {m.content}")
        if m.why:
            print(f"    why: {m.why}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mnemo", description="Local long-term memory for agents.")
    p.add_argument("--db", help="database path (default $MNEMO_DB or ~/.local/share/mnemo/memory.db)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--version", action="version", version=f"mnemo {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("remember", help="store a memory")
    r.add_argument("content")
    r.add_argument("-s", "--scope", default="global")
    r.add_argument("-k", "--kind", default="fact")
    r.add_argument("--key")
    r.add_argument("-t", "--tag", action="append", default=[])
    r.add_argument("-i", "--importance", type=float, default=0.5)
    r.add_argument("--pin", action="store_true")
    r.add_argument("--ttl-days", type=float)
    r.add_argument("--source")

    q = sub.add_parser("recall", help="search memories")
    q.add_argument("query", nargs="?", default="")
    q.add_argument("-s", "--scope")
    q.add_argument("--no-inherit", action="store_true")
    q.add_argument("-n", "--k", type=int, default=8)
    q.add_argument("--kind", action="append")
    q.add_argument("-t", "--tag", action="append")
    q.add_argument("--budget", type=int, help="token budget")
    q.add_argument("--as-of", type=float, help="unix time for time-travel queries")
    q.add_argument("--explain", action="store_true")

    c = sub.add_parser("context", help="prompt-ready memory block")
    c.add_argument("-s", "--scope", default="global")
    c.add_argument("-q", "--query", default="")
    c.add_argument("--budget", type=int, default=1200)

    u = sub.add_parser("update", help="revise a memory (new version)")
    u.add_argument("id")
    u.add_argument("content", nargs="?")
    u.add_argument("-i", "--importance", type=float)
    u.add_argument("--pin", action=argparse.BooleanOptionalAction, default=None)

    f = sub.add_parser("forget", help="delete a memory")
    f.add_argument("id", nargs="?")
    f.add_argument("-s", "--scope")
    f.add_argument("--key")
    f.add_argument("--hard", action="store_true")

    h = sub.add_parser("history", help="versions of a fact")
    h.add_argument("id", nargs="?")
    h.add_argument("-s", "--scope")
    h.add_argument("--key")

    sub.add_parser("stats", help="store statistics")
    m = sub.add_parser("maintain", help="purge expired/deleted, optimize indexes")
    m.add_argument("--vacuum", action="store_true")
    sub.add_parser("embed", help="backfill vectors with the configured embedder")
    sub.add_parser("export", help="dump all memories as JSONL to stdout")
    sub.add_parser("import", help="load JSONL from stdin")

    s = sub.add_parser("serve", help="run the MCP server on stdio")
    s.add_argument("-s", "--scope", action="append",
                   help="default scope (repeatable: writes use the first, recall searches all)")

    w = sub.add_parser("http", help="run the local HTTP API")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=7077)
    w.add_argument("-s", "--scope", action="append")

    hm = sub.add_parser("hermes", help="Hermes Agent integration")
    hm_sub = hm.add_subparsers(dest="hermes_cmd", required=True)
    hi = hm_sub.add_parser("install", help="install the mnemo memory provider plugin into a Hermes home")
    hi.add_argument("--home", default=None, help="Hermes home (default $HERMES_HOME or ~/.hermes)")
    hi.add_argument("--link", action="store_true", help="symlink this checkout instead of copying (dev)")

    b = sub.add_parser("bench", help="run the retrieval benchmark")
    b.add_argument("--scale", type=int, default=10000, help="distractor memories for the latency test")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "bench":
        from .bench import main as bench_main

        return bench_main(scale=args.scale, as_json=args.json)
    if args.cmd == "hermes":
        import os
        from pathlib import Path

        from .hermes import install

        home = args.home or os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        dest = install(home, link=args.link)
        print(f"installed mnemo provider at {dest}\nactivate: hermes config set memory.provider mnemo")
        return 0

    store = MemoryStore(args.db)
    try:
        if args.cmd == "remember":
            r = store.remember(
                args.content, scope=args.scope, kind=args.kind, key=args.key, tags=args.tag,
                importance=args.importance, pinned=args.pin, ttl_days=args.ttl_days, source=args.source,
            )
            print(json.dumps(r.to_dict()) if args.json else f"{r.status} {r.id}" +
                  (f" (replaced {', '.join(r.replaced)})" if r.replaced else ""))
        elif args.cmd == "recall":
            mems = store.recall(
                args.query, scope=args.scope, inherit=not args.no_inherit, k=args.k, kinds=args.kind,
                tags=args.tag, budget_tokens=args.budget, as_of=args.as_of, explain=args.explain,
            )
            _print_mems(mems, args.json)
        elif args.cmd == "context":
            print(store.context(args.scope, query=args.query, budget_tokens=args.budget))
        elif args.cmd == "update":
            changes = {}
            if args.importance is not None:
                changes["importance"] = args.importance
            if args.pin is not None:
                changes["pinned"] = args.pin
            r = store.update(args.id, args.content, **changes)
            print(json.dumps(r.to_dict()) if args.json else f"{r.status} {r.id}")
        elif args.cmd == "forget":
            print(store.forget(args.id, scope=args.scope, key=args.key, hard=args.hard))
        elif args.cmd == "history":
            _print_mems(store.history(args.id, scope=args.scope, key=args.key), args.json)
        elif args.cmd == "stats":
            print(json.dumps(store.stats(), indent=2))
        elif args.cmd == "maintain":
            print(json.dumps(store.maintain(vacuum=args.vacuum)))
        elif args.cmd == "embed":
            print(f"embedded {store.embed_missing()} memories")
        elif args.cmd == "export":
            for rec in store.export():
                sys.stdout.write(json.dumps(rec) + "\n")
        elif args.cmd == "import":
            print(f"imported {store.import_(json.loads(line) for line in sys.stdin if line.strip())}")
        elif args.cmd == "serve":
            from .mcp import Server

            Server(store, default_scope=args.scope or ["global"]).serve()
        elif args.cmd == "http":
            from .http import serve

            serve(store, host=args.host, port=args.port, default_scope=args.scope or ["global"])
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"mnemo: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0
