# CP8 交付与研究进度

## 交付状态

CP8 已成为有效数据检查点，规范提交为 `2e749d4994bd3b8c66fcde59950779adc5d66085`，树为 `6428de0a5ac1e7c288928462eb9c768d08dfff4c`。研究快照冻结于 **2026-11-27 15:28:22 UTC+8**；仅用 GitHub 数据的独立恢复验证于 **2026-11-27 15:49:04 UTC+8** 通过。

本目录包含完整 CP8 增量包；本运输分支同时包含 `temp/sync/CP-0007/` 的完整前置包。CP8 的 **54/54 片、28,210,811 字节**和 CP7 的 **60/60 片、31,221,121 字节**均已逐片核验并成功连续恢复。验证采用全新 bare 仓库，没有借用本地研究库、旧审计库、alternates、浅克隆或 promisor 对象。详见 [独立远端恢复证明](verification.json)。

**远端数据包完整可恢复；main 尚未合入 CP8。** 验证时 main 为 `bb7726c2ef334df0d7069165156b1cbc2c4e2fd8`，远端 `research/p3-p6-cp7` 仍为 `0ee3b7de167a70933bc9884b9217142c2661c374`，远端 `research/p3-p6-cp8` 尚不存在。普通 git push 缺少认证，自动审批又拒绝安装具有仓库写权限的持续 Actions 导入工作流，因此采用用户已授权的数据包方式；没有安装或执行该工作流。

[README.md](README.md) 提供完整 **PowerShell 7+** 命令：拉取运输分支、解包并校验 CP7→CP8、普通推送研究分支、快进合并 main、推送、按精确条件删除本轮临时分支，以及可选清理提取目录。Windows/PowerShell 未实际执行；命令已经静态审查，等价 Linux/Git 恢复已真实执行并通过。

## CP6、CP7、CP8 完整性

| 检查点 | 完整快照文件 | 总字节数 | 核验结论 |
| --- | ---: | ---: | --- |
| CP6 | 1,256 | 881,966,656 | 本轮从远端独立取回核验通过 |
| CP7 | 1,317 | 1,045,568,594 | 60 片及整包恢复、全部文件通过 |
| CP8 | 1,361 | 1,150,803,660 | 54 片及整包恢复、全部文件通过 |

每个快照均按检查点 artifact 清单及检查点自身校验；CP7、CP8 各 7 个逻辑数据集、120 个物理分片的 SHA-256、字节数、记录数和拼接逻辑哈希全部匹配。Git 历史继承及 `git fsck --full --strict --no-reflogs` 通过。CP6 的本轮完整验证记录在 [CP7 证明的 previous_checkpoint_verification](../CP-0007/verification.json) 中；CP6 检查点原字节也在 CP7、CP8 中保持一致。

## 本轮 P3–P6 更新

| 项目 | CP7 | CP8 |
| --- | ---: | ---: |
| Work | 5,098 | 5,098 |
| 已解析参考出现项 | 34,184 | 34,187 |
| 未解析参考出现项 | 124,360 | 124,357 |
| 已核正文科学语境的引用边 | 20 | 24 |
| Assessment | 71 | 72 |
| 合格主张 | 62 | 63 |
| 不足主张 | 9 | 9 |
| 反证主张 | 23 | 23 |
| L08 主题 Work | 4 | 5 |
| 未结任务 | 130,727 | 130,753 |

- **P3/P4：**解析 3 个旧参考出现项，核验 Strübbe2015→早期匹配滤波前作及 Egelhaaf2023→Strübbe2015/Kern2012 的 4 条既有引用边语境；补充 1 条中文摘要。Müller1966 身份冲突、完整参考表和跨源施引覆盖继续保留待核。详见 [P3 候选](in-progress/temp/reports/RUN-0006-seed-reference-candidate.json) 与 [P4 候选](in-progress/temp/reports/RUN-0006-citation-candidate.json)。
- **P5：**核对 Lecoeur2019 全部 4 位作者，补充 5 条发表时机构关联；新增 1 个下属机构、3 条致谢级 grant 记录和 4 条明确受助作者关系。没有把发表时署名当作当前任职，也没有把致谢升级为官方项目登记。详见 [P5 候选](in-progress/temp/reports/RUN-0006-Lecoeur2019-P5-candidate.json)。
- **P6：**新增 `AS-RUN06-Lecoeur2019-L08-flight-speed-statistics`，限定为同一受控走廊六种布局的飞行速度条件统计，337 次飞行。N 是飞行次数，SD 是飞行均值之间的离散程度；没有跨条件去重个体表或原始轨迹再分析。m/s 来自外部相机测量，不证明动物或纯视觉算法恢复绝对尺度。照度、重建噪声、离群与遮挡比例保留待查。详见 [Assessment 候选](in-progress/temp/reports/RUN-0006-Lecoeur2019-assessment-candidate.json)。

本轮实际记录 **10 次外部科研调用、3 次合法缓存复用、18 个人工复核单位**。关闭 4 个旧 unknown 字段工单，同时将新发现的缺口显式建为任务，因此未结任务净增 26。全部新来源回执、审阅候选和脚本按小批及时提交；规范数据与导出通过完整数据包同步。

## 验收与阶段评估

数据审计 **0 错误、16 项既有辅助表 schema 警告**；这些辅助表仍接受通用外键和来源检查。七项导出独立重建后逐字一致，真实 Chromium 的十项 UI 检查全部通过。旧 71 条 Assessment、9 条不足判定、23 条反证记录和 14 个历史冻结文件原字节保持。

- [完整阶段报告](in-progress/temp/reports/P3-P6-CP0008.md)
- [数据审计](in-progress/temp/validation/cp8-data-audit.json)
- [七项导出确定性](in-progress/temp/validation/cp8-determinism.json)
- [十项网页检查](in-progress/temp/validation/cp8-ui-validation.json)
- [历史数据保留](in-progress/temp/validation/cp8-delta-preservation.json)
- [完整 QA 凭据](in-progress/temp/validation/cp8-qa/qa-final-receipt.json)

**P3–P6 仍为部分完成，递归闭包未成立；P7 最终研究验收未启动，P8 未触发。** 全库仍有 124,357 个未解析参考出现项、130,753 个未结任务和 65,049 个开放 unknown 工单。unknown 到期统计以 15:28:22 的冻结时点为准，恢复研究时须按原始 deadline 重新计算并先处理到期项。后续重点是剩余参考与施引分页、缺失全文、项目官方资料、更多可定位科学语境及 L01–L09 条件证据，而不是把本次检查点通过解释为研究完成。
