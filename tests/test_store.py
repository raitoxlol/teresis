import io
import json
import multiprocessing as mp
import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore, scope_chain
from teresis.mcp import Server
from teresis.store import DAY


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _writer(path, n, tag):
    s = MemoryStore(path, embedder=None)
    for i in range(n):
        s.remember(f"process {tag} wrote fact number {i} about topic{i}", scope=f"p/{tag}")
    s.close()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "m.db"
        self.clock = Clock()
        self.s = MemoryStore(self.path, embedder=None, clock=self.clock)

    def tearDown(self):
        self.s.close()
        self.dir.cleanup()

    def test_scope_chain(self):
        self.assertEqual(scope_chain("project/a/agent"), ["project/a/agent", "project/a", "project", "global"])
        self.assertEqual(scope_chain("global"), ["global"])

    def test_remember_and_recall(self):
        r = self.s.remember("The API gateway retries failed requests three times", scope="project/x")
        self.assertEqual(r.status, "created")
        hits = self.s.recall("gateway retry", scope="project/x")
        self.assertEqual(hits[0].id, r.id)

    def test_exact_duplicate_reinforces(self):
        a = self.s.remember("User likes dark mode", scope="user")
        b = self.s.remember("user likes   dark mode!", scope="user", importance=0.9)
        self.assertEqual(b.status, "duplicate")
        self.assertEqual(a.id, b.id)
        m = self.s.get(a.id)
        self.assertEqual(m.access_count, 1)
        self.assertAlmostEqual(m.importance, 0.9)
        self.assertEqual(self.s.stats()["active"], 1)

    def test_refinement_supersedes(self):
        a = self.s.remember("Staging deploys happen on Fridays", scope="p")
        b = self.s.remember("Staging deploys happen on Fridays after the QA sign-off", scope="p")
        self.assertEqual(b.status, "refined")
        self.assertEqual(b.replaced, [a.id])
        self.assertEqual([m.id for m in self.s.recall("staging deploys", scope="p")], [b.id])

    def test_key_supersession_and_history(self):
        a = self.s.remember("Editor is VS Code", scope="user", key="user.editor")
        self.clock.t += DAY
        b = self.s.remember("Editor is Neovim", scope="user", key="user.editor")
        self.assertEqual(b.status, "superseded")
        self.assertEqual(b.replaced, [a.id])
        ids = [m.id for m in self.s.recall("editor", scope="user")]
        self.assertEqual(ids, [b.id])
        self.assertEqual([m.id for m in self.s.history(b.id)], [a.id, b.id])
        self.assertEqual([m.id for m in self.s.history(scope="user", key="user.editor")], [a.id, b.id])

    def test_time_travel(self):
        t0 = self.clock.t
        a = self.s.remember("Database is MySQL", scope="p", key="db")
        self.clock.t += 10 * DAY
        b = self.s.remember("Database is PostgreSQL", scope="p", key="db")
        self.assertEqual(self.s.recall("database", scope="p", as_of=t0 + DAY)[0].id, a.id)
        self.assertEqual(self.s.recall("database", scope="p")[0].id, b.id)

    def test_scope_isolation_and_inheritance(self):
        g = self.s.remember("Never push to main directly", scope="global")
        a = self.s.remember("Service port is 4000", scope="project/a")
        b = self.s.remember("Service port is 5000", scope="project/b")
        ids = {m.id for m in self.s.recall("service port push main", scope="project/a")}
        self.assertIn(a.id, ids)
        self.assertIn(g.id, ids)
        self.assertNotIn(b.id, ids)
        ids = {m.id for m in self.s.recall("service port", scope="project/a", inherit=False)}
        self.assertEqual(ids, {a.id})

    def test_typo_tolerance(self):
        r = self.s.remember("We replicate SQLite with Litestream to S3", scope="p")
        self.s.remember("Unrelated note about lunch plans", scope="p")
        self.assertEqual(self.s.recall("litstream", scope="p")[0].id, r.id)

    def test_ttl_expiry_and_maintain(self):
        self.s.remember("Temporary freeze on merges", scope="p", ttl_days=1)
        self.assertEqual(len(self.s.recall("freeze", scope="p")), 1)
        self.clock.t += 2 * DAY
        self.assertEqual(self.s.recall("freeze", scope="p"), [])
        self.assertEqual(self.s.maintain()["expired"], 1)

    def test_forget(self):
        a = self.s.remember("Remove me later", scope="p")
        self.assertEqual(self.s.forget(a.id), 1)
        self.assertEqual(self.s.recall("remove", scope="p"), [])
        self.assertIsNotNone(self.s.get(a.id).deleted_at)

    def test_update_versions(self):
        a = self.s.remember("Cache TTL is 5 minutes", scope="p")
        r = self.s.update(a.id, "Cache TTL is 15 minutes")
        self.assertEqual(self.s.get(a.id).superseded_by, r.id)
        self.s.update(r.id, importance=0.9, pinned=True)
        self.assertTrue(self.s.get(r.id).pinned)

    def test_budget_packing(self):
        for i in range(30):
            self.s.remember(f"Fact {i}: " + "word " * 40 + f"marker{i}", scope="p")
        out = self.s.recall("word", scope="p", k=100, budget_tokens=200)
        self.assertTrue(0 < len(out) < 30)

    def test_recency_breaks_ties(self):
        self.clock.t -= 100 * DAY
        old = self.s.remember("Incident: resizer crashed with OOM", scope="p", kind="event")
        self.clock.t += 99 * DAY
        new = self.s.remember("Incident: resizer crashed with OOM after upgrade", scope="p", kind="event",
                              key=None)
        hits = self.s.recall("resizer OOM incident", scope="p")
        self.assertEqual(hits[0].id, new.id)
        self.assertNotIn(old.id, [h.id for h in hits])  # refinement superseded it

    def test_context_block(self):
        self.s.remember("Never commit secrets", scope="global", pinned=True, importance=1.0)
        self.s.remember("Project uses pnpm", scope="project/a")
        block = self.s.context("project/a", query="package manager")
        self.assertIn("Never commit secrets", block)
        self.assertIn("pnpm", block)
        self.assertTrue(block.startswith("<memory"))

    def test_export_import_roundtrip(self):
        self.s.remember("A", scope="p", key="k")
        self.s.remember("B", scope="p", key="k")
        recs = list(self.s.export())
        other = MemoryStore(Path(self.dir.name) / "o.db", embedder=None)
        self.assertEqual(other.import_(recs), 2)
        self.assertEqual(other.recall("B", scope="p")[0].content, "B")
        self.assertEqual(other.stats()["superseded"], 1)
        other.close()

    def test_concurrent_processes(self):
        ctx = mp.get_context("spawn")
        procs = [ctx.Process(target=_writer, args=(str(self.path), 50, t)) for t in "abcd"]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(self.s.stats()["active"], 200)

    def test_fake_embedder_vector_channel(self):
        class Emb:
            name = "fake"

            def embed(self, texts):
                vocab = ["coffee", "drink", "gpu", "graphics"]
                return [[1.0 if w in t.lower() else 0.01 for w in vocab] for t in texts]

        s = MemoryStore(Path(self.dir.name) / "v.db", embedder=Emb())
        m = s.remember("Prefers coffee drink in the morning", scope="u")
        s.remember("Has a big gpu", scope="u")
        hits = s.recall("coffee drink", scope="u", explain=True)
        self.assertEqual(hits[0].id, m.id)
        self.assertIn("vector", hits[0].why["channels"])
        s.close()

    def test_possessive_and_contraction_tokens(self):
        m = self.s.remember("Caroline uses Neovim for Rust", scope="u")
        hits = self.s.recall("What is Caroline's editor?", scope="u")
        self.assertTrue(hits and hits[0].id == m.id)

    def test_temporal_window_boost(self):
        import datetime as dt
        t_old = dt.datetime(2023, 1, 16, 12, 0, tzinfo=dt.timezone.utc).timestamp()
        t_other = dt.datetime(2022, 10, 5, 12, 0, tzinfo=dt.timezone.utc).timestamp()
        t_now = dt.datetime(2023, 2, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp()
        clock = {"t": t_other}
        s = MemoryStore(Path(self.dir.name) / "tmp.db", embedder=None, clock=lambda: clock["t"])
        s.remember("Attended an art event at the Civic Hall", scope="u")
        clock["t"] = t_old
        m_two_weeks = s.remember("Attended an art event at the River Gallery", scope="u")
        clock["t"] = t_now
        hits = s.recall("Where was the art event two weeks ago?", scope="u", explain=True)
        self.assertEqual(hits[0].id, m_two_weeks.id)
        self.assertGreater(hits[0].why["temporal"], 1.1)
        s.close()

    def test_compound_sub_query_retrieval(self):
        for i in range(6):
            self.s.remember(f"Project Atlas milestone note {i} about database migration", scope="u")
        m_helios = self.s.remember("Project Helios launched on Tuesday", scope="u")
        hits = self.s.recall("Which started first, 'Project Atlas' or 'Project Helios'?", scope="u", k=3)
        self.assertIn(m_helios.id, [h.id for h in hits[:3]])

    def test_pluggable_reranker(self):
        class FakeReranker:
            name = "fake-ce"

            def rerank(self, query, docs):
                return [10.0 if "single parent" in d else -5.0 for d in docs]

        s = MemoryStore(Path(self.dir.name) / "rr.db", embedder=None, reranker=FakeReranker())
        s.remember("Caroline talked about relationship advice with friends", scope="u")
        m_target = s.remember("Caroline said it will be tough as a single parent", scope="u")
        hits = s.recall("Caroline relationship status", scope="u", explain=True)
        self.assertEqual(hits[0].id, m_target.id)
        self.assertIn("rerank", hits[0].why)
        s.close()


class McpTests(unittest.TestCase):
    def test_protocol_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = MemoryStore(Path(d) / "m.db", embedder=None)
            reqs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_remember",
                 "arguments": {"content": "Atlas uses PostgreSQL", "scope": "project/atlas", "key": "db"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_recall",
                 "arguments": {"query": "atlas database", "scope": "project/atlas"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "memory_update",
                 "arguments": {"id": "nope", "content": "x"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "bogus"},
            ]
            out = io.StringIO()
            Server(store).serve(io.StringIO("\n".join(json.dumps(r) for r in reqs) + "\nnot json\n"), out)
            resps = [json.loads(line) for line in out.getvalue().splitlines()]
            by_id = {r["id"]: r for r in resps}
            self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(len(by_id[2]["result"]["tools"]), 9)
            self.assertIn("created", by_id[3]["result"]["content"][0]["text"])
            self.assertIn("PostgreSQL", by_id[4]["result"]["content"][0]["text"])
            self.assertTrue(by_id[5]["result"]["isError"])
            self.assertEqual(by_id[6]["error"]["code"], -32601)
            self.assertEqual(by_id[None]["error"]["code"], -32700)
            self.assertEqual(len(resps), 7)  # notification got no response
            store.close()


if __name__ == "__main__":
    unittest.main()
