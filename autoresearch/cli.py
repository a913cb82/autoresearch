"""CLI: parse args, wire the worker loop."""

import argparse
import random
from pathlib import Path

from autoresearch import db, loop


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    parser.add_argument("--working-dir", required=True)
    parser.add_argument("--starter", required=True)
    parser.add_argument("--evaluate", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--max-evals", required=True, type=int)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    workdir = Path(args.working_dir)
    conn = db.connect(workdir)
    seed = Path(args.starter).read_bytes()
    db.meta_set(conn, "seed_suffix", Path(args.starter).suffix)
    loop.ensure_seed(conn, workdir, seed, args.evaluate)
    template = loop.TEMPLATE.read_text()
    loop.run(
        conn,
        workdir,
        args.evaluate,
        args.model,
        random.Random(args.seed),
        args.max_evals,
        template,
    )
    return 0
