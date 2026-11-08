"""Generators select and improve via pi; evaluators score. Loud failures."""

import glob
import hashlib
import logging
import math
import os
import random
import sqlite3
import subprocess
import time
from importlib.resources import files
from pathlib import Path

from autoresearch import db, select
from autoresearch.prompts.improve import render

logger = logging.getLogger(__name__)


def run_eval(eval_exe: str, path: Path) -> float:
    proc = subprocess.run([eval_exe, str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{eval_exe} {path} exited {proc.returncode}: {proc.stderr.strip()}"
        )
    for line in proc.stdout.splitlines():
        if line.strip():
            try:
                score = float(line)
            except ValueError:
                continue
            if not math.isfinite(score):
                raise RuntimeError(f"{eval_exe} {path} printed non-finite score")
            return score
    raise RuntimeError(f"{eval_exe} {path} printed no score")


def _dir_files(path: Path) -> list[str]:
    return sorted(str(p) for p in path.rglob("*") if p.is_file())


def expand_read_paths(entries: list[str]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        if any(c in entry for c in "*?["):
            matches = sorted(glob.glob(entry, recursive=True))
            if not matches:
                raise ValueError(f"--read-paths {entry!r} matched no files")
            for match in matches:
                path = Path(match)
                if path.is_dir():
                    out.extend(_dir_files(path))
                elif path.is_file():
                    out.append(match)
                else:
                    raise FileNotFoundError(
                        f"--read-paths match {match!r} not readable"
                    )
        else:
            path = Path(entry)
            if not path.exists():
                raise FileNotFoundError(f"--read-paths {entry!r} not found")
            if path.is_dir():
                out.extend(_dir_files(path))
            else:
                out.append(str(path))
    return sorted({os.path.abspath(p) for p in out})


def improve(prompt: str, model: str, read_paths: list[str]) -> bytes:
    if read_paths:
        ext = files("autoresearch").joinpath("read_approved.ts")
        assert ext.is_file(), f"missing shipped tool: {ext}"
        cmd = [
            "pi",
            "--print",
            "-e",
            str(ext),
            "--tools",
            "read_approved,read",
            "--no-mcp",
            "--model",
            model,
        ]
    else:
        cmd = ["pi", "--print", "-nt", "--model", model]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8"
    )
    proc.check_returncode()
    return proc.stdout.encode("utf-8")


def _scores(value: float | None) -> str:
    return "?" if value is None else str(value)


def iterate(
    conn: sqlite3.Connection,
    workdir: Path,
    model: str,
    rng: random.Random,
    read_paths: list[str] | None = None,
) -> None:
    nodes_dir = workdir / "nodes"
    paths = read_paths or []
    rows = db.all_rows(conn)
    node_id = select.select(rng, rows)
    node = next(r for r in rows if int(r["id"]) == node_id)
    current_code = db.node_path(nodes_dir, str(node["sha"])).read_bytes()
    parent_code: str | None = None
    parent_score: str | None = None
    if node["parent"] is not None:
        parent = db.get(conn, int(node["parent"]))
        blob = db.node_path(nodes_dir, str(parent["sha"])).read_bytes()
        parent_code = blob.decode("utf-8")
        parent_score = _scores(parent["score"])
    prompt = render(
        parent_code=parent_code,
        parent_score=parent_score,
        current_code=current_code.decode("utf-8"),
        current_score=str(node["score"]),
        read_paths=paths,
    )
    new_code = improve(prompt, model, paths)
    db.add_node(conn, nodes_dir, node_id, new_code)


def ensure_seed(
    conn: sqlite3.Connection, workdir: Path, seed: bytes, eval_exe: str
) -> int:
    sha = hashlib.sha256(seed).hexdigest()
    roots = [r for r in db.all_rows(conn) if r["parent"] is None]
    if any(str(r["sha"]) != sha for r in roots):
        raise SystemExit("working dir seed differs from --initial")
    hit = [r for r in roots if r["sha"] == sha and r["score"] is not None]
    if hit:
        return int(hit[0]["id"])
    same = [r for r in roots if r["sha"] == sha]
    if same:
        target = int(same[0]["id"])
    else:
        assert not roots
        target, _ = db.add_node(conn, workdir / "nodes", None, seed)
        assert target == 1
    score = run_eval(eval_exe, db.node_path(workdir / "nodes", sha))
    db.record_score(conn, target, score, count=False)
    return target


def generate(
    conn: sqlite3.Connection,
    workdir: Path,
    model: str,
    rng: random.Random,
    max_rewrites: int,
    read_paths: list[str] | None = None,
) -> None:
    while db.claim_round(conn, max_rewrites):
        iterate(conn, workdir, model, rng, read_paths)


def evaluate(
    conn: sqlite3.Connection, workdir: Path, eval_exe: str, max_rewrites: int
) -> None:
    nodes_dir = workdir / "nodes"
    best_row = db.best(conn)
    assert best_row is not None
    last_best = float(best_row["score"])
    while True:
        row = db.reserve(conn)
        if row is None:
            if int(db.meta_get(conn, "round") or 0) >= max_rewrites:
                # Round hits max at last dispatch (passes still in flight);
                # the tail is drained by the parent after joining.
                if db.reserve(conn) is None:
                    return
            else:
                time.sleep(1)
            continue
        node_id = int(row["id"])
        score = run_eval(eval_exe, db.node_path(nodes_dir, str(row["sha"])))
        db.record_score(conn, node_id, score, count=False)
        logger.info("scored node %s: %s", node_id, score)
        best_row = db.best(conn)
        assert best_row is not None
        if score > last_best and int(best_row["id"]) == node_id:
            last_best = score
            logger.info(
                "[%s/%s] best %s (node %s)",
                db.meta_get(conn, "round"),
                max_rewrites,
                score,
                node_id,
            )


def generator(
    workdir: str,
    model: str,
    seed: int,
    max_rewrites: int,
    read_paths: list[str] | None = None,
) -> None:
    logger.info("generator seed %s", seed)
    conn = db.connect(workdir)
    try:
        generate(
            conn,
            Path(workdir),
            model,
            random.Random(seed),
            max_rewrites,
            read_paths,
        )
    finally:
        conn.close()


def evaluator(workdir: str, eval_exe: str, max_rewrites: int) -> None:
    logger.info("evaluator start")
    conn = db.connect(workdir)
    try:
        evaluate(conn, Path(workdir), eval_exe, max_rewrites)
    finally:
        conn.close()
