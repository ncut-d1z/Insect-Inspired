# CP6 候选构建和最终冻结

本批准备文件不执行 canonical 写入、研究、GitHub 写入或完整 QA。
`checkpoint_cp6.py` 与 `finalize_cp6.py` 均默认只预演；只有显式 `--apply` 才写入下列六路径：

- `temp/snapshots/checkpoints/CP-0006.json`
- `temp/progress.md`
- `temp/reports/P3-P6-CP0006.md`
- `temp/change-log.md`
- `README.md`（只替换唯一的执行状态指针段）
- `temp/runs/RUN-0004.json`

脚本不写 logical datasets、导出或 schema，不修改旧检查点。所有 CP1–CP5、两份 scope 和 seed-manifest 均校验精确 CP5 Git blob 原字节；69 条旧 Assessment 逐记录及原始 JSONL 行保留。

## 输入契约

精确基线：CP5 commit `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006`，tree `27b8ac91e5e86fca891dc24e0f08134aaab96ebd`。
所有本轮 canonical JSONL 均使用原 storage.read_logical、显式当前 repo/temp，并校验完整分片 manifest。基线由该提交的 manifest 和全部 Git blobs 读取，不能将首分片视为全集。

集成报告必须先存在于 `temp/reports/RUN-0004-integration.json`，包含 root 已约定的全部统计键、`counts_before`、`counts_after`、`events` 及 `changed_records`。
后者每项有 `dataset`（不含 .jsonl）、`id`、完整深拷贝 `before` / `after` 和准确 `changed_field_names`。
允许本批修改的既有实体集为 works、versions、authors、reference-occurrences、source-list-coverage；每项实际修改必须与 changed_records 一一完全相等，所有旧行顺序保留。任务、查询、边、路径、原 Assessment、人工活动和观测记录保持旧事件前缀；其余19集中的旧记录不改。

新科学记录必须与 `temp/reports/RUN-0004-Jung2011-adaptation-review.json` 中的 Assessment 完全一致，且是唯一新增科学记录。图组总样本、四项均值、单位、范式及限制都从该报告与 canonical 对应记录生成，不手填上轮 Longden 内容或固定数量。

所有新查询必须用 `Q-RUN04-` 前缀并属于 CP6，每条新查询须有唯一 source-observation，显式记录 `external_request_performed`。缓存 flag 为 true 的查询不能计作 HTTP。人工活动按 run_id=RUN-0004 计数；与 RUN4 账本及 integration 声明逐项核对。

项目来源覆盖从完整列表、全部既有 CiterIdentity 任务和 CP5 已验证分母对账得到；`epmc_core_success` 与 `identity_via_pubmed` 区分 provider core 和跨来源补证。direct_readable_metadata 与 indexed_official_record 的原始区别保留在任务/来源字段，不因统一身份成功状态而丢失。没有固化“成功4/9”等中间值。

## 执行顺序

1. root 完成原始回执同步、原子 canonical 集成、RUN4 真账本、集成报告；执行既有 CP5 导出 CLI，显式 `--checkpoint CP-0006`，得到 BibTeX、HTML、五研究视图以及 `temp/validation/cp6-export-validation.json`。
2. root 执行下列候选构建；默认预演与 `--apply` 都会私有输出 `final-counts.json`、`final-coverage.json`、`cp6-delta-preservation.json`、`checkpoint-generation.json`。只有 `--apply` 才写上述六 canonical 路径。

```bash
python3 -B /workspace/scratch/2e518600ca4c/cp6_work/checkpoint_cp6.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project --apply
```

3. 所有源回执、人工决定和脚本须已经发布并精确回读。canonical integration → exports → candidate → QA → finalize 属于同一冻结检查点交付批，期间只整合和验证、不新增研究。root 将私有 `cp6-delta-preservation.json` 原字节归档至 `temp/validation/cp6-delta-preservation.json`；正式冻结后按 cp6_qa/RUN.md 运行完整数据审计、七产物确定性和十项 UI，然后执行 `cp6_qa/make_receipt.py` 生成带精确输入绑定的原始 QA receipt。此步骤不宣称临时 invalid 候选已经远端发布。
4. QA 完成后，root 将以下原字节归档。finalize 不替代这一步，也不会创建这些 canonical 文件：

| 私有 QA 文件 | canonical 目标 |
| --- | --- |
| data-audit-final.json | temp/validation/cp6-data-audit.json |
| cp6-determinism.json | temp/validation/cp6-determinism.json |
| ui-audit-final.json | temp/validation/cp6-ui-validation.json |
| qa-final-receipt.json、其中列明的八个原始文件（四 JSON、四截图） | temp/validation/cp6-qa/ 下保留原文件名 |

5. 完成原始证据归档后运行 finalize：

```bash
python3 -B /workspace/scratch/2e518600ca4c/cp6_work/finalize_cp6.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project \
  --qa /workspace/scratch/2e518600ca4c/cp6_qa --apply
```

finalize 重算 canonical 事实并核对冻结候选的计数、任务游标、query 高水位和未结队列，验证候选输入哈希；要求全部 QA 对应当前 CP6 的精确七产物，旧科学保护全部通过、S19 例外恰1、warnings 与原 CP5 完整告警集合相同。任何新增或丢失警告都要求先独立核查，不能静默过滤。

每次候选刷新都更新 `input_frozen_at_utc` 和 `canonical_input_digest_sha256`；`created_at_utc` 仅保留首次创建历史。
完整审计保存候选自身 SHA、审计前后精确输入映射与摘要。finalize 必须核对当前候选 SHA 与审计时一致，
候选 / 当前 / audit before / audit after 输入映射完全相等，QA receipt 完整保留该绑定，且审计不早于本次冻结。
同时强制 `candidate.coverage.derived_views.artifacts == state['exports']`，不能以另一轮同内容导出或旧时间戳替代本次正式审计。

最终哈希按六个路径的预定最终字节计算，覆盖仓库所有文件，排除 Git 内部文件和 CP6 本身，拒绝意外符号链接。CP6 最后写入并标 valid，再全文件复核；旧检查点始终不动。结果只写私有 `final-checkpoint-result.json`，提供 CP6 自身 SHA。

## 同步与闭包

valid 仅代表本检查点已经通过数据与交付验收。P3–P6 继续 partial、研究闭包 false、P7 未启动、P8 未触发。
最终主机合并/推送权限不由脚本推断。本检查点中的同步说明固定记录创建时刻，并预留后置同步证明：

https://github.com/ncut-d1z/Insect-Inspired/blob/sync/cp6-checkpoint-import/temp/sync/CP-0006/verification.json

该回执后置保存，不再改写已冻结 CP6。同步未被精确远端回读证明前，不开启新的研究批次。
完成本冻结交付批后立即 commit、打包并同步，独立远端完整验收通过前不进入下一研究批。
用户可见 Markdown 的当前日期、进度时间和 change-log 日期采用 Asia/Singapore 并标记 UTC+8；机器 `_utc` 字段、查询与冻结时间继续保留 UTC。
