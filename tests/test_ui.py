import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from teresis import MemoryStore
from teresis.ui import make_handler


class UiTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.d.name) / "ui.db", embedder=None)
        self.mem = self.store.remember("Atlas uses PostgreSQL 16", scope="project/atlas", key="atlas.db")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, "tok"))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()
        self.d.cleanup()

    def get(self, path, token=None):
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {token or 'tok'}"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())

    def post(self, path, body, token="tok"):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())

    def test_index_serves_html(self):
        with urllib.request.urlopen(self.base + "/") as r:
            body = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn("teresis", body)
        self.assertIn("memory inspector", body)

    def test_stats_scopes_and_list(self):
        _, stats = self.get("/api/stats")
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["version"], self.store and stats["version"])
        _, scopes = self.get("/api/scopes")
        self.assertEqual(scopes[0]["scope"], "project/atlas")
        _, rows = self.get("/api/memories?scope=project/atlas")
        self.assertEqual(rows[0]["content"], "Atlas uses PostgreSQL 16")

    def test_detail_has_entities_and_history(self):
        _, detail = self.get(f"/api/memories/{self.mem.id}")
        self.assertEqual(detail["memory"]["id"], self.mem.id)
        self.assertTrue(any(e["key"] == "atlas" for e in detail["entities"]))
        self.assertEqual(len(detail["history"]), 1)

    def test_recall_endpoint(self):
        _, hits = self.get("/api/recall?q=postgres&scope=project/atlas")
        self.assertEqual(hits[0]["id"], self.mem.id)

    def test_pin_and_forget(self):
        _, res = self.post(f"/api/memories/{self.mem.id}/pin", {"pinned": True})
        self.assertEqual(res["status"], "updated")
        self.assertTrue(self.store.get(self.mem.id).pinned)
        _, res = self.post(f"/api/memories/{self.mem.id}/forget", {})
        self.assertEqual(res["removed"], 1)
        self.assertIsNotNone(self.store.get(self.mem.id).deleted_at)

    def test_writes_need_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(f"/api/memories/{self.mem.id}/pin", {"pinned": True}, token="bad")
        self.assertEqual(ctx.exception.code, 401)

    def test_create_and_edit(self):
        _, res = self.post("/api/memories", {"content": "Atlas moved to Postgres 17", "scope": "project/atlas",
                                             "key": "atlas.db"})
        self.assertEqual(res["status"], "superseded")
        _, detail = self.get(f"/api/memories/{res['id']}")
        self.assertEqual(len(detail["history"]), 2)

    def test_entities_endpoint(self):
        _, ents = self.get("/api/entities?limit=10")
        self.assertTrue(any(e["key"] == "atlas" for e in ents))


if __name__ == "__main__":
    unittest.main()
