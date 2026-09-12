# V2_CLEAN_ROOM_REPORT — Phase 7R 干净库重建验收

- 时间：2026-09-13 02:20 (+0800)
- 方式：`CREATE DATABASE ycki_cleanroom TEMPLATE template_postgis`（全新空库，禁止复用生产结构）
- 步骤：clone repo 工作树 → `001→002→003→004→005→006→007` → `python tools/init_canonical_v2.py --apply --dsn <cleanroom>` → `--verify`

## 结果

| 检查项 | 结果 |
|---|---|
| 001–007 全部 exit=0 | PASS |
| 005 重复执行安全（幂等） | PASS |
| Schema drift | 0 |
| Missing Controlled Nodes | 0 |
| Unexpected Controlled Nodes | 0 |
| Missing Controlled Relations | 0 |
| Duplicate Controlled Objects | 0 |
| FK Violation | 0 |
| Constraint Violation | 0 |
| manifest_hash（cleanroom vs 生产） | `5b8d7b54…197cee` 完全一致 |

受控骨架（EXPECTED==ACTUAL）：8 文化系统 / 7 文化区域 / 93 文化领域 / 13 历史分期 /
4 宏观演化模式 / 13 分期-模式映射 / 34 水系单元 / 46 水系拓扑关系 /
7 条 ONTOLOGY 结构关系。数量全部由当前版本 YAML manifest 定义（goal §9），非硬编码。

## clean-room 发现并已修复的存量缺陷

1. `deploy/sql/005_retrieval_graph.sql` 文件头为 Python 风格注释（`# -*- coding -*-` + docstring），
   根本不是合法 SQL——生产库从未重放因此未暴露。已改为 SQL 注释；修复后 005 可重复执行。
2. 运行库 cultural_regions 与 cultural_systems 撞名（均为"XX文化系统"）。已在 seed YAML 中
   规范化为"XX文化区"并声明 `legacy_names`，builder 确定性改名合并，membership.region_id 重指向。

## 生产库同步修复（同一 builder --apply 完成）

- 金沙江 Tributary→RiverSection（干流上段）、雅砻江→汇入金沙江、大渡河→汇入岷江（水文事实修正）
- 21 条 0 证据 structural_relations 降级 ADMITTED→CANDIDATE（007 数据迁移）
- 10,004 条 system_memberships 全部标记 `derivation_method=legacy_geo_rule_v0, status=CANDIDATE`
  （等待 membership 重建管线；geo-only ADMITTED = 0 达成）
- macro_evolution_patterns 表 + 13 条 phase_patterns junction 落库（§11 分离达成）

## Phase 7R 验收结论

**PASS。** canonical_v2 骨架从"本地数据库实验状态"恢复为完全可复现系统：
Git(manifest+SQL+builder) → 任意空库 → 与生产受控层 100% 一致。

## 复现命令

```bash
docker exec ycki-postgres psql -U postgres -c "CREATE DATABASE ycki_cleanroom TEMPLATE template_postgis"
for f in 001_init 002_canonical_migration 003_pipeline_resume 004_er_evolution 005_retrieval_graph 006_cultural_system_v2 007_structural_layer_v2; do
  docker exec -i ycki-postgres psql -U postgres -d ycki_cleanroom -v ON_ERROR_STOP=1 < deploy/sql/$f.sql || exit 1
done
python tools/init_canonical_v2.py --apply --dsn "host=127.0.0.1 port=5433 dbname=ycki_cleanroom user=postgres password=ycki_pg_2026"
python tools/init_canonical_v2.py --verify --dsn "host=127.0.0.1 port=5433 dbname=ycki_cleanroom user=postgres password=ycki_pg_2026"
docker exec ycki-postgres psql -U postgres -c "DROP DATABASE ycki_cleanroom"
```

## 第二次验收（§96，2026-09-13 06:05）

- 全新空库 → 001–008 全部幂等通过（含 008 合成约束）→ builder --apply → --verify **0 漂移**
- 重复 --apply 两次后 --verify 仍 **0 漂移、manifest_hash 一致**（`49a6b71e…`，与生产一致）
- 测试库已删除
- **PASS**
