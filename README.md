# autoresearch

Evolve code against a score. You bring the exam; the loop brings the search.

## Contract

1. `evaluate(filepath: str) -> float` — your scoring function. Deterministic.
2. A seed file — starting code. Its score is the root of the tree.

## Loop

Forever, serially:

1. **Select** — pick the node to expand using the Bayesian tree selector
   (`docs/selector.md`): each node models its children's scores, and the loop
   descends toward the highest upper-quantile prospect.
2. **Improve** — an agent rewrites the node's code to maximize the score.
3. **Score** — run `evaluate`, attach the child to the tree with its score.

Best score is kept. Budgets stop the loop.

## Non-goals (v0)

No concurrency, no population grids, no islands, no LLM judges.
One loop, one exam, one tree.

## Layout

```
docs/selector.md   the Bayesian selection rule
```

## Status

v0: this README. Loop and selector to follow.
