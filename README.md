# autoresearch

Evolve code against a score. You bring the exam; the loop brings the search.

## Contract

1. `evaluate(filepath: str) -> float` — your scoring function. Deterministic.
2. A seed file — starting code. Its score is the root of the tree.

## Loop

Forever, serially:

1. **Select** — pick the node to expand (rule below).
2. **Improve** — an agent rewrites the node's code to maximize the score.
3. **Score** — run `evaluate`, attach the child to the tree with its score.

Best score is kept. Budgets stop the loop.

## Selection rule

A tree of evaluated programs. Node `n` has score `s_n` and `k ≥ 0`
evaluated children scoring `s_1…s_k` (`k` is that count).
`best` = highest score in the tree.

**Population level.** Pool every gain `g = child − parent` from every
evaluated child in the tree. `σ₀²` = variance of that pool: how much
mutations wobble.

**Node level.** For node `n` as a parent, with unknown child-mean `θ_n`
and child-spread `σ²_n`. Only direct children enter — they alone drew
from `n`'s launchpad:
* Prior: `θ_n ~ N(s_n, σ₀²)`, worth 1 pseudo-child — children resemble
  their parent (1 is the smallest sample with a mean).
* Prior: `σ²_n ~ InvGamma` centered at `σ₀²`, worth 2 pseudo-observations —
  children wobble like the population until the node's own children say
  otherwise (2 is the smallest sample with a variance).
* Likelihood: each child `s_i ~ N(θ_n, σ²_n)`.

**Posterior** (closed form). Evidence counters `κ = 1+k` (weight behind
the mean) and `ν = 2+k` (weight behind the spread):
* `μ = (s_n + Σs_i)/κ`
* `νσ² = 2σ₀² + Σ(sᵢ−x̄)² + k(x̄−s_n)²/κ`
* Next child of `n`, `X_n` `~ Student-t(ν, μ, σ√(1+1/κ))` — derived, not
  chosen: integrating a Normal likelihood over the conjugate posterior
  evaluates exactly to Student-t. Small `ν` (unexplored) ⇒ heavy tails ⇒
  optimism; large `ν` (well-sampled) ⇒ near-Normal ⇒ estimates at face
  value.

**Potential.** `V_n` = best score achievable in `n`'s subtree, including
unexpanded future. `B_n` = best evaluated score at/below `n` (exact).
Bottom-up, leaves first: `V_n = max(B_n, X_n, max_c V_c)` over children
`c`. Children's potentials enter only here — they route *through* `n`
without corrupting its launchpad.

**Selection (Thompson).** One draw per round, seeded RNG (reproducible):
sample every `V_n` bottom-up (draw each `X_n`, max with `B_n` and
children's samples). Then descend from the root: at node `n`, if its
fresh sample `x_n ≥ max_c v_c` over children, **expand `n`**; else recurse
to `argmax_c v_c`. `B_n` never competes — banked past, not an action.
Stop on budget exhaustion. In one sentence: sample the RVs, follow the
max down, expand where fresh beats below.

**Reading it.** No children ⇒ posterior equals prior, so unexplored nodes
are naturally optimistic. Flat children ⇒ mean pins to their level and
spread collapses, so the node deselects itself. A climbing child ⇒ mean
rises while spread stays broad, so the node stays attractive. A subtree
with many live shots outranks one peak.

**Numbers.** Fixed indifference defaults, never tuned: prior strengths 1
and 2. Learned from data: `σ₀` global; `μ`, `σ` per node. No other knobs.

## Non-goals (v0)

No concurrency, no population grids, no islands, no LLM judges.
One loop, one exam, one tree.

## Status

v0: this README. Loop implementation to follow.
