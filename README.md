# autoresearch

Searches code improvements against a user-supplied scoring function.

## Setup

Python 3.11+ and `pi` with a logged-in provider:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
curl -fsSL https://pi.dev/install.sh | sh  # needs Node.js 22.19+
pi auth
```

- Write executable `EVAL` file; called as `EVAL <filepath>` with `AUTORESEARCH_SEED` in the environment
  - Evaluates the code in `filepath` and always outputs a finite float score to stdout.
- Write `INITIAL`; first file to be scored by `EVAL`.
  - Describe the goal of the code in `INITIAL`; the coding agents won't be able to see the `EVAL` script.

## Usage

### Run
```bash
autoresearch \
  --working-dir DIR --initial INITIAL --evaluate EVAL --max-rewrites M \
  [--model MODEL --seed N --generators G --evaluators E --read-paths PATH]
```
- `--read-paths`: files the agent may read
- Running in an existing working-dir restores the previous run
  - `--initial` and `--evaluate` must either match or not be specified, budget is from resume point onwards

### Read results
```bash
autoresearch-read --working-dir DIR
```

## Loop

Until the budget runs out:

1. Select a previously scored candidate.
2. pi coding agent rewrites code.
3. Score the rewrite.

### Concurrency

`--generators G` (rewrite workers) and `--evaluators E` (score workers)
run as separate processes over the same working dir. Generators select,
rewrite, and insert unscored rows; evaluators score them.

## Selection

For node `n` with score `s_n` and children `c_1…k` scoring `s_1…s_k`:

**Priors** (direct children):
- `σ²_n ~ InvGamma(1, τ_n²)`: 2 observations at `τ_n²`.
- `τ_n²` is the variance of `n`'s child gains (fewer than two ⇒ `σ₀²`, the variance over all gains).
- `θ_n | σ²_n ~ N(s_n, σ²_n)`: 1 observation at `s_n`.
- Likelihood: each observed child score `s_i ~ N(θ_n, σ²_n)`.

**Posterior** (exact):
- `μ = (s_n + Σs_i)/(1+k)`
- `(2+k)σ² = 2τ_n² + Σ(sᵢ−x̄)² + k(x̄−s_n)²/(1+k)` (`x̄` = mean of child scores, `s_n` when childless)
- `X_n ~ Student-t(2+k, μ, σ√(1+1/(1+k)))`
- `X_n` predicts the score of the next child of `n`

**Decide** (Thompson sampling; one seeded draw per node per round):
1. Draw each `X_n` once.
2. Expand the node with the highest draw. Ties break by lower id.
- Unscored rows are ignored.

**Behavior** (selection frequency over rounds; one draw fluctuates):
- No children: selected by score on average; tails add exploration
  (once gains exist; before that, best score wins).
- Flat children: tight local temperature samples low ⇒ rarely selected.
- Improving child: high mean, broad local spread ⇒ often selected.
- Large subtrees get no extra weight: one node, one draw.

## Storage

```
working-dir/              # --working-dir DIR, per run
├── tree.db               # SQLite WAL: nodes, meta tables
└── nodes/                # code for each node
    ├── <sha1>
    ├── <sha2>
    └── …
```

```sql
CREATE TABLE nodes(
  id      INTEGER PRIMARY KEY,
  sha     TEXT UNIQUE NOT NULL,
  parent  INTEGER REFERENCES nodes(id),
  score   REAL,
  scoring INTEGER DEFAULT 0
);
CREATE TABLE meta(
  key TEXT PRIMARY KEY CHECK(key IN ('round', 'evaluate')),  -- attempt counter
  value TEXT);
```
