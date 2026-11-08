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
        with self.assertRaises(RuntimeError):
            loop.run_eval(str(FIXTURES / "eval_neginf.py"), target)
        with self.assertRaises(RuntimeError):
            loop.run_eval(str(FIXTURES / "eval_nan.py"), target)

    def test_expand_read_paths_sorted_absolute(self) -> None:
        root = Path(self.tmp.name) / "ctx"
        (root / "sub").mkdir(parents=True)
        (root / "b.py").write_bytes(b"BBB")
        (root / "a.py").write_bytes(b"AAA")
        (root / "sub" / "c.py").write_bytes(b"CCC")
        out = loop.expand_read_paths([str(root / "b.py"), str(root / "*.py")])
        self.assertEqual(out, sorted(out))
        self.assertTrue(all(Path(p).is_absolute() for p in out))
        self.assertEqual(len(out), 2)

    def test_expand_read_paths_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            loop.expand_read_paths([str(Path(self.tmp.name) / "nope")])

    def test_expand_read_paths_empty_glob_raises(self) -> None:
        with self.assertRaises(ValueError):
            loop.expand_read_paths([str(Path(self.tmp.name) / "*.zz")])

    def test_read_paths_listed_not_pasted(self) -> None:
        approved = Path(self.tmp.name) / "ref.py"
        approved.write_bytes(b"SECRET_BODY")
        work = Path(self.tmp.name) / "wctx"
        conn = db.connect(str(work))
        with fixture_pi("echo"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(
                conn,
                work,
                "m",
                random.Random(0),
                2,
                [str(approved)],
            )
        blobs = [
            p.read_bytes() for p in (work / "nodes").iterdir() if p.name != "env_seen"
        ]
        self.assertTrue(any(str(approved).encode() in b for b in blobs))
        self.assertFalse(any(b"SECRET_BODY" in b for b in blobs))
        conn.close()

    def test_tool_argv_with_paths(self) -> None:
        approved = Path(self.tmp.name) / "ref.py"
        approved.write_bytes(b"x")
        work = Path(self.tmp.name) / "wtool"
        conn = db.connect(str(work))
        with fixture_pi("assert_read"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(
                conn,
                work,
                "m",
                random.Random(0),
                1,
                [str(approved)],
            )
        conn.close()

    def test_evaluate_logs_new_best(self) -> None:
        work = Path(self.tmp.name) / "wlog"
        conn = db.connect(str(work))
        with fixture_pi("grow"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(conn, work, "m", random.Random(0), 1)
            with self.assertLogs("autoresearch.loop", level="INFO") as logs:
                loop.evaluate(conn, work, EVAL, 1)
        self.assertTrue(any("[1/1] best 4.0 (node 2)" in line for line in logs.output))
        conn.close()

    def test_evaluate_logs_only_new_best(self) -> None:
        work = Path(self.tmp.name) / "wbest"
        conn = db.connect(str(work))
        with fixture_pi("const"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(conn, work, "m", random.Random(0), 3)
            with self.assertLogs("autoresearch.loop", level="INFO") as logs:
                loop.evaluate(conn, work, EVAL, 3)
        best_lines = [line for line in logs.output if "best" in line]
        self.assertEqual(len(best_lines), 1)
        self.assertIn("[3/3] best", best_lines[0])
        conn.close()

    def test_generate_inserts_unscored_and_spends(self) -> None:
        work = Path(self.tmp.name) / "wgen"
        conn = db.connect(str(work))
        with fixture_pi("grow"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(conn, work, "m", random.Random(0), 1)
        rows = db.all_rows(conn)
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[1]["score"])
        self.assertEqual(db.meta_get(conn, "round"), "1")
        conn.close()

    def test_evaluate_scores_and_drains(self) -> None:
        work = Path(self.tmp.name) / "weval"
        conn = db.connect(str(work))
        with fixture_pi("grow"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(conn, work, "m", random.Random(0), 1)
            with self.assertLogs("autoresearch.loop", level="INFO") as logs:
                loop.evaluate(conn, work, EVAL, 1)
        rows = db.all_rows(conn)
        self.assertTrue(all(r["score"] is not None for r in rows))
        self.assertEqual(db.meta_get(conn, "round"), "1")
        self.assertTrue(any("scored node" in line for line in logs.output))
        conn.close()

    def test_evaluate_idle_exits_at_budget(self) -> None:
        work = Path(self.tmp.name) / "widle"
        conn = db.connect(str(work))
        with fixture_pi("grow"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            db.spend_round(conn)
            loop.evaluate(conn, work, EVAL, 1)
        conn.close()

    def test_evaluator_waits_for_work(self) -> None:
        import threading
        import time

        work = Path(self.tmp.name) / "wwait"
        conn = db.connect(str(work))
        with fixture_pi("grow"):
            loop.ensure_seed(conn, work, b"x", EVAL)

            def late_gen() -> None:
                time.sleep(1.2)
                c = db.connect(str(work))
                try:
                    loop.generate(c, work, "m", random.Random(0), 1)
                finally:
                    c.close()

            t = threading.Thread(target=late_gen)
            t.start()
            loop.evaluate(conn, work, EVAL, 1)
            t.join()
        rows = db.all_rows(conn)
        self.assertTrue(all(r["score"] is not None for r in rows))
        conn.close()

    def test_tool_argv_without_paths(self) -> None:
        work = Path(self.tmp.name) / "wnotool"
        conn = db.connect(str(work))
        with fixture_pi("assert_read"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(conn, work, "m", random.Random(0), 1)
        conn.close()

    def _run(self, seed: int, variant: str = "grow", max_rewrites: int = 5):
        work = Path(self.tmp.name) / f"w{seed}"
        conn = db.connect(str(work))
        with fixture_pi(variant):
            loop.ensure_seed(conn, work, b"x", EVAL)
            loop.generate(conn, work, "m", random.Random(0), max_rewrites)
        rows = [(r["sha"], r["score"]) for r in db.all_rows(conn)]
        round_ = db.meta_get(conn, "round")
        conn.close()
        return rows, round_

    def test_lone_parent_dupes_burn_budget(self) -> None:
        rows, round_ = self._run(1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(round_, "5")
        again, _ = self._run(2)
        self.assertEqual(again, rows)

    def test_staged_scores_steer_selection(self) -> None:
        work = Path(self.tmp.name) / "wstage"
        conn = db.connect(str(work))
        with fixture_pi("grow"):
            loop.ensure_seed(conn, work, b"x", EVAL)
            rng = random.Random(0)
            loop.generate(conn, work, "m", rng, 1)
            loop.evaluate(conn, work, EVAL, 1)
            loop.generate(conn, work, "m", rng, 2)
        self.assertEqual(
            [(r["id"], r["parent"], r["score"]) for r in db.all_rows(conn)],
            [(1, None, 1.0), (2, 1, 4.0), (3, 2, None)],
        )
        conn.close()

    def test_budget_stops(self) -> None:
        rows, round_ = self._run(3, max_rewrites=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(round_, "2")

    def test_duplicate_drops_and_burns(self) -> None:
        rows, round_ = self._run(4, variant="const")
        self.assertEqual(len(rows), 2)
        self.assertEqual(round_, "5")

    def test_improve_failure_raises(self) -> None:
        loop.ensure_seed(self.conn, self.work, b"x", EVAL)
        with fixture_pi("fail"):
            with self.assertRaises(subprocess.CalledProcessError):
                loop.iterate(
                    self.conn,
                    self.work,
                    "m",
                    random.Random(0),
                )

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
