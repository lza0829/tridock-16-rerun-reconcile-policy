from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import sqlite3

from app.db import write_txn
from app.services.units import (
    BUCKET_MATCHED,
    BUCKET_UNIT_MISMATCH,
    BUCKET_UNIT_MISS,
    BUCKET_VARIANCE,
    BASE_UNIT,
    convert_line,
)

_LEGS = ("expect", "receive", "confirm")
_QTY_COL = {"expect": "expect_qty", "receive": "receive_qty", "confirm": "confirm_qty"}
_RAW_COL = {"expect": "expect_raw_qty", "receive": "receive_raw_qty", "confirm": "confirm_raw_qty"}
_UNIT_COL = {"expect": "expect_unit", "receive": "receive_unit", "confirm": "confirm_unit"}
_PACK_COL = {"expect": "expect_pack_size", "receive": "receive_pack_size", "confirm": "confirm_pack_size"}
_TABLE = {"expect": "expect_lines", "receive": "receive_lines", "confirm": "confirm_lines"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_specs(conn: sqlite3.Connection) -> dict[tuple[str, str, str], tuple[str, float]]:
    rows = conn.execute(
        "SELECT supplier_code, sku, unit, base_unit, pack_size FROM pack_specs"
    ).fetchall()
    return {
        (r["supplier_code"], r["sku"], r["unit"]): (r["base_unit"], float(r["pack_size"]))
        for r in rows
    }


def _collect_legs(conn: sqlite3.Connection, dock_day: str, specs) -> dict[str, dict]:
    """Convert every line of the day to pieces, grouped per (supplier, sku) per leg.

    A leg group is ``ok`` only when *every* line in it converts to pieces.  An
    ``ok`` group carries a piece total; a non-``ok`` group carries ``None`` so a
    partial sum is never mistaken for the leg's real quantity.
    """
    legs: dict[str, dict] = {leg: {} for leg in _LEGS}
    for leg in _LEGS:
        rows = conn.execute(
            f"SELECT supplier_code, sku, qty, unit FROM {_TABLE[leg]} WHERE dock_day=? ORDER BY id",
            (dock_day,),
        ).fetchall()
        for r in rows:
            key = (r["supplier_code"], r["sku"])
            conv = convert_line(float(r["qty"]), r["unit"], specs.get((r["supplier_code"], r["sku"], (r["unit"] or "").strip())))
            g = legs[leg].setdefault(
                key,
                {
                    "pieces": 0.0,
                    "raw": 0.0,
                    "units": set(),
                    "packs": set(),
                    "rules": set(),
                    "bucket": None,
                    "reason": None,
                },
            )
            g["raw"] += float(r["qty"])
            g["units"].add((r["unit"] or "").strip() or "?")
            if conv["pack_size"] is not None:
                g["packs"].add(conv["pack_size"])
            if conv["rule"]:
                g["rules"].add(conv["rule"])
            if conv["bucket"]:
                g["bucket"] = conv["bucket"]
                g["reason"] = g["reason"] or conv["reason"]
            else:
                g["pieces"] += conv["pieces"]
    for leg in _LEGS:
        for g in legs[leg].values():
            g["ok"] = g["bucket"] is None
            if not g["ok"]:
                g["pieces"] = None
    return legs


def _leg_cell(g: dict | None) -> dict:
    if g is None:
        return {
            "qty": 0.0,
            "raw": 0.0,
            "unit": BASE_UNIT,
            "pack": None,
            "rule": "",
        }
    packs = sorted(g["packs"])
    return {
        "qty": g["pieces"],
        "raw": g["raw"],
        "unit": "+".join(sorted(g["units"])) if g["units"] else BASE_UNIT,
        "pack": packs[0] if len(packs) == 1 else None,
        "rule": ";".join(sorted(r for r in g["rules"] if r != BASE_UNIT)),
    }


def run_reconcile(conn: sqlite3.Connection, dock_day: str) -> dict:
    with write_txn(conn):
        sealed = conn.execute(
            "SELECT 1 FROM reconcile_batches WHERE dock_day=? AND status='sealed' LIMIT 1",
            (dock_day,),
        ).fetchone()
        if sealed:
            raise ValueError(f"到货日 {dock_day} 已结案，不能重跑对账")

        old = conn.execute(
            "SELECT id FROM reconcile_batches WHERE dock_day=? AND status='open'", (dock_day,)
        ).fetchall()
        for r in old:
            conn.execute("DELETE FROM match_rows WHERE batch_id=?", (r["id"],))
            conn.execute("DELETE FROM variance_rows WHERE batch_id=?", (r["id"],))
            conn.execute("DELETE FROM reconcile_batches WHERE id=?", (r["id"],))

        # Read pack specs *inside* the immediate write txn: a concurrent spec
        # edit cannot interleave, so one run never mixes an old and new pack_size.
        specs = _load_specs(conn)
        legs = _collect_legs(conn, dock_day, specs)
        keys = set().union(*(set(legs[leg]) for leg in _LEGS))

        n = conn.execute("SELECT COUNT(*) c FROM reconcile_batches").fetchone()["c"] + 1
        batch_no = f"RB-{dock_day.replace('-', '')}-{n:03d}"
        cur = conn.execute(
            '''INSERT INTO reconcile_batches(batch_no, dock_day, matched_count, variance_count,
                   unit_miss_count, unit_mismatch_count, expect_pieces, receive_pieces, confirm_pieces,
                   policy, status, sealed_at, note)
               VALUES (?,?,0,0,0,0,0,0,0,'pack_convert','open',NULL,?)''',
            (batch_no, dock_day, "三联对齐（箱规换算）"),
        )
        batch_id = int(cur.lastrowid)

        counts = {BUCKET_MATCHED: 0, BUCKET_VARIANCE: 0, BUCKET_UNIT_MISS: 0, BUCKET_UNIT_MISMATCH: 0}
        totals = {leg: 0.0 for leg in _LEGS}
        now = _now()

        for supplier_code, sku in sorted(keys):
            cells = {leg: _leg_cell(legs[leg].get((supplier_code, sku))) for leg in _LEGS}
            raw_groups = {leg: legs[leg].get((supplier_code, sku)) for leg in _LEGS}

            bad = [leg for leg in _LEGS if raw_groups[leg] is not None and not raw_groups[leg]["ok"]]
            if bad:
                bucket = (
                    BUCKET_UNIT_MISMATCH
                    if any(raw_groups[leg]["bucket"] == BUCKET_UNIT_MISMATCH for leg in bad)
                    else BUCKET_UNIT_MISS
                )
                reason = "；".join(
                    f"{_LEG_CN[leg]}:{raw_groups[leg]['reason']}" for leg in bad
                )
                aligned = 0
            else:
                eq = cells["expect"]["qty"]
                rq = cells["receive"]["qty"]
                cq = cells["confirm"]["qty"]
                bucket = BUCKET_MATCHED if _same3(eq, rq, cq) else BUCKET_VARIANCE
                reason = None
                aligned = 1 if bucket == BUCKET_MATCHED else 0

            counts[bucket] += 1
            for leg in _LEGS:
                if cells[leg]["qty"] is not None:
                    totals[leg] += cells[leg]["qty"]

            rule = ";".join(
                sorted({cells[leg]["rule"] for leg in _LEGS if cells[leg]["rule"]})
            )
            values = (
                batch_id,
                dock_day,
                supplier_code,
                sku,
                cells["expect"]["qty"],
                cells["receive"]["qty"],
                cells["confirm"]["qty"],
                cells["expect"]["raw"],
                cells["receive"]["raw"],
                cells["confirm"]["raw"],
                cells["expect"]["unit"],
                cells["receive"]["unit"],
                cells["confirm"]["unit"],
                cells["expect"]["pack"],
                cells["receive"]["pack"],
                cells["confirm"]["pack"],
                rule,
                bucket,
                reason,
                aligned,
            )
            conn.execute(
                '''INSERT INTO match_rows(batch_id, dock_day, supplier_code, sku,
                       expect_qty, receive_qty, confirm_qty,
                       expect_raw_qty, receive_raw_qty, confirm_raw_qty,
                       expect_unit, receive_unit, confirm_unit,
                       expect_pack_size, receive_pack_size, confirm_pack_size,
                       convert_rule, bucket, bucket_reason, aligned)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                values,
            )
            if bucket == BUCKET_VARIANCE:
                conn.execute(
                    '''INSERT INTO variance_rows(batch_id, dock_day, supplier_code, sku,
                           expect_qty, receive_qty, confirm_qty,
                           expect_raw_qty, receive_raw_qty, confirm_raw_qty,
                           expect_unit, receive_unit, confirm_unit,
                           expect_pack_size, receive_pack_size, confirm_pack_size,
                           convert_rule, bucket, bucket_reason, fate, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)''',
                    values[:-1] + (now,),
                )

        conn.execute(
            '''UPDATE reconcile_batches
               SET matched_count=?, variance_count=?, unit_miss_count=?, unit_mismatch_count=?,
                   expect_pieces=?, receive_pieces=?, confirm_pieces=?
               WHERE id=?''',
            (
                counts[BUCKET_MATCHED],
                counts[BUCKET_VARIANCE],
                counts[BUCKET_UNIT_MISS],
                counts[BUCKET_UNIT_MISMATCH],
                totals["expect"],
                totals["receive"],
                totals["confirm"],
                batch_id,
            ),
        )
        return {
            "batch_id": batch_id,
            "batch_no": batch_no,
            "dock_day": dock_day,
            "matched_count": counts[BUCKET_MATCHED],
            "variance_count": counts[BUCKET_VARIANCE],
            "unit_miss_count": counts[BUCKET_UNIT_MISS],
            "unit_mismatch_count": counts[BUCKET_UNIT_MISMATCH],
            "expect_pieces": totals["expect"],
            "receive_pieces": totals["receive"],
            "confirm_pieces": totals["confirm"],
            "policy": "pack_convert",
            "status": "open",
        }


def _same3(a, b, c) -> bool:
    if a is None or b is None or c is None:
        return False
    return round(float(a), 6) == round(float(b), 6) == round(float(c), 6)


_LEG_CN = {"expect": "预报", "receive": "实收", "confirm": "回执"}


def seal_day(conn: sqlite3.Connection, dock_day: str) -> dict:
    with write_txn(conn):
        batch = conn.execute(
            "SELECT * FROM reconcile_batches WHERE dock_day=? AND status='open' ORDER BY id DESC LIMIT 1",
            (dock_day,),
        ).fetchone()
        if not batch:
            raise ValueError("没有可结案的对账批次，请先跑三联对账")
        pending = conn.execute(
            "SELECT COUNT(*) c FROM variance_rows WHERE batch_id=? AND fate='pending'",
            (batch["id"],),
        ).fetchone()["c"]
        blockers = []
        if pending:
            blockers.append(f"{pending} 条差额未处置")
        if batch["unit_miss_count"]:
            blockers.append(f"{batch['unit_miss_count']} 条缺箱规(unit_miss)")
        if batch["unit_mismatch_count"]:
            blockers.append(f"{batch['unit_mismatch_count']} 条单位不可换算(unit_mismatch)")
        if blockers:
            raise ValueError("不能结案：" + "；".join(blockers))
        now = _now()
        conn.execute(
            "UPDATE reconcile_batches SET status='sealed', sealed_at=? WHERE id=?",
            (now, batch["id"]),
        )
        return dict(conn.execute("SELECT * FROM reconcile_batches WHERE id=?", (batch["id"],)).fetchone())


def set_variance_fate(conn: sqlite3.Connection, variance_id: int, fate: str) -> dict:
    allowed = {"pending", "accept_short", "accept_over", "quarantine"}
    if fate not in allowed:
        raise ValueError("非法差额命运")
    with write_txn(conn):
        row = conn.execute("SELECT * FROM variance_rows WHERE id=?", (variance_id,)).fetchone()
        if not row:
            raise ValueError("差额行不存在")
        batch = conn.execute("SELECT * FROM reconcile_batches WHERE id=?", (row["batch_id"],)).fetchone()
        if batch and batch["status"] == "sealed":
            raise ValueError("已结案批次不可改差额命运")
        conn.execute("UPDATE variance_rows SET fate=? WHERE id=?", (fate, variance_id))
        return dict(conn.execute("SELECT * FROM variance_rows WHERE id=?", (variance_id,)).fetchone())
