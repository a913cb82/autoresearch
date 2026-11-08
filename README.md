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

### Concurrency

N processes run the same loop body. Orderly failure releases the claim;
crashed claims are abandoned.

## Selection

For node `n` with score `s_n` and children `c_1…k` scoring `s_1…s_k`:

**Priors** (direct children):
- `σ₀²` is the variance of all `child − parent` gains.
- `σ²_n ~ InvGamma` around `σ₀²`, weight 2 (smallest sample with a spread).
- `θ_n`, `σ²_n` are `n`'s unknown child-mean and child-spread.
- Prior: `θ_n ~ N(s_n, σ₀²)`, weight 1 (smallest sample with a mean).
- Likelihood: each observed child score `s_i ~ N(θ_n, σ²_n)`.

**Posterior** (exact):
- `μ = (s_n + Σs_i)/(1+k)`
- `(2+k)σ² = 2σ₀² + Σ(sᵢ−x̄)² + k(x̄−s_n)²/(1+k)`
- `X_n ~ Student-t(2+k, μ, σ√(1+1/(1+k)))`
- `X_n` predicts the score of the next child of `n`

**Potential** (bottom-up, leaves first):
- `B_n` is the best scored node at/below `n`
- `V_n = max(B_n, X_n, max child V)`
- `V_n` is the best score reachable in `n`'s subtree

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
- Claim: `UPDATE … SET claimed=1 WHERE id=? AND claimed=0`, winner
  reads rowcount. Dedup: `INSERT OR IGNORE` on `sha`.
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
