# CP5 私有导出与审计入口

作用域 `SCOPE-0001`，运行 `RUN-0003`，新检查点 `CP-0005`，有效父检查点 `CP-0004`。
这里的脚本不执行研究查询，不运行 CP4 导入器。准备阶段没有执行以下导出或完整验收命令。

## 导出

先完成并冻结本批规范数据。以下两条只有在显式指定 canonical 输出路径时才写入正式导出：

```bash
python3 /workspace/scratch/2e518600ca4c/cp5_qa/export_run.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project \
  --output-dir /workspace/scratch/2e518600ca4c/insect-project \
  --checkpoint CP-0005 \
  --report /workspace/scratch/2e518600ca4c/insect-project/temp/validation/cp5-export-validation.json

python3 /workspace/scratch/2e518600ca4c/cp5_qa/render_html.py \
  --base /workspace/scratch/2e518600ca4c/insect-project/temp \
  --output /workspace/scratch/2e518600ca4c/insect-project/ref.html \
  --checkpoint CP-0005 \
  --summary-output /workspace/scratch/2e518600ca4c/cp5_qa/html-summary.json
```

export_run 的默认输出为本目录 export-preview，图 schema 兼容说明只写本目录；规范 schema 不变。
render_html 默认输出为本目录 preview.html。两者均按 manifest 读取完整逻辑 JSONL。

## 冻结后的完整验收

```bash
python3 /workspace/scratch/2e518600ca4c/cp5_qa/audit_cp5.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project \
  --out /workspace/scratch/2e518600ca4c/cp5_qa/data-audit-final.json

python3 /workspace/scratch/2e518600ca4c/cp5_qa/check_determinism.py

node /workspace/scratch/2e518600ca4c/cp5_qa/html-smoke.mjs \
  /workspace/scratch/2e518600ca4c/insect-project/ref.html
```

完整审计、确定性和 UI 验收输出均在仓库外。验收期间保持 canonical 冻结。
audit_cp5 在原始 audit_run 全部规则和原 CP4 严格适配器之上增加 CP4 冻结基线；不改变 S19 历史补证。
检查点候选可以在完整审计前保持 invalid，counts/cursors/导出标识须完整；最后报告落盘后再计算全部 artifact hashes 及检查点自身 SHA。

要求：数据审计 status=passed、error_count=0、changed_inputs=[]；S19 explicit_manual_reassessments=1；
cp4_protected_assessments_compared=30、cp4_manual_rejections_preserved=9、cp4_manual_counterevidence_preserved=22。
确定性报告 cp5-determinism.json 必须恰含七个产物且全 byte_equal、changed_inputs=[]。
UI 报告 ui-audit-final.json（同时保存原始 html-browser-check.json）必须十项全通过、passed=true、input_changed=false；
报告保存实际 HTML SHA、字节数和四张截图。既有 16 项辅助 schema 警告须明示；新增警告单独核查。

## 冻结基线的规则

cp4-assessments.jsonl 是从 bb7726c2ef334df0d7069165156b1cbc2c4e2fd8 的分片 manifest 顺序提取的 68 条完整记录；
SHA-256 为 80429e385bce83bbd7e5a42f2aac417b8afb39253b731b3eb4098b3f401eb6df。
cp4-assessment-baseline.json 固定其 commit/tree/blob、字节数和目标集合。
全部 9 条 active insufficient_evidence 与 22 条反证形成 30 条受保护记录，是人工否决的保守全集。
本批不得删除、停用或改写其主张身份；不足结论与拒收代码须保留；反证标志、类型、证据定位、Upload/Version 来源须保留。
这些是 CP5 新增保护，无新的升级例外。若需要修改其中已有主张，须先独立审查实际补证，当前脚本会拒绝静默升级。
新增且不同 claim_id 的主张仍由全部原科学门禁评估；不得通过改 ID 隐藏旧否决。

## 复用依赖及本轮不执行的脚本

S19 原适配器、独立证明及原文证据仍位于 cp4_qa 和原私有运行目录，保持字节不变。
audit_cp5 直接继承 ../cp4_qa/audit_cp4.py；它继续加载 /workspace/scratch/9d487ee78414/p3p6_work/audit_run.py。
导出、HTML 和完整审计依赖该原运行目录的 storage.py；每次读取均显式传入本轮 repo/temp。
UI 继续使用原 chromium 包和现有 playwright 环境。
preparation-manifest.json 记录复用文件原始/副本 SHA 和依赖路径；preflight.json 只记录语法与隔离基线检查，不是完整 CP5 验收。

不得直接重跑 cp4_work/counts.py、finish_data.py、import_*、repair_scientific.py、incremental.py 主入口，
或 CP4 finalize/package 脚本；它们含 CP4 写入、旧统计和追加行为。
不得运行 storage.py 的 partition_snapshot 主入口覆盖已分片 manifest。
本目录没有创建 bundle、远端分支、commit、tree 或推送。
