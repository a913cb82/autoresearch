"""CLI: parse args, wire the worker loop."""

import argparse
import multiprocessing
import os
import random
import sys
from pathlib import Path

from autoresearch import db, loop


def _worker_main(
    workdir: str,
    eval_exe: str,
    model: str,
    seed: int,
    max_rewrites: int,
    read_paths: list[str],
) -> None:
    loop.worker(workdir, eval_exe, model, seed, max_rewrites, read_paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    parser.add_argument("--working-dir", required=True)
    parser.add_argument("--initial", default=None)
    parser.add_argument("--evaluate", default=None)
    parser.add_argument("--seed", default=0, type=int)
    parser.add_argument("--max-rewrites", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--workers", default=1, type=int)
    parser.add_argument("--read-paths", action="append", default=[])
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    workdir = Path(args.working_dir)
    conn = db.connect(workdir)
    fresh = not db.all_rows(conn)
    if fresh and (args.initial is None or args.evaluate is None):
        parser.error("--initial and --evaluate are required for a fresh working dir")
    if args.initial is None:
        roots = [r for r in db.all_rows(conn) if r["parent"] is None]
        if len(roots) != 1:
            raise SystemExit("working dir has no single root; pass --initial")
        seed = db.node_path(workdir / "nodes", str(roots[0]["sha"])).read_bytes()
    else:
        seed = Path(args.initial).read_bytes()
    stored = db.meta_get(conn, "evaluate")
    if args.evaluate is None:
        if stored is None:
            parser.error("--evaluate required: working dir predates stored eval")
        eval_exe = stored
    else:
        eval_exe = str(Path(args.evaluate).absolute())
        if stored is not None and eval_exe != stored:
            raise SystemExit("--evaluate differs from the stored run")
    loop.ensure_seed(conn, workdir, seed, eval_exe)
    if stored is None:
        db.meta_set(conn, "evaluate", eval_exe)
    try:
        read_paths = loop.expand_read_paths(args.read_paths)
    except (FileNotFoundError, ValueError) as e:
        parser.error(str(e))
    if args.read_paths and not read_paths:
        parser.error("--read-paths matched no files")
    os.environ["AUTORESEARCH_SEED"] = str(args.seed)
    os.environ["AUTORESEARCH_READ_PATHS"] = os.pathsep.join(read_paths)
    if args.workers == 1:
        loop.run(
            conn,
            workdir,
            eval_exe,
            args.model,
            random.Random(args.seed),
            args.max_rewrites,
            read_paths,
        )
        return 0
    conn.close()
    ctx = multiprocessing.get_context()
    procs = [
        ctx.Process(
            target=_worker_main,
            args=(
                str(workdir),
                eval_exe,
                args.model,
                args.seed + i,
                args.max_rewrites,
                read_paths,
            ),
        )
        for i in range(args.workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    codes = [p.exitcode for p in procs]
    if any(c != 0 for c in codes):
        print(f"worker exit codes: {codes}", file=sys.stderr)
        return 1
    return 0
