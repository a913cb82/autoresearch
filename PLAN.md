# Plan (v0)

Each phase: tests → code → hooks → commit → push. Short transactions
everywhere; no transaction is ever held across improve/evaluate.

## 1. `db.py`

Store. `connect(dir)` creates dirs, enables WAL, builds schema.

```sql
CREATE TABLE nodes(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL,
  parent INTEGER REFERENCES nodes(id), score REAL,
  scoring INTEGER DEFAULT 0);
CREATE TABLE meta(
  key TEXT PRIMARY KEY CHECK(key IN ('round', 'evaluate')),
  value TEXT);
-- meta.round: rewrite attempts (seed setup excluded)
-- meta.evaluate: absolute EVAL path (match-or-omit on resume)
```

Functions: `add_node(parent, code: bytes) -> (id, is_new)` (tmp+rename +
`INSERT OR IGNORE`; on sha hit, SELECT the existing id — `lastrowid` is
stale on ignore),
`record_score(id, score)` (UPDATE score + clear scoring, one txn; rounds are
claimed only at dispatch via `claim_round`), `reserve()` (atomic eval grab:
`UPDATE … SET scoring=1 WHERE score IS NULL AND scoring=0 … RETURNING id`;
needs SQLite 3.35+, asserted), `get(id)`, `best()` (highest score,
lowest id), `all_rows()`. `connect()` ensures the scoring column
(`ALTER TABLE`, old dirs).
`node_path(nodes_dir, sha)` (extensionless).
Dedup-hit ⇒ skip eval, burns its dispatch-claimed round; next pass re-picks.
No claims: concurrent same-parent work just yields siblings (dedup
absorbs identical code); kills leave NULL orphans the selector
ignores, so no recovery exists.

Tests (`test_db.py`, `:memory:`): dedup collapse + id SELECT,
score+round atomic, reserve race (two processes, one NULL ⇒ one winner),
`:memory:` asserts no WAL.

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
  id.

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
`pi --print` (on PATH) with `--model` verbatim; the agent saves the
new file with the `write_candidate` tool and stdout is ignored.
Two static, checked-in gates (shipped in the package, found via
`importlib.resources`): `read_approved.ts` in front of pi's own
`read`, `write_candidate.ts` in front of pi's own `write`, always
`-e` both with `--tools
read_approved,read,write_candidate,write --no-mcp`. The
read gate checks `realpath` against `AUTORESEARCH_READ_PATHS` (same
env pattern as `AUTORESEARCH_SEED`) and denials return model-readable
text; allowed reads delegate via `ctx.executeTool`, so behavior
(offset/limit, truncation, images) is the built-in's byte for byte.
The write gate takes only `{content}` and writes it to the single
`AUTORESEARCH_CANDIDATE` path (set per iteration); it delegates to
the built-in `write`, so mkdir/encoding behavior is identical.
Both builtins stay declared but hidden from the model
(`prepareLoadout` + `reachesTools`), so the gates are the only
read/write paths it sees. A unique `.candidate-*` temp in `nodes/`
is reserved per pass and removed afterwards; exit 0 without a write
⇒ `FileNotFoundError`, so fence-wrapped stdout chatter can no longer
poison the tree.

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
before running (workers inherit via fork). CLI wipes `scoring` markers
at startup (previous owners gone) and takes `--generators G` /
`--evaluators E` (default 1/1). Generator claims one round per pass (atomic at dispatch; dupe/crash
burns it — round never exceeds max) → select (scores trail
generation; staleness accepted) → improve → insert. Evaluator loop: reserve oldest NULL → evaluate →
record → exit when `generators_done` is set and no unmarked NULLs,
else sleep-poll 1s. Stuck markers are left for resume; FIFO
by id scores them first. `evaluate()` logs `scored node …` per score
and `best <score> (node <id>)` (INFO) only on improvement
(timestamps via `basicConfig`); generator/evaluator start INFO;
nonzero exits WARNING. Improve/EVAL failure propagates loudly.
Crashes abandon rows (NULL orphans stay invisible). Budget claimed
from `meta` (seed setup excluded; shared across processes; atomic so
concurrent claims never exceed max).
Exit: CLI joins generators, sets `generators_done` (every claimed round
has landed), joins evaluators. Terminate + return 1 on generator failure; leftovers for
resume. Generators (`seed + i`) and evaluators spawn
as separate processes; nonzero exits fail loudly.

`read.py` (`autoresearch-read --working-dir DIR`): read-only open,
prints best path+score, exit 1 when empty.
Test: fixed db, assert output.

Tests (`test_loop.py`, fixture eval + fake-`pi` scripts, fake eval e.g.
byte-length score): exit-0 parse, bad float/nonzero ⇒ `RuntimeError`, template
renders fixture code containing braces/dollars intact, candidate
file passthrough with stdout ignored (missing write ⇒ `FileNotFoundError`),
5-round run (reaches selection past the 2-gain bootstrap),
budgets stop, const-`pi` burns budget on dupes and ends at budget,
plus read-paths expansion/argv/prompt tests, plus split-role
(generator inserts NULL, evaluator scores and exits on done) tests.

## 4. Smoke

Fake-eval CLI run (byte-length, covered by `test_cli.py`): tree grows,
scores recorded, `read.py` prints best. Read-paths run: session log
shows `read_approved` calls and denials. TSP split-role smoke
(G=4, E=1): scores trail generation, evaluators exit on done.
No example game.

## Deferred

Diff edits, `--quiet`, model tiers, MAD spread,
git anything, docs beyond README, MCP read proxy
(if the tool boundary is ever gamed).
