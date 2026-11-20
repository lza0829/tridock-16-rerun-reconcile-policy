from __future__ import annotations
from fastapi import APIRouter
from app.db import connect, read_snapshot
from app.services.gate import is_sealed

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard():
    conn = connect()
    try:
        with read_snapshot(conn):
            day = conn.execute("SELECT value FROM settings WHERE key='dock_day'").fetchone()["value"]
            expect_n = conn.execute("SELECT COUNT(*) c FROM expect_lines WHERE dock_day=?", (day,)).fetchone()["c"]
            receive_n = conn.execute("SELECT COUNT(*) c FROM receive_lines WHERE dock_day=?", (day,)).fetchone()["c"]
            confirm_n = conn.execute("SELECT COUNT(*) c FROM confirm_lines WHERE dock_day=?", (day,)).fetchone()["c"]
            batch = conn.execute(
                "SELECT * FROM reconcile_batches WHERE dock_day=? ORDER BY id DESC LIMIT 1",
                (day,),
            ).fetchone()
            pending = 0
            buckets = {"matched": 0, "variance": 0, "unit_miss": 0, "unit_mismatch": 0}
            pieces = {"expect": 0.0, "receive": 0.0, "confirm": 0.0}
            if batch:
                pending = conn.execute(
                    "SELECT COUNT(*) c FROM variance_rows WHERE batch_id=? AND fate='pending'",
                    (batch["id"],),
                ).fetchone()["c"]
                # 总览的件数与分桶一律取自批次快照 match_rows，绝不重算原始行，
                # 保证与三联对账展示的是同一组数据、同一套件数。
                for r in conn.execute(
                    "SELECT bucket, COUNT(*) c FROM match_rows WHERE batch_id=? GROUP BY bucket",
                    (batch["id"],),
                ).fetchall():
                    buckets[r["bucket"]] = r["c"]
                pieces = {
                    "expect": float(batch["expect_pieces"]),
                    "receive": float(batch["receive_pieces"]),
                    "confirm": float(batch["confirm_pieces"]),
                }
            return {
                "dock_day": day,
                "sealed": is_sealed(conn, day),
                "expect_count": expect_n,
                "receive_count": receive_n,
                "confirm_count": confirm_n,
                "latest_batch": dict(batch) if batch else None,
                "pending_variance": pending,
                "unit_policy": "pack_convert",
                "buckets": buckets,
                "pieces": pieces,
            }
    finally:
        conn.close()
