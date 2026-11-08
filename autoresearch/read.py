"""Print best path+score from a working dir. Read-only."""

import argparse
import sqlite3
import sys
from pathlib import Path

from autoresearch import db


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch-read")
    parser.add_argument("--working-dir", required=True)
    args = parser.parse_args(argv)
    workdir = Path(args.working_dir)
    conn = sqlite3.connect(f"file:{workdir / 'tree.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    best = db.best(conn)
    if best is None:
        print(f"no scored nodes in {workdir}", file=sys.stderr)
        return 1
    path = db.node_path(workdir / "nodes", str(best["sha"]))
    print(f"{path} {best['score']}")
    return 0
