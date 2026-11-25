# Do source-date notes help with "when" questions?

This experiment adds a calendar note after an excerpt such as
`[Calendar for this turn: last month = March 2023]`. The note uses the date
of the source conversation and leaves the speaker's words unchanged.
The experiment does not update stored memories or enable a Hermes feature.

## Measured result

| Same local model | Correct public answers | Correct controls | Mean public evidence tokens |
| --- | ---: | ---: | ---: |
| Inline dates | 1/16 | 4/4 | 602.6 |
| Inline dates and calendar notes | 9/16 | 4/4 | 629.5 |

Eight public answers improved across five histories; none regressed. All 40
attempts returned an answer. The effective system-prompt hash matched within
every pair. On the donation question, the inline answer gave the conversation
date (December 22); the note led to the event date (December 21). Seven public
questions remained wrong. The cohort deliberately selects questions where
relative dates occur in retrieved text. It is not a general memory benchmark
score. The scored answers are in `bench/results/relative-dates-hermes.json`.

One evaluator graded 33 distinct, arm-blind replies. "November 6, 2023" and
"November 2023" received credit for the vacation question: the November 6
turn says the travelers had just left. "Week before June 6" was not counted
as equivalent to "first week of June" for the palpitation question, although
it follows the source's relative wording.

## Rebuild the inputs

Run in an English `C` locale with Python, SQLite FTS5 and
`tokenizers==0.23.2`. From the repository root:

```sh
d=$(mktemp -d)
curl -fsSL https://raw.githubusercontent.com/snap-research/locomo/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json -o "$d/locomo10.json"
curl -fsSL https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/resolve/66285546d2b821cf421d4f5eb2576359d3770cd3/tokenizer.json -o "$d/tokenizer.json"
LC_ALL=C python3 bench/relative_dates.py --corpus "$d/locomo10.json" \
    --tokenizer "$d/tokenizer.json" --out "$d/jobs.json"
```

The command verifies the corpus, tokenizer and rank fixture. It ingests each
history into a temporary Teresis database, applies redaction and disclosure
checks, then verifies the exact output fingerprint. It prepares 40 jobs from
frozen rankings; it does not run inference or recompute the retrieval ranks.
The inference runner and blind grading sheet are not part of this repository.
It reproduces the exact model inputs; the scored outputs are an archived run.

## Protocol

- Select two fresh public questions per history (LoCoMo 2-9) from temporal
  questions starting with "when". Exclude all questions used in the prior
  Hermes answer pilot. A supported relative phrase must occur in the first
  three lexical hits. Within each history select the lowest SHA-256 values
  of `calendar-v1:c{history}q{question}`. Answer text and gold evidence do
  not enter selection. The cohort targets this feature rather than estimating
  general LoCoMo accuracy.
  These histories were previously used for retrieval. The rank source was the
  `base` field of `dialogue-confirm-ranks.json.gz` (uncompressed SHA-256
  `44f5986bb46a30894e5e47709fea320e29115a41e1b1aa4fe5ef0d32214ec292`).
  The exclusion source was `hermes-dialogue-pilot.json` (SHA-256
  `19f74de7d0fefdc14b72570f57cac84b2da06fcff01085744109d022f23c832e`).
  Neither upstream artifact is required to replay the selected IDs.
- Compare inline dates against inline dates plus calendar notes. Consider the
  same ten eligible hits. Admit a whole turn to both arms only if both complete
  packets still fit in 700 Qwen tokens. Question, prompt wrapper and completion
  are outside this evidence cap. Turn order, identities and user text match.
  This isolates date interpretation at matched evidence.
- Add two latest-value questions and two never-told date questions. Shuffle
  question order by the same hash, alternating which arm answers first.
  Use a fresh real Hermes `AIAgent` session for each call, no tools, no
  previous conversation, no remote fallback, temperature zero and 48 maximum
  completion tokens. Replay the packet in user content; bypass live prefetch.
  Local Ollama model: `qwen2.5vl:3b`, digest
  `fb90415cde1ef08aa669ae74b082d49b158729b6db1ab183c941417d507e71a1`.
- Grade distinct normalized replies blind to arm. Require the right calendar
  answer at the gold precision. Reject an unanchored "yesterday", unsupported
  extra precision, contradictions and missing items. Keep failed calls in the
  denominator without retries. Require at least two more public answers
  correct, all four controls correct in both arms and no failed calls to accept
  the benchmark-only candidate. No production promotion from this pilot.

The note recognizes `yesterday`, `tomorrow`, `last month`, `last year` and
`last week`. For `last week` it retains the precision of "week before DATE".
It skips `the last ...` rather than assuming a calendar period. It cannot
establish the date of an event from a quotation, a plan or a counterfactual.
Phrase matching can also misread idioms or nested references, such as
"my last year of college" or "the day before yesterday". Do not use these
notes as authoritative timestamps.
