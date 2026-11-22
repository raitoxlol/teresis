"""Text normalization, tokenization, and FTS5 query building."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WORD = re.compile(r"[\w][\w'’.-]*[\w]|[\w]", re.UNICODE)
_CONTRACTIONS = frozenset(
    """aren't can't couldn't didn't doesn't don't hadn't hasn't haven't he'd he'll he's
    i'd i'll i'm i've isn't it's let's mightn't mustn't shan't she'd she'll she's
    shouldn't that's there's they'd they'll they're they've wasn't we'd we'll we're
    we've weren't what's where's who's won't wouldn't you'd you'll you're you've""".split()
)

STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does doing for from had has have
    having he her here hers him his how i if in into is it its itself just me my of on or our
    ours she should so some such than that the their them then there these they this those
    to too us was we were what when where which while who whom why will with would you your
    yours about after again all also am any because before being below between both down
    during each few further more most no nor not now off once only other out over own same
    under until up very""".split()
)


def normalize(text: str) -> str:
    """Canonical form used for exact-duplicate detection."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()[:32]


def tokens(text: str, *, keep_stopwords: bool = False) -> list[str]:
    out = []
    for raw in _WORD.findall(unicodedata.normalize("NFKC", text).casefold()):
        tok = raw.replace("’", "'").strip("'.-")
        if not tok:
            continue
        if not keep_stopwords and tok in _CONTRACTIONS:
            continue
        if tok.endswith("'s") and len(tok) > 2:
            tok = tok[:-2]
        if not tok or (not keep_stopwords and tok in STOPWORDS):
            continue
        out.append(tok)
    return out


def _stem(tok: str) -> str:
    # Light suffix stripping for similarity scoring only (FTS uses Porter).
    for suf in ("ingly", "edly", "ing", "ed", "es", "ly", "s"):
        if len(tok) > len(suf) + 2 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


def term_set(text: str) -> set[str]:
    return {_stem(t) for t in tokens(text)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[str], b: set[str]) -> float:
    """Fraction of the smaller set contained in the larger."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _quote(tok: str) -> str:
    return '"' + tok.replace('"', '""') + '"'


def fts_query(text: str) -> str | None:
    """OR-query over meaningful terms; BM25 rewards documents matching more of them."""
    toks = tokens(text)
    if not toks:
        toks = tokens(text, keep_stopwords=True)
    toks = list(dict.fromkeys(toks))
    if not toks:
        return None
    return " OR ".join(_quote(t) for t in toks)


def trigram_query(text: str, max_grams: int = 48) -> str | None:
    """OR over character trigrams so misspellings and partial words still match."""
    grams: list[str] = []
    for tok in dict.fromkeys(tokens(text)):
        if len(tok) < 4:
            continue
        for i in range(len(tok) - 2):
            grams.append(tok[i : i + 3])
    grams = list(dict.fromkeys(grams))[:max_grams]
    if not grams:
        return None
    return " OR ".join(_quote(g) for g in grams)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


_BETWEEN = re.compile(r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:\?|$)", re.I)
_FIRST_OR = re.compile(r"(?:first|earlier|before|longer|more recently)[,:]\s+(.+?)\s+or\s+(.+?)(?:\?|$)", re.I)
_SINCE_WHEN = re.compile(r"\bsince\s+(.+?)\s+when\s+(.+?)(?:\?|$)", re.I)
_COMPARE = re.compile(r"\bcompare\s+(.+?)\s+(?:and|with|to|vs\.?)\s+(.+?)(?:\?|$)", re.I)
_QUOTED = re.compile(r"['\"]([^'\"]{2,60})['\"]")


def sub_queries(query: str) -> list[str]:
    """Split comparison / multi-entity queries into clauses so neither side drowns the other."""
    q = (query or "").strip()
    for pat in (_BETWEEN, _FIRST_OR, _SINCE_WHEN, _COMPARE):
        if m := pat.search(q):
            a, b = m.group(1).strip(" ,.?!"), m.group(2).strip(" ,.?!")
            if tokens(a) and tokens(b):
                return [a, b]
    quoted = [m.group(1).strip() for m in _QUOTED.finditer(q) if tokens(m.group(1))]
    quoted = list(dict.fromkeys(quoted))
    if 2 <= len(quoted) <= 3:
        return quoted
    return []
