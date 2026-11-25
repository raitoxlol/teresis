import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from teresis.hermes_install import activate


class HermesActivationTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.home = Path(d.name) / "profiles/work"
        self.home.mkdir(parents=True)
        self.db = Path(d.name) / "chosen 🪴.db"
        self.values = {"memory.provider": "builtin", "plugins.disabled": []}
        self.writes = []
        self.drop = set()
        self.provider_after_db = None
        self.hermes = patch("teresis.hermes_install.shutil.which", return_value="/fixture/hermes")
        self.run = patch("teresis.hermes_install.subprocess.run", side_effect=self.run_cli)
        self.hermes.start()
        self.run.start()
        self.addCleanup(self.hermes.stop)
        self.addCleanup(self.run.stop)

    def run_cli(self, args, **_):
        self.assertEqual(args[:4], ["/fixture/hermes", "--profile", "work", "config"])
        op, *tail = args[4:]
        if op == "path":
            return subprocess.CompletedProcess(args, 0, str(self.home / "config.yaml") + "\n", "")
        if op == "get":
            key, flag = tail
            self.assertEqual(flag, "--json")
            if key not in self.values:
                return subprocess.CompletedProcess(args, 1, "", f"Config key not set: {key}")
            return subprocess.CompletedProcess(args, 0, json.dumps(self.values[key]), "")
        key, val = tail
        self.writes.append((key, val))
        if key not in self.drop:
            self.values[key] = val
        if key == "plugins.teresis.db_path" and self.provider_after_db:
            self.values["memory.provider"] = self.provider_after_db
        return subprocess.CompletedProcess(args, 0, "", "")

    def test_named_profile_install_is_pinned_and_repeat_does_not_write(self):
        res = activate("work", self.db)
        self.assertEqual(res["status"], "configured")
        self.assertEqual(self.writes, [("plugins.teresis.db_path", str(self.db)), ("memory.provider", "teresis")])
        plugin = Path(res["plugin"]) / "plugin.yaml"
        self.assertTrue(plugin.is_file())
        before = plugin.stat().st_mtime_ns
        self.writes.clear()
        self.assertEqual(activate("work", self.db)["status"], "already")
        self.assertEqual(plugin.stat().st_mtime_ns, before)
        self.assertFalse(self.db.exists())  # selecting a provider does not open or initialize the store
        self.assertEqual(self.writes, [])

    def test_existing_absolute_and_templated_pins_are_reused_without_rewriting(self):
        for pin, expected in ((str(self.db), self.db), ("$HERMES_HOME/work memory.db", self.home / "work memory.db"),
                              ("${HERMES_HOME}/work memory.db", self.home / "work memory.db")):
            with self.subTest(pin=pin):
                self.values["plugins.teresis.db_path"] = pin
                self.values["memory.provider"] = "builtin"
                self.writes.clear()
                res = activate("work")
                self.assertEqual((res["status"], res["db"]), ("configured", str(expected)))
                self.assertEqual(self.writes, [("memory.provider", "teresis")])
                self.assertEqual(self.values["plugins.teresis.db_path"], pin)
                self.writes.clear()
                self.assertEqual(activate("work")["status"], "already")
                self.assertEqual(activate("work", expected)["status"], "already")
                self.assertEqual(self.writes, [])
                self.assertEqual(self.values["plugins.teresis.db_path"], pin)

    def test_relative_pin_is_rejected_before_install(self):
        self.values["plugins.teresis.db_path"] = "relative/memory.db"
        with self.assertRaisesRegex(ValueError, "absolute"):
            activate("work")
        self.assertFalse((self.home / "plugins").exists())
        self.assertEqual(self.writes, [])

    def test_unexpandable_user_pin_is_rejected_before_install(self):
        self.values["plugins.teresis.db_path"] = "~teresis-user-that-does-not-exist/file.db"
        original = Path.expanduser

        def expand(path):
            if str(path).startswith("~teresis-user-that-does-not-exist"):
                raise RuntimeError("Could not determine home directory.")
            return original(path)

        with patch.object(Path, "expanduser", expand):
            with self.assertRaisesRegex(ValueError, "cannot expand the user home"):
                activate("work")
        self.assertFalse((self.home / "plugins").exists())
        self.assertEqual(self.writes, [])
        self.assertEqual(self.values["memory.provider"], "builtin")

    def test_whitespace_pin_is_replaced_with_default(self):
        self.values["plugins.teresis.db_path"] = "   "
        with patch("teresis.hermes_install.default_db_path", return_value=self.db):
            res = activate("work")
        self.assertEqual(res["db"], str(self.db))
        self.assertEqual(self.writes, [("plugins.teresis.db_path", str(self.db)), ("memory.provider", "teresis")])

    def test_activation_hint_quotes_profile_and_dry_run_and_json_are_unchanged(self):
        from teresis.cli import main

        result = {"status": "configured", "profile": "work team", "db": "/tmp/example.db", "plugin": "/tmp/plugin"}
        with patch("teresis.hermes_install.activate", return_value=result):
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["hermes", "install", "--activate", "--profile", "work team"]), 0)
            self.assertIn("Check: hermes --profile 'work team' memory status\n", out.getvalue())
            self.assertIn("Start a new Hermes session to use Teresis.\n", out.getvalue())
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["hermes", "install", "--activate", "--profile", "work team", "--dry-run"]), 0)
            self.assertNotIn("Check:", out.getvalue())
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["hermes", "install", "--activate", "--profile", "work team", "--json"]), 0)
            self.assertEqual(json.loads(out.getvalue()), result)

    def test_dry_run_and_other_provider_do_not_change_profile(self):
        self.assertEqual(activate("work", self.db, dry_run=True)["status"], "planned")
        self.values["memory.provider"] = "holographic"
        with self.assertRaisesRegex(ValueError, "already selects"):
            activate("work", self.db)
        self.assertFalse((self.home / "plugins").exists())
        self.assertEqual(self.writes, [])

    def test_parked_or_different_database_is_rejected_before_install(self):
        self.values["plugins.disabled"] = ["teresis"]
        with self.assertRaisesRegex(ValueError, "explicitly disabled"):
            activate("work", self.db)
        self.values["plugins.disabled"] = []
        self.values["plugins.teresis.db_path"] = str(self.db.with_name("different.db"))
        with self.assertRaisesRegex(ValueError, "different Teresis db_path"):
            activate("work", self.db)
        self.assertFalse((self.home / "plugins").exists())
        self.assertEqual(self.writes, [])

    def test_db_must_persist_before_selection(self):
        self.drop.add("plugins.teresis.db_path")
        with self.assertRaisesRegex(ValueError, "provider not switched"):
            activate("work", self.db)
        self.assertEqual(self.values["memory.provider"], "builtin")
        self.assertEqual(self.writes, [("plugins.teresis.db_path", str(self.db))])

    def test_slot_is_rechecked_before_switching(self):
        self.provider_after_db = "holographic"
        with self.assertRaisesRegex(ValueError, "already selects"):
            activate("work", self.db)
        self.assertEqual(self.values["memory.provider"], "holographic")
        self.assertEqual(self.writes, [("plugins.teresis.db_path", str(self.db))])
