"""CLI: parse args, wire the worker loop."""

import argparse
import logging
import multiprocessing
import os
from collections.abc import Callable
from pathlib import Path

from autoresearch import db, loop

logger = logging.getLogger(__name__)


def _generator_main(
    workdir: str,
    model: "str | None",
    seed: int,
    max_rewrites: int,
    read_paths: list[str],
) -> None:
    loop.generator(workdir, model, seed, max_rewrites, read_paths)


def _evaluator_main(
    workdir: str, eval_exe: str, generators_done: Callable[[], bool]
) -> None:
    loop.evaluator(workdir, eval_exe, generators_done)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="autoresearch")
    parser.add_argument("--working-dir", required=True)
    parser.add_argument("--initial", default=None)
    parser.add_argument("--evaluate", default=None)
    parser.add_argument("--seed", default=0, type=int)
    parser.add_argument("--max-rewrites", required=True, type=int)
    parser.add_argument("--model", default=None)
    parser.add_argument("--generators", default=1, type=int)
    parser.add_argument("--evaluators", default=1, type=int)
    parser.add_argument("--read-paths", action="append", default=[])
    args = parser.parse_args(argv)
    if args.generators < 1:
        parser.error("--generators must be >= 1")
    if args.evaluators < 1:
        parser.error("--evaluators must be >= 1")
    if args.max_rewrites < 0:
        parser.error("--max-rewrites must be >= 0")
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
    try:
        read_paths = loop.expand_read_paths(args.read_paths)
    except (FileNotFoundError, ValueError) as e:
        parser.error(str(e))
    if args.read_paths and not read_paths:
        parser.error("--read-paths matched no files")
    os.environ["AUTORESEARCH_SEED"] = str(args.seed)
    os.environ["AUTORESEARCH_READ_PATHS"] = os.pathsep.join(read_paths)
    db.reset_scoring(conn)
    conn.close()
    ctx = multiprocessing.get_context()
    done = ctx.Event()
    gen_procs = [
        ctx.Process(
            target=_generator_main,
            args=(
                str(workdir),
                args.model,
                args.seed + i,
                args.max_rewrites,
                read_paths,
            ),
        )
        for i in range(args.generators)
    ]
    eval_procs = [
        ctx.Process(
            target=_evaluator_main,
            args=(str(workdir), eval_exe, done.is_set),
        )
        for _ in range(args.evaluators)
    ]
    for p in gen_procs + eval_procs:
        p.start()
    for p in gen_procs:
        p.join()
    if any(p.exitcode != 0 for p in gen_procs):
        for p in eval_procs:
            p.terminate()
        for p in eval_procs:
            p.join()
        logger.warning(
            "worker exit codes: %s",
            [p.exitcode for p in gen_procs + eval_procs],
        )
        return 1
    # Generators are joined: every claimed round has landed, so evaluators
    # exit on their own once the reserve runs dry.
    done.set()
    for p in eval_procs:
        p.join()
    codes = [p.exitcode for p in eval_procs]
    if any(c != 0 for c in codes):
        logger.warning("worker exit codes: %s", codes)
        return 1
    return 0
