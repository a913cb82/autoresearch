import math
import random
import tempfile
import unittest
from pathlib import Path

from autoresearch import db, select


def _mean_sampler(rng: random.Random, mu: float, scale: float, nu: int) -> float:
    del rng, scale, nu
    return mu


class TestSelect(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.nodes = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _tree(self, specs: "list[tuple[int | None, float | None, bytes]]"):
        conn = db.connect(":memory:")
        ids = []
        for parent_idx, score, code in specs:
            parent = ids[parent_idx] if parent_idx is not None else None
            node_id, _ = db.add_node(conn, self.nodes, parent, code)
            ids.append(node_id)
            if score is not None:
                db.record_score(conn, node_id, score)
        return conn, ids

    def test_posterior_math(self) -> None:
        mu, sigma, nu = select.posterior(0.8, [0.81, 0.79], 0.0025)
        self.assertAlmostEqual(mu, 0.8)
        self.assertAlmostEqual(sigma, math.sqrt(0.0013))
        self.assertEqual(nu, 4)

    def test_sigma0_returns_variance(self) -> None:
        conn, _ = self._tree([(None, 0.0, b"r"), (0, 3.0, b"a"), (0, 4.0, b"b")])
        spread = select.sigma0(db.all_rows(conn))
        assert spread is not None
        self.assertAlmostEqual(spread, 0.25)
        conn2, _ = self._tree([(None, 1.0, b"r"), (0, 4.0, b"a")])
        single = select.sigma0(db.all_rows(conn2))
        assert single is not None
        self.assertAlmostEqual(single, 9.0)

    def test_cold_start_returns_root(self) -> None:
        conn, ids = self._tree([(None, 0.5, b"root")])
        self.assertEqual(select.select(random.Random(0), db.all_rows(conn)), ids[0])

    def test_no_scored_raises(self) -> None:
        conn, _ = self._tree([(None, None, b"root")])
        with self.assertRaises(AssertionError):
            select.select(random.Random(0), db.all_rows(conn))

    def test_null_child_invisible(self) -> None:
        conn, ids = self._tree([(None, 0.5, b"root"), (0, None, b"broken")])
        self.assertEqual(select.select(random.Random(0), db.all_rows(conn)), ids[0])

    def test_orphan_parent_errors(self) -> None:
        conn, _ = self._tree(
            [(None, 0.5, b"root"), (0, None, b"broken"), (1, 0.9, b"star")]
        )
        with self.assertRaises(AssertionError):
            select.select(random.Random(0), db.all_rows(conn))

    def test_mean_sampler_greedy_deepens_best_leaf(self) -> None:
        conn, ids = self._tree(
            [
                (None, 0.50, b"R"),
                (0, 0.80, b"A"),
                (1, 0.81, b"A1"),
                (1, 0.80, b"A2"),
                (1, 0.82, b"A3"),
                (1, 0.81, b"A4"),
                (1, 0.80, b"A5"),
                (0, 0.65, b"B"),
                (7, 0.75, b"B1"),
            ]
        )
        got = select.select(random.Random(0), db.all_rows(conn), _mean_sampler)
        self.assertEqual(got, ids[4])

    def test_bad_root_respawns(self) -> None:
        conn, ids = self._tree(
            [
                (None, 0.90, b"R"),
                (0, 0.52, b"A"),
                (0, 0.51, b"B"),
                (0, 0.50, b"C"),
            ]
        )
        got = select.select(random.Random(0), db.all_rows(conn), _mean_sampler)
        self.assertEqual(got, ids[0])

    def test_thompson_explores_both_lines(self) -> None:
        conn, ids = self._tree(
            [
                (None, 0.50, b"R"),
                (0, 0.80, b"A"),
                (1, 0.81, b"A1"),
                (1, 0.80, b"A2"),
                (1, 0.82, b"A3"),
                (1, 0.81, b"A4"),
                (1, 0.80, b"A5"),
                (0, 0.65, b"B"),
                (7, 0.75, b"B1"),
            ]
        )
        a_family = set(ids[1:7])
        b_family = {ids[7], ids[8]}
        picks = {select.select(random.Random(s), db.all_rows(conn)) for s in range(30)}
        self.assertTrue(picks & a_family)
        self.assertTrue(picks & b_family)


if __name__ == "__main__":
    unittest.main()
