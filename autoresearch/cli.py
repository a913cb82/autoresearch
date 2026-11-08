"""CLI: parse args, wire the worker loop."""

import argparse
import random
import sys
from pathlib import Path

from autoresearch import db, loop


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    parser.add_argument("--working-dir", required=True)
    parser.add_argument("--starter", required=True)
    parser.add_argument("--evaluate", required=True)
    parser.add_argument("--rng-seed", required=True, type=int)
    parser.add_argument("--max-evals", required=True, type=int)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    workdir = Path(args.working_dir)
    conn = db.connect(workdir)
    starter = Path(args.starter)
    seed = starter.read_bytes()
    loop.ensure_seed(conn, workdir, seed, args.evaluate, starter.suffix)
    db.meta_set(conn, "seed_suffix", starter.suffix)
    template = loop.TEMPLATE.read_text()
    done = loop.run(
        conn,
        workdir,
        args.evaluate,
        args.model,
        random.Random(args.rng_seed),
        args.max_evals,
        template,
    )
    if not done:
        print("converged before budget ran out", file=sys.stderr)
    return 0
