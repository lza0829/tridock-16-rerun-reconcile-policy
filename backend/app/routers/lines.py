from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.db import connect, write_txn
from app.services.gate import assert_writable
from app.services.units import BASE_UNIT, norm_unit

router = APIRouter(tags=["lines"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unit(unit: str | None) -> str:
    u = norm_unit(unit)
    if not u:
        raise ValueError("单位不能为空")
    return u


class ExpectIn(BaseModel):
    doc_no: str
    supplier_code: str
    sku: str
    dock_day: str
    qty: float = Field(gt=0)
    unit: str = BASE_UNIT
    note: str | None = None


class ReceiveIn(BaseModel):
    receive_no: str
    supplier_code: str
    sku: str
    dock_day: str
    qty: float = Field(gt=0)
    unit: str = BASE_UNIT
    occurred_at: str | None = None
    note: str | None = None


class ConfirmIn(BaseModel):
    confirm_no: str
    supplier_code: str
    sku: str
    dock_day: str
    qty: float = Field(gt=0)
    unit: str = BASE_UNIT
    note: str | None = None


class PackSpecIn(BaseModel):
    supplier_code: str
    sku: str
    unit: str
    base_unit: str = BASE_UNIT
    pack_size: float = Field(gt=0)


_COMMON = {
    "expect": ("expect_lines", "doc_no"),
    "receive": ("receive_lines", "receive_no"),
    "confirm": ("confirm_lines", "confirm_no"),
}


@router.get("/suppliers")
def list_suppliers():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM suppliers ORDER BY code").fetchall()]
    finally:
        conn.close()


@router.get("/pack-specs")
def list_pack_specs():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM pack_specs ORDER BY supplier_code, sku, unit"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/pack-specs")
def upsert_pack_spec(body: PackSpecIn):
    """箱规表写入。与对账互斥：对账持写锁读取箱规，不会读到半更新值。

    已结案批次不受影响——其 match_rows 已快照折算前后的数量与规则。
    """
    conn = connect()
    try:
        unit = _unit(body.unit)
        base = _unit(body.base_unit)
        if unit == base:
            raise ValueError("箱规单位不能等于基准单位")
        with write_txn(conn):
            conn.execute(
                '''INSERT INTO pack_specs(supplier_code, sku, unit, base_unit, pack_size, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(supplier_code, sku, unit) DO UPDATE SET
                     base_unit=excluded.base_unit,
                     pack_size=excluded.pack_size,
                     updated_at=excluded.updated_at''',
                (body.supplier_code, body.sku, unit, base, body.pack_size, _now()),
            )
            row = conn.execute(
                "SELECT * FROM pack_specs WHERE supplier_code=? AND sku=? AND unit=?",
                (body.supplier_code, body.sku, unit),
            ).fetchone()
            return dict(row)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        conn.close()


@router.delete("/pack-specs/{spec_id}")
def delete_pack_spec(spec_id: int):
    conn = connect()
    try:
        with write_txn(conn):
            row = conn.execute("SELECT * FROM pack_specs WHERE id=?", (spec_id,)).fetchone()
            if not row:
                raise ValueError("箱规不存在")
            conn.execute("DELETE FROM pack_specs WHERE id=?", (spec_id,))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        conn.close()


@router.get("/expects")
def list_expects(dock_day: str | None = None):
    conn = connect()
    try:
        if dock_day:
            rows = conn.execute(
                "SELECT * FROM expect_lines WHERE dock_day=? ORDER BY id", (dock_day,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM expect_lines ORDER BY dock_day DESC, id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/expects")
def add_expect(body: ExpectIn):
    conn = connect()
    try:
        unit = _unit(body.unit)
        with write_txn(conn):
            assert_writable(conn, body.dock_day)
            conn.execute(
                '''INSERT INTO expect_lines(doc_no, supplier_code, sku, dock_day, qty, unit, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (body.doc_no, body.supplier_code, body.sku, body.dock_day, body.qty, unit, body.note, _now()),
            )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"写入失败: {e}") from e
    finally:
        conn.close()


@router.get("/receives")
def list_receives(dock_day: str | None = None):
    conn = connect()
    try:
        if dock_day:
            rows = conn.execute(
                "SELECT * FROM receive_lines WHERE dock_day=? ORDER BY id", (dock_day,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM receive_lines ORDER BY dock_day DESC, id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/receives")
def add_receive(body: ReceiveIn):
    conn = connect()
    try:
        unit = _unit(body.unit)
        occurred = body.occurred_at or _now()
        with write_txn(conn):
            assert_writable(conn, body.dock_day)
            conn.execute(
                '''INSERT INTO receive_lines(receive_no, supplier_code, sku, dock_day, qty, unit, occurred_at, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (
                    body.receive_no,
                    body.supplier_code,
                    body.sku,
                    body.dock_day,
                    body.qty,
                    unit,
                    occurred,
                    body.note,
                    _now(),
                ),
            )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"写入失败: {e}") from e
    finally:
        conn.close()


@router.get("/confirms")
def list_confirms(dock_day: str | None = None):
    conn = connect()
    try:
        if dock_day:
            rows = conn.execute(
                "SELECT * FROM confirm_lines WHERE dock_day=? ORDER BY id", (dock_day,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM confirm_lines ORDER BY dock_day DESC, id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/confirms")
def add_confirm(body: ConfirmIn):
    """回执装载：允许按箱申报（unit='箱'），单位不在此处强制换算。

    单位不可换算的行不在此拒入——它在对账时进入 unit_miss / unit_mismatch
    隔离桶，并以 unit 原样快照，从而让缺陷可见、可修（补箱规）而非静默丢行。
    真正阻断结案的是闸门：桶未清空即不得封印。
    """
    conn = connect()
    try:
        unit = _unit(body.unit)
        with write_txn(conn):
            assert_writable(conn, body.dock_day)
            conn.execute(
                '''INSERT INTO confirm_lines(confirm_no, supplier_code, sku, dock_day, qty, unit, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (body.confirm_no, body.supplier_code, body.sku, body.dock_day, body.qty, unit, body.note, _now()),
            )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"写入失败: {e}") from e
    finally:
        conn.close()
