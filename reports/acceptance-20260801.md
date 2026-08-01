# 验收报告（2026-08-01）

- 数据库：`data\ptcg-cn.db`（卡片 12420 行，验收动作只读；A5/A6 用副本）
- 结果：**全部 PASS**
- 生成时间：2026-08-01T15:49:37.172023+00:00

## A1 覆盖完整：白名单/能量分赛制逐卡核对 — PASS

- standard：55/55 项通过
- open：61/61 项通过

## A4 合法性引擎：卡池构建 + 妖能量二分 — PASS

- 构造用例 ≥12 组：以 pytest 套件全绿为证据（tests/test_legal_engine.py）
- standard：legal_at(2026-08-01) 构建成功，合法卡 5320 张
- open：legal_at(2026-08-01) 构建成功，合法卡 12413 张
- 妖能量二分正确：标准池 0 张 / 开放池 5 张

## A5 更新机制：提案 → apply → 新快照生效 + 冻结守卫 — PASS

- ✓ 新快照生效（effective_to=None）
- ✓ 旧快照闭合且可查询
- ✓ 冻结守卫拒绝历史快照 override 写入

## A6 回滚：脏合入 → 一键回滚 → 数据无损 — PASS

- 原 12420 行 → 脏合入后 12415 行 → 回滚（ptcg-cn-base.db）后 12420 行
- ✓ 数据无损复原

## A7 导出契约：七件套 + checksums + manifest 双轨版本 — PASS

- ✓ 8 件产物齐全: cards.jsonl, checksums.sha256, legality.json, manifest.json, ptcg-cn.db, relations.jsonl, schema.md, sets.jsonl
- ✓ checksums.sha256 逐一校验通过
- ✓ manifest 双轨版本: data=v20260801.0 schema=1.0.0

## A8 SDK 契约：open_db 与 open_jsonl 双后端一致 — PASS

- ✓ schema_version 一致可读: 1.0.0
- ✓ get_card 5 张逐一一致
- ✓ legal_at(standard) 卡池一致（5320 张）
- ✓ legal_at(open) 卡池一致（12413 张）
- ✓ effective_text 一致
