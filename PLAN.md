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
invisible). Seeded RNG in, one node id out.

- `sigma0(rows)`: 0 gains ⇒ only root exists ⇒ return root; 1 gain ⇒
  `|g|`; ≥2 ⇒ `statistics.pvariance`. Zero spread allowed (point mass).
- `posterior(node, children)`: `(μ, σ, ν)` per README.
- `sample_X(rng, μ, scale, nu)`: caller precomputes
  `scale = σ√(1+1/(1+k))`; chi-square via
  `random.gammavariate(nu/2, 2.0)`.
- `select(rng, rows, sampler=sample_X) -> id`: bottom-up V sample,
  descend from root (`x_n ≥ max child v` ⇒ expand `n`). Worker retries
  on lost claim (fresh draw each try); all-claimed ⇒ exit, nothing to do.

Tests (`test_select.py`, fixed tiny trees, hand-computed μ/σ): posterior
asserted directly, fixed draws injected; cold-start is prior, flat line
collapses, Tree A → B1, bad-kid root → respawn.

## 3. `loop.py` + `cli.py`

Two subprocess helpers live here, not as modules. Eval: `run(eval_exe,
path)` spawns `EVAL <path>` and waits; first non-empty stdout line
parses as float else `None`. Nonzero exit ⇒ `None` (unscored,
selector-blind). Timeouts are EVAL's job. stderr ignored. Improve:
render `prompts/improve.md` (tokens `__PARENT_CODE__`, `__PARENT_SCORE__`,
`__BEST_CODE__`, `__BEST_SCORE__`, `__CURRENT_CODE__`, `__CURRENT_SCORE__`;
long tokens so braces/dollars in code can't collide), pipe to
`pi --print -nt` (on PATH) via stdin; stdout taken verbatim as the new
file. `--model` passes through verbatim.

Flags: `--working-dir/--starter/--evaluate/--seed/--max-evals` plus
`--model` (forwarded to `pi --print`).
Step 0: checksum `--starter`; if the root row's sha differs, abort (two
seeds, one tree). Same sha scored ⇒ resume. Else insert and score
(fails ⇒ abort). Worker body: select → claim
(committed before improve) → improve → insert → evaluate → record.
Orderly failure releases the claim; crashes abandon rows. Budgets read
from `meta` (shared across processes; overshoot ≤ worker count
accepted). Exit when done.

`read.py` (`autoresearch-read --working-dir DIR`): prints best path+score.
Test: fixed db, assert output.

Tests (`test_loop.py`, fixture eval + fake-`pi` scripts, fake eval e.g.
byte-length score): exit-0 parse, bad float/nonzero ⇒ `None`, template
renders fixture code containing braces/dollars intact, stdout
passthrough, 5-round run (reaches selection past the 2-gain bootstrap),
budgets stop.

## 4. Smoke

Fake-eval CLI run (byte-length): tree grows, scores recorded, best
printed, history replays state-at-R. No example game.

## Deferred

Diff edits, `--max-time`, `--quiet`, model tiers/flags, split worker
roles, `--workers` flag, MAD spread, git anything, docs beyond README.
