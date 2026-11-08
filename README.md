# autoresearch

Searches code improvements against a user-supplied scoring function.

## Contract

- `evaluate(filepath: str) -> float` — scores a file. Deterministic: same
  file, same score.
- A seed file — the starting code. Its score is the tree root.

## Loop

Serial, until budgets run out:

1. Select a node (rule below).
2. An agent rewrites that node's code to raise the score.
3. Score the rewrite with `evaluate`; attach it as a child with its score.

Best score kept.

## Selection

Tree of scored programs. Node `n` has score `s_n` and `k` children
scoring `s_1…s_k`. `best` = top score in the tree.

**Population.** Collect every `child − parent` gain in the tree.
`σ₀²` = their variance: typical mutation wobble.

**Per node.** Only direct children count — they alone started from its
score. With unknown child-mean `θ_n` and child-spread `σ²_n`:
- Prior: `θ_n ~ N(s_n, σ₀²)`, weight 1 — children resemble their parent
  (1 is the smallest sample with a mean).
- Prior: `σ²_n ~ InvGamma` around `σ₀²`, weight 2 — children wobble like
  the population until proven otherwise (2 is the smallest sample with
  a spread).
- Likelihood: children `~ N(θ_n, σ²_n)`.

**Posterior** (exact math, no approximation):
- `μ = (s_n + Σs_i)/(1+k)`
- `σ²` from `(2+k)σ² = 2σ₀² + Σ(sᵢ−x̄)² + k(x̄−s_n)²/(1+k)`
- Next-child prediction `X_n ~ Student-t(2+k, μ, σ√(1+1/(1+k)))`.
  t, not Normal, because spread is learned too: few children ⇒ heavy
  tails ⇒ optimism; many ⇒ near-Normal ⇒ trust the estimates.

**Potential.** `V_n` = best score reachable in `n`'s subtree.
`B_n` = best scored node at/below `n` (exact). Bottom-up, leaves first:
`V_n = max(B_n, X_n, best child V)`. Descendants shape worth here —
never the prediction above.

**Decide.** One seeded random draw per round (reproducible):
- Sample every `V_n` bottom-up: draw each `X_n`, max with `B_n` and child
  samples.
- Walk down from the root: expand `n` if its fresh draw beats all
  children's samples; else step to the best child. Past scores never
  compete — only a new expansion can score.
- Stop on budget exhaustion.

**Behavior.** No children ⇒ prediction equals prior, so unexplored nodes
rank optimistically. Flat children ⇒ mean near their level with small
spread, so exhausted nodes rank low. An improving child ⇒ high mean with
broad spread, so improving nodes rank high. A subtree with several
promising nodes ranks above a single good node.

**Numbers.** Fixed, never tuned: weights 1 and 2. Learned: `σ₀` globally;
`μ`, `σ` per node. Nothing else.

## Storage

- `tree.db` (SQLite, WAL mode, stdlib only): one table —
  `nodes(id, sha UNIQUE, parent, score, claimed)`, index on `parent`.
  `score NULL` = unevaluated. `claimed` = worker-claim flag:
  `UPDATE … WHERE claimed=0`, winner reads rowcount. Dedup is atomic
  via `INSERT OR IGNORE` on `sha`.
- `nodes/{sha}.py`: code as raw files, content-addressed. `evaluate`
  takes the path directly; concurrent writers use write-tmp + rename.
  Seed is row 1, `parent = NULL`.
- Git commits `tree.db` + `nodes/` per keep: free time-travel.
- Tests run the same schema on `:memory:`.
- Ceiling: one machine. Multi-machine day = swap the backend;
  `claim/score/children` is the whole interface.

## Non-goals

No concurrency, grids, islands, judges. One loop, one exam, one tree.

## Status

v0: this README. Code to follow.
