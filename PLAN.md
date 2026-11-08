# Plan (v0)

Each phase: tests → code → hooks → commit → push.

## 1. `db.py`

Store. `connect(dir)` creates dirs, enables WAL, builds schema.

```sql
CREATE TABLE nodes(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL,
  parent INTEGER REFERENCES nodes(id), score REAL,
  claimed INTEGER DEFAULT 0);
CREATE INDEX idx_parent ON nodes(parent);
-- history(round,id,sha,parent,score) via triggers (claimed excluded)
-- meta(key,value): round counter
```

Functions: `add_node(parent, code: bytes) -> (id, sha)` (tmp+rename +
`INSERT OR IGNORE`), `claim(id, now) -> bool`, `record_score(id, score)`
(score + history + round bump, one txn), `children(id)`, `all_rows()`.
`node_path(sha)` for file paths.

Tests (`test_db.py`, `:memory:`): dedup collapse, double-claim one
winner, score+round atomic, children query, state-at-R via history.

## 2. `select.py`

Pure functions, no I/O. Seeded RNG in, node id out.

- `sigma0(rows)`: variance of all `child − parent` gains (needs ≥2 gains;
  before that, skip selection — expand root).
- `posterior(node, children)`: `(μ, σ, ν)` per README.
- `sample_X(rng, μ, σ, ν)`: `μ + σ√(1+1/κ)·Z/√(V/ν)`, `Z` normal,
  `V` chi-square via `random.gammavariate`.
- `select(rng, rows) -> id`: bottom-up V sample, descend from root
  (`x_n ≥ max child v` ⇒ expand `n`).

Tests (`test_select.py`, fixed tiny trees, hand-computed μ/σ): cold-start
is prior, flat line collapses, Tree A → B1, bad-kid root → respawn.

## 3. `evaluate.py`

`run(eval_exe, path, timeout) -> float | None`: spawn
`EVAL <path>`, first stdout line parses as float, else `None`. Nonzero
exit or timeout ⇒ `None` (unscored, selector-blind). ~30 lines.

Tests (`test_evaluate.py`, fixture scripts): exit-0 parse, bad float ⇒
`None`, nonzero ⇒ `None`, timeout kills.

## 4. `improve.py`

`improve(endpoint, model, priors_text, code: bytes) -> bytes`:
`urllib` POST to OpenAI-compatible `/chat/completions`, prompt =
metrics + prior code + current code + "reply with the complete file,
nothing else". Response body written verbatim.

Tests (`test_improve.py`, mocked HTTP): prompt contents, bytes
passthrough.

## 5. `loop.py` + `cli.py`

Worker body: select → claim → improve → insert → evaluate → record.
Orderly failure releases the claim; crashes abandon rows.
`--max-evals`, `--max-time`, `--seed`, `--timeout`, `--model`;
`best.py` always written. Fresh = `rm -rf DIR` (no flag). One worker;
N workers = N processes.

Tests (`test_loop.py`, fake eval e.g. byte-length score): 3-round run
grows the tree, budgets stop, best written.

## 6. Smoke

`examples/tictactoe/`: seed player + eval executable. One 20-eval run:
score climbs, tree reads sane.

## Deferred

Diff edits, `--target-score`, `--quiet`, model tiers, split worker
roles, `--workers` flag, MAD spread, git anything, docs beyond README.
