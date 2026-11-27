# 本项目研究数据工具：CP7 可移植迁移

这些脚本只服务于本仓库的文献数据和证据审计，不构成新的通用检索系统。RUN-0005 沿用 SCOPE-0001；科学范围、种子、截止时间、强类型规则、量化门禁和尺度门禁不因工具迁移改变。脚本生成的规范数据仍须按主 README 的检查点和即时同步规则提交。

## 来源与迁移范围

- `storage.py`、`export_run.py`、`render_html.py`、`index-base.css` 和 `audit_run.py` 来源于已发布的 `temp/validation/cp5-tools/`。旧文件保留不动。
- `gates.py` 来源于 P1/P2 已使用的项目门禁脚本；迁移前 SHA-256 为 `2c54ec78e1711b30e25164f5432c03e819bc1f4d99aed6d0939ae3555406a0fe`。仅改为从本仓库读取 schema，并修正文档中的路径说明；科学判断函数不变。
- 默认根路径和相邻模块引用改为相对 `scripts/`。`export_run.py` 的 `graph-schema-patch.json` 辅助文件改写到 `--report` 所在目录，避免独立验证时修改脚本目录。
- `render_html.py` 继续使用相邻 `index-base.css`，生成的结构和交互逻辑不变。
- 通用 `audit_run.py` 保留实体、外键、来源、查询、工单、量化、尺度、HTML、导出与分片规则；历史人工判断改为由适配器显式提供不可变已发布基准。没有适配器时，完整审计拒绝跳过该基准。

## CP7 历史科学保护

`audit_cp7.py` 的基准是完整已验收 CP6：

| 项目 | 固定值 |
| --- | --- |
| commit | `a1303b6b6c38692b4f57da5cfb342289c6dc17e5` |
| tree | `32a732212b9151c2ee1ee75a91081ffcbca60d9b` |
| 70 条 Assessment 逻辑 SHA-256 | `cd50a77228722297168c798ed65b599937433aa1eaf1e743c594c060a16ddf8a` |
| CP6 分片清单 SHA-256 | `6b75621b4b7db90a36a3858e315df3ad46d77d262cf4f63041fccabb82fedab8` |

审计逐记录、逐原始 JSONL 行保留全部 70 条既有 Assessment，其中包括 9 条不足主张和 23 条反证；还逐字核验 CP1–CP6、两份作用域快照、种子清单、schema、已发布 S19 历史证书和 CP6 数据审计报告。新主张通过全部通用门禁，不获得新的豁免。

此前 CP4 审计依赖原运行目录中的 PDF/PNG。当前适配器不假定这些私有文件仍可用，也不声称重新阅读了它们。S19 只继承已发布证书对应的精确 CP6 记录，并核对证书、规范记录及已通过 CP6 审计的固定证据。报告明确写明 `historical_primary_files_reread=false`；这不是新的原文核验。

若以后需要变更已有科学记录或升级其中的到期 unknown 字段，必须先记录真实证据／规范要求、完整 before/after 和对应验证方案。当前 CP7 适配器故意拒绝任何未明确处理的既有 Assessment 字节变化，不能通过删除保护检查来完成迁移。

## 入口

从仓库根执行；示例 QA 路径位于仓库外。运行时使用 Python 3.10+、Git 和 `jsonschema`。`-B` 防止产生 `__pycache__`。

```bash
python -B scripts/export_run.py --repo . --output-dir . --checkpoint CP-0007 --report ../cp7-qa/export-validation.json
python -B scripts/render_html.py --base temp --output ref.html --checkpoint CP-0007 --summary-output ../cp7-qa/html-summary.json
python -B scripts/audit_cp7.py --repo . --out ../cp7-qa/data-audit-final.json
```

前两条命令会生成规范交付物；第三条只读仓库，只把审计报告写到 `--out`。审计要求已经存在 CP7 候选，不能将 `--help` 或脚本语法检查当成数据验收成功。

候选生成器可导入 `audit_cp7.required_input_names(repo)`、`input_snapshot(repo, names)` 和 `input_digest(snapshot)`。将对应映射与真实冻结时间写入候选的 `validation_results.canonical_input_hashes`、`canonical_input_digest_sha256` 和 `input_frozen_at_utc`。审计绑定候选自身哈希，并在前后核对完整输入集合与字节；新出现或变化的输入使审计失败。必需输入包括完整逻辑数据／分片、RUN5 已保存的回执与 review、脚本和七项导出。RUN5 记录另以完整冻结记录、不可变字段投影和 SHA-256 绑定；授权、预算、起始时间／基线、截止时间及来源／缓存／人工计数不可变化，只有明列的最终化状态／时间／后置同步说明可以变化。审计期间 RUN5 文件仍必须逐字稳定。

独立确定性验证应将同样的七项输出生成到另一个仓库外目录，逐字比较。临时报告不应写入 `scripts/`；通过后由主任务显式归档。HTML 的十项真实交互检查仍须另行执行；本迁移本身不声称 UI 验证已完成。

## CP7 候选、QA 与最终化

先按已发布复核回执完成规范数据集成并生成七项产物，再运行以下步骤。默认不加 `--apply` 的候选／最终化命令只做只读检查和输出计划，不写规范文件。

```bash
python -B scripts/checkpoint_cp7.py prepare --repo . --apply --plan-out ../cp7-qa/candidate-plan.json
python -B scripts/audit_cp7.py --repo . --out ../cp7-qa/data-audit-final.json
python -B scripts/check_determinism.py --repo . --out-dir ../cp7-qa/determinism --report ../cp7-qa/cp7-determinism.json
node scripts/html-smoke.mjs --html ref.html --out-dir ../cp7-qa/ui --checkpoint CP-0007
python -B scripts/checkpoint_cp7.py finalize --repo . --qa-dir ../cp7-qa --apply --plan-out ../cp7-qa/finalization-plan.json
```

`html-smoke.mjs` 使用已安装的 Playwright；若需指定已安装浏览器，可增加 `--executable-path`。它沿用既有十项检查，报告和四张截图仅写到新建的仓库外目录。语法检查和 `--help` 不是这十项检查的运行结果。

`checkpoint_cp7.py` 从完整逻辑数据重算数量及最新任务游标，并逐条核验集成报告的完整 before/after；所有旧事件前缀、原参考文本和科学记录保留。新增 Assessment 必须与已经提交的 RUN5 review/candidate 文件内完整对象一致。`prepare` 只能生成 `invalid` 候选。`finalize` 只接受绑定该候选／同一输入的真实审计、确定性和 UI 成功凭据，并拒绝未审阅的新警告。

最终化会归档实际 QA 报告、截图和实际被审计的 invalid 候选，使后续能够核验审计引用的候选哈希。最后的有效 CP7 对仓库当前全部跟踪／待跟踪文件形成精确哈希集合，只排除 CP7 自身与 `.git`；发现没有进入计划的忽略文件或符号链接就停止。最终化不提交、不推送、不生成远端同步成功结论；这些仍须由调用方完成并保存独立后置回执。

## 数据与时间规则

- 始终通过 `read_logical(name, base=repo / 'temp')` 读取分片数据，不能只读取根 JSONL 第一片。
- `replace_logical()` 能维护已有分片；一个原先未分片的数据集首次超过 4 MiB 时，调用者仍须按主 README 另行分片及对账。
- 不重置既有 unknown 起始时间或 deadline。恢复、写入与冻结时使用真实当前时间检查 24 小时升级；升级需要规范字段和原工单追加事件同时完成。
- 历史 16 项 `unregistered_auxiliary_schema` 警告保持披露；它们不等于没有进行通用外键／来源检查，也不应被静默清零。
- 完整数据审计、确定性验证、UI 验证、最终哈希和独立远端回读各自证明不同事项；任何一个准备步骤都不能替代后续验收。
