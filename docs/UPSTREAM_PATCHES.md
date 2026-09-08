# UPSTREAM PATCHES — 对 LightRAG 原生文件的修改登记

> 规则：任何对 `upstream/LightRAG` 中**原生文件**的修改必须在此登记（文件、位置、原因、内容摘要、revert 方法）。
> 新增文件（`yangtze/ extensions/ adapters/ plugins/` 等）不需要登记，但重大新增在 CHANGELOG_YCKI.md 记录。
> 目标：LightRAG upstream 更新时可低成本 rebase/merge。

## 登记表

| # | 日期 | 文件 | 修改位置 | 原因 | 摘要 | Revert 方式 |
| --- | --- | --- | --- | --- | --- | --- |
| — | — | （暂无修改——T00/T01 阶段保持原版） | | | | |

## 修改前检查清单（每次修改原生文件前过一遍）

1. 能否用新增文件 + 配置/注入实现？（优先）
2. 修改是否影响 upstream merge？（影响面写明）
3. 是否已在 git 有独立 commit（便于 revert）？
4. 是否已在本文件登记？
