import multiprocessing
import tempfile
import unittest
from pathlib import Path

from autoresearch import db


def _claim_worker(
    db_dir: str, node_id: int, queue: "multiprocessing.Queue[bool]"
) -> None:
    conn = db.connect(db_dir)
    queue.put(db.claim(conn, node_id))
    conn.close()


class TestDb(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.nodes = Path(self.tmp.name) / "nodes"
        self.conn = db.connect(":memory:")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_add_and_dedup(self) -> None:
        node_id, is_new = db.add_node(self.conn, self.nodes, ".py", None, b"print(1)")
        self.assertEqual((node_id, is_new), (1, True))
        same_id, same_new = db.add_node(self.conn, self.nodes, ".py", None, b"print(1)")
        self.assertEqual((same_id, same_new), (1, False))
        self.assertEqual(db.node_path(self.nodes, ".py", "x").parent, self.nodes)
        files = list(self.nodes.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b"print(1)")

    def test_claim_release(self) -> None:
        node_id, _ = db.add_node(self.conn, self.nodes, ".py", None, b"a")
        self.assertTrue(db.claim(self.conn, node_id))
        self.assertFalse(db.claim(self.conn, node_id))
        db.release(self.conn, node_id)
        self.assertTrue(db.claim(self.conn, node_id))

    def test_record_score_round_history(self) -> None:
        node_id, _ = db.add_node(self.conn, self.nodes, ".py", None, b"a")
        db.claim(self.conn, node_id)
        db.record_score(self.conn, node_id, 0.5)
        row = db.all_rows(self.conn)[0]
        self.assertEqual(row["score"], 0.5)
        self.assertEqual(row["round"], 1)
        self.assertEqual(row["claimed"], 1)
        db.release(self.conn, node_id)
        self.assertTrue(db.claim(self.conn, node_id))
        self.assertEqual(db.meta_get(self.conn, "round"), "1")
        state = db.state_at(self.conn, 1)
        self.assertEqual(len(state), 1)
        self.assertEqual(state[0]["score"], 0.5)

    def test_record_none_stays_null_bumps_round(self) -> None:
        node_id, _ = db.add_node(self.conn, self.nodes, ".py", None, b"a")
        db.record_score(self.conn, node_id, None)
        self.assertIsNone(db.all_rows(self.conn)[0]["score"])
        self.assertEqual(db.meta_get(self.conn, "round"), "1")

    def test_state_at_reconstructs_rounds(self) -> None:
        root, _ = db.add_node(self.conn, self.nodes, ".py", None, b"root")
        db.record_score(self.conn, root, 0.1)
        kid, _ = db.add_node(self.conn, self.nodes, ".py", root, b"kid")
        db.record_score(self.conn, kid, 0.9)
        round1 = db.state_at(self.conn, 1)
        self.assertEqual(len(round1), 1)
        self.assertEqual(round1[0]["score"], 0.1)
        round2 = db.state_at(self.conn, 2)
        self.assertEqual(len(round2), 2)

    def test_claim_race_two_processes(self) -> None:
        db_dir = str(Path(self.tmp.name) / "race")
        conn = db.connect(db_dir)
        node_id, _ = db.add_node(conn, Path(db_dir) / "nodes", ".py", None, b"a")
        conn.close()
        queue: multiprocessing.Queue[bool] = multiprocessing.Queue()
        procs = [
            multiprocessing.Process(target=_claim_worker, args=(db_dir, node_id, queue))
            for _ in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        self.assertEqual(sorted(queue.get() for _ in range(2)), [False, True])


if __name__ == "__main__":
    unittest.main()
