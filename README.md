# autoresearch

Searches code improvements against a user-supplied scoring function.

## Contract

- `evaluate(filepath: str) -> float` — deterministic scorer.
- A seed file — starting code, tree root.

## Loop

Serial, until budgets run out:

1. Select a node.
2. Agent rewrites its code to raise the score.
3. Score the rewrite; attach as a child.

Best score kept.

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

**Decide** (one seeded draw per round):
1. Sample every `V_n`: draw each `X_n`, max with `B_n`, child samples.
2. Walk from root: expand `n` if its fresh draw beats all children's
   samples; else step to the best child.
3. Stop on budget exhaustion. Past scores never compete.

**Behavior** (selection frequency over rounds; one draw fluctuates):
- No children: selected by score on average; tails add exploration.
- Flat children: tight spread samples low every draw ⇒ rarely selected.
- Improving child: high mean, broad spread ⇒ often selected.
- Several live shots: more draws per round ⇒ higher max ⇒ selected more.

**Numbers.** Fixed: weights 1, 2. Learned: `σ₀` global; `μ`, `σ` per node.

## Storage

| What | Detail |
|---|---|
| `tree.db` | SQLite WAL, stdlib only |
| table | `nodes(id, sha UNIQUE, parent, score, claimed)`, index on `parent` |
| `score NULL` | unevaluated |
| `claimed` | worker flag; `UPDATE … WHERE claimed=0`, winner reads rowcount |
| dedup | atomic via `INSERT OR IGNORE` on `sha` |
| `nodes/{sha}.py` | code as raw files; `evaluate` takes the path; tmp+rename writes |
| seed | row 1, `parent = NULL` |
| git | commits `tree.db` + `nodes/` per keep |
| tests | same schema on `:memory:` |
| ceiling | one machine; later backends keep the `claim/score/children` interface |

## Non-goals

No concurrency, grids, islands, judges. One loop, one exam, one tree.

## Status

v0: this README. Code to follow.
