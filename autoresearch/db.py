"""SQLite store: nodes table, meta counter."""

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL,
  parent INTEGER REFERENCES nodes(id), score REAL,
  scoring INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY CHECK(key IN ('round', 'evaluate')),
  value TEXT);
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


def node_path(nodes_dir: "str | Path", sha: str) -> Path:
    return Path(nodes_dir) / sha


def add_node(
    conn: sqlite3.Connection,
    nodes_dir: "str | Path",
    parent: "int | None",
    code: bytes,
) -> "tuple[int, bool]":
    sha = hashlib.sha256(code).hexdigest()
    directory = Path(nodes_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(code)
    os.rename(tmp, directory / sha)
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


def meta_get(conn: sqlite3.Connection, key: str) -> "str | None":
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def reserve(conn: sqlite3.Connection) -> "sqlite3.Row | None":
    assert sqlite3.sqlite_version_info >= (3, 35), "reserve needs SQLite 3.35+"
    row = conn.execute(
        "UPDATE nodes SET scoring=1 WHERE id=("
        "SELECT MIN(id) FROM nodes WHERE score IS NULL AND scoring=0"
        ") RETURNING *"
    ).fetchone()
    conn.commit()
    return row


def reset_scoring(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE nodes SET scoring=0 WHERE scoring=1")
    conn.commit()


def record_score(
    conn: sqlite3.Connection, node_id: int, score: float, count: bool = True
) -> None:
    conn.execute("UPDATE nodes SET score=?, scoring=0 WHERE id=?", (score, node_id))
    if count:
        spend_round(conn)
    else:
        conn.commit()


def claim_round(conn: sqlite3.Connection, max_rewrites: int) -> bool:
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('round', '0')")
    cur = conn.execute(
        "UPDATE meta SET value = CAST(value AS INTEGER) + 1"
        " WHERE key = 'round' AND CAST(value AS INTEGER) < ?",
        (max_rewrites,),
    )
    conn.commit()
    return cur.rowcount == 1


def spend_round(conn: sqlite3.Connection) -> None:
    round_ = int(meta_get(conn, "round") or 0) + 1
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('round', ?)", (str(round_),)
    )
    conn.commit()


def get(conn: sqlite3.Connection, node_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    assert row is not None
    return row


def best(conn: sqlite3.Connection) -> "sqlite3.Row | None":
    return conn.execute(
        "SELECT * FROM nodes WHERE score IS NOT NULL "
        "ORDER BY score DESC, id ASC LIMIT 1"
    ).fetchone()


def all_rows(conn: sqlite3.Connection) -> "list[sqlite3.Row]":
    return conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
