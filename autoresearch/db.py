"""SQLite store: nodes table, explicit history, meta counter."""

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL,
  parent INTEGER REFERENCES nodes(id), score REAL,
  claimed INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_parent ON nodes(parent);
CREATE TABLE IF NOT EXISTS history(
  round INTEGER, id INTEGER, sha TEXT, parent INTEGER, score REAL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def connect(working_dir: "str | Path") -> sqlite3.Connection:
    if str(working_dir) == ":memory:":
        conn = sqlite3.connect(":memory:")
    else:
        directory = Path(working_dir)
        directory.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(directory / "tree.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def node_path(nodes_dir: "str | Path", suffix: str, sha: str) -> Path:
    return Path(nodes_dir) / f"{sha}{suffix}"


def add_node(
    conn: sqlite3.Connection,
    nodes_dir: "str | Path",
    suffix: str,
    parent: "int | None",
    code: bytes,
) -> "tuple[int, bool]":
    sha = hashlib.sha256(code).hexdigest()
    directory = Path(nodes_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(code)
    os.rename(tmp, directory / f"{sha}{suffix}")
    cur = conn.execute(
        "INSERT OR IGNORE INTO nodes(parent, sha) VALUES (?, ?)", (parent, sha)
    )
    conn.commit()
    if cur.rowcount == 1:
        assert cur.lastrowid is not None
        return cur.lastrowid, True
    row = conn.execute("SELECT id FROM nodes WHERE sha=?", (sha,)).fetchone()
    assert row is not None
    return row["id"], False


def claim(conn: sqlite3.Connection, node_id: int) -> bool:
    cur = conn.execute(
        "UPDATE nodes SET claimed=1 WHERE id=? AND claimed=0", (node_id,)
    )
    conn.commit()
    return cur.rowcount == 1


def release(conn: sqlite3.Connection, node_id: int) -> None:
    conn.execute("UPDATE nodes SET claimed=0 WHERE id=?", (node_id,))
    conn.commit()


def meta_get(conn: sqlite3.Connection, key: str) -> "str | None":
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def record_score(conn: sqlite3.Connection, node_id: int, score: "float | None") -> None:
    conn.execute("UPDATE nodes SET score=?, claimed=0 WHERE id=?", (score, node_id))
    row = conn.execute(
        "SELECT sha, parent FROM nodes WHERE id=?", (node_id,)
    ).fetchone()
    assert row is not None
    round_ = int(meta_get(conn, "round") or 0) + 1
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('round', ?)", (str(round_),)
    )
    conn.execute(
        "INSERT INTO history(round, id, sha, parent, score) VALUES (?, ?, ?, ?, ?)",
        (round_, node_id, row["sha"], row["parent"], score),
    )
    conn.commit()


def children(conn: sqlite3.Connection, node_id: int) -> "list[sqlite3.Row]":
    return conn.execute(
        "SELECT * FROM nodes WHERE parent=? ORDER BY id", (node_id,)
    ).fetchall()


def all_rows(conn: sqlite3.Connection) -> "list[sqlite3.Row]":
    return conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()


def state_at(conn: sqlite3.Connection, round_: int) -> "list[sqlite3.Row]":
    return conn.execute(
        """SELECT h.* FROM history h JOIN (
             SELECT id, MAX(round) AS m FROM history WHERE round<=? GROUP BY id
           ) t ON t.id=h.id AND t.m=h.round ORDER BY h.id""",
        (round_,),
    ).fetchall()
