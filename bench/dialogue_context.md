# Dialogue retrieval experiment

In a conversation, a question and its answer often occupy adjacent turns.
This experiment uses both neighbors to rank a turn. It returns only the
central turn, so a three-turn passage costs one result only when the other
two turns are **not** returned. All arms have at most ten result IDs. There
is no embedding, reranker model or write-time model call.

Run with Python and SQLite FTS5 from the project root. Use a fresh output
directory; the runner refuses to overwrite an existing result.

```sh
d=$(mktemp -d)
curl -fsSL https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -o "$d/locomo10.json"
gzip -dc bench/results/dialogue-dev-ranks.json.gz > "$d/dev-ref.json"
gzip -dc bench/results/dialogue-confirm-ranks.json.gz > "$d/confirm-ref.json"
python bench/dialogue_context.py --data "$d/locomo10.json" --ref "$d/dev-ref.json" --split dev --mode window author fusion --out "$d/dev.json"
python bench/dialogue_context.py --data "$d/locomo10.json" --ref "$d/confirm-ref.json" --split confirm --mode author --out "$d/confirm.json"
```

The runner verifies all three input hashes. The small reference files contain
the frozen rankings and public evidence IDs. `base` is Teresis lexical search.
`nearby` keeps six direct hits, adds eligible next/previous turns for the first
two hits, then fills from direct search, deduplicating before the cut at ten.
Neither ranking is recomputed when testing a new candidate.

An in-memory FTS5 index is rebuilt for each conversation from its active
Teresis episode rows after redaction and the prompt disclosure check. Missing
rows create gaps. Adjacent turns never cross sessions. The three development
candidates use the same body weight of 1 and neighbor weight of 0.45:

- `window`: rank by passage BM25.
- `author`: multiply a turn's score by 1.4 when the question names exactly
  one participant and that participant spoke the central turn.
- `fusion`: combine the `author` ranks and the frozen lexical ranks using
  reciprocal rank with offset 8.

**Decision rule.** Select on histories 0 and 1. Require at least baseline
recall_any@5 and multi-hop recall_all@10. Maximize overall recall_all@10,
breaking ties by NDCG@10, then declaration order. Validate the selected mode
once on public histories 2-9. Per-question ranks are included in each result.
The primary metric counts a question only when **every** labeled evidence
turn appears in the top ten. Category 5 has no gold retrieval target and is
not in this denominator.

This measures retrieval over transcripts with known speaker and session
boundaries. It does not run a Hermes answer model. The public validation
histories were used in an earlier experiment. Production prefetch defaults
and the published cross-provider comparison are unchanged.

## Frozen validation result

On the eight validation histories, the selected `author` mode returned all
labeled evidence on 890/1,305 questions (68.2%), versus 750 (57.5%) for
`base` and 815 (62.5%) for `nearby`. Against `base`, 160 questions gained
complete evidence and 20 lost it; the net gain was positive in each history.
The difference was +10.7 percentage points (95% percentile interval +8.0 to
+13.8 points, resampling whole histories with replacement 10,000 times,
weighted by question count, seed 113).

| All required evidence in top 10 | Base | Nearby | Author |
| --- | ---: | ---: | ---: |
| Single-hop (727) | 528 | 596 | 621 |
| Temporal (258) | 165 | 166 | 188 |
| Multi-hop (239) | 38 | 33 | 59 |
| Open-domain (81) | 19 | 20 | 22 |

Multi-hop remains the largest gap: 180/239 questions still missed at least
one required turn. The test used the same result count; equal prompt-token
budgets, answer correctness, stale answers and refusals require a separate
answer-model run.

## Real Hermes answer pilot

Hermes answered the same 40 questions with each of the three frozen rankings.
Each run used a fresh session, local `qwen2.5vl:3b`, temperature 0, no tools,
48 output tokens, and at most 700 Qwen tokens of evidence. This replays
retrieved text through the real answer model; it bypasses the live Teresis
provider. All 120 requests completed. The 32 public questions were selected
by hash, one per history and category. The eight synthetic controls are
reported separately because they are easier and have a different purpose.
One evaluator graded responses against the reference without seeing which
method produced them; identical responses received the same grade.

| Outcome | Base | Nearby | Author |
| --- | ---: | ---: | ---: |
| Correct public answers | 9/32 | 9/32 | 10/32 |
| Refused an answerable public question | 9/32 | 9/32 | 9/32 |
| Correct current value on updates | 4/4 | 4/4 | 4/4 |
| Asserted an obsolete value on updates | 0/4 | 0/4 | 0/4 |
| Correct refusal on never-told questions | 4/4 | 4/4 | 4/4 |

Compared with `base`, `author` corrected three answers and lost two. The
paired difference was +3.1 points (95% history-bootstrap interval -12.5 to
+18.8 points; eight histories). The answer-quality result is inconclusive.
`author` included every annotated turn on 15 public questions; the model
still missed 10 of those answers. In one case it said "last week" without
giving the date; in another it returned a lake when asked for a state.
Before promoting the ranker, test whether the same model answers correctly
with only the annotated evidence, then validate any change on fresh histories.

[Per-question answers, grades, evidence IDs, paired results and timing](results/hermes-dialogue-pilot.json)
