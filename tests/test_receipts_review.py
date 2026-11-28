"""Receipts (memory_why) and human-in-chat review (memory_review)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from teresis import provenance
from teresis import receipt as _receipt
from teresis import review as _review
from teresis.hermes import TeresisMemoryProvider
from teresis.mcp import MAX_TOOL_ITEM_CHARS, MAX_TOOL_OUTPUT_CHARS, Server
from teresis.store import DAY, MemoryStore
from teresis.text import estimate_tokens

SCOPE = "hermes/max"
HOUR = 3600.0


class StoreMixin:
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = MemoryStore(str(Path(self.dir) / "t.db"))
        self.addCleanup(self.store.close)


class ReceiptTests(StoreMixin, unittest.TestCase):
    def test_superseded_and_replaced(self):
        old = self.store.remember("Port is 4400", scope="global", key="app.port").id
        new = self.store.remember("Port is 6600", scope="global", key="app.port").id
        r_new = _receipt.receipt(self.store, new)
        self.assertEqual(r_new["status"], "current")
        self.assertIn("4400", r_new["replaced"][-1]["content"])
        r_old = _receipt.receipt(self.store, old)
        self.assertEqual(r_old["status"], "superseded")
        self.assertEqual(r_old["superseded_by"], new)

    def test_origin_wording_platform_profile(self):
        mid = self.store.remember("Tea over coffee", scope="user",
                                  meta={"origin": "user-typed", "platform": "telegram",
                                        "profile": "max"}).id
        text, _ = _receipt.explain(self.store, [mid])
        self.assertIn("you said this", text)
        self.assertIn("telegram", text)
        self.assertIn("max", text)

    def test_forgotten_and_missing(self):
        mid = self.store.remember("gone", scope="global").id
        self.store.forget(mid)
        r = _receipt.receipt(self.store, mid)
        self.assertEqual(r["status"], "forgotten")
        text, data = _receipt.explain(self.store, [mid, "deadbeefdeadbeef"])
        self.assertIn("deadbeefdeadbeef", data["missing"])
        self.assertIn("[deadbeefdeadbeef] not found", text)

    def test_candidate_status(self):
        mid = self.store.remember("maybe", scope="global", kind="candidate").id
        r = _receipt.receipt(self.store, mid)
        self.assertEqual(r["status"], "candidate")
        text, _ = _receipt.explain(self.store, [mid])
        self.assertIn("never injected", text)

    def test_mcp_no_id_is_error(self):
        server = Server(self.store)
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "memory_why", "arguments": {}}})
        self.assertTrue(resp["result"]["isError"])


class ProviderMixin:
    db = ":memory:"

    def provider(self, db=None, session="s1", **kw):
        config = {"db_path": db if db is not None else self.db, "scope": SCOPE,
                  "extra_scopes": "user", "embed": "", "rerank": "", **kw.pop("config", {})}
        init = {"platform": "cli", "agent_identity": "max"}
        init.update(kw.pop("init", {}))
        p = TeresisMemoryProvider(config)
        self.addCleanup(p.shutdown)
        p.initialize(session, **init)
        return p

    def _direct_candidate(self, p, content):
        return p._store.remember(content, scope=SCOPE, kind="candidate",
                                 source="hermes:auto-extract",
                                 meta={"origin": "auto-candidate", "trust": "untrusted",
                                       "candidate_kind": "fact", "seen": []}).id

    def candidates(self, p, *sentences):
        """Create candidates through the real extraction path (human turn, no strong marker)."""
        for s in sentences:
            p.sync_turn(s, "noted.")
        return [r for r in _review.queue(p._store) if r["scope"] in p._read_scopes]


class HermesWhyTests(ProviderMixin, unittest.TestCase):
    def test_memory_why_this_and_previous_turn(self):
        p = self.provider()
        mid = p._store.remember("Priya owns the billing service.", scope=SCOPE, kind="fact").id
        p.on_turn_start(1, "who owns billing?")
        p.prefetch("who owns billing?")
        out = json.loads(p.handle_tool_call("memory_why", {}))
        self.assertIn("This turn", out["result"])
        self.assertIn(mid, out["result"])
        p.on_turn_start(2, "something unrelated entirely")
        p.prefetch("something unrelated entirely")
        out = json.loads(p.handle_tool_call("memory_why", {}))
        self.assertIn("Previous turn", out["result"])
        self.assertIn(mid, out["result"])
        self.assertNotIn("This turn:", out["result"])

    def test_memory_why_nothing_injected(self):
        p = self.provider()
        out = json.loads(p.handle_tool_call("memory_why", {}))
        self.assertIn("Nothing was injected", out["result"])

    def test_hermes_writes_carry_platform_profile(self):
        p = self.provider(init={"platform": "telegram", "agent_identity": "max"})
        p.sync_turn("I prefer dark themes in every app.", "ok",
                    turn_author={"name": "Max", "id": "u1", "is_bot": False})
        prefs = [m for m in p._store.recall("", scope=["user"], k=50) if m.kind == "preference"]
        self.assertTrue(prefs)
        self.assertEqual(prefs[0].meta.get("platform"), "telegram")
        self.assertEqual(prefs[0].meta.get("profile"), "max")


class ParseReplyTests(unittest.TestCase):
    def test_table(self):
        good = {
            "keep 1 3": [("keep", [1, 3])],
            "Keep 1, 3 and drop 2.": [("keep", [1, 3]), ("drop", [2])],
            "keep all": [("keep", "all")],
            "forget #2": [("drop", [2])],
            "please keep 1": [("keep", [1])],
            "approve 1 and discard 2": [("keep", [1]), ("drop", [2])],
            "keep everything": [("keep", "all")],
        }
        for text, want in good.items():
            self.assertEqual(_review.parse_reply(text), want, text)
        for text in ("keep 2 eggs in the fridge", "drop it", "keep", "yes", "",
                     "keep all of them in mind", "hello there"):
            self.assertIsNone(_review.parse_reply(text), text)


class ReviewFlowTests(ProviderMixin, unittest.TestCase):
    def two_candidates(self, p):
        self.candidates(p, "My database port is 5432. We run Postgres on staging.")
        items = json.loads(p.handle_tool_call("memory_review", {}))
        self.assertEqual(items["waiting"], 2)
        self.assertEqual([i["n"] for i in items["items"]], [1, 2])
        return items["items"]

    def test_keep_via_chat_reply(self):
        p = self.provider()
        items = self.two_candidates(p)
        first, second = items[0]["id"], items[1]["id"]
        self.assertNotIn(first, p.prefetch("database port staging postgres"))
        p.on_turn_start(2, "keep 1")
        m1, m2 = p._store.get(first), p._store.get(second)
        self.assertEqual(m1.kind, items[0]["kind"])
        self.assertEqual(m1.meta.get("promoted_by"), "chat-review")
        self.assertTrue(provenance.injectable(m1.kind, m1.content, m1.meta, m1.source)[0])
        self.assertEqual(m2.kind, "candidate")
        self.assertIn("Memory review", p.prefetch("keep 1"))
        out = json.loads(p.handle_tool_call("memory_review", {}))
        self.assertTrue(out["applied"])

    def test_model_cannot_approve(self):
        p = self.provider()
        items = self.two_candidates(p)
        p.handle_tool_call("memory_review", {"action": "promote",
                                             "ids": [items[0]["id"], items[1]["id"]],
                                             "keep": [1, 2]})
        self.assertEqual(p._store.get(items[0]["id"]).kind, "candidate")
        self.assertEqual(p._store.get(items[1]["id"]).kind, "candidate")

    def test_non_human_turns_do_not_apply(self):
        p = self.provider()
        items = self.two_candidates(p)
        p.on_turn_start(2, "keep 1", author_is_bot=True)
        self.assertEqual(p._store.get(items[0]["id"]).kind, "candidate")
        for init in ({"platform": "cron"}, {"agent_context": "cron", "platform": "cli"}):
            px = self.provider(init=init)
            cid = self._direct_candidate(px, "My database port is 5432.")
            out = json.loads(px.handle_tool_call("memory_review", {}))
            self.assertEqual(out["waiting"], 1)
            px.on_turn_start(2, "keep 1")
            self.assertEqual(px._store.get(cid).kind, "candidate")
            self.assertEqual(px._review_note, "")

    def test_no_offer_no_action(self):
        p = self.provider()
        items = self.candidates(p, "My database port is 5432.")
        p.on_turn_start(2, "keep 1")
        self.assertEqual(p._store.get(items[0]["id"]).kind, "candidate")
        self.assertIn("no review list is pending in this conversation", p._review_note)
        self.assertIn("nothing was changed", p.prefetch("keep 1"))

    def test_offer_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "t.db")
            pa = self.provider(db=db)
            self.candidates(pa, "My database port is 5432.")
            items = json.loads(pa.handle_tool_call("memory_review", {}))["items"]
            target = items[0]["id"]
            pa.shutdown()
            pb = self.provider(db=db)
            pb.on_turn_start(1, "drop 1")
            self.assertIsNotNone(pb._store.get(target).deleted_at)
            pb.shutdown()

    def test_stale_offer_entries_are_skipped(self):
        p = self.provider()
        items = self.two_candidates(p)
        _review.promote(p._store, items[0]["id"], by="review")
        p.on_turn_start(2, "keep 1 2")
        self.assertEqual(p._store.get(items[1]["id"]).kind, items[1]["kind"])
        self.assertIn("skipped", p._review_note)

    def test_scope_filter(self):
        p = self.provider()
        p._store.remember("other scope claim", scope="hermes/other", kind="candidate",
                          meta={"origin": "auto-candidate", "candidate_kind": "fact"})
        out = json.loads(p.handle_tool_call("memory_review", {}))
        self.assertEqual(out["waiting"], 0)
        self.assertEqual(out["items"], [])

    def test_mixed_message_is_not_a_command(self):
        p = self.provider()
        items = self.two_candidates(p)
        p.on_turn_start(2, "keep 2 eggs in the fridge")
        self.assertEqual(p._store.get(items[1]["id"]).kind, "candidate")
        self.assertEqual(p._review_note, "")



T0 = 1_700_000_000.0

_WRITER = """
import sys
from pathlib import Path
from teresis import review
path, tag, n = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
for i in range(n):
    review.save_offer(path, "hermes/max", f"{tag}-{i}", [f"{tag}{i:03d}"], 1_700_000_000.0 + i)
"""


class OfferStoreTests(unittest.TestCase):
    """The offer file on its own: keying, expiry, cap, bad files, concurrent writers."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "t.db.review.json"

    def raw(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["offers"]

    def test_keyed_by_scope_and_session(self):
        _review.save_offer(self.path, SCOPE, "A", ["x"], T0)
        _review.save_offer(self.path, SCOPE, "B", ["y"], T0 + 1)
        _review.save_offer(self.path, "hermes/other", "A", ["z"], T0 + 2)
        self.assertEqual(_review.load_offer(self.path, SCOPE, "A", T0 + 3), ["x"])
        self.assertEqual(_review.load_offer(self.path, SCOPE, "B", T0 + 3), ["y"])
        self.assertEqual(_review.load_offer(self.path, "hermes/other", "A", T0 + 3), ["z"])
        self.assertEqual(_review.load_offer(self.path, SCOPE, "C", T0 + 3), [])

    def test_old_offers_expire_and_are_pruned(self):
        _review.save_offer(self.path, SCOPE, "old", ["x"], T0)
        self.assertEqual(_review.load_offer(self.path, SCOPE, "old", T0 + 23 * HOUR), ["x"])
        self.assertEqual(_review.load_offer(self.path, SCOPE, "old", T0 + 25 * HOUR), [])
        _review.save_offer(self.path, SCOPE, "new", ["y"], T0 + 25 * HOUR)
        self.assertEqual([e["session"] for e in self.raw().values()], ["new"])

    def test_expire_closes_one_session_and_writes_only_when_needed(self):
        self.assertFalse(_review.expire_offer(self.path, SCOPE, "A", T0))
        self.assertFalse(self.path.exists())  # nothing to close: no file is created
        _review.save_offer(self.path, SCOPE, "A", ["x"], T0)
        _review.save_offer(self.path, SCOPE, "B", ["y"], T0 + 1)
        before = self.path.stat().st_ino
        self.assertFalse(_review.expire_offer(self.path, SCOPE, "C", T0 + 2))
        self.assertEqual(self.path.stat().st_ino, before)  # no rewrite
        self.assertTrue(_review.expire_offer(self.path, SCOPE, "A", T0 + 2))
        self.assertEqual(_review.load_offer(self.path, SCOPE, "A", T0 + 2), [])
        self.assertEqual(_review.load_offer(self.path, SCOPE, "B", T0 + 2), ["y"])
        # An offer shown after the one that was read is not removed by the locked write.
        offers = _review.put_offer({}, SCOPE, "A", ["new"], T0 + 5)
        self.assertEqual(_review.get_offer(_review.close_offer(offers, SCOPE, "A", T0 + 5, T0 + 4),
                                           SCOPE, "A", T0 + 5), ["new"])
        self.assertEqual(_review.close_offer(offers, SCOPE, "A", T0 + 5), {})

    def test_count_is_capped_newest_kept(self):
        cap = _review.OFFER_MAX_COUNT
        for i in range(cap + 5):
            _review.save_offer(self.path, SCOPE, f"s{i}", [f"m{i}"], T0 + i)
        sessions = {e["session"] for e in self.raw().values()}
        self.assertEqual(len(sessions), cap)
        self.assertNotIn("s0", sessions)
        self.assertNotIn("s4", sessions)
        self.assertIn("s5", sessions)
        self.assertIn(f"s{cap + 4}", sessions)
        # The in-memory fallback uses the same bounds.
        offers = {}
        for i in range(cap + 5):
            offers = _review.put_offer(offers, SCOPE, f"s{i}", [f"m{i}"], T0 + i)
        self.assertEqual(len(offers), cap)
        self.assertEqual(_review.get_offer(offers, SCOPE, "s0", T0 + cap + 5), [])
        self.assertEqual(_review.get_offer(offers, SCOPE, f"s{cap + 4}", T0 + cap + 5), [f"m{cap + 4}"])

    def test_legacy_and_corrupt_files_hold_no_offer(self):
        # A pre-session file ({scope: {at, ids}}) was not shown in any known conversation.
        self.path.write_text(json.dumps({SCOPE: {"at": T0, "ids": ["x"]}}), encoding="utf-8")
        self.assertEqual(_review.load_offer(self.path, SCOPE, "", T0), [])
        self.assertEqual(_review.load_offer(self.path, SCOPE, "s1", T0), [])
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(_review.load_offer(self.path, SCOPE, "s1", T0), [])
        _review.save_offer(self.path, SCOPE, "s1", ["y"], T0)
        self.assertEqual(_review.load_offer(self.path, SCOPE, "s1", T0), ["y"])
        self.assertEqual(len(self.raw()), 1)

    def test_concurrent_processes_keep_every_offer(self):
        procs, n = 4, 40
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        running = [subprocess.Popen([sys.executable, "-c", _WRITER, str(self.path), f"p{k}", str(n)], env=env)
                   for k in range(procs)]
        for proc in running:
            self.assertEqual(proc.wait(timeout=120), 0)
        offers = self.raw()  # also proves the file is valid JSON
        self.assertEqual(len(offers), procs * n)
        for k in range(procs):
            for i in range(n):
                self.assertEqual(_review.load_offer(self.path, SCOPE, f"p{k}-{i}", T0 + n), [f"p{k}{i:03d}"])
        self.assertEqual([f for f in os.listdir(self.dir.name) if f.endswith(".tmp")], [])


class OfferSessionTests(ProviderMixin, unittest.TestCase):
    """Two conversations on one db and scope, as a gateway and a dashboard process run them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file_db = str(Path(self.tmp.name) / "t.db")
        self.now = [T0]

    def chat(self, session, db=None):
        p = self.provider(db=db or self.file_db, session=session)
        p._store.clock = lambda: self.now[0]
        return p

    def review_ids(self, p):
        return [i["id"] for i in json.loads(p.handle_tool_call("memory_review", {}))["items"]]

    def test_keep_applies_the_list_its_own_conversation_showed(self):
        a, b = self.chat("chat-A"), self.chat("chat-B")
        x = self._direct_candidate(a, "The database port is 5432.")
        self.assertEqual(self.review_ids(a), [x])
        self.now[0] += 2 * HOUR
        y = self._direct_candidate(b, "Deployments go to the eu-west region.")
        self.assertEqual(self.review_ids(b), [y, x])  # newer first: chat B's item 1 is Y
        a.on_turn_start(2, "keep 1")
        self.assertNotEqual(a._store.get(x).kind, "candidate")
        self.assertEqual(a._store.get(y).kind, "candidate")
        self.assertIn(x, a._review_note)
        b.on_turn_start(2, "keep 1")
        self.assertNotEqual(b._store.get(y).kind, "candidate")

    def test_drop_in_other_conversation_cannot_delete_this_list(self):
        a, b = self.chat("chat-A"), self.chat("chat-B")
        x = self._direct_candidate(a, "The database port is 5432.")
        self.assertEqual(self.review_ids(a), [x])
        self.now[0] += 2 * HOUR
        y = self._direct_candidate(b, "Deployments go to the eu-west region.")
        self.assertEqual(self.review_ids(b), [y, x])
        a.on_turn_start(2, "drop 1")
        self.assertIsNone(a._store.get(y).deleted_at)
        self.assertIsNotNone(a._store.get(x).deleted_at)

    def test_reply_in_a_conversation_with_no_list_changes_nothing(self):
        a, c = self.chat("chat-A"), self.chat("chat-C")
        x = self._direct_candidate(a, "The database port is 5432.")
        self.assertEqual(self.review_ids(a), [x])
        c.on_turn_start(2, "keep all")
        self.assertEqual(c._store.get(x).kind, "candidate")
        self.assertIn("no review list is pending", c._review_note)
        a.on_turn_start(2, "keep 1")  # chat A's list is untouched
        self.assertNotEqual(a._store.get(x).kind, "candidate")

    def check_session_switch(self, db):
        p = self.chat("s1", db=db)
        x = self._direct_candidate(p, "The database port is 5432.")
        self.assertEqual(self.review_ids(p), [x])
        # /new: a fresh conversation does not inherit the list.
        p.on_session_switch("s2", parent_session_id="s1", reset=True, reason="new_session")
        p.on_turn_start(2, "keep 1")
        self.assertEqual(p._store.get(x).kind, "candidate")
        self.assertIn("no review list is pending", p._review_note)
        # /resume back into s1: its own list applies again.
        p.on_session_switch("s1", parent_session_id="", reset=False)
        self.assertEqual(self.review_ids(p), [x])
        # Compression continues s1 under a new id: the list follows.
        p.on_session_switch("s1-c", parent_session_id="s1", reset=False, reason="compression")
        p.on_turn_start(3, "keep 1")
        self.assertNotEqual(p._store.get(x).kind, "candidate")
        self.assertIn("kept 1", p._review_note)

    def test_session_switch_file_db(self):
        self.check_session_switch(self.file_db)

    def test_session_switch_memory_db(self):
        self.check_session_switch(":memory:")

    def test_memory_db_offers_are_keyed_by_session(self):
        p = self.chat("s1", db=":memory:")
        x = self._direct_candidate(p, "The database port is 5432.")
        self.assertEqual(self.review_ids(p), [x])
        p.on_session_switch("s2")
        p.on_turn_start(2, "keep 1")
        self.assertEqual(p._store.get(x).kind, "candidate")
        p.on_session_switch("s1")
        p.on_turn_start(3, "keep 1")
        self.assertNotEqual(p._store.get(x).kind, "candidate")
        self.now[0] += 25 * HOUR
        p.on_turn_start(4, "keep 1")  # expired by age
        self.assertIn("no review list is pending", p._review_note)


class OfferLifetimeTests(ProviderMixin, unittest.TestCase):
    """A list can be answered only in the replies right after it is shown, and within 24 hours."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file_db = str(Path(self.tmp.name) / "t.db")
        self.now = [T0]

    def chat(self, db, session="s1"):
        p = self.provider(db=db, session=session)
        p._store.clock = lambda: self.now[0]
        return p

    def shown(self, db):
        """A provider whose conversation was just shown two candidates; returns (p, id1, id2)."""
        p = self.chat(db)
        self._direct_candidate(p, "The database port is 5432.")
        self.now[0] += 1
        self._direct_candidate(p, "Deployments go to the eu-west region.")
        items = json.loads(p.handle_tool_call("memory_review", {}))["items"]
        self.assertEqual(len(items), 2)
        return p, items[0]["id"], items[1]["id"]

    def test_unrelated_message_closes_the_list(self):
        for db in (self.file_db, ":memory:"):
            with self.subTest(db=db):
                self.check_unrelated_message_closes_the_list(db)

    def check_unrelated_message_closes_the_list(self, db):
        p, first, second = self.shown(db)
        p.on_turn_start(2, "Give me three options for the release name.")
        self.assertEqual(p._review_note, "")  # closing is silent
        # The model answered with its own numbered list; the user replies to that one.
        p.on_turn_start(3, "drop 2")
        self.assertIsNone(p._store.get(second).deleted_at)
        self.assertEqual(p._store.get(first).kind, "candidate")
        self.assertIn("nothing was changed", p._review_note)
        self.assertIn("show the list again with memory_review", p._review_note)
        self.assertIn("nothing was changed", p.prefetch("drop 2"))
        # A new memory_review opens a new list, which the next reply answers.
        ids = [i["id"] for i in json.loads(p.handle_tool_call("memory_review", {}))["items"]]
        p.on_turn_start(4, "drop 2")
        self.assertIsNotNone(p._store.get(ids[1]).deleted_at)

    def test_consecutive_replies_all_apply(self):
        for db in (self.file_db, ":memory:"):
            with self.subTest(db=db):
                self.check_consecutive_replies_all_apply(db)

    def check_consecutive_replies_all_apply(self, db):
        p, first, second = self.shown(db)
        p.on_turn_start(2, "keep 1")
        self.assertIn("kept 1", p._review_note)
        p.on_turn_start(3, "drop 2")
        self.assertIn("dropped 1", p._review_note)
        self.assertNotEqual(p._store.get(first).kind, "candidate")
        self.assertIsNotNone(p._store.get(second).deleted_at)

    def test_bot_turn_closes_the_list(self):
        p, first, _ = self.shown(self.file_db)
        p.on_turn_start(2, "keep 1", author_is_bot=True)
        p.on_turn_start(3, "keep 1")
        self.assertEqual(p._store.get(first).kind, "candidate")
        self.assertIn("nothing was changed", p._review_note)

    def test_lists_expire_after_24_hours(self):
        for db in (self.file_db, ":memory:"):
            with self.subTest(db=db):
                self.check_lists_expire_after_24_hours(db)

    def check_lists_expire_after_24_hours(self, db):
        p, first, second = self.shown(db)
        self.now[0] += 23 * HOUR
        p.on_turn_start(2, "keep 1")
        self.assertNotEqual(p._store.get(first).kind, "candidate")
        self.now[0] += 2 * HOUR
        p.on_turn_start(3, "drop 2")
        self.assertIsNone(p._store.get(second).deleted_at)
        self.assertIn("nothing was changed", p._review_note)

    def test_closing_is_per_conversation_and_skips_writes_without_a_list(self):
        a, first, _ = self.shown(self.file_db)
        b = self.chat(self.file_db, session="s2")
        path = Path(self.file_db + ".review.json")
        before = path.stat().st_ino
        b.on_turn_start(1, "What is on the calendar today?")
        self.assertEqual(path.stat().st_ino, before)  # B had no list: the file is not rewritten
        a.on_turn_start(2, "keep 1")  # A's list is still open
        self.assertNotEqual(a._store.get(first).kind, "candidate")
        a.on_turn_start(3, "thanks")
        self.assertNotEqual(path.stat().st_ino, before)  # A's list closed: one locked, atomic write
        self.assertEqual(_review.load_offer(path, SCOPE, "s1", self.now[0]), [])


class WhyBoundsTests(ProviderMixin, unittest.TestCase):
    """memory_why is clipped like recall: 1200 characters per text field, 20000 per reply."""

    def big(self, i, n=6000):
        return f"Fact {i}: " + " ".join(f"w{i}x{j}" for j in range(n // 6))[:n]

    def setUp(self):
        self.p = self.provider()
        store = self.p._store
        self.ids = [store.remember(self.big(i), scope=SCOPE, kind="fact").id for i in range(30)]
        store.remember(self.big(100), scope=SCOPE, key="app.notes")
        self.keyed = store.remember(self.big(101), scope=SCOPE, key="app.notes").id

    def check(self, out, requested):
        self.assertEqual({"result", "receipts", "missing"} - set(out), set())
        self.assertLessEqual(len(out["result"]), MAX_TOOL_OUTPUT_CHARS + 60)
        self.assertLessEqual(len(json.dumps(out["receipts"])), MAX_TOOL_OUTPUT_CHARS)
        self.assertTrue(out["receipts"])
        limit = MAX_TOOL_ITEM_CHARS + len("... [truncated, 99999 chars]")
        for r in out["receipts"]:
            self.assertLessEqual(len(r["content"]), limit)
            self.assertIn("truncated", r["content"])
            self.assertTrue({"id", "origin", "status", "replaced"} <= set(r))
            for v in r["replaced"]:
                self.assertLessEqual(len(v["content"]), limit)
        self.assertEqual(len(out["receipts"]) + len(out["missing"]) + out.get("omitted", 0), requested)
        self.assertIn("more not shown", out["result"])

    def test_tool_call_with_ids(self):
        ids = [self.keyed] + self.ids
        out = json.loads(self.p.handle_tool_call("memory_why", {"ids": ids}))
        self.check(out, len(ids))
        self.assertEqual(out["receipts"][0]["id"], self.keyed)
        self.assertTrue(out["receipts"][0]["replaced"])
        text, data = Server(self.p._store).call_tool("memory_why", {"ids": ids})
        self.assertEqual(text, out["result"])

    def test_no_argument_path(self):
        # What prefetch injected this turn and last turn (set directly: the packet would trim them).
        self.p._last_ids, self.p._prev_ids = self.ids[:15], self.ids[15:]
        out = json.loads(self.p.handle_tool_call("memory_why", {}))
        self.check(out, 30)
        self.assertTrue(out["result"].startswith("This turn:"))

    def test_small_reply_unchanged(self):
        mid = self.p._store.remember("Tea over coffee", scope=SCOPE).id
        out = json.loads(self.p.handle_tool_call("memory_why", {"id": mid}))
        self.assertEqual(out["result"], _receipt.explain(self.p._store, [mid])[0])
        self.assertNotIn("omitted", out)


class ReviewNoteBudgetTests(ProviderMixin, unittest.TestCase):
    """The "Memory review" note is part of the prefetch packet and its budget."""

    QUERY = "who owns the billing service"

    def setUp(self):
        self.p = self.provider()
        cid = self._direct_candidate(self.p, "The database port is 5432.")
        self.p.handle_tool_call("memory_review", {})
        self.fact = self.p._store.remember("Priya owns the billing service.", scope=SCOPE).id
        self.p.on_turn_start(2, "keep 1")
        self.assertNotEqual(self.p._store.get(cid).kind, "candidate")

    def prefetch(self, budget, query=None):
        self.p._config["prefetch_budget_tokens"] = budget
        return self.p.prefetch(query or self.QUERY)

    def test_budget_boundary(self):
        full = self.prefetch(10_000)
        self.assertTrue(full.startswith("## Memory review (teresis)"))
        self.assertIn(self.fact, full)
        need = estimate_tokens(full)
        self.assertEqual(self.prefetch(need), full)
        under = self.prefetch(need - 1)
        self.assertLessEqual(estimate_tokens(under), need - 1)
        self.assertIn("Memory review", under)
        self.assertNotIn(self.fact, under)
        self.assertEqual(self.p._last_ids, [])

    def test_note_alone_is_cut_to_budget(self):
        note = self.p._review_note
        self.assertEqual(self.prefetch(estimate_tokens(note), "ok"), note)
        for budget in (estimate_tokens(note) - 1, 20, 3, 1):
            out = self.prefetch(budget, "ok")
            self.assertTrue(out)
            self.assertLessEqual(estimate_tokens(out), budget)
            self.assertLessEqual(estimate_tokens(self.prefetch(budget)), budget)
        self.assertEqual(self.prefetch(0), "")

    def test_long_note_drops_items_but_keeps_the_instruction(self):
        p = self.provider()
        for i in range(8):
            self._direct_candidate(p, f"Claim {i}: " + " ".join(f"t{i}y{j}" for j in range(400)))
        p.handle_tool_call("memory_review", {"limit": 8})
        p.on_turn_start(2, "keep all")
        self.assertIn("kept 8", p._review_note)
        p._config["prefetch_budget_tokens"] = 400
        out = p.prefetch("ok")
        self.assertLessEqual(estimate_tokens(out), 400)
        self.assertIn("kept 8", out)
        self.assertIn("more not shown", out)
        self.assertTrue(out.endswith("Confirm this to the user in one line."))

if __name__ == "__main__":
    unittest.main()
