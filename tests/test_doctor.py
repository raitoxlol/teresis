import json
import tempfile
import unittest
from pathlib import Path

from teresis.doctor import clients, run_doctor, setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.home = Path(self.d.name)
        (self.home / ".claude.json").write_text(json.dumps({"numStartups": 3}))
        (self.home / ".cursor").mkdir()
        (self.home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text('model = "gpt-5"\n')

    def tearDown(self):
        self.d.cleanup()

    def test_json_clients_configured_and_preserved(self):
        rows = {r["client"]: r for r in setup(self.home)}
        self.assertEqual(rows["claude-code"]["status"], "configured")
        data = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(data["numStartups"], 3)
        self.assertIn("teresis", data["mcpServers"])
        self.assertIn("serve", data["mcpServers"]["teresis"]["args"])
        cursor = json.loads((self.home / ".cursor" / "mcp.json").read_text())
        self.assertIn("other", cursor["mcpServers"])
        self.assertIn("teresis", cursor["mcpServers"])

    def test_toml_appended_and_idempotent(self):
        setup(self.home)
        text = (self.home / ".codex" / "config.toml").read_text()
        self.assertIn('model = "gpt-5"', text)
        self.assertEqual(text.count("[mcp_servers.teresis]"), 1)
        rows = {r["client"]: r for r in setup(self.home)}
        self.assertEqual(rows["codex"]["status"], "already")
        self.assertEqual((self.home / ".codex" / "config.toml").read_text().count("[mcp_servers.teresis]"), 1)

    def test_dry_run_writes_nothing(self):
        rows = {r["client"]: r for r in setup(self.home, dry_run=True)}
        self.assertEqual(rows["claude-code"]["status"], "configured")
        self.assertNotIn("mcpServers", json.loads((self.home / ".claude.json").read_text()))
        self.assertNotIn("[mcp_servers.teresis]", (self.home / ".codex" / "config.toml").read_text())

    def test_only_filter_and_missing_clients(self):
        rows = {r["client"]: r for r in setup(self.home, only=["cursor", "hermes"])}
        self.assertEqual(set(rows), {"cursor", "hermes"})
        self.assertEqual(rows["hermes"]["status"], "skipped")

    def test_bad_json_is_reported_not_clobbered(self):
        (self.home / ".claude.json").write_text("{not json")
        rows = {r["client"]: r for r in setup(self.home)}
        self.assertEqual(rows["claude-code"]["status"], "failed")
        self.assertEqual((self.home / ".claude.json").read_text(), "{not json")


class DoctorTests(unittest.TestCase):
    def test_healthy_on_fresh_db(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            db = home / "doctor.db"
            setup(home)  # an unconfigured but installed client is a real failure, so wire it first
            res = run_doctor(db, home=home)
            names = {c["name"]: c for c in res["checks"]}
            self.assertTrue(names["python"]["ok"])
            self.assertTrue(names["sqlite-fts5"]["ok"])
            self.assertTrue(names["store"]["ok"])
            self.assertTrue(names["graph"]["ok"])
            self.assertEqual(res["failed"], 0)
            self.assertTrue(res["ok"])

    def test_unconfigured_client_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
            res = run_doctor(home / "x.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertFalse(claude["ok"])
            self.assertFalse(res["ok"])

    def test_reports_configured_clients(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
            res = run_doctor(Path(d) / "x.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertFalse(claude["ok"])
            self.assertIn("teresis setup", claude["detail"])
            setup(home)
            res = run_doctor(Path(d) / "x.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertTrue(claude["ok"])

    def test_client_detection(self):
        with tempfile.TemporaryDirectory() as d:
            ids = {c.id for c in clients(Path(d))}
            self.assertEqual(ids, {"claude-code", "cursor", "codex", "hermes"})


if __name__ == "__main__":
    unittest.main()
