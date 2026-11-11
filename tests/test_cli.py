import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from autoresearch import cli, db, read
from tests.helpers import FIXTURES, fixture_pi


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = str(Path(self.tmp.name) / "work")
        self.seed = str(Path(self.tmp.name) / "seed.py")
        Path(self.seed).write_bytes(b"x")
        self.base = [
            "--working-dir",
            self.work,
            "--initial",
            self.seed,
            "--evaluate",
            str(FIXTURES / "eval_len.py"),
            "--seed",
            "0",
            "--max-rewrites",
            "2",
            "--model",
            "m",
        ]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_end_to_end_and_read(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
            self.assertEqual(cli.main(self.base), 0)
        conn = db.connect(self.work)
        self.assertEqual(len(db.all_rows(conn)), 2)
        conn.close()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(read.main(["--working-dir", self.work]), 0)
        self.assertIn("4.0", out.getvalue())

    def test_stuck_agent_ends_at_budget(self) -> None:
        args = self.base[: self.base.index("--max-rewrites") + 1] + [
            "3",
            "--model",
            "m",
        ]
        with fixture_pi("const"):
            self.assertEqual(cli.main(args), 0)
        conn = db.connect(self.work)
        self.assertEqual(len(db.all_rows(conn)), 2)
        self.assertEqual(db.meta_get(conn, "round"), "3")
        conn.close()

    def _split_base(
        self, max_rewrites: str, generators: str, evaluators: str
    ) -> "list[str]":
        args = self.base[: self.base.index("--max-rewrites") + 1] + [max_rewrites]
        return args + [
            "--model",
            "m",
            "--generators",
            generators,
            "--evaluators",
            evaluators,
        ]

    def test_split_completes(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self._split_base("3", "2", "1")), 0)
        conn = db.connect(self.work)
        self.assertEqual(len(db.all_rows(conn)), 2)
        self.assertEqual(db.meta_get(conn, "round"), "3")
        conn.close()

    def test_negative_max_rewrites_aborts(self) -> None:
        args = list(self.base)
        args[args.index("--max-rewrites") + 1] = "-1"
        with self.assertRaises(SystemExit):
            cli.main(args)

    def test_split_zero_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(self._split_base("2", "0", "1"))
        with self.assertRaises(SystemExit):
            cli.main(self._split_base("2", "1", "0"))

    def test_startup_wipes_scoring(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
        conn = db.connect(self.work)
        target, _ = db.add_node(conn, Path(self.work) / "nodes", 1, b"stuck")
        row = db.reserve(conn)
        assert row is not None
        self.assertEqual(row["id"], target)
        conn.close()
        args = list(self.base)
        args[args.index("--max-rewrites") + 1] = "3"
        with fixture_pi("grow"):
            self.assertEqual(cli.main(args), 0)
        conn = db.connect(self.work)
        rows = {r["id"]: r for r in db.all_rows(conn)}
        self.assertIsNotNone(rows[target]["score"])
        conn.close()

    def test_eval_sees_seed_env(self) -> None:
        args = list(self.base)
        args[args.index("--evaluate") + 1] = str(FIXTURES / "eval_record.py")
        with fixture_pi("grow"):
            self.assertEqual(cli.main(args), 0)
        seen = Path(self.work) / "nodes" / "env_seen"
        self.assertEqual(seen.read_text(), "0")

    def test_model_optional(self) -> None:
        args = list(self.base)
        del args[args.index("--model") : args.index("--model") + 2]
        with fixture_pi("grow"):
            self.assertEqual(cli.main(args), 0)

    def test_seed_defaults(self) -> None:
        args = list(self.base)
        del args[args.index("--seed") : args.index("--seed") + 2]
        with fixture_pi("grow"):
            self.assertEqual(cli.main(args), 0)

    def test_read_paths_sets_env(self) -> None:
        ref = str(Path(self.tmp.name) / "ref.py")
        Path(ref).write_bytes(b"x")
        try:
            with fixture_pi("grow"):
                self.assertEqual(cli.main(self.base + ["--read-paths", ref]), 0)
                self.assertEqual(os.environ["AUTORESEARCH_READ_PATHS"], ref)
        finally:
            os.environ.pop("AUTORESEARCH_READ_PATHS", None)

    def test_read_paths_missing_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(self.base + ["--read-paths", str(Path(self.tmp.name) / "no")])

    def test_read_paths_empty_glob_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(self.base + ["--read-paths", str(Path(self.tmp.name) / "*.zz")])

    def test_read_paths_empty_dir_aborts(self) -> None:
        empty = str(Path(self.tmp.name) / "empty")
        Path(empty).mkdir()
        with self.assertRaises(SystemExit):
            cli.main(self.base + ["--read-paths", empty])

    def _without(self, args: "list[str]", flag: str) -> "list[str]":
        args = list(args)
        del args[args.index(flag) : args.index(flag) + 2]
        return args

    def test_fresh_missing_initial_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(self._without(self.base, "--initial"))

    def test_fresh_missing_evaluate_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(self._without(self.base, "--evaluate"))

    def test_resume_omits_both(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
            args = self._without(self.base, "--initial")
            args = self._without(args, "--evaluate")
            args[args.index("--max-rewrites") + 1] = "3"
            self.assertEqual(cli.main(args), 0)
        conn = db.connect(self.work)
        self.assertEqual(db.meta_get(conn, "round"), "3")
        self.assertEqual(len(db.all_rows(conn)), 3)
        conn.close()

    def test_resume_eval_mismatch_aborts(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
            args = list(self.base)
            args[args.index("--evaluate") + 1] = str(FIXTURES / "eval_warn.py")
            with self.assertRaises(SystemExit):
                cli.main(args)

    def test_resume_eval_omitted_uses_stored(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
            args = self._without(self.base, "--evaluate")
            args[args.index("--max-rewrites") + 1] = "3"
            self.assertEqual(cli.main(args), 0)
        conn = db.connect(self.work)
        rows = db.all_rows(conn)
        newest = rows[-1]
        target = Path(self.work) / "nodes" / str(newest["sha"])
        self.assertEqual(newest["score"], len(target.read_bytes()))
        conn.close()

    def test_resume_unstamped_eval_adopts(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
        conn = db.connect(self.work)
        conn.execute("DELETE FROM meta WHERE key='evaluate'")
        conn.commit()
        conn.close()
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
        conn = db.connect(self.work)
        self.assertEqual(
            db.meta_get(conn, "evaluate"),
            str((FIXTURES / "eval_len.py").absolute()),
        )
        conn.close()

    def test_resume_unstamped_eval_omitted_aborts(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self.base), 0)
        conn = db.connect(self.work)
        conn.execute("DELETE FROM meta WHERE key='evaluate'")
        conn.commit()
        conn.close()
        with self.assertRaises(SystemExit):
            cli.main(self._without(self.base, "--evaluate"))

    def test_multi_root_omitted_initial_aborts(self) -> None:
        conn = db.connect(self.work)
        db.add_node(conn, Path(self.work) / "nodes", None, b"a")
        db.add_node(conn, Path(self.work) / "nodes", None, b"b")
        conn.close()
        args = self._without(self.base, "--initial")
        with self.assertRaises(SystemExit):
            cli.main(args)

    def test_meta_accepts_evaluate(self) -> None:
        conn = db.connect(self.work)
        db.meta_set(conn, "evaluate", "/x/eval")
        self.assertEqual(db.meta_get(conn, "evaluate"), "/x/eval")
        conn.close()

    def test_read_empty(self) -> None:
        conn = db.connect(self.work)
        conn.close()
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(read.main(["--working-dir", self.work]), 1)
        self.assertIn(f"no scored nodes in {self.work}", err.getvalue())


if __name__ == "__main__":
    unittest.main()
