"""Invariant tests for the pack-size conversion (箱规换算) reconciliation policy.

Run from ``backend/``:  .venv/bin/python -m pytest -q
"""
from __future__ import annotations
import sqlite3
import threading
import time

import pytest

from app import db
from app.services import reconcile_service as svc
from app.seed import init_schema
from app.services.units import convert_line


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    c = db.connect()
    init_schema(c)
    yield c
    c.close()


def add(conn, table, key, supplier, sku, day, qty, unit, no):
    ts = "2026-11-18T00:00:00Z"
    if table == "receive_lines":
        conn.execute(
            "INSERT INTO receive_lines(receive_no, supplier_code, sku, dock_day, qty, unit, occurred_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (no, supplier, sku, day, qty, unit, ts, ts),
        )
    else:
        conn.execute(
            f"INSERT INTO {table}({key}, supplier_code, sku, dock_day, qty, unit, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (no, supplier, sku, day, qty, unit, ts),
        )


def spec(conn, supplier, sku, unit, size):
    conn.execute(
        """INSERT INTO pack_specs(supplier_code, sku, unit, base_unit, pack_size, updated_at)
           VALUES (?,?,?,'件',?,'2026-11-18T00:00:00Z')""",
        (supplier, sku, unit, size),
    )


def rows(conn, batch_id, table="match_rows"):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE batch_id=?", (batch_id,))]


def one(conn, batch_id, sku):
    return next(r for r in rows(conn, batch_id) if r["sku"] == sku)


DAY = "2026-11-18"


# --- unit primitive -------------------------------------------------------


def test_convert_base_unit_is_identity():
    assert convert_line(7, "件", None)["pieces"] == 7


def test_convert_case_uses_pack_size():
    out = convert_line(5, "箱", ("件", 20))
    assert out["pieces"] == 100 and out["bucket"] is None


def test_missing_spec_is_unit_miss_not_one_to_one():
    out = convert_line(5, "箱", None)
    assert out["pieces"] is None and out["bucket"] == "unit_miss"


def test_non_count_unit_is_mismatch():
    assert convert_line(20, "kg", None)["bucket"] == "unit_mismatch"
    assert convert_line(3, "箱", ("件", 0))["bucket"] == "unit_mismatch"


# --- reconcile: conversion path ------------------------------------------


def test_case_declared_confirm_matches_piece_legs(conn):
    spec(conn, "S", "K", "箱", 20)
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 5, "箱", "C1")
    res = svc.run_reconcile(conn, DAY)
    assert res["matched_count"] == 1
    r = one(conn, res["batch_id"], "K")
    # raw case qty preserved, pieces converted, rule snapshotted
    assert r["confirm_raw_qty"] == 5 and r["confirm_qty"] == 100
    assert r["confirm_pack_size"] == 20 and "箱×20→件" in r["convert_rule"]
    assert r["aligned"] == 1 and r["bucket"] == "matched"


def test_missing_spec_goes_to_unit_miss_and_never_matches(conn):
    # receipt says 5 箱 with no pack spec; 5 != 100 so 1:1 compare would be wrong.
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 5, "箱", "C1")
    res = svc.run_reconcile(conn, DAY)
    assert res["matched_count"] == 0 and res["unit_miss_count"] == 1
    r = one(conn, res["batch_id"], "K")
    assert r["bucket"] == "unit_miss" and r["aligned"] == 0
    assert r["confirm_qty"] is None  # un-convertible leg has no piece total
    assert rows(conn, res["batch_id"], "variance_rows") == []  # not a fake variance


def test_non_count_unit_goes_to_unit_mismatch(conn):
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 20, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 20, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 20, "kg", "C1")
    res = svc.run_reconcile(conn, DAY)
    assert res["unit_mismatch_count"] == 1 and res["matched_count"] == 0
    assert one(conn, res["batch_id"], "K")["bucket"] == "unit_mismatch"


def test_converted_but_unequal_is_variance(conn):
    spec(conn, "S", "K", "箱", 20)
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 4, "箱", "C1")  # 80
    res = svc.run_reconcile(conn, DAY)
    assert res["variance_count"] == 1 and res["unit_miss_count"] == 0
    r = one(conn, res["batch_id"], "K")
    assert r["confirm_qty"] == 80 and r["aligned"] == 0


# --- seal gate ------------------------------------------------------------


def test_seal_blocked_by_unit_miss(conn):
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 5, "箱", "C1")
    svc.run_reconcile(conn, DAY)
    with pytest.raises(ValueError, match="unit_miss"):
        svc.seal_day(conn, DAY)


def test_seal_blocked_by_unit_mismatch(conn):
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 20, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 20, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 20, "kg", "C1")
    svc.run_reconcile(conn, DAY)
    with pytest.raises(ValueError, match="unit_mismatch"):
        svc.seal_day(conn, DAY)


def test_clean_day_seals(conn):
    spec(conn, "S", "K", "箱", 20)
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 5, "箱", "C1")
    svc.run_reconcile(conn, DAY)
    assert svc.seal_day(conn, DAY)["status"] == "sealed"


# --- sealed batch immunity ------------------------------------------------


def test_sealed_batch_immune_to_later_pack_spec_change(conn):
    spec(conn, "S", "K", "箱", 20)
    add(conn, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", "E1")
    add(conn, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", "R1")
    add(conn, "confirm_lines", "confirm_no", "S", "K", DAY, 5, "箱", "C1")
    res = svc.run_reconcile(conn, DAY)
    svc.seal_day(conn, DAY)
    # change pack spec afterwards
    conn.execute("UPDATE pack_specs SET pack_size=999 WHERE supplier_code='S' AND sku='K'")
    r = one(conn, res["batch_id"], "K")
    assert r["confirm_pack_size"] == 20 and r["confirm_qty"] == 100
    # sealed day may not be re-reconciled
    with pytest.raises(ValueError, match="已结案"):
        svc.run_reconcile(conn, DAY)


# --- concurrency: no half-old/half-new pack_size -------------------------


def test_concurrent_spec_change_never_mixes_pack_size(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "c.db")
    setup = db.connect()
    init_schema(setup)
    spec(setup, "S", "K", "箱", 20)
    for i in range(8):
        add(setup, "expect_lines", "doc_no", "S", "K", DAY, 100, "件", f"E{i}")
        add(setup, "receive_lines", "receive_no", "S", "K", DAY, 100, "件", f"R{i}")
        add(setup, "confirm_lines", "confirm_no", "S", "K", DAY, 5, "箱", f"C{i}")
    setup.close()

    stop = threading.Event()
    errors: list[Exception] = []

    def flipper():
        c = db.connect()
        try:
            size = 20
            while not stop.is_set():
                size = 40 if size == 20 else 20
                with db.write_txn(c):
                    c.execute(
                        "UPDATE pack_specs SET pack_size=? WHERE supplier_code='S' AND sku='K'",
                        (size,),
                    )
                time.sleep(0.002)
        except Exception as e:  # pragma: no cover
            errors.append(e)
        finally:
            c.close()

    t = threading.Thread(target=flipper)
    t.start()
    try:
        rc = db.connect()
        for _ in range(40):
            res = svc.run_reconcile(rc, DAY)
            r = one(rc, res["batch_id"], "K")
            # every snapshot is internally consistent: pieces == raw * stored pack
            assert r["confirm_qty"] == r["confirm_raw_qty"] * r["confirm_pack_size"]
            assert r["confirm_pack_size"] in (20, 40)
        rc.close()
    finally:
        stop.set()
        t.join()
    assert not errors
