# autoresearch

Searches code improvements against a user-supplied scoring function.

## Usage

`autoresearch --working-dir DIR --starter SEED --evaluate EVAL`

- `EVAL`: executable. Called as `EVAL <filepath>`; returns the score to stdout.
- `SEED`: starting file.

## Loop

Until budgets run out — one worker runs it serially, N run it
concurrently:

1. Select a node (atomic claim).
2. Agent rewrites its code to raise the score.
3. Score the rewrite; attach as a child.

Best score kept.

Workers: N processes run the loop body. Selection claims atomically;
stale claims are retried, unscored orphans evaluated before generating
new.

## Selection

| Symbol | Meaning |
|---|---|
| `n` | a node (scored program) |
| `s_n` | its score |
| `k`, `s_1…s_k` | child count, child scores |
| `best` | top score in tree |
| `σ₀²` | variance of all `child − parent` gains (mutation wobble) |
| `θ_n`, `σ²_n` | unknown child-mean, child-spread of `n` |
| `X_n` | predicted next-child score of `n` |
| `V_n` | best score reachable in `n`'s subtree |
| `B_n` | best scored node at/below `n` (exact) |

**Priors** (direct children only — they alone started from its score):
- `θ_n ~ N(s_n, σ₀²)`, weight 1 (smallest sample with a mean).
- `σ²_n ~ InvGamma` around `σ₀²`, weight 2 (smallest sample with a spread).
- Likelihood: children `~ N(θ_n, σ²_n)`.

**Posterior** (exact):
- `μ = (s_n + Σs_i)/(1+k)`
- `(2+k)σ² = 2σ₀² + Σ(sᵢ−x̄)² + k(x̄−s_n)²/(1+k)`
- `X_n ~ Student-t(2+k, μ, σ√(1+1/(1+k)))`
- t, not Normal: learned spread ⇒ heavy tails when unexplored
  (optimism), near-Normal when sampled (trust estimates).

**Potential** (bottom-up, leaves first):
- `V_n = max(B_n, X_n, best child V)`
- Descendants shape worth here — never the prediction above.

**Decide** (Thompson sampling; one seeded draw per node per round):
1. Sample every `V_n`: draw each `X_n`, max with `B_n`, child samples.
2. Walk from root: expand `n` if its fresh draw beats all children's
   samples; else step to the best child.
3. Stop on budget exhaustion.

**Behavior** (selection frequency over rounds; one draw fluctuates):
- No children: selected by score on average; tails add exploration.
- Flat children: tight spread samples low every draw ⇒ rarely selected.
- Improving child: high mean, broad spread ⇒ often selected.
- Several live shots: more draws per round ⇒ higher max ⇒ selected more.

**Numbers.** Fixed: weights 1, 2. Learned: `σ₀` global; `μ`, `σ` per node.

## Storage

```
working-dir/              # --working-dir DIR, per run
├── tree.db               # SQLite WAL: nodes, history, meta tables
└── nodes/                # code for each node
    ├── <sha1>.py
    ├── <sha2>.py
    └── …
```

- `tree.db`: SQLite WAL. `score NULL` = unevaluated.

```sql
CREATE TABLE nodes(
  id      INTEGER PRIMARY KEY,
  sha     TEXT UNIQUE NOT NULL,
  parent  INTEGER REFERENCES nodes(id),
  score   REAL,
  claimed INTEGER DEFAULT 0
);
CREATE INDEX idx_parent ON nodes(parent);
```
- Claim sets `claimed` to now-epoch: single `UPDATE` taking `claimed=0`
  or stale rows. Dedup: `INSERT OR IGNORE` on `sha`.
- `nodes/{sha}<suffix>`: raw code (suffix from seed), tmp+rename writes.
  Seed is row 1.
- Working dir holds `tree.db` + `nodes/`; this repo holds neither.
- History: `history` table via triggers (`claimed` flips excluded).
  State at R = latest rows with `round <= R`.
- Tests: same schema on `:memory:`.
- Ceiling: one machine. Later backends keep the `claimed/score/parent`
  columns.

## Status

v0: this README. Code to follow.
