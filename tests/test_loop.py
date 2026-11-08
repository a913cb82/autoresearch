import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from autoresearch import db, loop
from tests.helpers import FIXTURES, fixture_pi

EVAL = str(FIXTURES / "eval_len.py")


class TestLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "work"
        self.conn = db.connect(str(self.work))
        self.nodes = self.work / "nodes"
        self.template = (
            Path(__file__).parent.parent / "autoresearch" / "prompts" / "improve.md"
        ).read_text()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_run_eval_variants(self) -> None:
        target = self.nodes / "t.py"
        self.nodes.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"12345")
        self.assertEqual(loop.run_eval(str(FIXTURES / "eval_len.py"), target), 5.0)
        self.assertEqual(loop.run_eval(str(FIXTURES / "eval_warn.py"), target), 42.0)
        with self.assertRaises(RuntimeError):
            loop.run_eval(str(FIXTURES / "eval_bad.py"), target)
        with self.assertRaises(RuntimeError):
            loop.run_eval(str(FIXTURES / "eval_fail.py"), target)

    def test_render_keeps_braces_dollars(self) -> None:
        code = "f('${x}')  # {brace} $dollar"
        out = loop.render_prompt("A __CURRENT_CODE__ B", {"__CURRENT_CODE__": code})
        self.assertEqual(out, f"A {code} B")

    def _run(self, seed: int, variant: str = "grow", max_evals: int = 5):
        work = Path(self.tmp.name) / f"w{seed}"
        conn = db.connect(str(work))
        with fixture_pi(variant):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.run(conn, work, EVAL, "m", random.Random(0), max_evals, self.template)
        rows = [(r["sha"], r["score"]) for r in db.all_rows(conn)]
        round_ = db.meta_get(conn, "round")
        conn.close()
        return rows, round_

    def test_run_grows_tree_and_replays(self) -> None:
        rows, round_ = self._run(1)
        self.assertEqual(len(rows), 4)
        self.assertEqual(round_, "5")
        again, _ = self._run(2)
        self.assertEqual(again, rows)

    def test_budget_stops(self) -> None:
        rows, round_ = self._run(3, max_evals=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(round_, "2")

    def test_duplicate_drops_and_burns(self) -> None:
        rows, round_ = self._run(4, variant="const")
        self.assertEqual(len(rows), 2)
        self.assertEqual(round_, "5")

    def test_improve_failure_raises_and_releases(self) -> None:
        loop.ensure_seed(self.conn, self.work, b"x", EVAL)
        with fixture_pi("fail"):
            with self.assertRaises(subprocess.CalledProcessError):
                loop.iterate(
                    self.conn,
                    self.work,
                    EVAL,
                    "m",
                    random.Random(0),
                    self.template,
                )
        self.assertEqual(db.all_rows(self.conn)[0]["claimed"], 0)

    def test_ensure_seed_resume_mismatch_broken(self) -> None:
        loop.ensure_seed(self.conn, self.work, b"x", EVAL)
        before = (len(db.all_rows(self.conn)), db.meta_get(self.conn, "round"))
        loop.ensure_seed(self.conn, self.work, b"x", EVAL)
        self.assertEqual(
            (len(db.all_rows(self.conn)), db.meta_get(self.conn, "round")), before
        )
        with self.assertRaises(SystemExit):
            loop.ensure_seed(self.conn, self.work, b"other", EVAL)
        conn2 = db.connect(str(Path(self.tmp.name) / "w9"))
        with self.assertRaises(RuntimeError):
            loop.ensure_seed(
                conn2,
                Path(self.tmp.name) / "w9",
                b"x",
                str(FIXTURES / "eval_fail.py"),
            )
        conn2.close()


if __name__ == "__main__":
    unittest.main()
