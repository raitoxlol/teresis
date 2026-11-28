"""Credential shapes the durability lab found leaking into the database (E4/E5)."""
import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore
from teresis.secrets import contains_secret, redact_secrets

GOOGLE = "AIza" + "SyDabcdefghijklmnopqrstuvwxyz1234567"


class MoreSecretShapesTests(unittest.TestCase):
    def test_google_api_key(self):
        text, kinds = redact_secrets(f"maps key {GOOGLE} for the lab")
        self.assertNotIn(GOOGLE, text)
        self.assertEqual(kinds, ["google_api_key"])

    def test_card_numbers_with_a_valid_checksum(self):
        for card in ("4111 1111 1111 1111", "5500-0000-0000-0004", "378282246310005", "6011111111111117"):
            text, kinds = redact_secrets(f"my card is {card} expiry 12/30")
            self.assertNotIn(card, text, card)
            self.assertEqual(kinds, ["payment_card"], card)
            self.assertIn("expiry 12/30", text)

    def test_numbers_that_are_not_cards_survive(self):
        for text in ("order 4111 1111 1111 1112 shipped",   # fails the Luhn check
                     "build 20261125123456 finished",       # 14 digits, fails Luhn
                     "phone +81 70 5010 3041",              # too short
                     "ticket 1234567 and 7654321",
                     "unix ms 1795614751000"):
            self.assertEqual(redact_secrets(text)[0], text, text)

    def test_natural_language_password(self):
        text, kinds = redact_secrets("my password is hunter2-hunter2 and the wifi password: Sup3rS3cret!")
        self.assertNotIn("hunter2", text)
        self.assertNotIn("Sup3rS3cret", text)
        self.assertEqual(kinds, ["password_phrase"])
        self.assertIn("my password is", text)

    def test_talking_about_passwords_is_not_redacted(self):
        for text in ("The password is required for login", "password is incorrect", "Your password is strong",
                     "the password manager is 1Password", "reset password: see the docs",
                     "password: <your password here>"):
            self.assertEqual(redact_secrets(text)[0], text, text)

    def test_contains_secret_reports_the_new_kinds(self):
        self.assertEqual(contains_secret("4111111111111111"), "payment_card")
        self.assertEqual(contains_secret(GOOGLE), "google_api_key")


class ImportRedactsTests(unittest.TestCase):
    def test_import_does_not_write_raw_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "i.db"
            s = MemoryStore(db, embedder=None, reranker=None)
            secret = "ghp_" + "a" * 36
            n = s.import_([{"id": "imp0000000000001", "scope": "hermes/lab", "content": f"deploy token {secret} and card 4111 1111 1111 1111",
                            "created_at": 1.0, "updated_at": 1.0}])
            self.assertEqual(n, 1)
            row = s.get("imp0000000000001")
            self.assertNotIn(secret, row.content)
            self.assertNotIn("4111 1111", row.content)
            s.close()
            self.assertNotIn(secret.encode(), db.read_bytes())

    def test_clean_export_still_round_trips_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            a = MemoryStore(Path(d) / "a.db", embedder=None, reranker=None)
            a.remember("plain fact about okapi", scope="user", key="user.okapi")
            rows = list(a.export())
            b = MemoryStore(Path(d) / "b.db", embedder=None, reranker=None)
            b.import_(rows)
            self.assertEqual([r["content"] for r in b.export()], [r["content"] for r in rows])
            a.close(); b.close()


if __name__ == "__main__":
    unittest.main()
