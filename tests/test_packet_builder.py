"""evidence.build_packet: byte-identical prefetch text, reason codes, memory_why notes, `teresis packet`.

``legacy_prefetch`` below is a frozen copy of the prefetch assembly as it was before the packet
builder (commit 06e074b). The parity tests pin the injected text to it byte for byte.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from teresis import cli
from teresis import evidence as E
from teresis import provenance as _prov
from teresis import receipt as _receipt
from teresis import secrets as _secrets
from teresis import temporal as _temporal
from teresis.hermes import TeresisMemoryProvider
from teresis.store import MemoryStore
from teresis.text import estimate_tokens, tokens

SCOPE = "hermes/replay"
ASK = "Is the billing service owner available?"
T0 = 1_700_000_000.0


# -- frozen reference: prefetch before evidence.build_packet (06e074b) ---------------------------

_L_WEAK = frozenset(
    t + suffix
    for t in """like want need order get make use have take give please help really just more some also
    thing things stuff good bad new one user call write read file run set put see look time day
    way work said first later check about would could should done yeah yes okay thanks something
    anything remotely table place can""".split()
    for suffix in ("", "s", "es", "ed", "ing")
)


def _l_trivial(text):
    t = (text or "").strip().lower().strip("!?. ")
    return not t or t.startswith("/") or t in {"ok", "okay", "yes", "no", "thanks", "thank you", "hi", "hey",
                                                "continue", "go ahead", "do it", "done", "next", "lgtm", "k"}


def _l_covers(q, m):
    if q == m:
        return True
    if len(q) < 4 or not m.startswith(q):
        return False
    return m[len(q):] in {"s", "es", "ed", "ing", "d"}


def _l_relevant(query, content, *, floor, score):
    if (score or 0) < floor:
        return False
    distinctive = [t for t in tokens(query) if len(t) >= 4 and t not in _L_WEAK]
    if not distinctive:
        return False
    memory_toks = [t for t in tokens(content) if t not in _L_WEAK]
    return any(_l_covers(q, m) for q in distinctive for m in memory_toks)


def _l_fit_note(lines, budget):
    if not lines or budget <= 0:
        return ""
    head, items, tail = lines[:2], lines[2:-1], lines[-1:]
    text = ""
    for n in range(len(items), -1, -1):
        more = [f"- ... {len(items) - n} more not shown"] if n < len(items) else []
        text = "\n".join(head + items[:n] + more + tail)
        if estimate_tokens(text) <= budget:
            return text
    cap = 4 * budget
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _l_trim(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


class _LegacyPacket:
    def __init__(self, limit, budget, text=""):
        self.limit, self.budget, self.text, self.ids, self._section = limit, budget, text, set(), ""

    @property
    def full(self):
        return len(self.ids) >= self.limit or self.budget <= 0

    def add(self, memory, section, *, via=""):
        if self.full or memory.id in self.ids:
            return False
        label = memory.kind + (f" {memory.key}" if memory.key else "")
        ref = f"; linked from {via}" if via else ""
        content = _temporal.with_saved_note(memory.content, memory.created_at,
                                            display_content=_l_trim(memory.content, 1200))
        line = f"- [{label}] {content} (id {memory.id}{ref})"
        header = "" if self._section == section else ("\n" if self.text else "") + "## " + section + "\n"
        fragment = ("\n" if self.text else "") + header + line
        if estimate_tokens(self.text + fragment) > self.budget:
            return False
        self.text += fragment
        self.ids.add(memory.id)
        self._section = section
        return True


def _l_truthy(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes", "on"}


def legacy_prefetch(p, query):
    """(text, ids) exactly as the pre-builder prefetch produced them. ``p`` needs _config,
    _store, _read_scopes, _scope and _review_lines."""
    try:
        budget = int(p._config["prefetch_budget_tokens"])
    except (TypeError, ValueError):
        budget = 700
    note = _l_fit_note(p._review_lines, budget)
    if not p._store or _l_trivial(query):
        return note, []
    try:
        k = min(30, int(p._config["prefetch_k"]))
        packet = _LegacyPacket(k, int(p._config["prefetch_budget_tokens"]), text=note)
        if packet.full:
            return note, []
        query = _secrets.redact_secrets(query)[0]
        try:
            floor = float(p._config.get("prefetch_min_score", 0.45))
        except (TypeError, ValueError):
            floor = 0.45
        direct = p._store.recall(query, scope=p._read_scopes, k=min(60, max(12, 3 * k)),
                                 exclude_kinds=["episode", _prov.CANDIDATE_KIND], touch=False, expand_entities=False)
        anchors = []
        for m in direct:
            if packet.full:
                break
            if (_l_relevant(query, m.content, floor=floor, score=m.score)
                    and _prov.injectable(m.kind, m.content, m.meta, m.source)[0]
                    and packet.add(m, "Long-term memory (teresis)")):
                anchors.append(m)
        if not packet.full and p._store.w.entity_hop > 0 and _l_truthy(p._config["prefetch_linked"]):
            for anchor in anchors[:3]:
                linked = False
                for peer in p._store.unique_peers(anchor):
                    if (_prov.injectable(peer.kind, peer.content, peer.meta, peer.source)[0]
                            and packet.add(peer, "Related facts (shared entity)", via=anchor.id)):
                        anchors.append(peer)
                        linked = True
                        break
                if linked:
                    break
        if not packet.full and _l_truthy(p._config["capture_turns"]):
            episodes = p._store.recall(query, scope=[p._scope], inherit=False, kinds=["episode"],
                                       k=8, touch=False, expand_entities=False)
            known = [" ".join(m.content.casefold().split()).removeprefix("user: ") for m in anchors]
            accepted = 0
            for m in episodes:
                if packet.full or accepted >= 2:
                    break
                body = " ".join(m.content.casefold().split())
                if (_prov.injectable(m.kind, m.content, m.meta, m.source)[0]
                        and _l_relevant(query, m.content, floor=max(0.3, floor), score=m.score)
                        and not any(k and k in body for k in known)
                        and packet.add(m, "Related past conversation")):
                    accepted += 1
        return packet.text, sorted(packet.ids)
    except Exception:
        return note, []


def legacy_for(store, scopes, *, limit, budget, min_score=0.45, linked=False, episodes=True, lead=()):
    """A provider-shaped namespace for ``legacy_prefetch`` from build_packet arguments."""
    config = {"prefetch_k": limit, "prefetch_budget_tokens": budget, "prefetch_min_score": min_score,
              "prefetch_linked": linked, "capture_turns": episodes}
    return SimpleNamespace(_config=config, _store=store, _read_scopes=list(scopes), _scope=scopes[0],
                           _review_lines=list(lead))


# -- helpers ------------------------------------------------------------------------------------

class ProviderMixin:
    def provider(self, **settings):
        config = {"db_path": ":memory:", "scope": SCOPE, "extra_scopes": "", "embed": "", "rerank": "", **settings}
        p = TeresisMemoryProvider(config)
        self.addCleanup(p.shutdown)
        p.initialize("synthetic", platform="cli")
        p._store.clock = lambda: T0
        return p

    def remember(self, p, content, *, scope=SCOPE, kind="fact", key=None, source="hermes:memory-tool",
                 ttl_days=None, meta=None, importance=0.5):
        return p._store.remember(content, scope=scope, kind=kind, key=key, source=source,
                                 ttl_days=ttl_days, meta=meta, importance=importance).id

    def assert_parity(self, p, query):
        expected, ids = legacy_prefetch(p, query)
        got = p.prefetch(query)
        self.assertEqual(got, expected)
        self.assertEqual(sorted(p._last_ids), ids)
        self.assertEqual(p._last_count, len(ids))
        return got


class LegacyParityTests(ProviderMixin, unittest.TestCase):
    """prefetch text is byte-identical to the pre-builder output for the same inputs."""

    def test_literal_direct_and_linked(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.")
        text = self.assert_parity(p, ASK)
        self.assertEqual(text, "## Long-term memory (teresis)\n"
                               f"- [fact] Priya owns the billing service. (id {owner})\n\n"
                               "## Related facts (shared entity)\n"
                               f"- [fact] Priya is on leave through October. (id {leave}; linked from {owner})")

    def test_literal_fact_then_episode(self):
        p = self.provider()
        current = self.remember(p, "The Kestrel worker now listens on port 6600.", key="kestrel.port")
        turn = self.remember(p, "User: The Kestrel worker listens on port 4400.\nAssistant: Noted.",
                             kind="episode", source="hermes:cli")
        text = self.assert_parity(p, "Which port does the Kestrel worker use now?")
        self.assertEqual(text, "## Long-term memory (teresis)\n"
                               f"- [fact kestrel.port] The Kestrel worker now listens on port 6600. (id {current})\n\n"
                               "## Related past conversation\n"
                               "- [episode] User: The Kestrel worker listens on port 4400.\n"
                               f"Assistant: Noted. (id {turn})")

    def test_literal_review_note_leads(self):
        p = self.provider()
        fact = self.remember(p, "Priya owns the billing service.")
        p._set_review_note(["## Memory review (teresis)", "Applied from the user's own message: kept 1, dropped 0.",
                            "- kept [abcdef0123456789] The database port is 5432.",
                            "Confirm this to the user in one line."])
        text = self.assert_parity(p, "who owns the billing service")
        self.assertEqual(text, "## Memory review (teresis)\nApplied from the user's own message: kept 1, dropped 0.\n"
                               "- kept [abcdef0123456789] The database port is 5432.\n"
                               "Confirm this to the user in one line.\n\n"
                               "## Long-term memory (teresis)\n"
                               f"- [fact] Priya owns the billing service. (id {fact})")
        self.assertEqual(p._last_packet.items[0].reason, E.REVIEW_NOTE)

    def test_fixtures_match_legacy(self):
        cases = []

        def fixture(settings, rows, query, setup=None):
            cases.append((settings, rows, query, setup))

        owner = ("Priya owns the billing service.", {})
        leave = ("Priya is on leave through October.", {})
        fixture({}, [owner, leave], ASK)
        fixture({"prefetch_linked": True}, [owner, leave, ("Priya collects vintage fountain pens.", {})], ASK)
        fixture({}, [(f"User: The Kestrel worker {d}.\nAssistant: Noted.", {"kind": "episode", "source": "hermes:cli"})
                     for d in ("listens on port 4400", "writes logs to stderr", "restarts every hour")],
                "Kestrel worker")
        fixture({"prefetch_k": 2}, [owner] + [(f"User: The Kestrel worker {d}.\nAssistant: Noted.",
                                               {"kind": "episode", "source": "hermes:cli"})
                                              for d in ("listens on port 4400", "writes logs to stderr")],
                "Priya billing Kestrel worker")
        fixture({}, [owner, ("User: Priya owns the billing service.\nAssistant: Noted.",
                             {"kind": "episode", "source": "hermes:cli"})], ASK)
        fixture({}, [("Billing owner review is tomorrow " + "detail " * 400, {})], "billing owner review")
        fixture({"prefetch_budget_tokens": 40}, [("The Kestrel worker now listens on port 6600.", {"key": "kestrel.port"}),
                                                 ("User: The Kestrel worker listens on port 4400.\nAssistant: Noted.",
                                                  {"kind": "episode", "source": "hermes:cli"})],
                "Which port does the Kestrel worker use now?")
        fixture({}, [("The Kestrel worker listens on port 4400.", {"key": "kestrel.port"}),
                     ("The Kestrel worker now listens on port 6600.", {"key": "kestrel.port"})],
                "Which port does the Kestrel worker use now?")
        fixture({"prefetch_linked": True}, [owner, ("Priya is on leave through October.", {"source": "hermes:auto-extract"}),
                                            ("Priya likes dark mode.", {"kind": "candidate"})], ASK)
        fixture({"prefetch_k": 1, "prefetch_budget_tokens": 120},
                [("The billing owner is on leave.", {}),
                 ("The billing owner manages service and " + "details " * 80, {"importance": 1.0})], "billing owner")
        fixture({"prefetch_min_score": "not a number"}, [owner], ASK)
        fixture({"prefetch_budget_tokens": "abc"}, [owner], ASK,
                setup=lambda p: p._set_review_note(["## Memory review (teresis)", "head", "- one", "tail"]))
        fixture({"prefetch_k": "six"}, [owner], ASK)
        fixture({"capture_turns": "off"}, [("User: Priya owns the billing service and more.\nAssistant: ok",
                                            {"kind": "episode", "source": "hermes:cli"})], ASK)
        fixture({}, [owner], "thanks", setup=lambda p: p._set_review_note(["## Memory review (teresis)", "x", "y"]))
        fixture({"prefetch_budget_tokens": 0}, [owner], ASK)
        fixture({"prefetch_k": 0}, [owner], ASK)
        fixture({}, [owner, ("The billing service owner is Priya; token sk-abcdefghijklmnopqrstuvwxyz0123456789", {})],
                "billing owner sk-abcdefghijklmnopqrstuvwxyz0123456789")
        fixture({"extra_scopes": "user"}, [owner, ("Priya's billing team meets on Fridays.", {"scope": "user"}),
                                           ("Priya runs billing for the other profile.", {"scope": "hermes/other"})],
                "When does the billing team meet?")
        for i, (settings, rows, query, setup) in enumerate(cases):
            with self.subTest(case=i, query=query):
                p = self.provider(**settings)
                for content, kw in rows:
                    self.remember(p, content, **kw)
                if setup:
                    setup(p)
                self.assert_parity(p, query)

    def test_prefetch_uses_build_packet_once(self):
        p = self.provider()
        self.remember(p, "Priya owns the billing service.")
        with unittest.mock.patch.object(E, "build_packet", wraps=E.build_packet) as spy:
            text = p.prefetch(ASK)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(text, p._last_packet.render())


class ReasonCodeTests(ProviderMixin, unittest.TestCase):
    def build(self, p, query, **kw):
        opts = kw.pop("options", None) or E.PacketOptions(explain=True)
        return E.build_packet(p._store, query, p._read_scopes, limit=kw.pop("limit", 6),
                              budget=kw.pop("budget", 700), options=opts, **kw)

    def reasons(self, packet):
        return {d.id: d.reason for d in packet.dropped}

    def test_included_items_carry_roles_and_reasons(self):
        p = self.provider()
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.")
        turn = self.remember(p, "User: Is the billing owner around this week?\nAssistant: Checking.",
                             kind="episode", source="hermes:cli")
        packet = self.build(p, ASK, options=E.PacketOptions(linked=True))
        got = [(it.id, it.role, it.reason, it.via) for it in packet.items]
        self.assertEqual(got, [(owner, "direct", E.DIRECT_HIT, None), (leave, "linked", E.LINKED_PEER, owner),
                               (turn, "episode", E.EPISODE, None)])
        for it in packet.items:
            self.assertEqual((it.scope, it.origin, it.trust), (SCOPE, it.origin, _prov.trust_of(it.origin)))
            self.assertIn(f"(id {it.id}", it.text)
        self.assertEqual(sum(it.tokens for it in packet.items), packet.tokens)
        self.assertEqual(packet.tokens, estimate_tokens(packet.text))
        self.assertEqual(packet.render(), packet.text)

    def test_drop_reasons(self):
        p = self.provider()
        store = p._store
        owner = self.remember(p, "Priya owns the billing service.")
        unreviewed = self.remember(p, "The billing service owner is Sam.", source="hermes:auto-extract")
        cand = self.remember(p, "Priya owns billing service dashboards.", kind="candidate")
        old = self.remember(p, "Billing service region is eu-west-1.", key="billing.region")
        new = self.remember(p, "Billing service region is us-east-2.", key="billing.region")
        gone = self.remember(p, "Billing service owner was Alex, secret plan.")
        store.forget(gone)
        expired = self.remember(p, "Billing service owner is away today.", ttl_days=1)
        sibling = self.remember(p, "Billing service owner in the other profile.", scope="hermes/other")
        shared_turn = self.remember(p, "User: the billing service owner question\nAssistant: ok",
                                    kind="episode", source="hermes:cli", scope="user")
        store.clock = lambda: T0 + 2 * 86400
        packet = self.build(p, ASK)
        why = self.reasons(packet)
        self.assertIn(owner, packet.ids)
        self.assertIn(new, packet.ids)
        self.assertEqual(why[unreviewed], "unreviewed_auto")
        self.assertEqual(why[cand], E.CANDIDATE)
        self.assertEqual(why[old], E.SUPERSEDED)
        self.assertEqual(why[gone], E.FORGOTTEN)
        self.assertEqual(why[expired], E.EXPIRED)
        self.assertEqual(why[sibling], E.OUT_OF_SCOPE)
        self.assertEqual(why[shared_turn], E.OUT_OF_SCOPE)
        by_id = {d.id: d for d in packet.dropped}
        for hidden in (gone, sibling, shared_turn):
            self.assertEqual(by_id[hidden].preview, "")  # forgotten or other-scope text is never shown
        self.assertIn("eu-west-1", by_id[old].preview)
        rendered = E.explain_text(packet)
        self.assertNotIn("secret plan", rendered)
        self.assertNotIn("other profile", rendered)
        # Once the packet is full, a row that would fail a gate anyway keeps that reason.
        full = self.reasons(self.build(p, ASK, limit=1))
        self.assertEqual(full[unreviewed], "unreviewed_auto")
        self.assertIn(E.PACKET_FULL, full.values())
        # The explain pass only adds dropped rows; what is injected does not change.
        plain = self.build(p, ASK, options=E.PacketOptions())
        self.assertEqual((plain.text, plain.items), (packet.text, packet.items))
        self.assertFalse({d.id for d in plain.dropped if d.stage == "index"})

    def test_floor_anchor_budget_full_cap_repeat_duplicate(self):
        p = self.provider()
        a = self.remember(p, "Priya owns the billing service.")
        b = self.remember(p, "Priya is on leave from the billing service.")
        weak = self.remember(p, "Roll back the deploy before lunch.")
        packet = self.build(p, "tuna rolls for the billing service", options=E.PacketOptions(explain=False))
        self.assertEqual(self.reasons(packet).get(weak), E.NO_ANCHOR)
        packet = self.build(p, ASK, options=E.PacketOptions(min_score=0.99))
        self.assertEqual(len(packet.ids), 1)
        self.assertEqual(self.reasons(packet)[({a, b} - set(packet.ids)).pop()], E.BELOW_FLOOR)
        packet = self.build(p, ASK, limit=1)
        self.assertEqual(self.reasons(packet)[({a, b} - set(packet.ids)).pop()], E.PACKET_FULL)
        first = estimate_tokens(self.build(p, ASK, limit=1).text)
        packet = self.build(p, ASK, budget=first)
        self.assertEqual(self.reasons(packet)[({a, b} - set(packet.ids)).pop()], E.OVER_BUDGET)
        self.assertLessEqual(packet.tokens, first)
        # A linked peer that is already a direct hit is a duplicate.
        packet = self.build(p, "Priya billing service", options=E.PacketOptions(linked=True))
        self.assertEqual([it.role for it in packet.items], ["direct", "direct"])
        dups = [(d.id, d.reason, d.via) for d in packet.dropped if d.stage == "linked"]
        first, second = packet.ids
        self.assertEqual(dups, [(second, E.DUPLICATE, first), (first, E.DUPLICATE, second)])
        # A row below the floor as a direct hit can still come in as the linked peer.
        packet = self.build(p, "Priya billing service leave owner", options=E.PacketOptions(linked=True))
        self.assertEqual([it.role for it in packet.items], ["direct", "linked"])
        self.assertEqual(self.reasons(packet)[packet.ids[1]], E.BELOW_FLOOR)
        # Episodes: one repeats an admitted fact; of the other three matching turns two fit and one
        # hits the cap. A turn left out after the cap still gets its own reason first.
        q = self.provider()
        fact = self.remember(q, "The Kestrel worker writes logs to stderr.")
        turns = [self.remember(q, f"User: The Kestrel worker {d}.\nAssistant: Noted.", kind="episode",
                               source="hermes:cli")
                 for d in ("writes logs to stderr", "listens on port 4400", "restarts every hour", "uses 2 GB")]
        packet = self.build(q, "Kestrel worker writes logs to stderr")
        self.assertEqual(packet.ids, [fact])
        self.assertEqual(self.reasons(packet)[turns[0]], E.REPEATS_FACT)
        packet = self.build(q, "Kestrel worker")
        self.assertEqual(packet.ids[0], fact)
        self.assertEqual(len([i for i in packet.items if i.role == "episode"]), 2)
        why = self.reasons(packet)
        self.assertEqual(why[turns[0]], E.REPEATS_FACT)
        self.assertEqual([why[t] for t in turns[1:] if t not in packet.ids], [E.EPISODE_CAP])
        off = self.build(q, "Kestrel worker", options=E.PacketOptions(episodes=False, explain=True))
        self.assertEqual({self.reasons(off)[t] for t in turns}, {E.EPISODES_OFF})

    def test_empty_reasons(self):
        p = self.provider()
        self.remember(p, "Priya owns the billing service.")
        self.assertEqual(self.build(p, ASK, budget=0).empty_reason, E.BUDGET_ZERO)
        self.assertEqual(self.build(p, ASK, limit=0).empty_reason, E.LIMIT_ZERO)
        self.assertEqual(self.build(p, "thanks").empty_reason, E.TRIVIAL)
        self.assertEqual(self.build(p, "Who designed the aquarium?").empty_reason, E.NO_MATCH)
        self.assertEqual(self.build(p, "is the one about that?").empty_reason, E.NO_ANCHOR)
        packet = self.build(p, ASK, options=E.PacketOptions(min_score=5))
        self.assertEqual((packet.text, packet.items, packet.empty_reason), ("", [], E.BELOW_FLOOR))
        for code in (E.BUDGET_ZERO, E.LIMIT_ZERO, E.TRIVIAL, E.NO_MATCH, E.NO_ANCHOR, E.BELOW_FLOOR):
            self.assertNotEqual(E.describe(code), code)  # documented, never injected

    def test_limit_is_capped(self):
        p = self.provider()
        for i in range(40):
            self.remember(p, f"Billing service fact number {i} about owner {i}.")
        packet = self.build(p, "billing service owner", limit=100, budget=100_000)
        self.assertLessEqual(len(packet.ids), E.MAX_ITEMS)
        self.assertEqual(packet.limit, E.MAX_ITEMS)

    def test_to_dict_is_json(self):
        p = self.provider()
        self.remember(p, "Priya owns the billing service.")
        d = json.loads(json.dumps(self.build(p, ASK).to_dict()))
        self.assertEqual({"query", "scopes", "limit", "budget", "tokens", "empty_reason", "text", "items",
                          "dropped"}, set(d))
        self.assertEqual(d["items"][0]["reason"], E.DIRECT_HIT)
        self.assertTrue({"id", "kind", "scope", "text", "tokens", "reason", "role", "via"} <= set(d["items"][0]))


class WhyReasonTests(ProviderMixin, unittest.TestCase):
    def test_memory_why_says_why_each_item_was_injected(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.")
        p.on_turn_start(1, ASK)
        p.prefetch(ASK)
        self.assertEqual(p._last_ids, [owner, leave])  # packet order
        out = json.loads(p.handle_tool_call("memory_why", {}))
        self.assertIn(f"[{owner}] Priya owns the billing service.\n- fact in {SCOPE}; status: current\n"
                      "- injected: matched the question\n", out["result"])
        self.assertIn(f"- injected: {E.describe(E.LINKED_PEER)} (linked from {owner})", out["result"])
        keys = set(_receipt.receipt(p._store, owner))
        self.assertEqual([set(r) for r in out["receipts"]], [keys, keys])
        self.assertEqual(set(out), {"result", "receipts", "missing"})
        p.on_turn_start(2, "something unrelated entirely")
        p.prefetch("something unrelated entirely")
        out = json.loads(p.handle_tool_call("memory_why", {}))
        self.assertTrue(out["result"].startswith("Previous turn:"))
        self.assertIn("- injected: matched the question", out["result"])

    def test_explicit_ids_unchanged(self):
        p = self.provider()
        mid = self.remember(p, "Tea over coffee")
        out = json.loads(p.handle_tool_call("memory_why", {"id": mid}))
        self.assertEqual(out["result"], _receipt.explain(p._store, [mid])[0])
        self.assertNotIn("injected:", out["result"])


class PacketCliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "m.db")
        s = MemoryStore(self.db, embedder=None, reranker=None)
        try:
            self.owner = s.remember("Priya owns the billing service.", scope="hermes/default").id
            self.user = s.remember("Priya's billing team meets on Fridays.", scope="user").id
            s.remember("Billing service region is eu-west-1.", scope="hermes/default", key="billing.region")
            self.region = s.remember("Billing service region is us-east-2.", scope="hermes/default",
                                     key="billing.region").id
            self.gone = s.remember("Billing service owner was Alex, secret plan.", scope="hermes/default").id
            s.forget(self.gone)
            s.remember("The billing service owner in the work profile.", scope="hermes/work")
        finally:
            s.close()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {k: v for k, v in os.environ.items() if not k.startswith("TERESIS_")}
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def digest(self):
        """Bytes and mtime of the database file, plus the files next to it (-wal/-shm included)."""
        return (hashlib.sha256(Path(self.db).read_bytes()).hexdigest(), os.stat(self.db).st_mtime_ns,
                sorted(os.listdir(self.dir)))

    def test_explain_is_read_only(self):
        before = self.digest()
        rc, out, _ = self.run_cli("packet", "--db", self.db, "--explain", "Who owns the billing service?")
        self.assertEqual(rc, 0)
        self.assertEqual(self.digest(), before)
        for argv in (["--json", "--explain", "--linked"], ["--budget", "40"], ["-s", "user", "--explain"]):
            self.assertEqual(self.run_cli("packet", "--db", self.db, *argv, "billing service owner")[0], 0)
        self.assertIn(f"direct_hit   {self.owner}", out)
        self.assertIn("superseded", out)
        self.assertIn(f"forgotten    {self.gone}", out)
        self.assertIn("out_of_scope", out)
        self.assertNotIn("secret plan", out)
        self.assertNotIn("work profile", out)
        self.assertIn("injected text:\n## Long-term memory (teresis)\n", out)
        self.assertEqual(self.digest(), before)
        s = MemoryStore(self.db, embedder=None, reranker=None)
        try:
            for mid in (self.owner, self.user, self.region):
                m = s.get(mid)
                self.assertEqual((m.access_count, m.accessed_at), (0, None))
        finally:
            s.close()

    def test_plain_json_scope_budget(self):
        rc, out, _ = self.run_cli("packet", "--db", self.db, "Who owns the billing service?")
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("## Long-term memory (teresis)\n"))
        rc, out, _ = self.run_cli("packet", "--db", self.db, "--json", "--explain", "Who owns the billing service?")
        d = json.loads(out)
        self.assertEqual(d["scopes"], ["hermes/default", "user"])
        self.assertEqual(d["budget"], 700)
        self.assertEqual(d["limit"], 6)
        self.assertIn(self.owner, [it["id"] for it in d["items"]])
        self.assertTrue(all(it["reason"] in E.INCLUDED for it in d["items"]))
        s = MemoryStore(self.db, embedder=None, reranker=None)
        try:
            direct = E.build_packet(s, "Who owns the billing service?", ["hermes/default", "user"], limit=6,
                                    budget=700, options=E.PacketOptions(explain=True))
        finally:
            s.close()
        self.assertEqual(d, json.loads(json.dumps(direct.to_dict())))
        rc, out, _ = self.run_cli("packet", "--db", self.db, "--json", "-s", "hermes/work", "--budget", "12",
                                  "Who owns the billing service?")
        d = json.loads(out)
        self.assertEqual(d["scopes"], ["hermes/work"])
        self.assertEqual((d["text"], d["empty_reason"]), ("", E.OVER_BUDGET))
        rc, out, _ = self.run_cli("packet", "--db", self.db, "--budget", "0", "Who owns the billing service?")
        self.assertEqual((rc, out.strip()), (0, "(nothing would be injected: budget_zero)"))

    def test_missing_db_is_not_created(self):
        path = os.path.join(self.dir, "absent.db")
        rc, _, err = self.run_cli("packet", "--db", path, "--explain", "anything")
        self.assertEqual(rc, 1)
        self.assertIn("no database", err)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
