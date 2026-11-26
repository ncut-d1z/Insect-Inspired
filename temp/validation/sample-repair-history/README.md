# 隔离样本检查点哈希修复历史

修复编号：`P1-SAMPLE-HASH-REPAIR-001`。

`before-p1-real-samples.json` 和 `before-sample-checkpoint.json` 是发现问题时的完整原件，按字节保留。旧脚本在已有样本目录中重跑，先将上一次 checkpoint.json 纳入哈希清单，再覆写该文件，造成旧报告对 checkpoint.json 的哈希与最终字节不一致。其余八个生成数据文件的旧哈希一致。恢复测试没有修改文件，根因为自文件历史哈希误纳入。

旧报告的“passed”仅反映当时执行的43项检查，其清单存在已披露失配，不能作为当前有效样本清单。旧文件不做静默修订。

修复采用两层清单：检查点内部只记录八个非自身产物；检查点写入后再将其最终哈希加入外层报告。新增两项最终字节校验，真实样本重新执行45项，全部通过。`after-p1-real-samples.json` 和 `after-sample-checkpoint.json` 保留修复后完整字节；`repair-audit.json` 保存前后哈希、原因、校验与持久化位置。完整事件链另保留在上级 p1-real-sample-events.jsonl。

本目录是历史审计，不进入正式论文数据库，也不作为当前正式 CP-0001。有效隔离样本位于 ../samples/SCOPE-P1-REAL-SAMPLE。
