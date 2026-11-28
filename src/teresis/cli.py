"""Command line interface: `teresis <command>`."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile

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
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS,
                        help="database path (default $TERESIS_DB or ~/.local/share/teresis/memory.db)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")

    p = argparse.ArgumentParser(prog="teresis", description="Local long-term memory for agents.")
    p.add_argument("--db", default=None, help="database path (default $TERESIS_DB or ~/.local/share/teresis/memory.db)")
    p.add_argument("--json", action="store_true", default=False, help="machine-readable output")
    p.add_argument("--version", action="version", version=f"teresis {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("remember", help="store a memory", parents=[common])
    r.add_argument("content")
    r.add_argument("-s", "--scope", default="global")
    r.add_argument("-k", "--kind", default="fact")
    r.add_argument("--key")
    r.add_argument("-t", "--tag", action="append", default=[])
    r.add_argument("-i", "--importance", type=float, default=0.5)
    r.add_argument("--pin", action="store_true")
    r.add_argument("--ttl-days", type=float)
    r.add_argument("--source")

    q = sub.add_parser("recall", help="search memories", parents=[common])
    q.add_argument("query", nargs="?", default="")
    q.add_argument("-s", "--scope")
    q.add_argument("--no-inherit", action="store_true")
    q.add_argument("-n", "--k", type=int, default=8)
    q.add_argument("--kind", action="append")
    q.add_argument("-t", "--tag", action="append")
    q.add_argument("--budget", type=int, help="token budget")
    q.add_argument("--as-of", type=float, help="unix time for time-travel queries")
    q.add_argument("--explain", action="store_true")

    c = sub.add_parser("context", help="prompt-ready memory block", parents=[common])
    c.add_argument("-s", "--scope", default="global")
    c.add_argument("-q", "--query", default="")
    c.add_argument("--budget", type=int, default=1200)

    u = sub.add_parser("update", help="revise a memory (new version)", parents=[common])
    u.add_argument("id")
    u.add_argument("content", nargs="?")
    u.add_argument("-i", "--importance", type=float)
    u.add_argument("--pin", action=argparse.BooleanOptionalAction, default=None)

    f = sub.add_parser("forget", help="delete a memory", parents=[common])
    f.add_argument("id", nargs="?")
    f.add_argument("-s", "--scope")
    f.add_argument("--key")
    f.add_argument("--hard", action="store_true")

    h = sub.add_parser("history", help="versions of a fact", parents=[common])
    h.add_argument("id", nargs="?")
    h.add_argument("-s", "--scope")
    h.add_argument("--key")

    w2 = sub.add_parser("why", help="explain where a memory came from", parents=[common])
    w2.add_argument("ids", nargs="+")

    sub.add_parser("stats", help="store statistics", parents=[common])
    m = sub.add_parser("maintain", help="purge expired/deleted, optimize indexes", parents=[common])
    m.add_argument("--vacuum", action="store_true")
    sub.add_parser("embed", help="backfill vectors with the configured embedder", parents=[common])
    sub.add_parser("export", help="dump all memories as JSONL to stdout", parents=[common])
    sub.add_parser("import", help="load JSONL from stdin", parents=[common])

    s = sub.add_parser("serve", help="run the MCP server on stdio", parents=[common])
    s.add_argument("-s", "--scope", action="append",
                   help="default scope (repeatable: writes use the first, recall searches all)")

    w = sub.add_parser("http", help="run the local HTTP API", parents=[common])
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=7077)
    w.add_argument("-s", "--scope", action="append")

    hm = sub.add_parser("hermes", help="Hermes Agent integration")
    hm_sub = hm.add_subparsers(dest="hermes_cmd", required=True)
    hi = hm_sub.add_parser("install", help="install the Teresis memory provider", parents=[common])
    hi.add_argument("--home", default=None, help="Hermes home (default $HERMES_HOME or ~/.hermes)")
    hi.add_argument("--link", action="store_true", help="symlink this checkout instead of copying (dev)")
    hi.add_argument("--activate", action="store_true", help="select Teresis for the named Hermes profile")
    hi.add_argument("--profile", help="Hermes profile for --activate (e.g. default or work)")
    hi.add_argument("--dry-run", action="store_true", help="preflight --activate without changing Hermes config")
    him = hm_sub.add_parser("import", help="import built-in Hermes MEMORY.md and USER.md into teresis", parents=[common])
    him.add_argument("--home", default=None, help="Hermes home or profile dir (default $HERMES_HOME or ~/.hermes)")
    him.add_argument("--scope", default=None, help="target scope for MEMORY.md (default from config.yaml)")
    him.add_argument("--user-scope", default="user", help="target scope for USER.md (default: user)")
    him.add_argument("--dry-run", action="store_true", help="count entries without writing")

    b = sub.add_parser("bench", help="run the retrieval benchmark", parents=[common])
    b.add_argument("--scale", type=int, default=10000, help="distractor memories for the latency test")
    sc = sub.add_parser("scrub", help="find bad auto-extracted rows (dry-run unless --apply)", parents=[common])
    sc.add_argument("--apply", action="store_true",
                    help="soft-delete flagged rows. Default is a dry-run and never runs on its own.")
    sc.add_argument("--expiry-days", type=float, default=14.0,
                    help="unreviewed auto-extracted rows older than this are flagged (default 14)")
    rv = sub.add_parser("review", help="list quarantined auto-captured candidates; promote or reject them",
                        parents=[common])
    rv.add_argument("action", nargs="?", default="list", choices=["list", "promote", "reject"])
    rv.add_argument("ids", nargs="*", help="memory ids (or unique prefixes of 6+ characters)")

    ui = sub.add_parser("ui", help="open a local memory inspector in the browser", parents=[common])
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=7878)
    ui.add_argument("--no-browser", action="store_true")

    st = sub.add_parser("setup", help="pin supported desktop MCP launchers to this store", parents=[common])
    st.add_argument("--home", default=None, help="home directory to configure (default ~)")
    st.add_argument("--only", default=None, help="comma-separated client ids")
    st.add_argument("--dry-run", action="store_true")

    dr = sub.add_parser("doctor", help="probe the DB and check saved launcher configuration", parents=[common])
    dr.add_argument("--home", default=None)
    dr.add_argument("--embed", action="store_true", help="also ping the configured embedder")

    sy = sub.add_parser("sync", help="encrypted multi-machine sync")
    sy_sub = sy.add_subparsers(dest="sync_cmd", required=True)
    se = sy_sub.add_parser("export", parents=[common], help="write an encrypted bundle")
    se.add_argument("--out", required=True)
    se.add_argument("--scope", action="append")
    se.add_argument("--key-env", default="TERESIS_SYNC_KEY")
    si = sy_sub.add_parser("import", parents=[common], help="decrypt a bundle and merge it")
    si.add_argument("--in", dest="inp", required=True)
    si.add_argument("--key-env", default="TERESIS_SYNC_KEY")
    si.add_argument("--dry-run", action="store_true")
    sm = sy_sub.add_parser("merge", parents=[common], help="merge another plain teresis .db")
    sm.add_argument("--from", dest="src", required=True)
    sm.add_argument("--dry-run", action="store_true")
    sp = sy_sub.add_parser("push", parents=[common], help="export and copy to host:/path over ssh")
    sp.add_argument("--out", default=None)
    sp.add_argument("--to", required=True)
    sp.add_argument("--key-env", default="TERESIS_SYNC_KEY")
    spl = sy_sub.add_parser("pull", parents=[common], help="fetch host:/path over ssh and merge")
    spl.add_argument("--from", dest="src", required=True)
    spl.add_argument("--in", dest="inp", default=None)
    spl.add_argument("--key-env", default="TERESIS_SYNC_KEY")
    spl.add_argument("--dry-run", action="store_true")

    lk = sub.add_parser("link", help="attach an entity to a memory", parents=[common])
    lk.add_argument("id")
    lk.add_argument("entity")
    lk.add_argument("--kind", default="concept", choices=["person", "project", "host", "tool", "concept"])
    lk.add_argument("--weight", type=float, default=1.0)
    ul = sub.add_parser("unlink", help="detach an entity from a memory", parents=[common])
    ul.add_argument("id")
    ul.add_argument("entity")
    en = sub.add_parser("entities", help="list entities, or rebuild the graph", parents=[common])
    en.add_argument("--limit", type=int, default=50)
    en.add_argument("--rebuild", action="store_true")
    li = sub.add_parser("links", help="entities attached to a memory", parents=[common])
    li.add_argument("id")
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if args.cmd == "bench":
        from .bench import main as bench_main

        return bench_main(scale=args.scale, as_json=args.json)
    if args.cmd == "hermes":
        import os
        from pathlib import Path

        from .hermes import import_memories, install

        home = args.home or os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        if args.hermes_cmd == "install":
            if args.activate:
                from .hermes_install import activate

                if not args.profile or args.home or args.link:
                    p.error("hermes install --activate needs --profile, without --home or --link")
                try:
                    res = activate(args.profile, args.db, dry_run=args.dry_run)
                except (OSError, ValueError) as exc:
                    print(f"Teresis Hermes setup stopped: {exc}", file=sys.stderr)
                    return 1
                if args.json:
                    print(json.dumps(res, indent=2))
                else:
                    print(f"{res['status']}: Teresis for Hermes profile {res['profile']} → {res['db']}")
                    if not args.dry_run:
                        print("Start a new Hermes session and check `hermes memory status` for that profile.")
                return 0
            if args.profile or args.dry_run or args.db:
                p.error("--profile, --dry-run and --db apply to hermes install --activate")
            dest = install(home, link=args.link)
            print(f"installed teresis provider at {dest}\nactivate: hermes config set memory.provider teresis")
            return 0
        res = import_memories(home, db_path=args.db, scope=args.scope, user_scope=args.user_scope,
                              dry_run=args.dry_run)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            mode = "dry-run" if res["dry_run"] else f"created {res['created']}, skipped {res['duplicates']} duplicates"
            print(f"hermes import ({res['hermes_home']} -> {res['db_path']}): "
                  f"{res['memory_entries']} MEMORY.md ({res['scope']}), "
                  f"{res['user_entries']} USER.md ({res['user_scope']}) — {mode}")
        return 0

    if args.cmd == "setup":
        from pathlib import Path

        from .doctor import setup

        rows = setup(None if not args.home else Path(args.home), db=args.db,
                     only=(args.only.split(",") if args.only else None), dry_run=args.dry_run)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['status']:12} {r['name']:14} {r['detail']}")
        return 1 if any(r["status"] in {"failed", "partial"} for r in rows) else 0
    if args.cmd == "doctor":
        from pathlib import Path

        from .doctor import run_doctor

        res = run_doctor(args.db, home=None if not args.home else Path(args.home), embed=args.embed)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            for c in res["checks"]:
                print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['name']:16} {c['detail']}")
            queue = (res.get("provenance") or {}).get("queue") or []
            if queue:
                print(f"\ncandidate queue ({len(queue)}):")
                for it in queue[:10]:
                    print(f"  {it['id']}  [{it['intended_kind']} · origin={it['origin']} · {it['age_days']}d] "
                          f"{(it['content'] or '')[:100]}")
            print(f"\n{'healthy' if res['ok'] else 'problems found'} · db {res['db']}")
        return 0 if res["ok"] else 1

    store = MemoryStore(args.db)
    try:
        if args.cmd == "remember":
            r = store.remember(
                args.content, scope=args.scope, kind=args.kind, key=args.key, tags=args.tag,
                importance=args.importance, pinned=args.pin, ttl_days=args.ttl_days, source=args.source,
                meta={"origin": "user-explicit-tool", "trust": "human"},
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
        elif args.cmd == "why":
            from . import receipt as _receipt

            text, data = _receipt.explain(store, args.ids)
            print(text if not args.json else json.dumps(data, indent=2))
            if not data["receipts"]:
                return 1
        elif args.cmd == "stats":
            print(json.dumps(store.stats(), indent=2))
        elif args.cmd == "maintain":
            print(json.dumps(store.maintain(vacuum=args.vacuum)))
        elif args.cmd == "embed":
            print(f"embedded {store.embed_missing()} memories")
        elif args.cmd == "review":
            from . import review as _review

            items = _review.queue(store)
            if args.action == "list":
                if args.json:
                    print(json.dumps(items, indent=2))
                elif not items:
                    print("review: nothing waiting")
                else:
                    print(f"review: {len(items)} waiting (not injected until promoted)")
                    for it in items:
                        legacy = " legacy-unreviewed" if it["legacy"] else ""
                        print(f"{it['id']}  [{it['intended_kind']} · {it['scope']} · origin={it['origin']} "
                              f"trust={it['trust']} src={it['source']} age={it['age_days']}d "
                              f"seen={it['sessions']}s/{it['days']}d{legacy}]\n    {it['content']}")
                    print("promote: teresis review promote <id>…   reject: teresis review reject <id>…")
            else:
                known = [it["id"] for it in items]
                done, missing = [], []
                for raw in args.ids:
                    hits = [i for i in known if i == raw or (len(raw) >= 6 and i.startswith(raw))]
                    if len(hits) != 1:
                        missing.append(raw)
                        continue
                    if args.action == "promote":
                        _review.promote(store, hits[0], by="review")
                    else:
                        _review.reject(store, hits[0])
                    done.append(hits[0])
                payload = {"action": args.action, "done": done, "not_found": missing}
                print(json.dumps(payload) if args.json else
                      f"review {args.action}: {len(done)} done" + (f", not found/ambiguous: {', '.join(missing)}" if missing else ""))
                if missing or (args.ids == [] and args.action != "list"):
                    return 1
        elif args.cmd == "scrub":
            from . import provenance as _prov
            from .extract import extraction_problem
            from .store import DAY

            flagged = []
            now = store.clock()
            for rec in store.export():
                if rec.get("deleted_at") or rec.get("superseded_by"):
                    continue
                kind, meta, source = rec.get("kind") or "", rec.get("meta") or {}, rec.get("source") or ""
                reviewed = meta.get("promoted_by") == "review"
                reason = None if reviewed else extraction_problem(rec.get("content") or "", kind=kind, source=source)
                if not reason and kind != "episode" and not reviewed:
                    origin = _prov.effective_origin(meta, source, kind)
                    expired = rec.get("expires_at") is not None and rec["expires_at"] <= now
                    age = now - (rec.get("created_at") or now)
                    if source == "hermes:pre-compress":
                        reason = "pre-compress-source"
                    elif origin == _prov.AUTO_CANDIDATE and not _prov.is_promoted(meta):
                        if kind == _prov.CANDIDATE_KIND and expired:
                            reason = "expired-candidate"
                        elif kind != _prov.CANDIDATE_KIND and age > args.expiry_days * DAY:
                            reason = "stale-unreviewed-auto"
                    elif origin == _prov.SYSTEM_TURN:
                        reason = "system-turn-row"
                if reason:
                    flagged.append({"id": rec["id"], "kind": kind, "source": rec.get("source"),
                                    "reason": reason, "content": rec.get("content")})
            removed = 0
            if args.apply:
                for row in flagged:
                    removed += store.forget(row["id"]) or 0
            payload = {"dry_run": not args.apply, "flagged": len(flagged), "removed": removed, "rows": flagged}
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                mode = "applied" if args.apply else "dry-run"
                tail = f", soft-deleted {removed}" if args.apply else ", pass --apply to soft-delete"
                print(f"scrub ({mode}): {len(flagged)} bad extracted rows{tail}")
                if not args.apply:
                    for row in flagged:
                        print(f"{row['id']}  [{row['reason']}] {row['content'][:160]}")
        elif args.cmd == "export":
            for rec in store.export():
                sys.stdout.write(json.dumps(rec) + "\n")
        elif args.cmd == "import":
            print(f"imported {store.import_(json.loads(line) for line in sys.stdin if line.strip())}")
        elif args.cmd == "ui":
            from .ui import serve

            serve(store, host=args.host, port=args.port, open_browser=not args.no_browser)
        elif args.cmd == "sync":
            from pathlib import Path

            from . import sync as _sync

            if args.sync_cmd == "export":
                pw = _sync.passphrase(args.key_env, confirm=True)
                print(json.dumps(_sync.export_bundle(store, Path(args.out), pw, args.scope)))
            elif args.sync_cmd == "import":
                pw = _sync.passphrase(args.key_env)
                recs = _sync.read_bundle(Path(args.inp), pw)
                print(json.dumps(_sync.merge(store, recs, dry_run=args.dry_run)))
            elif args.sync_cmd == "merge":
                other = MemoryStore(args.src, embedder=None)
                try:
                    recs = list(other.export())
                finally:
                    other.close()
                print(json.dumps(_sync.merge(store, recs, dry_run=args.dry_run)))
            elif args.sync_cmd == "push":
                pw = _sync.passphrase(args.key_env, confirm=True)
                out = Path(args.out) if args.out else Path(tempfile.mkdtemp()) / "teresis-sync.json"
                info = _sync.export_bundle(store, out, pw)
                print(json.dumps(info))
                _sync.push(out, args.to)
            else:  # pull
                pw = _sync.passphrase(args.key_env)
                inp = Path(args.inp) if args.inp else Path(tempfile.mkdtemp()) / "teresis-sync.json"
                _sync.pull(args.src, inp)
                recs = _sync.read_bundle(inp, pw)
                print(json.dumps(_sync.merge(store, recs, dry_run=args.dry_run)))
        elif args.cmd == "link":
            print(store.link(args.id, args.entity, kind=args.kind, weight=args.weight))
        elif args.cmd == "unlink":
            print(store.unlink(args.id, args.entity))
        elif args.cmd == "entities":
            if args.rebuild:
                print(json.dumps(store.reindex_entities()))
            for e in store.top_entities(limit=args.limit):
                mark = " explicit" if e["explicit"] else ""
                print(f"{e['memories']:4}  {e['name']}  [{e['kind']}{mark}]")
        elif args.cmd == "links":
            for e in store.entities_for(args.id):
                mark = " explicit" if e["explicit"] else ""
                print(f"{e['weight']:.2f}  {e['name']}  [{e['kind']}{mark}]")
        elif args.cmd == "serve":
            from .mcp import Server

            Server(store, default_scope=args.scope or ["global"]).serve()
        elif args.cmd == "http":
            from .http import serve

            serve(store, host=args.host, port=args.port, default_scope=args.scope or ["global"])
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"teresis: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0
