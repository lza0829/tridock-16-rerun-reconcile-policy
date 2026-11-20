"""Unit normalisation for three-leg reconciliation.

Architecture: **箱规换算**.

Receipts (回执) are commonly declared per case (箱) while forecasts (预报) and
actual receipts (实收) are booked per piece (件).  The only canonical quantity
used by reconciliation is therefore *converted pieces*:

    pieces = qty * pack_size      (when unit != BASE_UNIT)
    pieces = qty                  (when unit == BASE_UNIT)

The rule is applied to every leg, so a case-declared forecast or receipt is
handled too.  A line whose unit cannot be turned into pieces is never compared
1:1: it is bucketed as ``unit_miss`` (no pack spec on file) or
``unit_mismatch`` (unit is not a countable unit / spec is invalid).
"""

from __future__ import annotations

BASE_UNIT = "件"

BUCKET_MATCHED = "matched"
BUCKET_VARIANCE = "variance"
BUCKET_UNIT_MISS = "unit_miss"
BUCKET_UNIT_MISMATCH = "unit_mismatch"

UNIT_BUCKETS = (BUCKET_UNIT_MISS, BUCKET_UNIT_MISMATCH)

# Units that measure mass/volume/length and can never be converted into pieces
# by a pack size.  Lower-cased for comparison.
NON_COUNT_UNITS = {
    "kg", "g", "mg", "t", "克", "千克", "公斤", "吨",
    "l", "ml", "升", "毫升",
    "m", "cm", "mm", "米", "厘米", "毫米",
}


def norm_unit(unit: str | None) -> str:
    return (unit or "").strip()


def convert_line(
    qty: float,
    unit: str | None,
    spec: tuple[str, float] | None,
) -> dict:
    """Convert one line to pieces.

    ``spec`` is ``(base_unit, pack_size)`` for an exact
    (supplier_code, sku, unit) pack-spec row, or ``None`` when absent.

    Returns a dict with keys: ``pieces`` (float | None), ``pack_size``
    (float | None), ``rule`` (str), ``bucket`` (None or a UNIT_BUCKETS value),
    ``reason`` (str | None).
    """
    u = norm_unit(unit)
    if not u:
        return {
            "pieces": None,
            "pack_size": None,
            "rule": "",
            "bucket": BUCKET_UNIT_MISMATCH,
            "reason": "单位为空，无法换算为件",
        }
    if u.lower() in NON_COUNT_UNITS:
        return {
            "pieces": None,
            "pack_size": None,
            "rule": "",
            "bucket": BUCKET_UNIT_MISMATCH,
            "reason": f"单位 {u} 为计量单位，不可换算为{BASE_UNIT}",
        }
    if u == BASE_UNIT:
        return {
            "pieces": round(float(qty), 6),
            "pack_size": None,
            "rule": BASE_UNIT,
            "bucket": None,
            "reason": None,
        }
    # Non-base "pack" unit: must be backed by a pack spec.
    if spec is None:
        return {
            "pieces": None,
            "pack_size": None,
            "rule": "",
            "bucket": BUCKET_UNIT_MISS,
            "reason": f"缺少 {u}→{BASE_UNIT} 箱规",
        }
    base_unit, pack_size = spec
    if norm_unit(base_unit) != BASE_UNIT or pack_size is None or float(pack_size) <= 0:
        return {
            "pieces": None,
            "pack_size": None,
            "rule": "",
            "bucket": BUCKET_UNIT_MISMATCH,
            "reason": f"{u} 箱规无效（基准单位 {base_unit}，箱规 {pack_size}）",
        }
    ps = float(pack_size)
    return {
        "pieces": round(float(qty) * ps, 6),
        "pack_size": ps,
        "rule": f"{u}×{_fmt(ps)}→{BASE_UNIT}",
        "bucket": None,
        "reason": None,
    }


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)
