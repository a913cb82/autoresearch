#!/usr/bin/env python3
"""Score a TSP solver over generated maps. Usage: evaluate.py CANDIDATE.

CANDIDATE defines order(cities) -> tour (a permutation of range(n)).
Maps are generated from seed 0, so every run scores the same maps.
Each map runs in its own process (this file re-invoked with --drive)
with a 10s timeout; any failure (timeout, crash, invalid tour) falls
back to a fixed random tour so the score is always finite. Timeouts
are EVAL's job.
"""

import json
import random
import subprocess
import sys

N_MAPS = 8
N_CITIES = 50
TIMEOUT = 10


def make_maps():
    rng = random.Random(0)
    return [
        [[rng.random() * 1000, rng.random() * 1000] for _ in range(N_CITIES)]
        for _ in range(N_MAPS)
    ]


MAPS = make_maps()


def length(cities, tour):
    total = 0.0
    for i in range(len(tour)):
        a, b = cities[tour[i]], cities[tour[(i + 1) % len(tour)]]
        total += ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    return total


def fallback(n):
    tour = list(range(n))
    random.Random(0).shuffle(tour)
    return tour


def valid(tour, cities):
    return (
        isinstance(tour, list)
        and len(tour) == len(cities)
        and sorted(tour) == list(range(len(cities)))
    )


def drive(cand, cities_json):
    ns: dict = {}
    exec(compile(open(cand).read(), cand, "exec"), ns)
    tour = ns["order"](json.loads(cities_json))
    print("TOUR:" + json.dumps(tour))


def solve(cand, cities):
    try:
        proc = subprocess.run(
            [sys.executable, __file__, "--drive", cand, json.dumps(cities)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if proc.returncode != 0:
            raise ValueError("driver failed")
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("TOUR:")]
        tour = json.loads(lines[-1][5:])
        if not valid(tour, cities):
            raise ValueError("invalid tour")
        return tour
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return fallback(len(cities))


def main():
    if sys.argv[1] == "--drive":
        drive(sys.argv[2], sys.argv[3])
        return
    total = 0.0
    for cities in MAPS:
        total += length(cities, solve(sys.argv[1], cities))
    print(-total / len(MAPS))


main()
