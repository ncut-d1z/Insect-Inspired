# CP6 完整性与独立远端核验

本目录只提供同步验收工具，不执行科研任务。准备阶段只创建脚本；在 CP6 canonical 尚未冻结时，不运行清单生成或 clone。两个 Python 文件必须放在同一目录，使用 Python 3.10+ 和 Git；只依赖 Python 标准库。

## 已确认锚点与待冻结参数

固定目标为 `https://github.com/ncut-d1z/Insect-Inspired.git` 的 `research/p3-p6-cp6` 分支，检查点为 `CP-0006`。有效检查点父项是 `CP-0005`，其已核验 Git 锚点为 `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006`。

CP6 的直接 Git 父提交通常是最后一次已上传回执的 HEAD，与有效检查点父项不同。脚本不预填尚未冻结的父 SHA；本轮还会增加回执，当前活动分支 HEAD 不能提前当成最终 parent。

运行前由 root 冻结并记录四个值：

1. `--expected-head`：CP6 最终完整 40 位 commit SHA。
2. `--expected-tree`：该 commit 的完整 40 位 tree SHA。
3. `--expected-parent`：CP6 的唯一直接 Git 父提交完整 SHA；该父提交必须包含已确认 CP5 锚点。
4. `--manifest-sha`：本地清单生成器成功输出后，文件的完整 64 位 SHA256。远端核验必须使用这份精确清单，不能临时从远端构建预期值。

不预填 CP6 的文件数、字节数、Work 数或分片数量；所有数量从冻结树、检查点或分片清单读取、重算和比较。CP1 的首次入库 commit 从 CP5 不变的可达历史中查询，不猜测额外 SHA。

## 第一步：冻结后生成本地清单

下面的尖括号是占位符，须替换为 root 确认的冻结值：

```bash
python -B /workspace/scratch/2e518600ca4c/cp6_sync/make_local_integrity_cp6.py \
  --repo /workspace/scratch/2e518600ca4c/insect-project \
  --expected-head <CP6完整commit-SHA> \
  --expected-tree <CP6完整tree-SHA> \
  --expected-parent <CP6唯一直接Git父SHA> \
  --out /workspace/scratch/2e518600ca4c/cp6_sync/local-integrity-cp6.json
```

生成器只读 canonical 和 Git 对象；要求冻结 HEAD/tree/parent、干净工作树和有效 CP6。输出在仓库外。只有退出码 0 且 `status=passed` 才能使用其打印的 `manifest_sha256`。

## 第二步：发布后独立 clone 核验

此步骤在 CP6 已发布后执行。`--clone-dir` 必须不存在；不可复用现有 clone、bundle 或本地对象目录。

```bash
python -B /workspace/scratch/2e518600ca4c/cp6_sync/verify_remote_cp6.py \
  --expected-head <同一CP6完整commit-SHA> \
  --expected-tree <同一CP6完整tree-SHA> \
  --expected-parent <同一CP6唯一直接Git父SHA> \
  --manifest /workspace/scratch/2e518600ca4c/cp6_sync/local-integrity-cp6.json \
  --manifest-sha <生成器打印的manifest-SHA256> \
  --clone-dir /workspace/scratch/2e518600ca4c/cp6_sync/remote-cp6-frozen-verification \
  --out /workspace/scratch/2e518600ca4c/cp6_sync/remote-verification-cp6.json
```

也可省略 `--clone-dir`，由脚本生成唯一目录。报告必须位于 clone 和 canonical 之外。脚本只做 HTTPS GitHub clone 和本地只读检查，不 push、不更新 main/tag、不设置 GitHub 权限；不会改写原 canonical。若网络策略阻止 clone，保留失败报告并停止，不通过代理、授权重试或本地对象替代来声称通过。

## 验收内容

- 路径集合、Git mode、blob SHA、字节数和 SHA256；远端树必须与可信本地清单逐项一致。
- CP6 的 artifact hash 集合严格覆盖所有跟踪文件，唯一排除 CP6 文件自身；自身哈希仍由本地可信清单与远端实际字节核验。
- CP6 唯一直接 Git 父提交按 CLI 核验；有效检查点链 CP6→CP5→CP4→CP2→CP1 保留。CP3 继续作为 invalid 历史保留，原 CP4→CP3→CP2 Git 父链不变。
- CP1–CP5 文件与其原始提交及 CP5 冻结锚点逐字一致。`temp/snapshots/scopes/SCOPE-0001.json`、`temp/snapshots/scope.json` 与 `temp/seed-manifest.jsonl` 必须与 CP5 锚点逐字一致；不改 cutoff 或种子集合。
- 所有 `*/partitions/manifest.json`：每片路径、字节数、SHA256、JSONL 记录数；依清单顺序拼接后的逻辑 SHA256 和记录总数；拒绝遗漏的跟踪分片。
- `git fsck --full --strict`、全部 HEAD 可达对象存在及对象库存摘要；拒绝 shallow、partial/promisor、alternates、grafts、replace refs、对象软/硬链接，以及可达历史中的 LFS 指针。
- fresh clone 禁止 file/ext 协议和本地对象借用；不执行项目代码、hooks、模板、外部 filter 或凭据助手，不输出凭据。

退出码为 0 表示通过；1 表示检查不通过；2 表示执行失败。准备完成或本地清单通过都不等于远端同步验收通过；必须等待独立 clone 报告成功。
