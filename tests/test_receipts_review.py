"""Receipts (memory_why) and human-in-chat review (memory_review)."""

import json
import tempfile
import unittest
from pathlib import Path

from teresis import provenance
from teresis import receipt as _receipt
from teresis import review as _review
from teresis.hermes import TeresisMemoryProvider
from teresis.mcp import Server
from teresis.store import MemoryStore

SCOPE = "hermes/max"


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

    def provider(self, db=None, **kw):
        config = {"db_path": db if db is not None else self.db, "scope": SCOPE,
                  "extra_scopes": "user", "embed": "", "rerank": ""}
        init = {"platform": "cli", "agent_identity": "max"}
        init.update(kw.pop("init", {}))
        p = TeresisMemoryProvider(config)
        self.addCleanup(p.shutdown)
        p.initialize("s1", **init)
        return p

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

    def _direct_candidate(self, p, content):
        return p._store.remember(content, scope=SCOPE, kind="candidate",
                                 source="hermes:auto-extract",
                                 meta={"origin": "auto-candidate", "trust": "untrusted",
                                       "candidate_kind": "fact", "seen": []}).id

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
        self.assertEqual(p._review_note, "")

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


if __name__ == "__main__":
    unittest.main()
