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
  key TEXT PRIMARY KEY CHECK(key IN ('round', 'evaluate')),
  value TEXT);
-- meta.round: rewrite attempts (seed setup excluded)
-- meta.evaluate: absolute EVAL path (match-or-omit on resume)
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
call `prompts/improve.render()` (plain-Python template: parent block
omitted for roots, reference section omitted without `--read-paths`;
values are never parsed, so braces/dollars in code can't collide),
pipe via stdin to
`pi --print` (on PATH) with `--model` verbatim; stdout taken verbatim
as the new file. No `--read-paths` ⇒ `-nt` (no tools). With paths ⇒
`-e read_approved.ts` plus `--tools read_approved,read --no-mcp`:
a static, checked-in gate (shipped in the package, found via
`importlib.resources`) in front of pi's own `read`. The gate checks
`realpath` against `AUTORESEARCH_READ_PATHS` (same env pattern as
`AUTORESEARCH_SEED`) and denials return model-readable text; allowed
reads delegate via `ctx.executeTool`, so behavior (offset/limit,
truncation, images) is the built-in's byte for byte. `read` is
declared but hidden from the model (`prepareLoadout` +
`reachesTools`), so the gate is the only read path it sees.

Flags: `--working-dir/--initial/--evaluate/--seed/--max-rewrites`
(`--initial/--evaluate` optional on resume, required fresh).
plus `--model` (forwarded to `pi --print`), plus repeatable
`--read-paths`. `expand_read_paths(entries)`: each entry a file, a
dir (recursive files), or a quoted glob (`Path.glob`, `**`
supported); relative entries resolve from invocation cwd; output
absolutized, sorted, frozen at startup. Missing entry or zero-match
glob ⇒ `parser.error`. CLI exports the frozen list as
`AUTORESEARCH_READ_PATHS` alongside `AUTORESEARCH_SEED`; the prompt
section renders from the same variable.
Step 0: resolve `--initial` (omitted ⇒ read the root file out of the
tree; zero/ambiguous roots abort) and `--evaluate` (omitted ⇒ stored
path or abort; specified ⇒ normalize and compare, mismatch aborts;
fresh run stores it). Checksum the seed; divergent root aborts (two
seeds, one tree). Same sha scored ⇒ resume. Else insert as row 1 and
score (fails ⇒ abort). CLI exports `--seed` as `AUTORESEARCH_SEED`
before running (workers inherit via fork). Worker body per pass: select → claim (lost ⇒
pass, next pass redraws) → improve → insert → new? evaluate + record
: spend one round, drop. Every improve advances `round` exactly once;
contention passes cost nothing. Improve failure propagates loudly.
Crashes abandon rows. Budgets read from `meta` (seed setup excluded;
shared across processes; overshoot ≤ worker count accepted).
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
budgets stop, const-`pi` burns budget on dupes and ends at budget,
plus read-paths expansion/argv/prompt tests.

## 4. Smoke

Fake-eval CLI run (byte-length, covered by `test_cli.py`): tree grows,
scores recorded, `read.py` prints best. Read-paths run: session log
shows `read_approved` calls and denials.
No example game.

## Deferred

Diff edits, `--quiet`, model tiers, split worker
roles, MAD spread, git anything, docs beyond README, MCP read proxy
(if the tool boundary is ever gamed).
