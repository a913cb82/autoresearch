# Plan (v0)

Each phase: tests → code → hooks → commit → push. Short transactions
everywhere; no transaction is ever held across improve/evaluate.

## 1. `db.py`

Store. `connect(dir)` creates dirs, enables WAL, builds schema.

```sql
CREATE TABLE nodes(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL,
  parent INTEGER REFERENCES nodes(id), score REAL,
  claimed INTEGER DEFAULT 0);
CREATE INDEX idx_parent ON nodes(parent);
-- history(round,id,sha,parent,score): written explicitly, no triggers
-- meta(key,value): round counter (round = evaluation attempts), seed_suffix
```

Functions: `add_node(parent, code: bytes) -> (id, is_new)` (tmp+rename +
`INSERT OR IGNORE`; on sha hit, SELECT the existing id — `lastrowid` is
stale on ignore), `claim(id) -> bool`
(`UPDATE … SET claimed=1 WHERE id=? AND claimed=0`, winner reads
rowcount), `release(id)`, `record_score(id, score|None)` (UPDATE nodes +
INSERT history + meta bump, one txn, in that order), `children(id)`
(raw rows — filtering is select's job), `all_rows()`.
`node_path(sha)` appends the seed suffix from `meta`.
Dedup-hit scored ⇒ reuse row, skip eval. Dedup-hit unscored ⇒ adopt it
(evaluate now). Failed evals still bump round (work was spent).

Tests (`test_db.py`, `:memory:` except one tmpdir two-process claim
race): dedup collapse + id SELECT, double-claim one winner, score+round
atomic, children query, state-at-R, `:memory:` asserts no WAL.

## 2. `select.py`

Pure functions, no I/O. Candidates = scored nodes only (NULL rows are
invisible). Seeded RNG in, ranked id list out (worker claims down the
list until one wins).

- `sigma0(rows)`: 0 gains ⇒ only root exists ⇒ return root; 1 gain ⇒
  `|g|`; ≥2 ⇒ `statistics.pvariance`. Zero spread allowed (point mass).
- `posterior(node, children)`: `(μ, σ, ν)` per README.
- `sample_X(rng, μ, scale, nu)`: caller precomputes
  `scale = σ√(1+1/(1+k))`; chi-square via
  `random.gammavariate(nu/2, 2.0)`.
- `select(rng, rows, sampler=sample_X) -> [ids]`: bottom-up V sample,
  descend from root (`x_n ≥ max child v` ⇒ expand `n`), full ranking.

Tests (`test_select.py`, fixed tiny trees, hand-computed μ/σ): posterior
asserted directly, fixed draws injected; cold-start is prior, flat line
collapses, Tree A → B1, bad-kid root → respawn.

## 3. `evaluate.py`

`run(eval_exe, path) -> float | None`: spawn `EVAL <path>` and wait,
first non-empty stdout line parses as float else `None`. Nonzero exit
⇒ `None` (unscored, selector-blind). Timeouts are EVAL's job, not the
framework's. stderr ignored. ~20 lines.

Tests (`test_evaluate.py`, fixture scripts): exit-0 parse, bad float ⇒
`None`, nonzero ⇒ `None`, warning lines skipped.

## 4. `improve.py`

`improve(code: bytes, parent_code, best_code) -> bytes`: `urllib` POST
to `$OPENAI_BASE_URL/chat/completions` (`$OPENAI_API_KEY`,
`$OPENAI_MODEL`), prompt = parent + best + current code with "reply
with the complete file, nothing else". Parse JSON envelope, take
`choices[0].message.content`, strip ``` fences, return remainder bytes.

Tests (`test_improve.py`, mocked HTTP): prompt contents, envelope
parse, fence strip, bytes passthrough.

## 5. `loop.py` + `cli.py`

Flags: `--working-dir/--starter/--evaluate/--seed/--max-evals`.
Step 0: seed identity check — a scored NULL-parent row with another sha
⇒ abort (refuse to mix lineages). Same sha scored ⇒ resume (skip).
Otherwise insert and score (fails ⇒ abort). Worker body: select → claim
(committed before improve) → improve → insert → evaluate → record.
Orderly failure releases the claim; crashes abandon rows. Budgets read
from `meta` (shared across processes; overshoot ≤ worker count
accepted). Best sha+score printed to stdout.

Tests (`test_loop.py`, fake eval e.g. byte-length score): 5-round run
(reaches selection past the 2-gain bootstrap), budgets stop, best
printed.

## 6. Smoke

Fake-eval CLI run (byte-length): tree grows, scores recorded, best
printed, history replays state-at-R. No example game.

## Deferred

Diff edits, `--max-time`, `--quiet`, model tiers/flags, split worker
roles, `--workers` flag, MAD spread, git anything, docs beyond README.
