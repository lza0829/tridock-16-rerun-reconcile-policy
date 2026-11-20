# Tridock（到货三联台）

骨架：到货预报装载 → 实收入账 → 供应商回执装载 → 三方键对齐与差额处置 → 到货日结案封印。

- 前端 http://127.0.0.1:5900
- API http://127.0.0.1:10900

## 单位口径：箱规换算（全局唯一口径）

回执常按箱申报，预报/实收按件记账。为避免「箱数当件数」造成的大面积假差额，全链路
只贯彻一种口径——**折算成件再对齐**：

```
件数 = qty            （unit == 件）
件数 = qty × pack_size（unit 为箱等包装单位，且箱规表已有该 供应商+货号+单位 记录）
```

关键联动（改一处必须同步改另几处）：

| 环节 | 行为 |
| --- | --- |
| 箱规表 `/api/pack-specs` | 按 供应商+货号+单位 维护「单位 → 件」箱规；写入与对账互斥 |
| 回执装载 | 允许按箱申报，qty 与 unit 原样入账，不在此拒入 |
| 对齐扫描 | 三腿统一折成件后比较；件数不等即差额 |
| 分桶 | 缺箱规 → `unit_miss`；单位为空/计量单位/箱规非法 → `unit_mismatch`；**绝不按 1:1 硬比** |
| 批次快照 | `match_rows` 落 raw qty、unit、pack_size、convert_rule、折算前后件数；结案后不受箱规改动影响 |
| 结案闸 | 未决差额、`unit_miss`、`unit_mismatch` 任一非空即拒绝封印 |
| 总览 | 件数与分桶一律取自最近批次快照，不重算原始行 |

并发：对账在 `BEGIN IMMEDIATE` 事务内读取箱规，箱规写入同样走写锁，因此单次对账不会
混用新旧 pack_size。

## 启动

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 10900 --app-dir .
```

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5900
```

## 测试

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
