"""Find short tours visiting every city once.

Goal: minimize average tour length over many unseen city sets.
Budget: order() must return within 10 seconds per map.
Future agents will try to improve your code; leave notes for them.
"""

import random


def order(cities: list[tuple[float, float]]) -> list[int]:
    rng = random.Random(7)
    tour = list(range(len(cities)))
    rng.shuffle(tour)
    return tour
