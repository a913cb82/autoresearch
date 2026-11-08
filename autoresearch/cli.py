"""CLI: parse args, wire the worker loop."""

import argparse
import multiprocessing
import random
import sys
from pathlib import Path

from autoresearch import db, loop


def _worker_main(
    workdir: str,
    eval_exe: str,
    model: str | None,
    rng_seed: int,
    max_evals: int,
    template: str,
) -> None:
    sys.exit(
        0 if loop.worker(workdir, eval_exe, model, rng_seed, max_evals, template) else 2
    )


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    parser.add_argument("--working-dir", required=True)
    parser.add_argument("--starter", required=True)
    parser.add_argument("--evaluate", required=True)
    parser.add_argument("--rng-seed", required=True, type=int)
    parser.add_argument("--max-evals", required=True, type=int)
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", default=1, type=int)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    workdir = Path(args.working_dir)
    conn = db.connect(workdir)
    starter = Path(args.starter)
    seed = starter.read_bytes()
    loop.ensure_seed(conn, workdir, seed, args.evaluate, starter.suffix)
    db.meta_set(conn, "seed_suffix", starter.suffix)
    template = loop.TEMPLATE.read_text()
    if args.workers == 1:
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
    conn.close()
    ctx = multiprocessing.get_context()
    procs = [
        ctx.Process(
            target=_worker_main,
            args=(
                str(workdir),
                args.evaluate,
                args.model,
                args.rng_seed + i,
                args.max_evals,
                template,
            ),
        )
        for i in range(args.workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    codes = [p.exitcode for p in procs]
    bad = [c for c in codes if c not in (0, 2)]
    if bad:
        print(f"worker exit codes: {codes}", file=sys.stderr)
        return 1
    if all(c == 2 for c in codes):
        print("converged before budget ran out", file=sys.stderr)
    return 0
