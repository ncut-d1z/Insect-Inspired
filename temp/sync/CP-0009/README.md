# CP9 增量恢复、完整性核验与主机合并

本目录包含 35 个二进制分片，每片至多 512 KiB。目标提交 `96ce04b268f648978581e87d3be551981f12917d`，树 `4e61e76e128b51c55c75bc0db1853376f549407e`，直接 Git 父项 `5881ca89952d5b83850a9c6f1131a4cce81fe0c5`。CP9 的唯一 bundle prerequisite 是冻结 CP8 `2e749d4994bd3b8c66fcde59950779adc5d66085`。检查点父项为 CP-0008。

运输分支 `sync/cp9-checkpoint-import` 同时保留 CP7、CP8 和 CP9 的完整包。以下 PowerShell 命令从真实 GitHub prerequisite 开始依次恢复三个检查点，校验分片、bundle、提交、树、全部规范文件及检查点自哈希。运输分支含打包目录，不能直接合并到 main。此目录不提供 Actions workflow。

需要 Git 和 **PowerShell 7 或更新版本（pwsh）**。修改 `$Cp9Repo` 为本机已有仓库的绝对路径，在同一会话按顺序运行。任何校验、快进或推送失败都会停止；保留数据并检查，不得改为强制覆盖 main。

## 1. 拉取运输分支并保留原始包

~~~powershell
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 or newer is required.' }
$Cp9Repo = 'C:\path\to\Insect-Inspired'
$Cp9Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp9SyncRef = 'refs/heads/sync/cp9-checkpoint-import'
$Cp9ResearchRef = 'refs/heads/research/p3-p6-cp9'
$Cp9RemoteBase = '0ee3b7de167a70933bc9884b9217142c2661c374'
$Cp9Commit = '96ce04b268f648978581e87d3be551981f12917d'
function Invoke-Cp9Git {
    $cp9Rows = @(& git -C $Cp9Repo -c core.hooksPath=/dev/null -c push.followTags=false @args)
    if ($LASTEXITCODE -ne 0) { throw ('Git failed: ' + ($args -join ' ')) }
    $cp9Rows
}
function Assert-Cp9Equal($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -cne [string]$Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp9Hash([string]$Path, [string]$Expected) {
    Assert-Cp9Equal (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() $Expected $Path
}
function Get-Cp9Remote([string]$Ref) {
    $cp9Rows = @(Invoke-Cp9Git ls-remote --heads origin $Ref)
    if ($cp9Rows.Count -eq 0) { return $null }
    if ($cp9Rows.Count -ne 1) { throw 'Unexpected remote ref count.' }
    $cp9Columns = $cp9Rows[0] -split '\s+'
    Assert-Cp9Equal $cp9Columns[1] $Ref 'remote ref name'
    return $cp9Columns[0]
}
Assert-Cp9Equal (Invoke-Cp9Git remote get-url origin) $Cp9Url 'repository origin'
if (@(Invoke-Cp9Git status --porcelain).Count) { throw 'Preserve local changes first.' }
Invoke-Cp9Git fetch --no-tags origin $Cp9SyncRef
$Cp9SyncTip = [string](Invoke-Cp9Git rev-parse FETCH_HEAD)
$Cp9HostRoot = Join-Path (Split-Path -Parent $Cp9Repo) ('cp9-recovery-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp9HostRoot
$Cp9Zip = Join-Path $Cp9HostRoot 'cp7-cp8-cp9-transport.zip'
$Cp9Package = Join-Path $Cp9HostRoot 'package'
Invoke-Cp9Git archive --format=zip ('--output=' + $Cp9Zip) $Cp9SyncTip -- temp/sync/CP-0007 temp/sync/CP-0008 temp/sync/CP-0009
Expand-Archive -LiteralPath $Cp9Zip -DestinationPath $Cp9Package
$Cp9Expected = @'
[
  {
    "checkpoint_id": "CP-0007",
    "parent_checkpoint_id": "CP-0006",
    "package_path": "temp/sync/CP-0007",
    "manifest_sha256": "a16a7cc1cb908e7c187300cfb18d83e83ae7fcd0cc0cdd6c1b7a55e3bcc131cd",
    "readme_sha256": "d98418bdd0383dd0cbea1b7663b71ee8ab8f911789e44295c94bdd58636d72bf",
    "expected_baseline_commit": "0ee3b7de167a70933bc9884b9217142c2661c374",
    "expected_parent_commit": "0ee3b7de167a70933bc9884b9217142c2661c374",
    "expected_commit": "3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f",
    "expected_tree": "c5d5f03ce399961429288e1ffb7ce3565e278fbf",
    "target_ref": "refs/heads/research/p3-p6-cp7",
    "source_sync_ref": "refs/heads/sync/cp7-checkpoint-import",
    "checkpoint_path": "temp/snapshots/checkpoints/CP-0007.json",
    "checkpoint_sha256": "c5d42d65a8d7b373a6dc6e6ccf5b27d67d09ba85af51b89f468a97795c5223e0",
    "bundle_sha256": "6477f3bd02d46ea494c6f08069e23d0eba4b2e74fdb32de92bc238ee829d87b6",
    "bundle_bytes": 31221121,
    "part_count": 60,
    "canonical_file_count": 1317,
    "canonical_file_bytes": 1045568594,
    "artifact_hash_count": 1316,
    "partition_dataset_count": 7,
    "partition_manifest_sha256": "e3e537a4817e8d7f735685f54e3c674329e4241f9d23c73e789195251caac0a6"
  },
  {
    "checkpoint_id": "CP-0008",
    "parent_checkpoint_id": "CP-0007",
    "package_path": "temp/sync/CP-0008",
    "manifest_sha256": "897f5dbf90c8cee21f67952e9a2fd65ac02b1c645415bd144be7577996e40974",
    "readme_sha256": "282aa145d2722b7144f27161e88662c62bffeed366e351bf663d111afb2ae6ad",
    "expected_baseline_commit": "3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f",
    "expected_parent_commit": "81cbe9940a1464be8483d859857d589883f388e5",
    "expected_commit": "2e749d4994bd3b8c66fcde59950779adc5d66085",
    "expected_tree": "6428de0a5ac1e7c288928462eb9c768d08dfff4c",
    "target_ref": "refs/heads/research/p3-p6-cp8",
    "source_sync_ref": "refs/heads/sync/cp8-checkpoint-import",
    "checkpoint_path": "temp/snapshots/checkpoints/CP-0008.json",
    "checkpoint_sha256": "85e5312505b14862df28c4193b74aeaf4767bb3b56942786f3948b172edcedb0",
    "bundle_sha256": "2520e20dfead3375c33489033c08b65437d0caf47b4a446ab0475fd942ebdf50",
    "bundle_bytes": 28210811,
    "part_count": 54,
    "canonical_file_count": 1361,
    "canonical_file_bytes": 1150803660,
    "artifact_hash_count": 1360,
    "partition_dataset_count": 7,
    "partition_manifest_sha256": "af1d5f3f7551119c3d68a56d522fe4ce03583acac673ca3351d5b9ab7de77c34"
  },
  {
    "checkpoint_id": "CP-0009",
    "parent_checkpoint_id": "CP-0008",
    "package_path": "temp/sync/CP-0009",
    "source_sync_ref": "refs/heads/sync/cp9-checkpoint-import",
    "target_ref": "refs/heads/research/p3-p6-cp9",
    "expected_baseline_commit": "2e749d4994bd3b8c66fcde59950779adc5d66085",
    "expected_commit": "96ce04b268f648978581e87d3be551981f12917d",
    "expected_tree": "4e61e76e128b51c55c75bc0db1853376f549407e",
    "expected_parent_commit": "5881ca89952d5b83850a9c6f1131a4cce81fe0c5",
    "checkpoint_path": "temp/snapshots/checkpoints/CP-0009.json",
    "bundle_bytes": 18103498,
    "bundle_sha256": "343a4dc01117d6577005e9031201fa06605187463174b107b599db8da0e70411",
    "part_count": 35,
    "checkpoint_sha256": "b1551bc78888c4df70569e81f9b8e95583d01fb22e996112db68b26087e9a172",
    "canonical_file_count": 1414,
    "canonical_file_bytes": 1346716802,
    "artifact_hash_count": 1413,
    "partition_dataset_count": 8,
    "partition_manifest_sha256": "892df8bbd8e5facf6586478d8f4b67761d337f1dc0b550b4c3fbbaf925299fe8"
  }
]
'@ | ConvertFrom-Json
~~~

## 2. 逐片校验、拼接，并依次导入三个检查点

~~~powershell
function Join-Cp9Parts([string]$Folder, $Manifest, [string]$Output, $Expected) {
    $cp9Parts = @($Manifest.parts)
    Assert-Cp9Equal $cp9Parts.Count $Expected.part_count 'part count'
    Assert-Cp9Equal (@(Get-ChildItem -LiteralPath (Join-Path $Folder 'parts') -File).Count) $Expected.part_count 'actual part count'
    $cp9Output = [IO.File]::Open($Output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    [long]$cp9Total = 0
    try {
        for ($cp9Index = 0; $cp9Index -lt $cp9Parts.Count; $cp9Index++) {
            $cp9Part = $cp9Parts[$cp9Index]
            $cp9Name = 'parts/recovery.bundle.part-{0:D4}' -f ($cp9Index + 1)
            Assert-Cp9Equal $cp9Part.index ($cp9Index + 1) 'part ordinal'
            Assert-Cp9Equal $cp9Part.path $cp9Name 'exact part name'
            if ($cp9Part.bytes -le 0 -or $cp9Part.bytes -gt 524288) { throw 'Invalid part size.' }
            if ($cp9Index -lt ($cp9Parts.Count - 1)) { Assert-Cp9Equal $cp9Part.bytes 524288 'full part size' }
            $cp9Path = Join-Path $Folder $cp9Name
            Assert-Cp9Equal (Get-Item -LiteralPath $cp9Path).Length $cp9Part.bytes 'part bytes'
            Assert-Cp9Hash $cp9Path $cp9Part.sha256
            $cp9Input = [IO.File]::OpenRead($cp9Path)
            try { $cp9Input.CopyTo($cp9Output) } finally { $cp9Input.Dispose() }
            $cp9Total += [long]$cp9Part.bytes
        }
    } finally { $cp9Output.Dispose() }
    Assert-Cp9Equal $cp9Total $Expected.bundle_bytes 'sum of part bytes'
    Assert-Cp9Equal (Get-Item -LiteralPath $Output).Length $Expected.bundle_bytes 'assembled bytes'
    Assert-Cp9Hash $Output $Expected.bundle_sha256
}
Invoke-Cp9Git fetch --no-tags origin $Cp9RemoteBase
Assert-Cp9Equal (Invoke-Cp9Git rev-parse FETCH_HEAD) $Cp9RemoteBase 'real GitHub prerequisite'
foreach ($cp9ExpectedItem in $Cp9Expected) {
    $cp9Folder = Join-Path $Cp9Package $cp9ExpectedItem.package_path
    $cp9ManifestPath = Join-Path $cp9Folder 'manifest.json'
    if ($cp9ExpectedItem.PSObject.Properties.Name -contains 'manifest_sha256') {
        Assert-Cp9Hash $cp9ManifestPath $cp9ExpectedItem.manifest_sha256
    }
    $cp9Manifest = Get-Content -LiteralPath $cp9ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Cp9Equal $cp9Manifest.format_version 1 'manifest format'
    Assert-Cp9Equal $cp9Manifest.repository 'ncut-d1z/Insect-Inspired' 'repository'
    Assert-Cp9Equal $cp9Manifest.scope_id 'SCOPE-0001' 'scope'
    Assert-Cp9Equal $cp9Manifest.bundle_kind 'incremental' 'bundle kind'
    Assert-Cp9Equal $cp9Manifest.bundle_storage 'ordered_binary_parts' 'storage'
    Assert-Cp9Equal $cp9Manifest.bundle_name 'recovery.bundle' 'bundle name'
    Assert-Cp9Equal $cp9Manifest.part_size_bytes 524288 'part size'
    foreach ($cp9Key in @('checkpoint_id','parent_checkpoint_id','source_sync_ref','target_ref','expected_baseline_commit','expected_parent_commit','expected_commit','expected_tree','checkpoint_path','checkpoint_sha256','bundle_bytes','bundle_sha256','canonical_file_count','canonical_file_bytes','artifact_hash_count','partition_dataset_count','partition_manifest_sha256')) {
        Assert-Cp9Equal $cp9Manifest.$cp9Key $cp9ExpectedItem.$cp9Key $cp9Key
    }
    Assert-Cp9Equal (@($cp9Manifest.bundle_prerequisites) -join ',') $cp9ExpectedItem.expected_baseline_commit 'sole prerequisite'
    Assert-Cp9Hash (Join-Path $cp9Folder 'README.md') $cp9Manifest.readme_sha256
    if ($cp9ExpectedItem.PSObject.Properties.Name -contains 'readme_sha256') {
        Assert-Cp9Hash (Join-Path $cp9Folder 'README.md') $cp9ExpectedItem.readme_sha256
    }
    $cp9Bundle = Join-Path $Cp9HostRoot ($cp9ExpectedItem.checkpoint_id + '-recovery.bundle')
    Join-Cp9Parts $cp9Folder $cp9Manifest $cp9Bundle $cp9ExpectedItem
    Invoke-Cp9Git bundle verify $cp9Bundle
    Assert-Cp9Equal (Invoke-Cp9Git bundle list-heads $cp9Bundle) ($cp9ExpectedItem.expected_commit + ' ' + $cp9ExpectedItem.target_ref) 'sole bundle head'
    # Fetch objects only: do not overwrite any existing local predecessor branch.
    Invoke-Cp9Git fetch --no-tags $cp9Bundle $cp9ExpectedItem.target_ref
    Assert-Cp9Equal (Invoke-Cp9Git rev-parse FETCH_HEAD) $cp9ExpectedItem.expected_commit 'restored commit'
    Assert-Cp9Equal (Invoke-Cp9Git show -s --format=%T $cp9ExpectedItem.expected_commit) $cp9ExpectedItem.expected_tree 'restored tree'
    Assert-Cp9Equal (Invoke-Cp9Git show -s --format=%P $cp9ExpectedItem.expected_commit) $cp9ExpectedItem.expected_parent_commit 'direct parent'
    Invoke-Cp9Git merge-base --is-ancestor $cp9ExpectedItem.expected_baseline_commit $cp9ExpectedItem.expected_commit
}
Invoke-Cp9Git fsck --full --strict --no-reflogs $Cp9Commit
~~~

## 3. 按 Git 原始字节验证全部规范文件，再发布研究分支

~~~powershell
function Assert-Cp9Snapshot($Expected) {
    $cp9Zip = Join-Path $Cp9HostRoot ($Expected.checkpoint_id + '-canonical.zip')
    $cp9Extract = Join-Path $Cp9HostRoot ($Expected.checkpoint_id + '-verified-canonical')
    Invoke-Cp9Git archive --format=zip ('--output=' + $cp9Zip) $Expected.expected_commit
    Expand-Archive -LiteralPath $cp9Zip -DestinationPath $cp9Extract
    $cp9CheckpointPath = Join-Path $cp9Extract $Expected.checkpoint_path
    Assert-Cp9Hash $cp9CheckpointPath $Expected.checkpoint_sha256
    $cp9Checkpoint = Get-Content -LiteralPath $cp9CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Cp9Equal $cp9Checkpoint.status 'valid' 'checkpoint validity'
    Assert-Cp9Equal $cp9Checkpoint.checkpoint_id $Expected.checkpoint_id 'checkpoint identity'
    Assert-Cp9Equal $cp9Checkpoint.parent_checkpoint_id $Expected.parent_checkpoint_id 'checkpoint parent'
    Assert-Cp9Equal $cp9Checkpoint.scope_id 'SCOPE-0001' 'checkpoint scope'
    $cp9Artifacts = @($cp9Checkpoint.artifact_hashes.PSObject.Properties)
    Assert-Cp9Equal $cp9Artifacts.Count $Expected.artifact_hash_count 'artifact count'
    $cp9TreePaths = @(Invoke-Cp9Git -c core.quotePath=false ls-tree -r --name-only $Expected.expected_commit)
    Assert-Cp9Equal $cp9TreePaths.Count $Expected.canonical_file_count 'tree file count'
    $cp9DeclaredPaths = @($cp9Artifacts | ForEach-Object { $_.Name }) + @($Expected.checkpoint_path)
    if (@(Compare-Object -CaseSensitive -ReferenceObject $cp9TreePaths -DifferenceObject $cp9DeclaredPaths).Count) { throw 'Artifact paths differ from tree.' }
    [long]$cp9Total = (Get-Item -LiteralPath $cp9CheckpointPath).Length
    foreach ($cp9Artifact in $cp9Artifacts) {
        if ([IO.Path]::IsPathRooted($cp9Artifact.Name) -or $cp9Artifact.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe artifact path.' }
        $cp9File = Join-Path $cp9Extract $cp9Artifact.Name
        Assert-Cp9Hash $cp9File ([string]$cp9Artifact.Value)
        $cp9Total += [long](Get-Item -LiteralPath $cp9File).Length
    }
    Assert-Cp9Equal $cp9Total $Expected.canonical_file_bytes 'all file bytes'
    Assert-Cp9Hash (Join-Path $cp9Extract 'temp/partitions/manifest.json') $Expected.partition_manifest_sha256
    Write-Host ('Verified ' + $Expected.checkpoint_id + ': ' + $Expected.canonical_file_count + ' complete files.')
}
foreach ($cp9ExpectedItem in $Cp9Expected) { Assert-Cp9Snapshot $cp9ExpectedItem }
$Cp9Evidence = [ordered]@{
    status = 'passed'; sync_commit = $Cp9SyncTip
    prerequisite_fetched_from_github = $Cp9RemoteBase
    snapshots = $Cp9Expected
    verified_at_utc = [DateTime]::UtcNow.ToString('o')
}
[IO.File]::WriteAllText((Join-Path $Cp9HostRoot 'host-verification.json'), ($Cp9Evidence | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
if ([string](Invoke-Cp9Git branch --show-current) -eq 'research/p3-p6-cp9') { Invoke-Cp9Git switch --detach }
$Cp9Bundle9 = Join-Path $Cp9HostRoot 'CP-0009-recovery.bundle'
Invoke-Cp9Git fetch --no-tags $Cp9Bundle9 ($Cp9ResearchRef + ':' + $Cp9ResearchRef)
Assert-Cp9Equal (Invoke-Cp9Git rev-parse $Cp9ResearchRef) $Cp9Commit 'local research ref'
Invoke-Cp9Git push origin ($Cp9Commit + ':' + $Cp9ResearchRef)
Assert-Cp9Equal (Get-Cp9Remote $Cp9ResearchRef) $Cp9Commit 'remote research after normal push'
~~~

`git archive` 避免 Windows checkout 换行转换影响哈希。保留原始 ZIP、三个 bundle、三个 verified-canonical 目录及 host-verification.json。已有本地研究分支若不能快进，fetch 会停止，不覆盖分叉。

## 4. 快进合并 main 并普通推送

~~~powershell
if (@(Invoke-Cp9Git status --porcelain).Count) { throw 'Working tree must remain clean.' }
Invoke-Cp9Git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
if (@(Invoke-Cp9Git for-each-ref --format='%(refname)' refs/heads/main).Count -eq 0) {
    Invoke-Cp9Git switch -c main --track origin/main
} else { Invoke-Cp9Git switch main }
Invoke-Cp9Git merge --ff-only refs/remotes/origin/main
Invoke-Cp9Git merge --ff-only $Cp9ResearchRef
Invoke-Cp9Git merge-base --is-ancestor $Cp9Commit HEAD
Invoke-Cp9Git push origin HEAD:refs/heads/main
$Cp9Main = Get-Cp9Remote 'refs/heads/main'
Invoke-Cp9Git fetch --no-tags origin refs/heads/main
Assert-Cp9Equal (Invoke-Cp9Git rev-parse FETCH_HEAD) $Cp9Main 'verified remote main'
Invoke-Cp9Git merge-base --is-ancestor $Cp9Commit $Cp9Main
~~~

## 5. main 已包含目标后，可选删除本轮临时分支和提取目录

~~~powershell
if (-not (Test-Path -LiteralPath (Join-Path $Cp9HostRoot 'host-verification.json'))) { throw 'Preserve verification first.' }
Assert-Cp9Equal (Get-Cp9Remote 'refs/heads/main') $Cp9Main 'main before cleanup'
Invoke-Cp9Git fetch --no-tags origin refs/heads/main
Assert-Cp9Equal (Invoke-Cp9Git rev-parse FETCH_HEAD) $Cp9Main 'fetched main before cleanup'
Invoke-Cp9Git merge-base --is-ancestor $Cp9Commit $Cp9Main
Assert-Cp9Equal (Get-Cp9Remote $Cp9ResearchRef) $Cp9Commit 'research deletion lease'
Assert-Cp9Equal (Get-Cp9Remote $Cp9SyncRef) $Cp9SyncTip 'sync deletion lease'
Invoke-Cp9Git push --atomic ('--force-with-lease=' + $Cp9ResearchRef + ':' + $Cp9Commit) ('--force-with-lease=' + $Cp9SyncRef + ':' + $Cp9SyncTip) origin (':' + $Cp9ResearchRef) (':' + $Cp9SyncRef)
Assert-Cp9Equal (Get-Cp9Remote $Cp9ResearchRef) $null 'research deleted'
Assert-Cp9Equal (Get-Cp9Remote $Cp9SyncRef) $null 'sync deleted'
Assert-Cp9Equal (Get-Cp9Remote 'refs/heads/main') $Cp9Main 'main retained'
# Optional: delete only this newly extracted package; retain bundles and verification.
Assert-Cp9Equal ([IO.Path]::GetFullPath($Cp9Package)) ([IO.Path]::GetFullPath((Join-Path $Cp9HostRoot 'package'))) 'exact cleanup path'
if ((Get-Item -LiteralPath $Cp9Package).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Do not clean a reparse point.' }
Remove-Item -LiteralPath $Cp9Package -Recurse
~~~

精确 lease 只用于本轮两个临时分支的条件删除；远端有新提交时删除失败并停止。CP7、CP8 等更早分支不在本段自动删除。不要删除规范 `temp/`、`temp/partitions/` 或历史归档。主机上的推送、main 合并与可选清理由上述命令执行，打包工具仅生成恢复材料，不执行这些操作。
