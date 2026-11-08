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
CREATE TABLE meta(
  key TEXT PRIMARY KEY CHECK(key IN ('round')),
  value TEXT);
-- meta.round: evaluation attempts (dupes burn attempts without rows)
```

Functions: `add_node(parent, code: bytes) -> (id, is_new)` (tmp+rename +
`INSERT OR IGNORE`; on sha hit, SELECT the existing id — `lastrowid` is
stale on ignore), `claim(id) -> bool`
(`UPDATE … SET claimed=1 WHERE id=? AND claimed=0`, winner reads
rowcount), `release(id)` (owns clearing; recording never clears),
`record_score(id, score)` (UPDATE score + meta bump via
`spend_round`, one txn), `spend_round()` (bare meta bump, also used for
dropped duplicates), `get(id)`, `best()` (highest score, lowest id),
`all_rows()`.
`node_path(nodes_dir, sha)` (extensionless).
Dedup-hit ⇒ skip eval, release, re-pick.

Tests (`test_db.py`, `:memory:` except one tmpdir two-process claim
race): dedup collapse + id SELECT, double-claim one winner,
score+round atomic with claim held, `:memory:` asserts no WAL.

## 2. `select.py`

Pure functions, no I/O. Candidates = scored nodes only (NULL rows are
invisible). Seeded RNG in, one node id out.

- `sigma0(rows)`: 0 gains ⇒ `None`; 1 gain ⇒ `g²`; ≥2 ⇒
  `statistics.pvariance`. Returns the variance `σ₀²`. Zero spread
  allowed (point mass).
- `posterior(node, children, variance)`: `(μ, σ, ν)` per README.
- `sample_X(rng, μ, scale, nu)`: caller precomputes
  `scale = σ√(1+1/(1+k))`; chi-square via
  `random.gammavariate(nu/2, 2.0)`.
- `select(rng, rows, sampler=sample_X) -> id`: bottom-up V sample,
  descend from root (`x_n > max child v` ⇒ expand `n`, else step to
  best child). No-gains ⇒ best score, lowest id. Ties break by lower
  id. Worker passes on lost claim (next pass redraws).

Tests (`test_select.py`, fixed tiny trees, hand-computed μ/σ): posterior
asserted directly, σ₀ variance units, fixed draws injected; cold-start
is prior, flat line collapses, Tree A → B1, bad-kid root → respawn.

## 3. `loop.py` + `cli.py`

Two subprocess helpers live here, not as modules. Eval: `run(eval_exe,
path)` spawns `EVAL <path>` and waits; first non-empty stdout line
parses as float else `RuntimeError`, aborting the run. Nonzero exit ⇒
`RuntimeError` with returncode and stderr. Timeouts are EVAL's job.
stderr ignored except in the error message. EVAL inherits
`AUTORESEARCH_SEED` (the `--seed` value) from the worker process env;
use or ignore. Improve:
render `prompts/improve.md` ("rewrite to score higher"; tokens
`__PARENT_CODE__`, `__PARENT_SCORE__`, `__BEST_CODE__`, `__BEST_SCORE__`,
`__CURRENT_CODE__`, `__CURRENT_SCORE__`; long tokens so braces/dollars
in code can't collide), pipe to `pi --print -nt` (on PATH) via stdin;
stdout taken verbatim as the new file. `--model` passes through
verbatim.

Flags: `--working-dir/--initial/--evaluate/--seed/--max-evals`
plus `--model` (forwarded to `pi --print`).
Step 0: checksum `--initial`; if a root row's sha differs, abort (two
seeds, one tree). Same sha scored ⇒ resume. Else insert as row 1 and
score (fails ⇒ abort). CLI exports `--seed` as `AUTORESEARCH_SEED`
before running (workers inherit via fork). Worker body per pass: select → claim (lost ⇒
pass, next pass redraws) → improve → insert → new? evaluate + record
: spend one round, drop. Every improve advances `round` exactly once;
contention passes cost nothing. Improve failure propagates loudly.
Crashes abandon rows. Budgets read from `meta` (seed scoring consumes
budget; shared across processes; overshoot ≤ worker count accepted).
Exit at budget. `worker()` (same body, own connection, `seed + i`)
is the multiprocess entry; `--workers W` spawns W of them, fails
loudly on nonzero exits.

`read.py` (`autoresearch-read --working-dir DIR`): read-only open,
prints best path+score, exit 1 when empty.
Test: fixed db, assert output.

Tests (`test_loop.py`, fixture eval + fake-`pi` scripts, fake eval e.g.
byte-length score): exit-0 parse, bad float/nonzero ⇒ `RuntimeError`, template
renders fixture code containing braces/dollars intact, stdout
passthrough, 5-round run (reaches selection past the 2-gain bootstrap),
budgets stop, const-`pi` burns budget on dupes and ends at budget.

## 4. Smoke

Fake-eval CLI run (byte-length, covered by `test_cli.py`): tree grows,
scores recorded, `read.py` prints best.
No example game.

## Deferred

Diff edits, `--quiet`, model tiers, split worker
roles, MAD spread, git anything, docs beyond README.
