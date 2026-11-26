# CP-0005 单批增量传输说明

本目录位于 `sync/cp5-checkpoint-import` 临时分支，保存已经审计的同仓库 Git 增量。正式目标为 `research/p3-p6-cp5`。本目录、上传提交与一次性 workflow 不构成新的研究结论，也不改变 CP5 原提交。

## 固定范围与预期结果

| 项目 | 固定值 |
| --- | --- |
| 仓库 | `ncut-d1z/Insect-Inspired` |
| 临时上传分支 | `sync/cp5-checkpoint-import`，从 `main` 的 CP4 提交创建 |
| 上传分支起点 | `bb7726c2ef334df0d7069165156b1cbc2c4e2fd8` |
| 唯一写入目标 | `refs/heads/research/p3-p6-cp5` |
| 必须从真实远端取得的基线 | `95a0a218667333967f4a6c18f8b8b71df8b464e0` |
| 原 CP5 提交 | `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006` |
| 原 CP5 tree | `27b8ac91e5e86fca891dc24e0f08134aaab96ebd` |
| CP5 Git 父提交 | 必须恰为上述 95a 基线，且只有这一个父提交 |
| 检查点父关系 | `CP-0004` |
| bundle 文件 | `recovery.bundle` |
| bundle 字节数 | `19638061` |
| bundle SHA-256 | `29eefe39d95fecd6cbcb909a8cc8242fed6bb168bd42452d3232d881a386738e` |
| CP5 检查点 SHA-256 | `ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270` |
| CP5 文件数／产物哈希数 | `1188`／`1187` |
| 分片逻辑数据集数 | `7` |
| 分片 manifest SHA-256 | `97e1286420002f40bcf599c350b3c96081eb7dc2dff35c11179b7c7d1e099bf6` |

## 包内内容与本批增量

CP5 恢复的是项目的完整工作树：既有规范实体、发现与引用关系、证据评价、任务及检索记录、回执、审计报告、检查点和校验证明均保留。`temp/partitions/manifest.json` 指定的全部逻辑分片也是完整工作树的一部分，不能只读取各数据集的首个 JSONL 文件。

7 项研究导出分别是：根目录 `ref.bib`、`ref.html`，以及 `temp/exports/` 内的 `evidence_matrix.csv`、`research_entities.json`、`citation_graph.json`、`research_paths.json`、`research_implications.csv`。规范 JSONL 则保存 Work、Version、署名限定 Person、机构与项目、原始参考出现项、引用边和 Assessment；`temp/tasks.jsonl`、`temp/queries.jsonl`、`temp/query-results/` 及审计目录保存继续执行所需的状态、来源和证明。

本批审计后的增量包括：

- 补全 **5 个已有 Work** 的可证实元数据，保留原 Work 身份。
- 建立 **20 个限定于本篇署名的 Person 记录**；跨 Work 同名身份仍需单独消歧。
- 解析 **7 条已保存参考记录**，形成 **7 条来源支持的引用边**；正文引用语境仍按实际核验状态保留。
- 加入 **1 条 L03 潜伏期主张**及其原始证据定位、复核记录与边界说明。

包内不含原始论文 PDF、受限正文或认证文件。原文哈希、合法来源、页码与证据定位可以出现在审计记录中。P3–P6 的其余未完成任务继续保留，本次增量不是研究全部完成的声明。

完整工作树由**远端 95a 基线与本增量共同重建**。`recovery.bundle` 只保存 95a 之后恢复 CP5 所需的 Git 对象，不重复封装整个历史，也不是一个可独立解压的论文压缩包。

## 增量的依赖

`recovery.bundle` 不是可独立 clone 的完整历史包。它只有一个前置提交：`95a0a218667333967f4a6c18f8b8b71df8b464e0`。这个基线已经包含 CP4 后逐批同步的回执和脚本；CP4 原提交不能替代它。

导入任务先检查目标远端分支只处于 95a 或精确 CP5，然后在一个全新 bare 仓库中，从固定 GitHub 仓库读取精确 95a 基线。基线对象到位之后，才执行 `git bundle verify` 并导入 CP5。原始 commit、tree、父链保持不变。

## 本目录的三个输入文件

- `recovery.bundle`：原 Git 增量对象流；本模板不预设分块。
- `manifest.json`：固定 commit/tree、唯一 prerequisite、长度及各 SHA-256。
- `README.md`：本说明；其 SHA-256 也写入 manifest。

传输目录固定为 `temp/sync/CP-0005/`。一次性 workflow 固定为 `.github/workflows/import-cp5.yml`，最后提交，以该临时分支的 `push` 触发。

## 手动下载、解包与恢复

以下步骤只读取 GitHub，并在全新目录恢复本地文件，不需要 GitHub CLI 授权或远端写入。需要 Git、Python 3 和 Bash；各段命令在同一终端依次执行。**不能直接 `git clone recovery.bundle`**：这个增量包依赖精确 95a prerequisite。

### 1. 保存三个原始文件并校验

在计划保存恢复资料的位置创建独立目录：

```bash
set -euo pipefail
cp5_recovery_root="$(mktemp -d "$PWD/insect-cp5-recovery.XXXXXX")"
cp5_package_dir="$cp5_recovery_root/package"
mkdir "$cp5_package_dir"
printf '请将 README.md、manifest.json、recovery.bundle 下载到：%s\n' "$cp5_package_dir"
```

从本临时分支的 `temp/sync/CP-0005/` 分别下载这三个文件到打印出的目录；保存 Raw/Download 的原始字节，不要另存 GitHub 文件展示网页。文件齐备后执行：

```bash
python3 - "$cp5_package_dir" <<'PYCHECK'
from pathlib import Path
import hashlib, json, sys
p = Path(sys.argv[1])
manifest_raw = (p / 'manifest.json').read_bytes()
m = json.loads(manifest_raw)
assert m['repository'] == 'ncut-d1z/Insect-Inspired'
assert m['target_ref'] == 'refs/heads/research/p3-p6-cp5'
assert m['expected_baseline_commit'] == m['expected_parent_commit'] == '95a0a218667333967f4a6c18f8b8b71df8b464e0'
assert m['bundle_prerequisites'] == ['95a0a218667333967f4a6c18f8b8b71df8b464e0']
assert m['expected_commit'] == '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006' and m['expected_tree'] == '27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
assert m['bundle_name'] == 'recovery.bundle' and m['bundle_kind'] == 'incremental'
bundle = (p / 'recovery.bundle').read_bytes()
assert type(m['bundle_bytes']) is int
assert len(bundle) == m['bundle_bytes'] == int('19638061')
assert hashlib.sha256(bundle).hexdigest() == m['bundle_sha256'] == '29eefe39d95fecd6cbcb909a8cc8242fed6bb168bd42452d3232d881a386738e'
assert hashlib.sha256((p / 'README.md').read_bytes()).hexdigest() == m['readme_sha256']
assert m['checkpoint_sha256'] == 'ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270'
print('输入文件校验通过；manifest SHA-256:', hashlib.sha256(manifest_raw).hexdigest())
PYCHECK
```

打印出的 manifest SHA-256 应与固定 `.github/workflows/import-cp5.yml` 中的清单哈希一致。该最终清单哈希不写回本 README，以避免 README 与 manifest 之间形成哈希循环。校验失败时停止，不继续导入。

### 2. 从真实仓库取得基线，再导入本地新分支

```bash
set -euo pipefail
cp5_repo_url='https://github.com/ncut-d1z/Insect-Inspired.git'
cp5_expected_base='95a0a218667333967f4a6c18f8b8b71df8b464e0'
cp5_expected_commit='82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
cp5_expected_tree='27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
cp5_restore_dir="$cp5_recovery_root/restored-cp5"
test ! -e "$cp5_restore_dir"
git clone -c core.autocrlf=false -c core.eol=lf -c core.hooksPath=/dev/null --no-checkout --no-tags "$cp5_repo_url" "$cp5_restore_dir"
git -C "$cp5_restore_dir" fetch --no-tags origin "$cp5_expected_base"
test "$(git -C "$cp5_restore_dir" rev-parse 'FETCH_HEAD^{commit}')" = "$cp5_expected_base"
test ! -s "$cp5_restore_dir/.git/shallow"
test ! -s "$cp5_restore_dir/.git/objects/info/alternates"
git -C "$cp5_restore_dir" bundle verify "$cp5_package_dir/recovery.bundle"
test "$(git -C "$cp5_restore_dir" bundle list-heads "$cp5_package_dir/recovery.bundle")" = "$cp5_expected_commit refs/heads/research/p3-p6-cp5"
test -z "$(git -C "$cp5_restore_dir" for-each-ref --format='%(refname)' refs/heads/restored-cp5)"
git -C "$cp5_restore_dir" fetch --no-tags "$cp5_package_dir/recovery.bundle" 'refs/heads/research/p3-p6-cp5:refs/heads/restored-cp5'
test "$(git -C "$cp5_restore_dir" rev-parse 'refs/heads/restored-cp5^{commit}')" = "$cp5_expected_commit"
test "$(git -C "$cp5_restore_dir" show -s --format=%T restored-cp5)" = "$cp5_expected_tree"
test "$(git -C "$cp5_restore_dir" show -s --format=%P restored-cp5)" = "$cp5_expected_base"
git -C "$cp5_restore_dir" checkout restored-cp5
git -C "$cp5_restore_dir" fsck --full --strict
test -z "$(git -C "$cp5_restore_dir" status --porcelain=v1 --untracked-files=all)"
python3 - "$cp5_restore_dir" <<'PYCP'
from pathlib import Path
import hashlib, json, sys
p = Path(sys.argv[1]) / 'temp/snapshots/checkpoints/CP-0005.json'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270'
cp = json.loads(raw)
assert cp['checkpoint_id'] == 'CP-0005' and cp['scope_id'] == 'SCOPE-0001'
assert cp['status'] == 'valid' and cp['parent_checkpoint_id'] == 'CP-0004'
print('本地恢复与检查点哈希校验通过：', p.parent.parent.parent.parent)
PYCP
```

这些命令使用新建的 clone 和新的本地 `restored-cp5` 分支，不覆盖用户现有目录或分支，也不运行项目脚本。恢复后的文件可以从 `ref.html`、`ref.bib` 和 `temp/` 查看。这里的本地恢复通过，仅证明本次本地恢复；仓库同步的正式验收仍须满足下一节的独立远端完整回读要求。

## 导入与验收

1. 从触发事件的固定上传 commit 读取三个输入文件；核验 manifest、README、bundle 长度和哈希，以及唯一 bundle head/prerequisite。
2. 从真实远端取得精确 95a，验证 bundle，确认 CP5 的 commit、tree 和唯一父提交。
3. 推送前先核验 CP5 检查点自身哈希、其完整 artifact_hashes、全部文件，以及所有逻辑数据集的完整分片与合并哈希。
4. 仅使用普通、非 force 的 Git push 更新固定研究分支。临时校验钩子核对本次 Git 实际通告的远端 SHA；不存在、意外回退或其他提交均拒绝更新。若远端已经是精确 CP5，则跳过写入。
5. 再创建一个没有本地对象、bundle 种子、alternates、浅克隆边界或 partial filter 的 bare 仓库，从 GitHub 完整回读目标分支，重复 commit/tree/父链、全文件、检查点与逻辑分片核验。

任务使用标准 `ubuntu-24.04` runner，只有 job 范围的 `contents: write`。`GITHUB_TOKEN` 只存在于临时进程配置；不写入 URL、文件或说明。任务不检出或运行项目代码，不写 main、tag、其他分支，不提供任意 URL/API 转发或通用远程执行能力。

## 完成状态

本说明已按冻结的 CP-0005 提交和实际增量包填写；它本身不是最终同步完成证明。上传文件成功或 Actions 开始运行，都不代表同步完成。只有固定目标远端提交与独立完整回读验收全部通过，root 才能将本批标为已同步并启动下一批研究。

最终独立远端回读通过后，将另行添加 [verification.json](verification.json) 记录验收证据；文件尚未出现时，不能据上传成功宣称同步完成。该凭据是后置记录，原 `README.md`、`manifest.json`、`recovery.bundle` 三个输入保持冻结。主 workflow 只写研究目标分支；后置添加 `verification.json` 不匹配其仅监听 workflow 文件路径的触发条件。当前说明不预先声明验收成功，也不预填运行 URL。
