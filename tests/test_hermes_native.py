"""Run against a Hermes checkout using HERMES_NATIVE_SOURCE and its Python environment."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "teresis"
FIRST = "For future reference, I prefer using the cobalt terminal."
SECOND = "For future reference, we always label backups with juniper."


def exercise_provider(phase):
    from agent.memory_manager import MemoryManager
    from plugins.memory import load_memory_provider

    manager = MemoryManager()
    provider = load_memory_provider("teresis", register_skills=False)
    assert provider is not None, "Hermes did not load Teresis"
    manager.add_provider(provider)
    manager.initialize_all("native-test", platform="cli")
    try:
        if phase != "restart":
            manager.sync_all(FIRST, "Understood.")
            manager.sync_all(SECOND, "Understood.")
            if phase == "capture":
                deadline = time.monotonic() + 5
                while not Path("embedding-started").exists():
                    assert time.monotonic() < deadline, "no embedding request started"
                    time.sleep(0.01)
        else:
            # Verify lexical recall before the delayed index completes, without a query embed.
            for word in ("cobalt", "juniper"):
                assert provider._store.recall(word, lexical_only=True, kinds=["episode"]), word
            assert provider._store.recall("cobalt", lexical_only=True, kinds=["preference"])
            deadline = time.monotonic() + 5
            while provider._store.pending_embeddings(provider._capture_indexer.owner):
                assert time.monotonic() < deadline, "pending embedding work did not resume"
                time.sleep(0.05)
            hits = json.loads(provider.handle_tool_call("memory_recall", {"query": "xqzv91", "k": 20}))
            episodes = [hit["content"] for hit in hits["memories"] if hit["kind"] == "episode"]
            assert any("cobalt" in text for text in episodes), hits
            assert any("juniper" in text for text in episodes), hits
    finally:
        manager.shutdown_all()
    assert manager.shutdown_drain_state["status"] == "drained", manager.shutdown_drain_state
    if phase == "lexical":
        provider = load_memory_provider("teresis", register_skills=False)
        provider.initialize("lexical-restart")
        try:
            for word in ("cobalt", "juniper"):
                assert provider._store.recall(word, kinds=["episode"]), word
            assert provider._store.stats()["vectors"] == 0
        finally:
            provider.shutdown()


@unittest.skipUnless(os.environ.get("HERMES_NATIVE_SOURCE"), "requires a Hermes checkout")
class HermesNativeCaptureTests(unittest.TestCase):
    def test_slow_index_does_not_hold_capture_drain_and_restart_retries_it(self):
        delay = threading.Event()
        requests = []
        self.addCleanup(delay.set)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                inputs = payload["input"]
                requests.append(inputs)
                (root / "semantic" / "embedding-started").touch()
                delay.wait(6.5)
                body = json.dumps({"embeddings": [[1, 0] for _ in inputs]}).encode()
                self.send_response(200)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def run(phase, *, lexical=False):
                    home = root / ("lexical" if lexical else "semantic")
                    plugin = home / "plugins" / "teresis"
                    if not plugin.exists():
                        shutil.copytree(PACKAGE, plugin, ignore=shutil.ignore_patterns("__pycache__"))
                    config = "memory:\n  provider: teresis\nplugins:\n  teresis:\n    db_path: '$HERMES_HOME/memory.db'\n"
                    if not lexical:
                        config += (f"    embed: ollama\n    embed_model: synthetic\n    embed_timeout: 12\n"
                                   f"    embed_url: http://127.0.0.1:{server.server_port}\n")
                    (home / "config.yaml").write_text(config)
                    env = {**os.environ, "HERMES_HOME": str(home),
                           "PYTHONPATH": os.environ["HERMES_NATIVE_SOURCE"]}
                    result = subprocess.run([sys.executable, __file__, phase], cwd=home, env=env,
                                            capture_output=True, text=True, timeout=16)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

                run("capture")
                delay.set()
                run("restart")
                self.assertTrue(any("xqzv91" in batch for batch in requests))
                total = len(requests)
                run("lexical", lexical=True)
                self.assertEqual(len(requests), total)
            finally:
                delay.set()
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    exercise_provider(sys.argv[1])
