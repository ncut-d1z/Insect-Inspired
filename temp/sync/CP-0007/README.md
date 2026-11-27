# CP7 增量数据恢复与主机合并

此目录保存 60 个原始二进制块，默认每块 512 KiB；实际块大小以 manifest.json 为准。按清单顺序拼接可恢复 recovery.bundle。增量仅声明 research/p3-p6-cp7，必须先取得 prerequisite 0ee3b7de167a70933bc9884b9217142c2661c374。目标提交 3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f，树 c5d5f03ce399961429288e1ffb7ce3565e278fbf，直接 Git 父提交 0ee3b7de167a70933bc9884b9217142c2661c374；检查点父项为 CP-0006。分块、manifest、此说明和导入 workflow 位于独立 sync 分支，不进入研究快照。

Actions 只接受固定仓库、固定 sync ref 和这些已冻结字节；普通 fast-forward 更新 research/p3-p6-cp7，随后从 GitHub 新建独立仓库回读全部 artifact SHA256 和分区逻辑哈希。成功摘要及验证阶段记录见对应 Actions run 的日志。主机恢复无需执行仓库里的 Python 代码。

以下适用于 Windows PowerShell 5.1 或更新版本及 Git。先把 $Cp7Repo 改成你的现有仓库绝对路径，在同一个 PowerShell 会话依次运行。命令在仓库外建立独立恢复目录；不把运输分支合并到 main。Git 操作失败就停止，保留现场。

## 1. 拉取两个分支并提取包

~~~powershell
$ErrorActionPreference = 'Stop'
$Cp7Repo = 'C:\path\to\Insect-Inspired'
$Cp7Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp7ResearchRef = 'refs/heads/research/p3-p6-cp7'
$Cp7SyncRef = 'refs/heads/sync/cp7-checkpoint-import'
$Cp7Base = '0ee3b7de167a70933bc9884b9217142c2661c374'
$Cp7Commit = '3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f'
$Cp7Parent = '0ee3b7de167a70933bc9884b9217142c2661c374'
$Cp7Tree = 'c5d5f03ce399961429288e1ffb7ce3565e278fbf'
$Cp7BundleHash = '6477f3bd02d46ea494c6f08069e23d0eba4b2e74fdb32de92bc238ee829d87b6'
$Cp7CheckpointHash = 'c5d42d65a8d7b373a6dc6e6ccf5b27d67d09ba85af51b89f468a97795c5223e0'
function Invoke-Cp7Git {
    $cp7Result = @(& git -C $Cp7Repo -c core.hooksPath=/dev/null -c push.followTags=false @args)
    if ($LASTEXITCODE -ne 0) { throw ('Git failed: ' + ($args -join ' ')) }
    $cp7Result
}
function Assert-Cp7Equal($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -cne [string]$Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp7Hash([string]$Path, [string]$Expected) {
    Assert-Cp7Equal (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() $Expected $Path
}
function Get-Cp7Remote([string]$Ref) {
    $cp7Rows = @(Invoke-Cp7Git ls-remote --heads origin $Ref)
    if ($cp7Rows.Count -eq 0) { return $null }
    if ($cp7Rows.Count -ne 1) { throw 'Unexpected remote ref count' }
    $cp7Columns = $cp7Rows[0] -split '\s+'
    Assert-Cp7Equal $cp7Columns[1] $Ref 'remote ref name'
    return $cp7Columns[0]
}
Assert-Cp7Equal (Invoke-Cp7Git remote get-url origin) $Cp7Url 'origin'
if (@(Invoke-Cp7Git status --porcelain).Count) { throw 'Commit or preserve local changes before restoration.' }
Invoke-Cp7Git fetch --no-tags origin ($Cp7SyncRef + ':refs/remotes/origin/sync/cp7-checkpoint-import') ($Cp7ResearchRef + ':refs/remotes/origin/research/p3-p6-cp7')
$Cp7SyncTip = [string](Invoke-Cp7Git rev-parse refs/remotes/origin/sync/cp7-checkpoint-import)
$Cp7ResearchBefore = [string](Invoke-Cp7Git rev-parse refs/remotes/origin/research/p3-p6-cp7)
if ($Cp7ResearchBefore -notin @($Cp7Base, $Cp7Commit)) { throw 'Research branch advanced unexpectedly; inspect before proceeding.' }
$Cp7HostRoot = Join-Path (Split-Path -Parent $Cp7Repo) ('cp7-recovery-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp7HostRoot
$Cp7Package = Join-Path $Cp7HostRoot 'package'
$Cp7Archive = Join-Path $Cp7HostRoot 'cp7-transport.zip'
Invoke-Cp7Git archive --format=zip ('--output=' + $Cp7Archive) $Cp7SyncTip -- temp/sync/CP-0007 .github/workflows/import-cp7.yml
Expand-Archive -LiteralPath $Cp7Archive -DestinationPath $Cp7Package
$Cp7PackageData = Join-Path $Cp7Package 'temp/sync/CP-0007'
$Cp7ManifestPath = Join-Path $Cp7PackageData 'manifest.json'
$Cp7Manifest = Get-Content -LiteralPath $Cp7ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp7Equal $Cp7Manifest.repository 'ncut-d1z/Insect-Inspired' 'repository'
Assert-Cp7Equal $Cp7Manifest.checkpoint_id 'CP-0007' 'checkpoint'
Assert-Cp7Equal $Cp7Manifest.parent_checkpoint_id 'CP-0006' 'parent checkpoint'
Assert-Cp7Equal $Cp7Manifest.scope_id 'SCOPE-0001' 'scope'
Assert-Cp7Equal $Cp7Manifest.source_sync_ref $Cp7SyncRef 'sync ref'
Assert-Cp7Equal $Cp7Manifest.target_ref $Cp7ResearchRef 'research ref'
Assert-Cp7Equal $Cp7Manifest.expected_baseline_commit $Cp7Base 'prerequisite'
Assert-Cp7Equal $Cp7Manifest.expected_parent_commit $Cp7Parent 'direct parent'
Assert-Cp7Equal $Cp7Manifest.expected_commit $Cp7Commit 'target commit'
Assert-Cp7Equal $Cp7Manifest.expected_tree $Cp7Tree 'target tree'
Assert-Cp7Equal $Cp7Manifest.bundle_storage 'ordered_binary_parts' 'storage'
Assert-Cp7Equal $Cp7Manifest.bundle_kind 'incremental' 'bundle kind'
Assert-Cp7Equal $Cp7Manifest.bundle_sha256 $Cp7BundleHash 'bundle SHA256'
Assert-Cp7Equal $Cp7Manifest.bundle_bytes 31221121 'bundle length'
Assert-Cp7Equal (@($Cp7Manifest.bundle_prerequisites) -join ',') $Cp7Base 'sole prerequisite'
Assert-Cp7Hash (Join-Path $Cp7PackageData 'README.md') $Cp7Manifest.readme_sha256
~~~

## 2. 逐片核验、流式拼接及 bundle prerequisite 检查

~~~powershell
$Cp7Parts = @($Cp7Manifest.parts)
Assert-Cp7Equal $Cp7Parts.Count 60 'part count'
$Cp7Bundle = Join-Path $Cp7Package 'recovery.bundle'
$Cp7Stream = [IO.File]::Open($Cp7Bundle, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    [long]$Cp7PartBytes = 0
    for ($cp7Index = 0; $cp7Index -lt $Cp7Parts.Count; $cp7Index++) {
        $cp7Part = $Cp7Parts[$cp7Index]
        $cp7Name = 'parts/recovery.bundle.part-{0:D4}' -f ($cp7Index + 1)
        Assert-Cp7Equal $cp7Part.index ($cp7Index + 1) 'part order'
        Assert-Cp7Equal $cp7Part.path $cp7Name 'part path'
        $cp7Path = Join-Path $Cp7PackageData $cp7Name
        Assert-Cp7Equal (Get-Item -LiteralPath $cp7Path).Length $cp7Part.bytes 'part length'
        Assert-Cp7Hash $cp7Path $cp7Part.sha256
        $cp7Input = [IO.File]::OpenRead($cp7Path)
        try { $cp7Input.CopyTo($Cp7Stream) } finally { $cp7Input.Dispose() }
        $Cp7PartBytes += [long]$cp7Part.bytes
    }
} finally { $Cp7Stream.Dispose() }
Assert-Cp7Equal $Cp7PartBytes 31221121 'sum of part lengths'
Assert-Cp7Equal (Get-Item -LiteralPath $Cp7Bundle).Length 31221121 'assembled length'
Assert-Cp7Hash $Cp7Bundle $Cp7BundleHash
Invoke-Cp7Git fetch --no-tags origin $Cp7Base
Assert-Cp7Equal (Invoke-Cp7Git rev-parse FETCH_HEAD) $Cp7Base 'real remote prerequisite'
Invoke-Cp7Git bundle verify $Cp7Bundle
Assert-Cp7Equal (Invoke-Cp7Git bundle list-heads $Cp7Bundle) ($Cp7Commit + ' ' + $Cp7ResearchRef) 'sole bundle head'
if ([string](Invoke-Cp7Git branch --show-current) -eq 'research/p3-p6-cp7') {
    Invoke-Cp7Git switch --detach
}
Invoke-Cp7Git fetch --no-tags $Cp7Bundle ($Cp7ResearchRef + ':' + $Cp7ResearchRef)
Assert-Cp7Equal (Invoke-Cp7Git rev-parse $Cp7ResearchRef) $Cp7Commit 'imported research branch'
Assert-Cp7Equal (Invoke-Cp7Git show -s --format=%T $Cp7Commit) $Cp7Tree 'imported tree'
Assert-Cp7Equal (Invoke-Cp7Git show -s --format=%P $Cp7Commit) $Cp7Parent 'imported direct parent'
Invoke-Cp7Git merge-base --is-ancestor $Cp7Base $Cp7Commit
Invoke-Cp7Git fsck --full --strict --no-reflogs $Cp7Commit
~~~

若当前检出的是目标研究分支，上述命令先在已确认干净的工作树上切换为 detached HEAD，再导入该分支；现有提交和工作文件均保留。

## 3. 以 Git 原始字节解包并核验全部检查点文件

~~~powershell
$Cp7SnapshotZip = Join-Path $Cp7HostRoot 'cp7-canonical.zip'
$Cp7VerifiedTree = Join-Path $Cp7HostRoot 'verified-canonical'
Invoke-Cp7Git archive --format=zip ('--output=' + $Cp7SnapshotZip) $Cp7Commit
Expand-Archive -LiteralPath $Cp7SnapshotZip -DestinationPath $Cp7VerifiedTree
$Cp7CheckpointPath = Join-Path $Cp7VerifiedTree 'temp/snapshots/checkpoints/CP-0007.json'
Assert-Cp7Hash $Cp7CheckpointPath $Cp7CheckpointHash
$Cp7Checkpoint = Get-Content -LiteralPath $Cp7CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp7Equal $Cp7Checkpoint.status 'valid' 'checkpoint validity'
Assert-Cp7Equal $Cp7Checkpoint.checkpoint_id 'CP-0007' 'checkpoint identity'
Assert-Cp7Equal $Cp7Checkpoint.parent_checkpoint_id 'CP-0006' 'checkpoint parent'
Assert-Cp7Equal (@($Cp7Checkpoint.artifact_hashes.PSObject.Properties).Count) 1316 'artifact count'
Assert-Cp7Equal (@(Invoke-Cp7Git ls-tree -r --name-only $Cp7Commit).Count) 1317 'tree file count'
foreach ($cp7Artifact in $Cp7Checkpoint.artifact_hashes.PSObject.Properties) {
    if ([IO.Path]::IsPathRooted($cp7Artifact.Name) -or $cp7Artifact.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe artifact path' }
    Assert-Cp7Hash (Join-Path $Cp7VerifiedTree $cp7Artifact.Name) ([string]$cp7Artifact.Value)
}
$Cp7Evidence = [ordered]@{
    status = 'passed'; target_commit = $Cp7Commit; target_tree = $Cp7Tree
    sync_commit = $Cp7SyncTip; bundle_sha256 = $Cp7BundleHash
    manifest_sha256 = (Get-FileHash -LiteralPath $Cp7ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    canonical_files = 1317; checkpoint_sha256 = $Cp7CheckpointHash
}
[IO.File]::WriteAllText((Join-Path $Cp7HostRoot 'host-verification.json'), ($Cp7Evidence | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Invoke-Cp7Git -c push.followTags=false push origin ($Cp7Commit + ':' + $Cp7ResearchRef)
Assert-Cp7Equal (Get-Cp7Remote $Cp7ResearchRef) $Cp7Commit 'remote research after normal push'
~~~

此解包目录通过 git archive 保留原始字节，不受 Windows checkout 换行转换影响；Git 仓库内导入的提交与这些文件完全对应。保留两个 ZIP、host-verification.json 和 verified-canonical；Actions 的独立远端验证结果仍需在对应 run 确认。

## 4. 由用户在主机快进合并 main 并普通推送

~~~powershell
if (@(Invoke-Cp7Git status --porcelain).Count) { throw 'Working tree must be clean.' }
Invoke-Cp7Git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
if (@(Invoke-Cp7Git for-each-ref --format='%(refname)' refs/heads/main).Count -eq 0) {
    Invoke-Cp7Git switch -c main --track origin/main
} else { Invoke-Cp7Git switch main }
Invoke-Cp7Git merge --ff-only refs/remotes/origin/main
Invoke-Cp7Git merge --ff-only $Cp7ResearchRef
Invoke-Cp7Git merge-base --is-ancestor $Cp7Commit HEAD
Invoke-Cp7Git -c push.followTags=false push origin HEAD:refs/heads/main
$Cp7Main = Get-Cp7Remote 'refs/heads/main'
Invoke-Cp7Git fetch --no-tags origin refs/heads/main
Assert-Cp7Equal (Invoke-Cp7Git rev-parse FETCH_HEAD) $Cp7Main 'verified remote main'
Invoke-Cp7Git merge-base --is-ancestor $Cp7Commit $Cp7Main
~~~

任一 fast-forward 检查失败时，保留分支并先处理分叉；这里不创建覆盖历史的推送。

## 5. 可选：确认 main 已包含目标后清理

先保留主机验证记录及 ZIP。下面的 lease 仅用于精确条件删除两个本轮临时分支；它不会强制更新 main 或研究内容。分支若在检查后改变，删除应失败，停止后查看变更。

~~~powershell
if (-not (Test-Path -LiteralPath (Join-Path $Cp7HostRoot 'host-verification.json'))) { throw 'Keep verification first.' }
Assert-Cp7Equal (Get-Cp7Remote 'refs/heads/main') $Cp7Main 'main before cleanup'
Invoke-Cp7Git fetch --no-tags origin refs/heads/main
Assert-Cp7Equal (Invoke-Cp7Git rev-parse FETCH_HEAD) $Cp7Main 'fetched main before cleanup'
Invoke-Cp7Git merge-base --is-ancestor $Cp7Commit $Cp7Main
Assert-Cp7Equal (Get-Cp7Remote $Cp7ResearchRef) $Cp7Commit 'research deletion lease'
Assert-Cp7Equal (Get-Cp7Remote $Cp7SyncRef) $Cp7SyncTip 'sync deletion lease'
Invoke-Cp7Git push --atomic ('--force-with-lease=' + $Cp7ResearchRef + ':' + $Cp7Commit) ('--force-with-lease=' + $Cp7SyncRef + ':' + $Cp7SyncTip) origin (':' + $Cp7ResearchRef) (':' + $Cp7SyncRef)
Assert-Cp7Equal (Get-Cp7Remote $Cp7ResearchRef) $null 'research deleted'
Assert-Cp7Equal (Get-Cp7Remote $Cp7SyncRef) $null 'sync deleted'
Assert-Cp7Equal (Get-Cp7Remote 'refs/heads/main') $Cp7Main 'main retained'
# 可选，仅删除此会话在仓库外建立的 package；保留 ZIP、数据和验证记录。
Assert-Cp7Equal ([IO.Path]::GetFullPath($Cp7Package)) ([IO.Path]::GetFullPath((Join-Path $Cp7HostRoot 'package'))) 'exact cleanup path'
if ((Get-Item -LiteralPath $Cp7Package).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Do not clean a reparse point.' }
Remove-Item -LiteralPath $Cp7Package -Recurse
~~~

请勿清理研究仓库里的 temp/ 或 temp/partitions/：它们属于检查点数据。以上 main 合并、推送和分支删除均由用户在主机执行；生成工具没有网络写入功能。
