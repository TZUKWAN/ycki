# V2 Computer-Use UAT 记录（进行中）

## 会话 1（2026-09-14 03:40-03:55，真实浏览器 ZCode IAB）

环境：dashboard uvicorn @ 127.0.0.1:9622（真实服务），PostgreSQL 5433，LightRAG 9621。

| # | persona | task | 操作 | 结果 |
|---|---------|------|------|------|
| 1 | 新用户 | 打开 /graph 图谱页 | goto + DOM 快照 | PASS：标题「YCKI 文化图谱」，统计「129 节点 · 112 边」 |
| 2 | 数字人文学者 | 切换 系统结构/区域互动/文化流动 三个视图 | 点击页签（vis-network canvas） | PASS：7节点/10节点·5边/129节点·112边 |
| 3 | 新用户 | 打开 /v2 主控台 | goto + 快照 | PASS：ROOT+7 区域系统及真实成员数（巴蜀154、荆楚112、湖湘99、赣皖117、吴越154、羌藏11、滇黔38） |
| 4 | 研究者 | 文化流动视图 | 点击「文化流动」 | PASS：5 条真实流动（川盐济楚/万里茶道/徽商/沪汉粮运/汉冶萍），含起讫、内容、路线 |
| 5 | 怀疑审稿人 | 图谱 API 空参数/坏 uuid | /graph/evidence?object_id=x | PASS：返回空 rows，不 500/503 |

发现并当场修复的问题：
- graph API 三处列名错误（cultural_domains.system_id 不存在、hsu_type 大小写、cultural_flows.confidence 不存在）→ 修复后 200；
- 非法 uuid 参数导致 503 → 增加 uuid 校验返回空集。

## 待执行
- Persona B/C/E 深度任务（荆楚演变、湖广填四川下钻、审稿人找错）≥100 条完整任务表
- 50 次无脚本探索
- 截图证据（IAB 截图接口当前 guest 报错，待修复后补）
