import io
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
            "--starter",
            self.seed,
            "--evaluate",
            str(FIXTURES / "eval_len.py"),
            "--rng-seed",
            "0",
            "--max-evals",
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

    def test_converged_reports(self) -> None:
        args = self.base[: self.base.index("--max-evals") + 1] + [
            "3",
            "--model",
            "m",
        ]
        err = io.StringIO()
        with fixture_pi("const"), redirect_stderr(err):
            self.assertEqual(cli.main(args), 0)
        self.assertIn("converged", err.getvalue())

    def _workers_base(self, max_evals: str, workers: str) -> "list[str]":
        args = self.base[: self.base.index("--max-evals") + 1] + [max_evals]
        return args + ["--model", "m", "--workers", workers]

    def test_workers_two(self) -> None:
        with fixture_pi("grow"):
            self.assertEqual(cli.main(self._workers_base("3", "2")), 0)
        conn = db.connect(self.work)
        self.assertGreaterEqual(len(db.all_rows(conn)), 3)
        self.assertGreaterEqual(int(db.meta_get(conn, "round") or 0), 3)
        conn.close()

    def test_workers_zero_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(self._workers_base("2", "0"))

    def test_read_empty(self) -> None:
        conn = db.connect(self.work)
        conn.close()
        self.assertEqual(read.main(["--working-dir", self.work]), 1)


if __name__ == "__main__":
    unittest.main()
