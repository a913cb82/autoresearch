import multiprocessing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autoresearch import db


class TestDb(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.nodes = Path(self.tmp.name) / "nodes"
        self.conn = db.connect(":memory:")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_add_and_dedup(self) -> None:
        node_id, is_new = db.add_node(self.conn, self.nodes, None, b"print(1)")
        self.assertEqual((node_id, is_new), (1, True))
        same_id, same_new = db.add_node(self.conn, self.nodes, None, b"print(1)")
        self.assertEqual((same_id, same_new), (1, False))
        self.assertEqual(db.node_path(self.nodes, "x").parent, self.nodes)
        files = list(self.nodes.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].suffix, "")
        self.assertEqual(files[0].read_bytes(), b"print(1)")

    def test_reserve_oldest_null(self) -> None:
        a, _ = db.add_node(self.conn, self.nodes, None, b"a")
        b, _ = db.add_node(self.conn, self.nodes, a, b"b")
        first = db.reserve(self.conn)
        assert first is not None
        self.assertEqual(first["id"], a)
        second = db.reserve(self.conn)
        assert second is not None
        self.assertEqual(second["id"], b)
        self.assertIsNone(db.reserve(self.conn))

    def test_reserve_skips_scored(self) -> None:
        a, _ = db.add_node(self.conn, self.nodes, None, b"a")
        db.record_score(self.conn, a, 1.0)
        b, _ = db.add_node(self.conn, self.nodes, a, b"b")
        row = db.reserve(self.conn)
        assert row is not None
        self.assertEqual(row["id"], b)

    def test_record_clears_scoring(self) -> None:
        a, _ = db.add_node(self.conn, self.nodes, None, b"a")
        db.reserve(self.conn)
        db.record_score(self.conn, a, 1.0)
        self.assertEqual(db.get(self.conn, a)["scoring"], 0)

    def test_reserve_race_two_processes(self) -> None:
        db_dir = str(Path(self.tmp.name) / "reserve_race")
        conn = db.connect(db_dir)
        db.add_node(conn, Path(db_dir) / "nodes", None, b"a")
        conn.close()

        def grab(db_dir: str, queue: "multiprocessing.Queue") -> None:
            c = db.connect(db_dir)
            row = db.reserve(c)
            queue.put(None if row is None else row["id"])
            c.close()

        queue: multiprocessing.Queue = multiprocessing.Queue()
        procs = [
            multiprocessing.Process(target=grab, args=(db_dir, queue)) for _ in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        self.assertEqual(sorted((queue.get() for _ in range(2)), key=str), [1, None])

    def test_claim_round_fresh(self) -> None:
        self.assertTrue(db.claim_round(self.conn, 3))
        self.assertEqual(db.meta_get(self.conn, "round"), "1")

    def test_claim_round_exhausted(self) -> None:
        db.meta_set(self.conn, "round", "3")
        self.assertFalse(db.claim_round(self.conn, 3))
        self.assertEqual(db.meta_get(self.conn, "round"), "3")

    def test_claim_round_burst_exact(self) -> None:
        db_dir = str(Path(self.tmp.name) / "claim_race")
        db.connect(db_dir).close()

        def grab(db_dir: str, queue: "multiprocessing.Queue", limit: int) -> None:
            c = db.connect(db_dir)
            try:
                wins = sum(db.claim_round(c, limit) for _ in range(5))
            finally:
                c.close()
            queue.put(wins)

        queue: multiprocessing.Queue = multiprocessing.Queue()
        procs = [
            multiprocessing.Process(target=grab, args=(db_dir, queue, 3))
            for _ in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        self.assertEqual(queue.get() + queue.get(), 3)
        conn = db.connect(db_dir)
        self.assertEqual(db.meta_get(conn, "round"), "3")
        conn.close()

    def test_record_score_round_history(self) -> None:
        node_id, _ = db.add_node(self.conn, self.nodes, None, b"a")
        db.record_score(self.conn, node_id, 0.5)
        row = db.all_rows(self.conn)[0]
        self.assertEqual(row["score"], 0.5)
        self.assertEqual(db.meta_get(self.conn, "round"), "1")

    def test_meta_rejects_unknown_key(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            db.meta_set(self.conn, "rounds", "1")


if __name__ == "__main__":
    unittest.main()
