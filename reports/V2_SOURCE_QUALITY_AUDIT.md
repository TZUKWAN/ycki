# V2 Source Quality Audit
- 生成：2026-09-14T05:57:23+0800

## 来源类 × 权威级

| 类 | 级 | 资源数 |
|---|---|---|
| GeneralWebsite | B | 2179 |
| GeneralWebsite | UNKNOWN | 1456 |
| GeneralWebsite | C | 281 |
| Government | S | 188 |
| University | A | 78 |
| Newspaper | B | 56 |
| Museum | A | 10 |
| AcademicJournal | A | 3 |

## 范围门通过率（按来源类）

| 类 | CORE/CONTEXT | REJECTED | 通过率 |
|---|---|---|---|
| GeneralWebsite | 1457 | 2459 | 37.2% |
| Government | 100 | 88 | 53.2% |
| University | 4 | 74 | 5.1% |
| Newspaper | 24 | 32 | 42.9% |
| Museum | 6 | 4 | 60.0% |
| AcademicJournal | 0 | 3 | 0.0% |

## 证据产出（有 ADMITTED 证据的资源，按来源类）

| 类 | 资源数 |
|---|---|
| GeneralWebsite | 600 |
| Government | 46 |
| Newspaper | 11 |
| Museum | 4 |
| University | 2 |

## 批次 yield

| 批次 | 注册 | 范围通过 | processed | failed |
|---|---|---|---|---|
| auto-batch1 | 47 | 22 | 22 | 0 |
| auto-batch10 | 46 | 23 | 24 | 0 |
| auto-batch2 | 40 | 18 | 18 | 0 |
| auto-batch3 | 18 | 12 | 9 | 0 |
| auto-batch4 | 3 | 0 | 0 | 0 |
| auto-batch5 | 31 | 11 | 10 | 0 |
| auto-batch6 | 32 | 5 | 5 | 0 |
| auto-batch7 | 24 | 12 | 12 | 0 |
| auto-batch8 | 21 | 9 | 11 | 0 |
| batch1 | 212 | 160 | 211 | 0 |
| batch1b | 81 | 44 | 81 | 0 |
| batch2 | 370 | 226 | 369 | 0 |
| batch3 | 167 | 110 | 167 | 0 |
| batch4 | 117 | 68 | 117 | 0 |
| batch5 | 132 | 57 | 131 | 0 |
| batch6 | 85 | 55 | 85 | 0 |
| batch7 | 111 | 60 | 111 | 0 |
| batch8 | 143 | 69 | 135 | 0 |
| batch9-smoke | 7 | 6 | 7 | 0 |
| diag | 2 | 1 | 1 | 0 |
| flow_boost1 | 28 | 12 | 12 | 0 |
| flow_targeted | 21 | 12 | 12 | 0 |
| gap-growth | 2220 | 552 | 348 | 215 |
| gaptest | 9 | 3 | 3 | 0 |
| gt_wave1 | 80 | 7 | 4 | 0 |
| smoke | 6 | 5 | 6 | 0 |
| smoke2 | 8 | 7 | 8 | 0 |
| task_1bc5dae1 | 2 | 0 | 0 | 0 |
| task_53406969 | 11 | 3 | 3 | 0 |
| task_642091b3 | 10 | 6 | 6 | 0 |
| task_6f91ae14 | 5 | 4 | 4 | 0 |
| task_71e086db | 95 | 6 | 6 | 0 |
| task_932b52a4 | 6 | 2 | 2 | 0 |
| task_aded52d5 | 1 | 1 | 1 | 0 |
| task_b76c814d | 10 | 3 | 3 | 0 |
| task_e476a163 | 5 | 0 | 0 | 0 |
| task_ec9c87ae | 45 | 0 | 0 | 0 |

## 独立来源簇（§7.3）

- 带簇标记资源：986
- 独立簇数：980

> 审计结论：以数据库实时统计为准；低通过率来源类不证明采集失败，
> 需结合 scope_gold 与 claim 准入拒绝原因复核。