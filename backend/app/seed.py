from __future__ import annotations
from app.db import connect, write_txn

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suppliers (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pack_specs (
  id INTEGER PRIMARY KEY,
  supplier_code TEXT NOT NULL,
  sku TEXT NOT NULL,
  unit TEXT NOT NULL,
  base_unit TEXT NOT NULL DEFAULT '件',
  pack_size REAL NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(supplier_code, sku, unit)
);
CREATE TABLE IF NOT EXISTS expect_lines (
  id INTEGER PRIMARY KEY,
  doc_no TEXT NOT NULL UNIQUE,
  supplier_code TEXT NOT NULL,
  sku TEXT NOT NULL,
  dock_day TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT NOT NULL DEFAULT '件',
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receive_lines (
  id INTEGER PRIMARY KEY,
  receive_no TEXT NOT NULL UNIQUE,
  supplier_code TEXT NOT NULL,
  sku TEXT NOT NULL,
  dock_day TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT NOT NULL DEFAULT '件',
  occurred_at TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confirm_lines (
  id INTEGER PRIMARY KEY,
  confirm_no TEXT NOT NULL UNIQUE,
  supplier_code TEXT NOT NULL,
  sku TEXT NOT NULL,
  dock_day TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT NOT NULL DEFAULT '件',
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconcile_batches (
  id INTEGER PRIMARY KEY,
  batch_no TEXT NOT NULL UNIQUE,
  dock_day TEXT NOT NULL,
  matched_count INTEGER NOT NULL,
  variance_count INTEGER NOT NULL,
  unit_miss_count INTEGER NOT NULL DEFAULT 0,
  unit_mismatch_count INTEGER NOT NULL DEFAULT 0,
  expect_pieces REAL NOT NULL DEFAULT 0,
  receive_pieces REAL NOT NULL DEFAULT 0,
  confirm_pieces REAL NOT NULL DEFAULT 0,
  policy TEXT NOT NULL DEFAULT 'pack_convert',
  status TEXT NOT NULL,
  sealed_at TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS match_rows (
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  dock_day TEXT NOT NULL,
  supplier_code TEXT NOT NULL,
  sku TEXT NOT NULL,
  expect_qty REAL,
  receive_qty REAL,
  confirm_qty REAL,
  expect_raw_qty REAL NOT NULL DEFAULT 0,
  receive_raw_qty REAL NOT NULL DEFAULT 0,
  confirm_raw_qty REAL NOT NULL DEFAULT 0,
  expect_unit TEXT NOT NULL DEFAULT '件',
  receive_unit TEXT NOT NULL DEFAULT '件',
  confirm_unit TEXT NOT NULL DEFAULT '件',
  expect_pack_size REAL,
  receive_pack_size REAL,
  confirm_pack_size REAL,
  convert_rule TEXT NOT NULL DEFAULT '',
  bucket TEXT NOT NULL DEFAULT 'variance',
  bucket_reason TEXT,
  aligned INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS variance_rows (
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  dock_day TEXT NOT NULL,
  supplier_code TEXT NOT NULL,
  sku TEXT NOT NULL,
  expect_qty REAL,
  receive_qty REAL,
  confirm_qty REAL,
  expect_raw_qty REAL NOT NULL DEFAULT 0,
  receive_raw_qty REAL NOT NULL DEFAULT 0,
  confirm_raw_qty REAL NOT NULL DEFAULT 0,
  expect_unit TEXT NOT NULL DEFAULT '件',
  receive_unit TEXT NOT NULL DEFAULT '件',
  confirm_unit TEXT NOT NULL DEFAULT '件',
  expect_pack_size REAL,
  receive_pack_size REAL,
  confirm_pack_size REAL,
  convert_rule TEXT NOT NULL DEFAULT '',
  bucket TEXT NOT NULL DEFAULT 'variance',
  bucket_reason TEXT,
  fate TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS late_spill (
  id INTEGER PRIMARY KEY,
  dock_day TEXT NOT NULL,
  reason TEXT
);
CREATE TABLE IF NOT EXISTS reopen_requests (
  id INTEGER PRIMARY KEY,
  dock_day TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'none'
);
'''

# Columns added after the first release, applied idempotently to older DBs.
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("expect_lines", "unit", "TEXT NOT NULL DEFAULT '件'"),
    ("receive_lines", "unit", "TEXT NOT NULL DEFAULT '件'"),
    ("confirm_lines", "unit", "TEXT NOT NULL DEFAULT '件'"),
    ("reconcile_batches", "unit_miss_count", "INTEGER NOT NULL DEFAULT 0"),
    ("reconcile_batches", "unit_mismatch_count", "INTEGER NOT NULL DEFAULT 0"),
    ("reconcile_batches", "expect_pieces", "REAL NOT NULL DEFAULT 0"),
    ("reconcile_batches", "receive_pieces", "REAL NOT NULL DEFAULT 0"),
    ("reconcile_batches", "confirm_pieces", "REAL NOT NULL DEFAULT 0"),
    ("reconcile_batches", "policy", "TEXT NOT NULL DEFAULT 'pack_convert'"),
]
_ROW_MIGRATIONS: list[tuple[str, str, str]] = [
    (table, col, decl)
    for table in ("match_rows", "variance_rows")
    for col, decl in [
        ("expect_raw_qty", "REAL NOT NULL DEFAULT 0"),
        ("receive_raw_qty", "REAL NOT NULL DEFAULT 0"),
        ("confirm_raw_qty", "REAL NOT NULL DEFAULT 0"),
        ("expect_unit", "TEXT NOT NULL DEFAULT '件'"),
        ("receive_unit", "TEXT NOT NULL DEFAULT '件'"),
        ("confirm_unit", "TEXT NOT NULL DEFAULT '件'"),
        ("expect_pack_size", "REAL"),
        ("receive_pack_size", "REAL"),
        ("confirm_pack_size", "REAL"),
        ("convert_rule", "TEXT NOT NULL DEFAULT ''"),
        ("bucket", "TEXT NOT NULL DEFAULT 'variance'"),
        ("bucket_reason", "TEXT"),
    ]
]


def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _apply_migrations(conn) -> None:
    for table, col, decl in _MIGRATIONS + _ROW_MIGRATIONS:
        if table not in {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}:
            continue
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_schema(conn) -> None:
    conn.executescript(SCHEMA)
    _apply_migrations(conn)


def seed_if_empty() -> None:
    conn = connect()
    try:
        # executescript() implicitly commits, so schema + migrations run outside
        # the explicit write transaction; only the demo inserts are transactional.
        init_schema(conn)
        with write_txn(conn):
            if conn.execute("SELECT COUNT(*) c FROM suppliers").fetchone()["c"]:
                return
            _seed_demo(conn)
    finally:
        conn.close()


def _seed_demo(conn) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES ('dock_day', ?)", ("2026-11-18",))
    for code, title in [("SUP-A", "东海食材"), ("SUP-B", "北岭包装"), ("SUP-C", "南湾百货")]:
        conn.execute("INSERT INTO suppliers(code, title) VALUES (?,?)", (code, title))

    # 箱规表：回执常按箱申报，必须换算成件再对齐。
    specs = [
        ("SUP-B", "SKU-箱-大", "箱", "件", 20),
        ("SUP-A", "SKU-米-25", "箱", "件", 25),
    ]
    for supplier, sku, unit, base, size in specs:
        conn.execute(
            '''INSERT INTO pack_specs(supplier_code, sku, unit, base_unit, pack_size, updated_at)
               VALUES (?,?,?,?,?,?)''',
            (supplier, sku, unit, base, size, "2026-11-18T07:00:00Z"),
        )

    expects = [
        ("EX-1001", "SUP-A", "SKU-米-25", "2026-11-18", 40, "件", "早班预报"),
        ("EX-1002", "SUP-A", "SKU-油-5", "2026-11-18", 20, "件", None),
        ("EX-1003", "SUP-B", "SKU-箱-大", "2026-11-18", 100, "件", None),
        ("EX-1004", "SUP-C", "SKU-巾-卷", "2026-11-18", 60, "件", None),
        ("EX-1005", "SUP-C", "SKU-托-整", "2026-11-18", 50, "件", "整托到货"),
        ("EX-0901", "SUP-A", "SKU-米-25", "2026-11-17", 10, "件", "昨日"),
    ]
    for row in expects:
        conn.execute(
            '''INSERT INTO expect_lines(doc_no, supplier_code, sku, dock_day, qty, unit, note, created_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (*row, "2026-11-18T08:00:00Z"),
        )

    receives = [
        ("RC-2001", "SUP-A", "SKU-米-25", "2026-11-18", 38, "件", "2026-11-18T09:10:00Z", "少2"),
        ("RC-2002", "SUP-A", "SKU-油-5", "2026-11-18", 20, "件", "2026-11-18T09:20:00Z", None),
        ("RC-2003", "SUP-B", "SKU-箱-大", "2026-11-18", 100, "件", "2026-11-18T10:00:00Z", None),
        ("RC-2004", "SUP-C", "SKU-巾-卷", "2026-11-18", 66, "件", "2026-11-18T11:00:00Z", "多6"),
        ("RC-2005", "SUP-C", "SKU-托-整", "2026-11-18", 50, "件", "2026-11-18T11:20:00Z", None),
    ]
    for row in receives:
        conn.execute(
            '''INSERT INTO receive_lines(receive_no, supplier_code, sku, dock_day, qty, unit, occurred_at, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (*row, row[6]),
        )

    # CF-3003 按箱申报（5 箱 × 20 = 100 件），与预报/实收对齐；
    # CF-3005 单位缺失箱规（托）→ unit_miss；CF-3002 单位为 kg → unit_mismatch。
    confirms = [
        ("CF-3001", "SUP-A", "SKU-米-25", "2026-11-18", 38, "件", "回执按实收"),
        ("CF-3002", "SUP-A", "SKU-油-5", "2026-11-18", 20, "kg", "回执单位异常"),
        ("CF-3003", "SUP-B", "SKU-箱-大", "2026-11-18", 5, "箱", "按箱申报"),
        ("CF-3004", "SUP-C", "SKU-巾-卷", "2026-11-18", 60, "件", "回执仍报预报数"),
        ("CF-3005", "SUP-C", "SKU-托-整", "2026-11-18", 2, "托", "缺托规"),
    ]
    for row in confirms:
        conn.execute(
            '''INSERT INTO confirm_lines(confirm_no, supplier_code, sku, dock_day, qty, unit, note, created_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (*row, "2026-11-18T12:00:00Z"),
        )
