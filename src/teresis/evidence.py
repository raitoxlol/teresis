"""The evidence packet: what Teresis puts in front of a model before a turn, and why.

``build_packet`` is the one function that decides what Hermes prefetch injects. It returns a
structured ``Packet``: the items it included, in order, each with a reason code, and the
candidates it looked at and left out, each with a reason code. ``Packet.render()`` turns the
items into the prompt text; ``Packet.text`` is the same string, kept up to date while the
packet is built so the budget check covers every header, citation and separator.

Building a packet never writes to the store: reads use ``touch=False`` and no entity
expansion, and the optional explain pass only reads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

from . import provenance as _prov
from . import secrets as _secrets
from . import temporal as _temporal
from .store import Memory, scope_chain
from .text import estimate_tokens, tokens

ITEM_CHARS = 1200  # per memory in the injected block, so one legacy row cannot crowd out the rest
MAX_ITEMS = 30     # hard cap on memories per packet, whatever the caller asks for
MAX_EPISODES = 2   # past-conversation excerpts per packet

SECTION_DIRECT = "Long-term memory (teresis)"
SECTION_LINKED = "Related facts (shared entity)"
SECTION_EPISODE = "Related past conversation"

# Roles, in packet order.
ROLE_NOTE, ROLE_DIRECT, ROLE_LINKED, ROLE_EPISODE = "note", "direct", "linked", "episode"
ROLE_ORDER = (ROLE_NOTE, ROLE_DIRECT, ROLE_LINKED, ROLE_EPISODE)

# Why an item is in the packet.
REVIEW_NOTE = "review_note"
DIRECT_HIT = "direct_hit"
LINKED_PEER = "linked_peer"
EPISODE = "episode"
INCLUDED = frozenset({REVIEW_NOTE, DIRECT_HIT, LINKED_PEER, EPISODE})

# Why a candidate was left out. The trust gate's own reasons (provenance.injectable) are kept
# with '-' turned into '_': candidate, threat, system_turn, checkpoint, injected, unreviewed_auto.
BELOW_FLOOR = "below_floor"
NO_ANCHOR = "no_anchor"
DUPLICATE = "duplicate"
REPEATS_FACT = "repeats_fact"
OVER_BUDGET = "over_budget"
PACKET_FULL = "packet_full"
EPISODE_CAP = "episode_cap"
EPISODES_OFF = "episodes_off"
# Only from the explain pass: rows the word index matches that recall never returned.
RANK_CUTOFF = "rank_cutoff"
OUT_OF_SCOPE = "out_of_scope"
CANDIDATE = "candidate"
SUPERSEDED = "superseded"
FORGOTTEN = "forgotten"
EXPIRED = "expired"
# Why a packet holds no memories (besides NO_ANCHOR, BELOW_FLOOR and the drop reasons above).
BUDGET_ZERO = "budget_zero"
LIMIT_ZERO = "limit_zero"
TRIVIAL = "trivial_query"
NO_MATCH = "no_match"

REASONS = {
    REVIEW_NOTE: "the memory review note for this turn",
    DIRECT_HIT: "matched the question",
    LINKED_PEER: "shares one unambiguous entity with an injected fact",
    EPISODE: "past conversation that matched the question",
    BELOW_FLOOR: "score below prefetch_min_score",
    NO_ANCHOR: "shares no distinctive word with the question",
    DUPLICATE: "already in the packet",
    REPEATS_FACT: "repeats a fact already in the packet",
    OVER_BUDGET: "would exceed the token budget",
    PACKET_FULL: "the packet already holds the maximum number of memories",
    EPISODE_CAP: f"{MAX_EPISODES} conversation excerpts already included",
    EPISODES_OFF: "past conversation is turned off",
    CANDIDATE: "unreviewed candidate (quarantined)",
    "threat": "instruction-shaped text",
    "system_turn": "written by an automated turn",
    "checkpoint": "compression checkpoint",
    "injected": "looks like injected or system text",
    "unreviewed_auto": "picked up automatically and not reviewed",
    RANK_CUTOFF: "matched, but ranked below the recall cutoff",
    OUT_OF_SCOPE: "outside the readable scopes",
    SUPERSEDED: "replaced by a newer version",
    FORGOTTEN: "forgotten",
    EXPIRED: "expired",
    BUDGET_ZERO: "the token budget is 0",
    LIMIT_ZERO: "the memory limit is 0",
    TRIVIAL: "trivial message, nothing is looked up",
    NO_MATCH: "nothing in the readable scopes matched",
}


def describe(reason: str) -> str:
    return REASONS.get(reason, reason.replace("_", " "))


# -- rendering ------------------------------------------------------------------------------

def _trim(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def render_content(memory: Memory) -> str:
    """The text injected for one memory: trimmed, plus the day it was saved when it says
    "tomorrow" or "next week" (detected on the full content, so a trimmed phrase still counts)."""
    return _temporal.with_saved_note(memory.content, memory.created_at,
                                     display_content=_trim(memory.content, ITEM_CHARS))


def render_line(memory: Memory, via: str | None = None) -> str:
    label = memory.kind + (f" {memory.key}" if memory.key else "")
    ref = f"; linked from {via}" if via else ""
    return f"- [{label}] {render_content(memory)} (id {memory.id}{ref})"


def _fragment(has_text: bool, prev_section: str, section: str, line: str) -> str:
    """What one memory line adds to the packet text: a separator, a section header when the
    section changes, and the line."""
    sep = "\n" if has_text else ""
    header = "" if prev_section == section else sep + "## " + section + "\n"
    return sep + header + line


def render(items: Iterable["PacketItem"]) -> str:
    """The prompt text for ``items``. A review note, if any, is the first item and is used as is."""
    text, section = "", ""
    for it in items:
        if it.role == ROLE_NOTE:
            text += it.text
            continue
        text += _fragment(bool(text), section, it.section, it.text)
        section = it.section
    return text


def fit_note(lines: Sequence[str], budget: int) -> str:
    """Render a ``[title, head, *items, tail]`` note within ``budget`` estimated tokens.

    Items are dropped from the end first (with a count of what was left out), and the
    title, head and tail stay. A budget too small even for that gets a hard cut.
    """
    lines = list(lines)
    if not lines or budget <= 0:
        return ""
    head, items, tail = lines[:2], lines[2:-1], lines[-1:]
    text = ""
    for n in range(len(items), -1, -1):
        more = [f"- ... {len(items) - n} more not shown"] if n < len(items) else []
        text = "\n".join(head + items[:n] + more + tail)
        if estimate_tokens(text) <= budget:
            return text
    cap = 4 * budget  # estimate_tokens(t) <= budget exactly when len(t) <= 4 * budget
    return text if len(text) <= cap else text[: cap - 1] + "…"


# -- the relevance gate (prefetch only; tool recall does not use it) -------------------------

# Unstemmed tokens that are too common to justify injecting a memory on their own.
# Inflected forms are included so "likes" does not sneak past "like".
PREFETCH_WEAK = frozenset(
    t + suffix
    for t in """like want need order get make use have take give please help really just more some also
    thing things stuff good bad new one user call write read file run set put see look time day
    way work said first later check about would could should done yeah yes okay thanks something
    anything remotely table place can""".split()
    for suffix in ("", "s", "es", "ed", "ing")
)


def term_covers(query_tok: str, memory_tok: str) -> bool:
    """True when the memory token is the query token or a light inflection of it.

    Query "rolls" does not cover memory "roll". That direction is how lexical
    search pulled "roll back" into a tuna-rolls turn.
    """
    if query_tok == memory_tok:
        return True
    if len(query_tok) < 4 or not memory_tok.startswith(query_tok):
        return False
    return memory_tok[len(query_tok):] in {"s", "es", "ed", "ing", "d"}


def distinctive_terms(query: str) -> list[str]:
    return [t for t in tokens(query) if len(t) >= 4 and t not in PREFETCH_WEAK]


def relevance(query: str, content: str, *, floor: float, score: float | None) -> str:
    """'' when ``content`` may be injected for ``query``, else BELOW_FLOOR or NO_ANCHOR."""
    if (score or 0) < floor:
        return BELOW_FLOOR
    distinctive = distinctive_terms(query)
    if not distinctive:
        return NO_ANCHOR
    memory_toks = [t for t in tokens(content) if t not in PREFETCH_WEAK]
    if any(term_covers(q, m) for q in distinctive for m in memory_toks):
        return ""
    return NO_ANCHOR


def prefetch_relevant(query: str, content: str, *, floor: float, score: float | None) -> bool:
    """Prefetch injection gate. Tool recall does not use this."""
    return not relevance(query, content, floor=floor, score=score)


def trust_gate(m: Memory) -> str:
    """'' when the row may stand in a prompt (provenance.injectable), else its reason code."""
    ok, why = _prov.injectable(m.kind, m.content, m.meta, m.source)
    return "" if ok else why.replace("-", "_")


_TRIVIAL = {"ok", "okay", "yes", "no", "thanks", "thank you", "hi", "hey", "continue", "go ahead",
            "do it", "done", "next", "lgtm", "k"}


def is_trivial(text: Optional[str]) -> bool:
    """Fallback for Hermes' ``is_trivial_prompt``: acknowledgements and slash commands."""
    t = (text or "").strip().lower().strip("!?. ")
    return not t or t.startswith("/") or t in _TRIVIAL


# -- the packet -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PacketItem:
    """One included block. ``id`` is None only for the review note."""
    id: Optional[str]
    kind: str
    key: Optional[str]
    scope: Optional[str]
    role: str            # note | direct | linked | episode
    reason: str          # one of INCLUDED
    section: str         # the "## ..." header it renders under ('' for the note)
    text: str            # the rendered line (the whole note for the note)
    tokens: int          # estimated tokens this item added, header and separators included
    via: Optional[str] = None
    score: Optional[float] = None
    origin: Optional[str] = None
    trust: Optional[str] = None
    created_at: Optional[float] = None
    expires_at: Optional[float] = None


@dataclass(frozen=True)
class Dropped:
    """A candidate that was looked at and left out."""
    id: str
    kind: str
    scope: str
    stage: str           # direct | linked | episode | index (explain pass: found by the word index only)
    reason: str
    score: Optional[float] = None
    via: Optional[str] = None
    preview: str = ""    # empty for forgotten or out-of-scope rows


@dataclass(frozen=True)
class PacketOptions:
    min_score: float = 0.45   # prefetch_min_score; episodes use max(0.3, min_score)
    linked: bool = False      # prefetch_linked
    episodes: bool = True     # capture_turns
    explain: bool = False     # also report rows recall never returned (read-only, extra queries)


@dataclass
class Packet:
    query: str                      # after secret redaction; '' when nothing was looked up
    scopes: tuple[str, ...]
    limit: int
    budget: int
    items: list[PacketItem] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    text: str = ""
    empty_reason: str = ""          # set when no memory is included; never rendered
    _section: str = field(default="", repr=False)
    _ids: set = field(default_factory=set, repr=False)

    @property
    def memories(self) -> list[PacketItem]:
        return [it for it in self.items if it.id]

    @property
    def ids(self) -> list[str]:
        return [it.id for it in self.items if it.id]

    @property
    def full(self) -> bool:
        return len(self._ids) >= self.limit or self.budget <= 0

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text) if self.text else 0

    def render(self) -> str:
        return render(self.items)

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "scopes": list(self.scopes), "limit": self.limit,
                "budget": self.budget, "tokens": self.tokens, "empty_reason": self.empty_reason,
                "text": self.text, "items": [asdict(it) for it in self.items],
                "dropped": [asdict(d) for d in self.dropped]}

    # -- building (build_packet only) --
    def _lead(self, note: str) -> None:
        if note:
            self.items.append(PacketItem(None, "note", None, None, ROLE_NOTE, REVIEW_NOTE, "", note,
                                         estimate_tokens(note)))
            self.text = note

    def _add(self, m: Memory, section: str, role: str, reason: str, via: str | None = None) -> str:
        """Append ``m`` if it fits; '' on success, else the reason it was left out."""
        if self.full:
            return PACKET_FULL
        if m.id in self._ids:
            return DUPLICATE
        line = render_line(m, via)
        fragment = _fragment(bool(self.text), self._section, section, line)
        total = estimate_tokens(self.text + fragment)
        if total > self.budget:
            return OVER_BUDGET
        origin = _prov.effective_origin(m.meta, m.source, m.kind)
        self.items.append(PacketItem(
            m.id, m.kind, m.key, m.scope, role, reason, section, line,
            total - (estimate_tokens(self.text) if self.text else 0), via=via, score=m.score,
            origin=origin, trust=_prov.trust_of(origin), created_at=m.created_at, expires_at=m.expires_at))
        self.text += fragment
        self._ids.add(m.id)
        self._section = section
        return ""


def _preview(m: Memory) -> str:
    return _trim(" ".join((m.content or "").split()), 100)


def _drop(m: Memory, stage: str, reason: str, *, via: str | None = None, preview: bool = True) -> Dropped:
    return Dropped(m.id, m.kind, m.scope, stage, reason, m.score, via, _preview(m) if preview else "")


def build_packet(store, query: str, scopes: Sequence[str], *, limit: int, budget: int,
                 options: PacketOptions | None = None, lead: Sequence[str] = (),
                 trivial: Callable[[str], bool] = is_trivial) -> Packet:
    """What prefetch injects for ``query``: at most ``limit`` memories in at most ``budget``
    estimated tokens of rendered text, review note (``lead`` lines) included.

    ``scopes[0]`` is the agent scope: past conversation comes only from it. Order: the review
    note, direct facts, at most one linked fact (``options.linked``), then at most two episodes.
    Every row passes the trust gate; recall supplies only active rows in readable scopes.
    """
    opts = options or PacketOptions()
    scopes = tuple(scopes)
    p = Packet(query="", scopes=scopes, limit=min(MAX_ITEMS, int(limit)), budget=int(budget))
    p._lead(fit_note(lead, p.budget))
    if trivial(query):
        p.empty_reason = TRIVIAL
        return p
    if p.full:
        p.empty_reason = BUDGET_ZERO if p.budget <= 0 else LIMIT_ZERO
        return p
    q = _secrets.redact_secrets(query)[0]
    p.query = q
    floor = opts.min_score

    direct = store.recall(q, scope=list(scopes), k=min(60, max(12, 3 * p.limit)),
                          exclude_kinds=["episode", _prov.CANDIDATE_KIND], touch=False, expand_entities=False)
    anchors: list[Memory] = []
    # The trust gate is reported before relevance (both are pure, so the order changes no
    # output, only which reason a row gets). Rows after the packet fills still get their gate
    # reason; only rows that pass it are reported as packet_full.
    for m in direct:
        why = (trust_gate(m) or relevance(q, m.content, floor=floor, score=m.score)
               or p._add(m, SECTION_DIRECT, ROLE_DIRECT, DIRECT_HIT))
        if why:
            p.dropped.append(_drop(m, ROLE_DIRECT, why))
        else:
            anchors.append(m)

    if not p.full and store.w.entity_hop > 0 and opts.linked:
        for anchor in anchors[:3]:
            linked = False
            for peer in store.unique_peers(anchor):
                why = trust_gate(peer) or p._add(peer, SECTION_LINKED, ROLE_LINKED, LINKED_PEER, via=anchor.id)
                if why:
                    p.dropped.append(_drop(peer, ROLE_LINKED, why, via=anchor.id))
                    continue
                anchors.append(peer)
                linked = True
                break
            if linked:
                break

    episode_stage = ""  # why the episode stage did not run, if it did not
    if p.full:
        episode_stage = PACKET_FULL
    elif not opts.episodes:
        episode_stage = EPISODES_OFF
    else:
        episodes = store.recall(q, scope=[scopes[0]], inherit=False, kinds=["episode"], k=8,
                                touch=False, expand_entities=False)
        # Deduplicate against all accepted facts, including a linked fact.
        known = [" ".join(m.content.casefold().split()).removeprefix("user: ") for m in anchors]
        accepted = 0
        for m in episodes:
            body = " ".join(m.content.casefold().split())
            why = (trust_gate(m) or relevance(q, m.content, floor=max(0.3, floor), score=m.score)
                   or (REPEATS_FACT if any(k and k in body for k in known) else "")
                   or (EPISODE_CAP if accepted >= MAX_EPISODES else "")
                   or p._add(m, SECTION_EPISODE, ROLE_EPISODE, EPISODE))
            if why:
                p.dropped.append(_drop(m, ROLE_EPISODE, why))
            else:
                accepted += 1

    if opts.explain:
        _explain_misses(store, p, episode_stage)
    if not p._ids:
        p.empty_reason = _empty_reason(p)
    return p


def _empty_reason(p: Packet) -> str:
    """Why a packet that was looked up holds no memories: no distinctive word in the question,
    else the first reason a direct fact or an episode was left out, else nothing matched."""
    if not distinctive_terms(p.query):
        return NO_ANCHOR
    stages = (ROLE_DIRECT, ROLE_EPISODE)
    first = next((d.reason for s in stages for d in p.dropped if d.stage == s), "")
    return first or NO_MATCH


def _explain_misses(store, p: Packet, episode_stage: str) -> None:
    """Add the rows the word index matches that recall did not return, with the reason.
    Read-only. Content of forgotten or out-of-scope rows is never shown."""
    seen = set(p._ids) | {d.id for d in p.dropped}
    allowed = {s for scope in p.scopes for s in scope_chain(scope)}
    agent = p.scopes[0] if p.scopes else ""
    now = store.clock()
    for m in store.lexical_matches(p.query, limit=50):
        if m.id in seen:
            continue
        seen.add(m.id)
        episode = m.kind == "episode"
        if m.deleted_at:
            reason = FORGOTTEN
        elif m.scope not in allowed or (episode and m.scope != agent):
            reason = OUT_OF_SCOPE
        elif m.superseded_by:
            reason = SUPERSEDED
        elif m.expires_at is not None and m.expires_at <= now:
            reason = EXPIRED
        elif _prov.is_candidate(m.kind):
            reason = CANDIDATE
        elif episode and episode_stage:
            reason = episode_stage
        else:
            reason = RANK_CUTOFF
        p.dropped.append(_drop(m, "index", reason, preview=reason not in (FORGOTTEN, OUT_OF_SCOPE)))


# -- explanation ----------------------------------------------------------------------------

def injected_note(item: PacketItem) -> str:
    """One line for a receipt: why this item was injected."""
    note = describe(item.reason)
    if item.via:
        note += f" (linked from {item.via})"
    return note


def explain_text(p: Packet) -> str:
    """Human-readable account of a packet: what is in, what is out and why, then the text."""
    scopes = ", ".join(p.scopes) or "(none)"
    lines = [f"query: {p.query or '(not looked up)'}",
             f"scopes: {scopes} (past conversation only from {p.scopes[0] if p.scopes else '-'})",
             f"memories: {len(p.memories)} of {p.limit} · estimated tokens: {p.tokens} of {p.budget}"]
    lines.append("")
    lines.append("included:" if p.items else "included: nothing")
    for n, it in enumerate(p.items, 1):
        if it.role == ROLE_NOTE:
            lines.append(f"  {n}. {it.reason:<12} {it.tokens} tok")
            continue
        bits = [f"{it.kind} · {it.scope}", f"{it.tokens} tok"]
        if it.score is not None:
            bits.append(f"score {it.score:.3f}")
        if it.via:
            bits.append(f"via {it.via}")
        lines.append(f"  {n}. {it.reason:<12} {it.id}  " + " · ".join(bits))
    if p.dropped:
        lines.append("left out:")
        for d in p.dropped:
            bits = [f"{d.kind} · {d.scope}", d.stage]
            if d.score is not None:
                bits.append(f"score {d.score:.3f}")
            if d.via:
                bits.append(f"via {d.via}")
            lines.append(f"  - {d.reason:<12} {d.id}  " + " · ".join(bits))
            if d.preview:
                lines.append(f"      {d.preview}")
    if p.empty_reason:
        lines.append(f"no memories: {p.empty_reason} ({describe(p.empty_reason)})")
    lines.append("")
    lines.append("injected text:" if p.text else "injected text: (empty)")
    if p.text:
        lines.append(p.text)
    return "\n".join(lines)
