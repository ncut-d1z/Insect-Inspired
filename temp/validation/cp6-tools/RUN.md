# CP6 独立验收入口

作用域 SCOPE-0001；运行 RUN-0004；新检查点 CP-0006；有效父检查点 CP-0005。
本批范围为九个未完成 PMID 身份任务，以及 Jung2011 的一个独立 L03 Fig. 6b 适应衰减常数主张。
本目录准备阶段只做语法和冻结基线预检，不执行研究查询、canonical 导出或完整验收。
每批新文件须由主代理先保存 GitHub 并回读精确字节，再开展下一批工作。

## 不变规则与依赖

audit_cp6.py 继承 ../cp5_qa/audit_cp5.py，并继续继承原 CP4 适配器和原 audit_run.py 的全部规则。
原始文件、科学门禁和 S19 历史补证均不修改；S19 explicit_manual_reassessments 必须恰为 1。
CP4 保护比较仍为 30 条、人工不足 9 条、反证 22 条。

新增基线从精确提交 82f759ce71e7b532f03cd4ba54a1fcc77c4f4006 的 Git blobs 读取，
树为 27b8ac91e5e86fca891dc24e0f08134aaab96ebd，先解析该提交的分片 manifest，再读完整逻辑 Assessment。
69 条既有 Assessment 的完整字段及各自 JSONL 原始行字节必须完全保留，
其中人工不足 9 条、反证 23 条、保护并集 31 条；新增不同 claim_id 仍须通过全部原门禁。
Longden2010 的既有 L07 不足结论和 RUN3 新增 L03 反证均包含在这 69 条内。
CP-0001 至 CP-0005、两份 SCOPE-0001 scope 文件及 seed-manifest 共八个历史文件必须原字节不变。
基线直接来自 Git 对象，故运行环境必须保留该完整历史提交；不另复制数 MB 的基线数据。

CP5 已参数化的 export_run.py、render_html.py 直接复用，旁置 index-base.css 和原 storage.py 路径不变。
check_determinism.py 仅改变 CP6 标签、报告及输出目录，仍调用上述 CP5 导出实现。
html-smoke.mjs 仅改变检查点标签，十项交互断言保持原样。继续使用原 Chromium 和已有 Playwright 环境。
不得重跑 CP4/CP5 导入、计数、候选生成或 finalize 脚本；不得运行 storage.py 的 partition_snapshot 主入口。

## 冻结后导出（由主代理另行授权执行）

```bash
python3 -B /workspace/scratch/2e518600ca4c/cp5_qa/export_run.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project \
  --output-dir /workspace/scratch/2e518600ca4c/insect-project \
  --checkpoint CP-0006 \
  --report /workspace/scratch/2e518600ca4c/insect-project/temp/validation/cp6-export-validation.json

python3 -B /workspace/scratch/2e518600ca4c/cp5_qa/render_html.py \
  --base /workspace/scratch/2e518600ca4c/insect-project/temp \
  --output /workspace/scratch/2e518600ca4c/insect-project/ref.html \
  --checkpoint CP-0006 \
  --summary-output /workspace/scratch/2e518600ca4c/cp6_qa/html-summary.json
```

先完成所有量化、进度、报告与 invalid 候选检查点，再冻结 canonical。
候选 CP-0006 的 artifact_hashes 可为空；完整验收成功后主代理落报告和验收状态，最后计算完整 hashes 并标记 valid。
旧检查点哈希不能用当前可变数据重新生成。

## 冻结后的完整只读验收

```bash
python3 -B /workspace/scratch/2e518600ca4c/cp6_qa/audit_cp6.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project \
  --out /workspace/scratch/2e518600ca4c/cp6_qa/data-audit-final.json

python3 -B /workspace/scratch/2e518600ca4c/cp6_qa/check_determinism.py

node /workspace/scratch/2e518600ca4c/cp6_qa/html-smoke.mjs \
  /workspace/scratch/2e518600ca4c/insect-project/ref.html

python3 -B /workspace/scratch/2e518600ca4c/cp6_qa/make_receipt.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project
```

先跑完整数据审计；成功后确定性与 UI 可在内存许可下并行。所有结果留在仓库外，验收期间不写 canonical。
验收必须满足以下条件：

- 数据审计 status=passed，error_count=0，changed_inputs=[]；既有 16 项辅助 schema 警告完整保留并说明，新警告单独核查。
- explicit_manual_reassessments=1；cp4_protected_assessments_compared=30；cp4_manual_rejections_preserved=9；cp4_manual_counterevidence_preserved=22。
- cp5_assessments_compared=69；cp5_assessments_byte_preserved=69；cp5_manual_rejections_preserved=9；cp5_manual_counterevidence_preserved=23；cp5_frozen_files_byte_preserved=8。
- cp6-determinism.json 恰含 BibTeX、HTML 和五个研究视图，共七个产物，全部 byte_equal，changed_inputs=[]。
- ui-audit-final.json 和原始 html-browser-check.json 保留完整十项通过结果、零 JavaScript 错误、input_changed=false、实际 HTML SHA 与字节数，以及四张截图。
- 主代理另外保存 19 个逻辑数据集与 CP5 的 delta 保留核查；不得仅凭新记录数量判断旧数据未丢失。

每次候选刷新均更新 `validation_results.input_frozen_at_utc`，不沿用历史创建时间充当新冻结时间。
审计在完整检查前后保存精确 `canonical_input_hashes` 映射及其规范 JSON SHA-256，并锁定候选自身 SHA。
审计时间不得早于这次冻结；本轮 canonical 逻辑全集不能超出候选绑定的输入范围。
`make_receipt.py` 只在三项正式 QA 完成后执行，把上述 before/after 映射完整写入私有 QA receipt，
并再次比较当前数据和候选。最终冻结脚本必须核对候选、数据审计、receipt 和当前输入全等；
候选保存的七产物完整清单也必须与当前导出清单全等。旧 QA 不能仅凭时间晚于首次创建或七产物相同而复用。

验收通过表示本次检查点的数据和产物合格，不表示 P3–P6 研究闭包：未结任务、原游标、未取得全文、源失败及未知字段时钟继续保留。
缓存复用不计 HTTP，外部尝试和手工审阅按实际活动记账。六小时/2000 请求/200 手工/零付费预算继续适用。
正式快照最终写回和远端完整回读由主代理执行；同步未通过时停止新研究。
