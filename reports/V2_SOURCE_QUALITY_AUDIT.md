# V2 Source Quality Audit
- 生成：2026-09-14T04:10:44+0800

## 来源类 × 权威级

| 类 | 级 | 资源数 |
|---|---|---|
| GeneralWebsite | B | 2159 |
| GeneralWebsite | UNKNOWN | 1401 |
| GeneralWebsite | C | 280 |
| Government | S | 186 |
| University | A | 77 |
| Newspaper | B | 55 |
| Museum | A | 10 |
| AcademicJournal | A | 3 |

## 范围门通过率（按来源类）

| 类 | CORE/CONTEXT | REJECTED | 通过率 |
|---|---|---|---|
| GeneralWebsite | 1451 | 2389 | 37.8% |
| Government | 100 | 86 | 53.8% |
| University | 4 | 73 | 5.2% |
| Newspaper | 24 | 31 | 43.6% |
| Museum | 6 | 4 | 60.0% |
| AcademicJournal | 0 | 3 | 0.0% |

## 证据产出（有 ADMITTED 证据的资源，按来源类）

| 类 | 资源数 |
|---|---|
| GeneralWebsite | 590 |
| Government | 45 |
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
| flow_boost1 | 28 | 12 | 0 | 0 |
| flow_targeted | 21 | 12 | 12 | 0 |
| gap-growth | 2220 | 553 | 309 | 215 |
| gaptest | 9 | 3 | 3 | 0 |
| smoke | 6 | 5 | 6 | 0 |
| smoke2 | 8 | 7 | 8 | 0 |
| task_1bc5dae1 | 2 | 0 | 0 | 0 |
| task_53406969 | 11 | 3 | 3 | 0 |
| task_642091b3 | 10 | 6 | 0 | 0 |
| task_6f91ae14 | 5 | 4 | 4 | 0 |
| task_71e086db | 95 | 6 | 5 | 0 |
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