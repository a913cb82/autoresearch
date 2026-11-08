"""Thompson-on-V selection over scored rows. Pure functions, no I/O."""

import math
import random
import sqlite3
import statistics
from collections.abc import Callable


def sigma0(rows: list[sqlite3.Row]) -> float | None:
    scored = {int(r["id"]): float(r["score"]) for r in rows if r["score"] is not None}
    gains = [
        scored[int(r["id"])] - scored[int(r["parent"])]
        for r in rows
        if r["score"] is not None
        and r["parent"] is not None
        and int(r["parent"]) in scored
    ]
    if not gains:
        return None
    if len(gains) == 1:
        return gains[0] ** 2
    return statistics.pvariance(gains)


def posterior(
    node_score: float, child_scores: list[float], variance: float
) -> tuple[float, float, int]:
    k = len(child_scores)
    mu = (node_score + sum(child_scores)) / (1 + k)
    nu = 2 + k
    mean = sum(child_scores) / k if k else node_score
    scatter = sum((s - mean) ** 2 for s in child_scores)
    pull = k * (mean - node_score) ** 2 / (1 + k)
    sigma = math.sqrt((2 * variance + scatter + pull) / nu)
    return mu, sigma, nu


def sample_X(rng: random.Random, mu: float, scale: float, nu: int) -> float:
    z = rng.normalvariate(0.0, 1.0)
    chi2 = rng.gammavariate(nu / 2.0, 2.0)
    return mu + scale * z / math.sqrt(chi2 / nu)


def select(
    rng: random.Random,
    rows: list[sqlite3.Row],
    sampler: Callable[[random.Random, float, float, int], float] = sample_X,
) -> int:
    scored = [r for r in rows if r["score"] is not None]
    assert scored, "no scored nodes"
    by_id = {int(r["id"]): r for r in scored}
    kids: dict[int, list[int]] = {}
    for r in scored:
        parent = r["parent"]
        if parent is not None and int(parent) in by_id:
            kids.setdefault(int(parent), []).append(int(r["id"]))
    spread = sigma0(rows)
    if spread is None:
        top = max(scored, key=lambda r: (float(r["score"]), -int(r["id"])))
        return int(top["id"])
    draws: dict[int, float] = {}
    potentials: dict[int, float] = {}

    def potential(node_id: int) -> float:
        if node_id in potentials:
            return potentials[node_id]
        node = by_id[node_id]
        child_ids = kids.get(node_id, [])
        child_scores = [float(by_id[c]["score"]) for c in child_ids]
        mu, sigma, nu = posterior(float(node["score"]), child_scores, spread)
        x = sampler(rng, mu, sigma * math.sqrt(1 + 1 / (1 + len(child_ids))), nu)
        best = float(node["score"])
        for c in child_ids:
            child_v = potential(c)
            if child_v > best:
                best = child_v
        value = x if x > best else best
        draws[node_id] = x
        potentials[node_id] = value
        return value

    for r in scored:
        potential(int(r["id"]))
    roots = [r for r in scored if r["parent"] is None or int(r["parent"]) not in by_id]
    node = max(roots, key=lambda r: (potentials[int(r["id"])], -int(r["id"])))
    while True:
        child_ids = kids.get(int(node["id"]), [])
        if not child_ids:
            return int(node["id"])
        top = max(child_ids, key=lambda c: (potentials[c], -c))
        if draws[int(node["id"])] > potentials[top]:
            return int(node["id"])
        node = by_id[top]
