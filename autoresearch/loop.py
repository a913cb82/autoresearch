"""Worker loop: select, improve via pi, evaluate. Loud failures."""

import hashlib
import random
import sqlite3
import subprocess
from pathlib import Path

from autoresearch import db, select

TEMPLATE = Path(__file__).parent / "prompts" / "improve.md"


def run_eval(eval_exe: str, path: Path) -> float:
    proc = subprocess.run([eval_exe, str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{eval_exe} {path} exited {proc.returncode}: {proc.stderr.strip()}"
        )
    for line in proc.stdout.splitlines():
        if line.strip():
            try:
                return float(line)
            except ValueError:
                continue
    raise RuntimeError(f"{eval_exe} {path} printed no score")


def render_prompt(template: str, mapping: dict[str, str]) -> str:
    for token, value in mapping.items():
        template = template.replace(token, value)
    return template


def improve(prompt: str, model: str) -> bytes:
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
    eval_exe: str,
    model: str,
    rng: random.Random,
    template: str,
) -> None:
    nodes_dir = workdir / "nodes"
    rows = db.all_rows(conn)
    node_id = select.select(rng, rows)
    if not db.claim(conn, node_id):
        return
    try:
        node = next(r for r in rows if int(r["id"]) == node_id)
        current_code = db.node_path(nodes_dir, str(node["sha"])).read_bytes()
        parent_code, parent_score = current_code, node["score"]
        if node["parent"] is not None:
            parent = db.get(conn, int(node["parent"]))
            parent_code = db.node_path(nodes_dir, str(parent["sha"])).read_bytes()
            parent_score = parent["score"]
        best = db.best(conn)
        assert best is not None
        best_code = db.node_path(nodes_dir, str(best["sha"])).read_bytes()
        prompt = render_prompt(
            template,
            {
                "__PARENT_CODE__": parent_code.decode("utf-8"),
                "__PARENT_SCORE__": _scores(parent_score),
                "__BEST_CODE__": best_code.decode("utf-8"),
                "__BEST_SCORE__": str(best["score"]),
                "__CURRENT_CODE__": current_code.decode("utf-8"),
                "__CURRENT_SCORE__": str(node["score"]),
            },
        )
        new_code = improve(prompt, model)
        target, is_new = db.add_node(conn, nodes_dir, node_id, new_code)
        if not is_new:
            db.spend_round(conn)
            return
        target_row = db.get(conn, target)
        score = run_eval(eval_exe, db.node_path(nodes_dir, str(target_row["sha"])))
        db.record_score(conn, target, score)
    finally:
        db.release(conn, node_id)


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


def run(
    conn: sqlite3.Connection,
    workdir: Path,
    eval_exe: str,
    model: str,
    rng: random.Random,
    max_rewrites: int,
    template: str,
) -> None:
    while int(db.meta_get(conn, "round") or 0) < max_rewrites:
        iterate(conn, workdir, eval_exe, model, rng, template)


def worker(
    workdir: str,
    eval_exe: str,
    model: str,
    seed: int,
    max_rewrites: int,
    template: str,
) -> None:
    conn = db.connect(workdir)
    try:
        run(
            conn,
            Path(workdir),
            eval_exe,
            model,
            random.Random(seed),
            max_rewrites,
            template,
        )
    finally:
        conn.close()
