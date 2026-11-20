from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from app.config import DATA_DIR, DB_PATH


def connect() -> sqlite3.Connection:
    """Open a connection in autocommit mode.

    All multi-statement writes must go through ``write_txn`` so they take an
    immediate (RESERVED) lock.  That serialises reconciliation against
    pack-spec edits, which is what prevents a single reconcile run from
    mixing an old and a new ``pack_size``.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def write_txn(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT/ROLLBACK.

    BEGIN IMMEDIATE grabs the write lock up front, so a second writer (e.g. a
    concurrent pack-spec update) blocks on ``busy_timeout`` instead of letting
    this transaction read a value another transaction changes mid-scan.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@contextmanager
def read_snapshot(conn: sqlite3.Connection):
    """A consistent read snapshot (WAL) for multi-query views such as 总览."""
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.execute("ROLLBACK")
