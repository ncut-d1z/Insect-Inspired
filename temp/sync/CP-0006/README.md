# CP-0006 二进制分块增量包：初始导入说明与 PowerShell 恢复

文档时点：2026-11-27 07:17:48 UTC+8。**本次恢复的完整数据审计、七产物确定性和十项 UI 均已通过；撰写这份初始说明时，远端导入及独立完整回读尚未完成。** 上传分块或启动 Actions 不能代替最终同步验收。

本次交付是重新构建的 CP6。运行环境切换导致上一版仅保存在本地的提交 `74a6a9b38fc02564d2782e30038eeda237bb7c9e` 及其 bundle 丢失，该提交未完成远端全量验收。已提交远端的规范数据、审阅记录和代码仍可恢复；本次据此重建，并重新通过完整数据审计、七项导出确定性和十项 UI 检查。当前恢复提交是 `a1303b6b6c38692b4f57da5cfb342289c6dc17e5`，所有校验均以本次交付的 commit、tree 和哈希为准，不能把旧提交视为已找回。

传输采用 GitHub API 上传按顺序编号的原始二进制块。API 请求用 base64 表示字节，仓库中的 `recovery.bundle.part-0001` 等文件仍存放原始二进制内容；下载后直接按 manifest 顺序进行二进制拼接，不再做 base64 解码。GitHub Actions 验证每块和整包的字节数、SHA256、bundle 前提及目标提交，再将该提交普通快进写入 `research/p3-p6-cp6`。本轮助手没有合并、推送或删除 `main`；下文涉及 main 与分支清理的命令由用户在自己的主机执行。

远端证明齐备后，本目录的 `README.md` 将更新为带实际 Actions、验证提交和完整证明清单的最终主机操作指南；本文件原字节保留为 `README.import-input.md`。`manifest.json` 的 `readme_sha256` 指向**这份初始说明**，不是后续指南。若两者并存，恢复时用初始说明校验该字段，操作优先遵循最终指南。本说明不记录 manifest 自身 SHA，避免循环哈希。

## 1. 交付内容与实际进度

本轮 RUN-0004 恢复 **9 个既有 PMID 身份**；新增 **15 个限定于具体 Work 的署名身份**，没有按姓名合并全局 Person；解析 **13 个已保存参考出现项**，新增 **13 条 source_supported 引用边**，没有据此关闭正文引用语境。另新增 Jung2011 的一个独立 **L03 Fig. 6b 脉冲响应衰减适应主张**。原有 69 条 Assessment 原始行、9 条不足结论、23 条反证及旧检查点保持不变。

当前共 5,085 个 Work、20,564 个署名身份、158,544 个参考出现项、31,824 条引用边、70 条活动 Assessment（61 合格、9 不足）、912 条查询和287项人工活动。主题 Work 并集35，U00为5,050；未结任务130,237。P3–P6仍为 **partial**，研究闭包为 **false**，不是文献检索或科学问题全部完成。

包恢复的是完整规范仓库：BibTeX、十表 HTML、五个研究视图、Work/Version/署名/机构/项目、参考与引文、Assessment、来源回执、查询和任务历史、分片清单、进度、检查点、脚本及 QA 证据。**不含原始论文 PDF、论文页图或整篇论文正文。** `temp/` 和 `temp/partitions/` 是规范数据，不能当下载缓存删除。

Jung 的准入限于作者报告的固定范式：非飞行适应前/后0.171/0.113 s，系留飞行前/后0.289/0.165 s；Fig. 6b总样本为5只蝇，均值±SEM，不能把四组累加成20只。精确P、SEM幅度、个体配对矩阵及完整拟合细节未列出；响应估计映射为模型高通参数不等于直接测得生物高通器件，也不证明平台速度幅值恢复。

本地验收为0错误、16项原有辅助 schema 警告；七产物全部字节一致，十项UI通过。规范树共 **1256文件、881966656字节**，CP6含 **1255项artifact hashes**，其自身哈希另行固定：

| 项目 | 固定值 |
| --- | --- |
| CP6 commit | `a1303b6b6c38692b4f57da5cfb342289c6dc17e5` |
| CP6 tree | `32a732212b9151c2ee1ee75a91081ffcbca60d9b` |
| 唯一直接 Git parent / bundle prerequisite | `fc43ccb0582611292811bbe4d2b7fb3ea0c9bcc0` |
| 有效检查点父项 | `CP-0005`，稳定锚点 `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006` |
| CP6 JSON 字节 | `51240014` |
| CP6 JSON SHA256 | `43c11e7465404e956274fdaadef74f7bd0d27177111de5200f127f36c8c7d47d` |
| recovery.bundle 字节 | `26519358` |
| recovery.bundle SHA256 | `cc53dbbe5ddc1045214c38a0aafe088e9c869836219e3c65707adab2c397a142` |
| 实际存储 | `bundle_storage=ordered_binary_parts`；`parts` 按 `index` 从 1 连续排列 |

## 2. PowerShell 5.1 / 7：建立独立恢复目录

以下命令面向**用户自己的主机**，按顺序在同一 PowerShell 会话执行，要求 Git 可用。流程只创建新的恢复目录，不覆盖已有克隆，不自动 stash/reset，也不修改全局 Git 配置。需要 GitHub 写权限的合并、推送和删除由用户执行。当前准备环境没有 PowerShell 运行时；这些命令经过静态审阅，**未声称 PowerShell 实测通过**。

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$Cp6Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp6Commit = 'a1303b6b6c38692b4f57da5cfb342289c6dc17e5'
$Cp6Tree = '32a732212b9151c2ee1ee75a91081ffcbca60d9b'
$Cp6Base = 'fc43ccb0582611292811bbe4d2b7fb3ea0c9bcc0'
$Cp5Anchor = '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
$Cp6SelfHash = '43c11e7465404e956274fdaadef74f7bd0d27177111de5200f127f36c8c7d47d'
$Cp6BundleHash = 'cc53dbbe5ddc1045214c38a0aafe088e9c869836219e3c65707adab2c397a142'
$Cp6BundleBytes = [long]'26519358'
$Cp6FileCount = [long]'1256'
$Cp6FileBytes = [long]'881966656'
$Cp6ArtifactCount = [long]'1255'
$Cp6CheckpointBytes = [long]'51240014'
$Cp6SyncRef = 'refs/heads/sync/cp6-checkpoint-import'
$Cp6ResearchRef = 'refs/heads/research/p3-p6-cp6'
$Cp6CheckpointRel = 'temp/snapshots/checkpoints/CP-0006.json'
$Cp6Prefix = 'temp/sync/CP-0006/'

# Validate the ordered plan before any per-part download or binary assembly.
function Get-Cp6BundlePartPlan {
    param([object]$Manifest, [long]$ExpectedSize, [string]$ExpectedHash)
    if ($Manifest.bundle_storage -cne 'ordered_binary_parts' -or
        $Manifest.bundle_name -cne 'recovery.bundle' -or
        [long]$Manifest.bundle_bytes -ne $ExpectedSize -or
        [string]$Manifest.bundle_sha256 -cne $ExpectedHash -or $ExpectedSize -le 0 -or
        $ExpectedHash -cnotmatch '^[0-9a-f]{64}$') { throw 'Unexpected binary-part manifest identity.' }
    $cp6Parts = @($Manifest.parts)
    if ($cp6Parts.Count -lt 1) { throw 'Missing binary-part plan.' }
    $cp6Seen = @{}
    [long]$cp6Ordinal = 0
    [long]$cp6DeclaredBytes = 0
    foreach ($cp6Part in $cp6Parts) {
        $cp6Ordinal++
        if (-not ($cp6Part.index -is [int] -or $cp6Part.index -is [long]) -or
            [long]$cp6Part.index -ne $cp6Ordinal) { throw 'Part indexes must be consecutive and ordered from 1.' }
        $cp6PartName = [string]$cp6Part.path
        $cp6ExpectedName = 'recovery.bundle.part-{0:D4}' -f $cp6Ordinal
        if ($cp6PartName -cnotmatch '^recovery\.bundle\.part-[0-9]{4,}$' -or
            $cp6PartName -cne $cp6ExpectedName -or $cp6Seen.ContainsKey($cp6PartName)) {
            throw 'Unsafe, duplicate, or out-of-order part path.'
        }
        $cp6Seen[$cp6PartName] = $true
        if (-not ($cp6Part.bytes -is [int] -or $cp6Part.bytes -is [long]) -or
            [long]$cp6Part.bytes -le 0 -or
            [long]$cp6Part.bytes -gt ($ExpectedSize - $cp6DeclaredBytes)) { throw 'Invalid part byte count.' }
        if ([string]$cp6Part.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid part SHA256.' }
        $cp6DeclaredBytes += [long]$cp6Part.bytes
    }
    if ($cp6DeclaredBytes -ne $ExpectedSize) { throw 'Part byte sum does not match the full bundle.' }
    return $cp6Parts
}
function Join-Cp6BundleParts {
    param([string]$RootDir, [object]$Manifest, [string]$OutputPath,
          [long]$ExpectedSize, [string]$ExpectedHash)
    $cp6Parts = @(Get-Cp6BundlePartPlan -Manifest $Manifest -ExpectedSize $ExpectedSize -ExpectedHash $ExpectedHash)
    $cp6ExpectedNames = @($cp6Parts | ForEach-Object { [string]$_.path })
    $cp6ActualNames = @(Get-ChildItem -LiteralPath $RootDir -File -Force -Filter 'recovery.bundle.part-*' |
        ForEach-Object { $_.Name })
    if ($cp6ActualNames.Count -ne $cp6ExpectedNames.Count -or
        @(Compare-Object -ReferenceObject ($cp6ExpectedNames | Sort-Object) -DifferenceObject ($cp6ActualNames | Sort-Object) -CaseSensitive).Count -ne 0) {
        throw 'Missing or unlisted binary-part file.'
    }
    if (Test-Path -LiteralPath $OutputPath) { throw 'Assembled bundle already exists; preserve it and use a fresh directory.' }
    $cp6OutStream = [IO.File]::Open($OutputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        foreach ($cp6Part in $cp6Parts) {
            $cp6PartPath = Join-Path $RootDir ([string]$cp6Part.path)
            if (-not (Test-Path -LiteralPath $cp6PartPath -PathType Leaf) -or
                (Get-Item -LiteralPath $cp6PartPath).Length -ne [long]$cp6Part.bytes -or
                (Get-FileHash -LiteralPath $cp6PartPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne [string]$cp6Part.sha256) {
                throw ('Binary-part bytes/hash mismatch: ' + [string]$cp6Part.path)
            }
            $cp6InStream = [IO.File]::OpenRead($cp6PartPath)
            try { $cp6InStream.CopyTo($cp6OutStream) } finally { $cp6InStream.Dispose() }
        }
    } finally { $cp6OutStream.Dispose() }
    if ((Get-Item -LiteralPath $OutputPath).Length -ne $ExpectedSize -or
        (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedHash) {
        throw 'Assembled bundle bytes/SHA256 mismatch.'
    }
    Write-Host ('All {0} original binary parts and the assembled bundle passed byte/hash checks.' -f $cp6Parts.Count)
}

function Invoke-Cp6Git {
    param([Parameter(Mandatory=$true)][string[]]$GitArgs)
    $cp6SavedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & git @GitArgs
        $cp6Exit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $cp6SavedPreference }
    if ($cp6Exit -ne 0) { throw ('Git failed, exit=' + $cp6Exit) }
}
function Get-Cp6GitLine {
    param([Parameter(Mandatory=$true)][string[]]$GitArgs)
    $cp6Rows = @(Invoke-Cp6Git -GitArgs $GitArgs)
    if ($cp6Rows.Count -ne 1) { throw 'Expected exactly one Git output line.' }
    return ([string]$cp6Rows[0]).Trim()
}
function Assert-Cp6Equal {
    param($Actual, $Expected, [string]$Label)
    if ([string]$Actual -cne [string]$Expected) { throw ('Mismatch: ' + $Label) }
}
function Get-Cp6Hash {
    param([Parameter(Mandatory=$true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Assert-Cp6Clean {
    if (@(Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'status','--porcelain=v1','--untracked-files=all')).Count -ne 0) {
        throw 'Working tree/index is not clean. Stop; do not reset or delete user files.'
    }
}
function Get-Cp6RemoteRef {
    param([Parameter(Mandatory=$true)][string]$Ref)
    $cp6Rows = @(Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'ls-remote','--heads','origin',$Ref))
    if ($cp6Rows.Count -eq 0) { return $null }
    if ($cp6Rows.Count -ne 1) { throw 'Ambiguous remote ref.' }
    $cp6Parts = ([string]$cp6Rows[0]) -split "`t"
    if ($cp6Parts.Count -ne 2 -or $cp6Parts[0] -notmatch '^[0-9a-f]{40}$' -or $cp6Parts[1] -cne $Ref) {
        throw 'Unexpected remote ref response.'
    }
    return $cp6Parts[0]
}
function Assert-Cp6Origin {
    Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'remote','get-url','origin')) $Cp6Url 'origin fetch URL'
    $cp6PushUrls = @(Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'remote','get-url','--push','--all','origin'))
    if ($cp6PushUrls.Count -ne 1) { throw 'Expected one push URL.' }
    Assert-Cp6Equal $cp6PushUrls[0] $Cp6Url 'origin push URL'
}

$Cp6Root = Join-Path (Get-Location).Path ('CP6-restore-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $Cp6Root) { throw 'Recovery directory already exists.' }
$null = New-Item -ItemType Directory -Path $Cp6Root
$Cp6Repo = Join-Path $Cp6Root 'Insect-Inspired'
$Cp6InputRepo = Join-Path $Cp6Root 'input.git'
$Cp6PackageDir = Join-Path $Cp6Root 'package'
$Cp6AuditDir = Join-Path $Cp6Root 'audit-keep'
$null = New-Item -ItemType Directory -Path $Cp6PackageDir
$null = New-Item -ItemType Directory -Path $Cp6AuditDir
$Cp6Zip = Join-Path $Cp6AuditDir 'import-input.zip'
$Cp6Proof = Join-Path $Cp6AuditDir 'host-verification.json'
Invoke-Cp6Git -GitArgs @('--version')
Write-Host ('Recovery root: ' + $Cp6Root)
```

## 3. 从真实 GitHub 分支取全部二进制块、按清单拼接并验证

`git archive --output` 直接写 ZIP 二进制；不要改成 PowerShell `>` 或 `Out-File` 保存 bundle/ZIP。归档范围包含 manifest、原始 README 和所有 `recovery.bundle.part-0001` 等原二进制块。每条 `parts` 记录含 `index`、`path`、`bytes`、`sha256`；块数和块大小由实际冻结清单决定，不固定为 256 KiB 或 1 MiB。先按原顺序逐块验证，再由 `[IO.File]` 文件流拼接并验证整包 SHA256；不要按操作系统目录枚举顺序拼接。若失败留下部分输出，保留排查并换新目录，不能跳过校验覆盖。这里取到的真实运输分支 tip 会记录在本地证明中。若远端尚未发布该分支，fetch 将停止；不要绕过为另一个来源。

```powershell
Invoke-Cp6Git -GitArgs @('init','--bare',$Cp6InputRepo)
Invoke-Cp6Git -GitArgs @(('--git-dir=' + $Cp6InputRepo),'fetch','--no-tags','--depth=1',$Cp6Url,$Cp6SyncRef)
$Cp6InputTip = Get-Cp6GitLine -GitArgs @(('--git-dir=' + $Cp6InputRepo),'rev-parse','FETCH_HEAD')
if ($Cp6InputTip -notmatch '^[0-9a-f]{40}$') { throw 'Invalid input commit.' }
Invoke-Cp6Git -GitArgs @(('--git-dir=' + $Cp6InputRepo),'archive','--format=zip',('--output=' + $Cp6Zip),$Cp6InputTip,'--','temp/sync/CP-0006')
Expand-Archive -LiteralPath $Cp6Zip -DestinationPath $Cp6PackageDir
$Cp6Payload = Join-Path $Cp6PackageDir 'temp/sync/CP-0006'
$Cp6Bundle = Join-Path $Cp6Payload 'recovery.bundle'
$Cp6ManifestPath = Join-Path $Cp6Payload 'manifest.json'
$Cp6OriginalReadme = Join-Path $Cp6Payload 'README.import-input.md'
if (-not (Test-Path -LiteralPath $Cp6OriginalReadme -PathType Leaf)) {
    $Cp6OriginalReadme = Join-Path $Cp6Payload 'README.md'
}
$Cp6Manifest = Get-Content -LiteralPath $Cp6ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp6Equal $Cp6Manifest.repository 'ncut-d1z/Insect-Inspired' 'manifest repository'
Assert-Cp6Equal $Cp6Manifest.checkpoint_id 'CP-0006' 'manifest checkpoint'
Assert-Cp6Equal $Cp6Manifest.scope_id 'SCOPE-0001' 'manifest scope'
Assert-Cp6Equal $Cp6Manifest.source_sync_ref $Cp6SyncRef 'manifest input ref'
Assert-Cp6Equal $Cp6Manifest.target_ref $Cp6ResearchRef 'manifest research ref'
Assert-Cp6Equal $Cp6Manifest.expected_commit $Cp6Commit 'manifest commit'
Assert-Cp6Equal $Cp6Manifest.expected_tree $Cp6Tree 'manifest tree'
Assert-Cp6Equal $Cp6Manifest.expected_parent_commit $Cp6Base 'manifest direct parent'
Assert-Cp6Equal $Cp6Manifest.expected_baseline_commit $Cp6Base 'manifest prerequisite'
Assert-Cp6Equal $Cp6Manifest.parent_checkpoint_id 'CP-0005' 'manifest checkpoint parent'
Assert-Cp6Equal $Cp6Manifest.bundle_kind 'incremental' 'manifest bundle kind'
Assert-Cp6Equal $Cp6Manifest.bundle_name 'recovery.bundle' 'manifest bundle name'
Assert-Cp6Equal $Cp6Manifest.bundle_bytes $Cp6BundleBytes 'manifest bundle bytes'
Assert-Cp6Equal $Cp6Manifest.bundle_sha256 $Cp6BundleHash 'manifest bundle hash'
if (@($Cp6Manifest.bundle_prerequisites).Count -ne 1) { throw 'Unexpected prerequisite count.' }
Assert-Cp6Equal $Cp6Manifest.bundle_prerequisites[0] $Cp6Base 'manifest prerequisite'
Assert-Cp6Equal $Cp6Manifest.checkpoint_sha256 $Cp6SelfHash 'manifest checkpoint hash'
Assert-Cp6Equal $Cp6Manifest.canonical_file_count $Cp6FileCount 'manifest file count'
Assert-Cp6Equal $Cp6Manifest.artifact_hash_count $Cp6ArtifactCount 'manifest artifact count'
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6OriginalReadme) $Cp6Manifest.readme_sha256 'original import README hash'
Join-Cp6BundleParts -RootDir $Cp6Payload -Manifest $Cp6Manifest -OutputPath $Cp6Bundle -ExpectedSize $Cp6BundleBytes -ExpectedHash $Cp6BundleHash
Copy-Item -LiteralPath $Cp6OriginalReadme -Destination (Join-Path $Cp6AuditDir 'README.import-input.md')
Copy-Item -LiteralPath $Cp6ManifestPath -Destination (Join-Path $Cp6AuditDir 'manifest.json')
```

## 4. 先取得 prerequisite，再恢复完整 CP6

这是增量 bundle，不能直接 `git clone recovery.bundle`。下面先从 GitHub 获取唯一 prerequisite 的完整历史，再验包和获取目标提交。新的研究克隆固定 LF，避免 Windows 换行转换改变已哈希数据。

```powershell
Invoke-Cp6Git -GitArgs @('init',$Cp6Repo)
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'config','core.autocrlf','false')
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'config','core.eol','lf')
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'remote','add','origin',$Cp6Url)
Assert-Cp6Origin
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'fetch','--no-tags','origin',$Cp6Base)
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','FETCH_HEAD')) $Cp6Base 'fetched prerequisite'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'merge-base','--is-ancestor',$Cp5Anchor,$Cp6Base)
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'bundle','verify',$Cp6Bundle)
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'bundle','list-heads',$Cp6Bundle)) ($Cp6Commit + ' ' + $Cp6ResearchRef) 'only bundle head'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'fetch','--no-tags',$Cp6Bundle,($Cp6ResearchRef + ':refs/heads/restored-cp6'))
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'checkout','restored-cp6')
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','HEAD')) $Cp6Commit 'restored HEAD'
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'show','-s','--format=%T',$Cp6Commit)) $Cp6Tree 'restored tree'
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'show','-s','--format=%P',$Cp6Commit)) $Cp6Base 'single direct parent'
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','--is-shallow-repository')) 'false' 'complete history'
if (Test-Path -LiteralPath (Join-Path $Cp6Repo '.git/objects/info/alternates')) { throw 'Unexpected alternate object store.' }
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'fsck','--full','--strict',$Cp6Commit)
Assert-Cp6Clean
```

## 5. 核验 CP6 自身和全部 1255 项制品，保存原包与证明

下面核对磁盘上的真实文件字节，不只检查 Git 状态。失败时停止，保留目录排查；不要批量改换行或跳过哈希检查。

```powershell
$Cp6CheckpointPath = Join-Path $Cp6Repo $Cp6CheckpointRel
Assert-Cp6Equal (Get-Item -LiteralPath $Cp6CheckpointPath).Length $Cp6CheckpointBytes 'checkpoint bytes'
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6CheckpointPath) $Cp6SelfHash 'checkpoint SHA256'
$Cp6Checkpoint = Get-Content -LiteralPath $Cp6CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp6Equal $Cp6Checkpoint.checkpoint_id 'CP-0006' 'checkpoint ID'
Assert-Cp6Equal $Cp6Checkpoint.parent_checkpoint_id 'CP-0005' 'checkpoint parent'
Assert-Cp6Equal $Cp6Checkpoint.status 'valid' 'checkpoint status'
$Cp6Artifacts = @($Cp6Checkpoint.artifact_hashes.PSObject.Properties)
if ($Cp6Artifacts.Count -ne $Cp6ArtifactCount -or $Cp6ArtifactCount -ne ($Cp6FileCount - 1)) { throw 'Frozen artifact hash count mismatch.' }
$Cp6Checked = @()
foreach ($cp6Entry in $Cp6Artifacts) {
    $cp6Name = [string]$cp6Entry.Name
    if ([IO.Path]::IsPathRooted($cp6Name) -or $cp6Name -match '(^|/)\.\.(/|$)' -or
        $cp6Name -match '(^|/)\.git(/|$)' -or $cp6Name -ceq $Cp6CheckpointRel) {
        throw ('Unsafe/self-referential artifact path: ' + $cp6Name)
    }
    $cp6Path = Join-Path $Cp6Repo $cp6Name
    if (-not (Test-Path -LiteralPath $cp6Path -PathType Leaf)) { throw ('Missing artifact: ' + $cp6Name) }
    $cp6Hash = Get-Cp6Hash -Path $cp6Path
    Assert-Cp6Equal $cp6Hash ([string]$cp6Entry.Value) ('artifact ' + $cp6Name)
    $Cp6Checked += [pscustomobject]@{ path=$cp6Name; bytes=(Get-Item -LiteralPath $cp6Path).Length; sha256=$cp6Hash }
}
$cp6ExpectedPaths = @($Cp6Artifacts | ForEach-Object { [string]$_.Name }) + @($Cp6CheckpointRel)
$cp6Tracked = @(Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'-c','core.quotePath=false','ls-tree','-r','--name-only',$Cp6Commit))
if ($cp6Tracked.Count -ne $Cp6FileCount -or @(Compare-Object ($cp6ExpectedPaths | Sort-Object) ($cp6Tracked | Sort-Object)).Count -ne 0) {
    throw 'Checkpoint hash set does not cover the complete Git tree.'
}
$cp6RepoPrefix = [IO.Path]::GetFullPath($Cp6Repo).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$cp6GitPrefix = [IO.Path]::GetFullPath((Join-Path $Cp6Repo '.git')).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$cp6ActualFiles = @(Get-ChildItem -LiteralPath $Cp6Repo -Recurse -File -Force |
    Where-Object { -not $_.FullName.StartsWith($cp6GitPrefix,[StringComparison]::OrdinalIgnoreCase) })
$cp6ActualPaths = @($cp6ActualFiles | ForEach-Object { $_.FullName.Substring($cp6RepoPrefix.Length).Replace('\','/') })
if ($cp6ActualPaths.Count -ne $Cp6FileCount -or @(Compare-Object ($cp6ExpectedPaths | Sort-Object) ($cp6ActualPaths | Sort-Object)).Count -ne 0) {
    throw 'Unexpected or missing working-tree file.'
}
Assert-Cp6Equal (($cp6ActualFiles | Measure-Object -Property Length -Sum).Sum) $Cp6FileBytes 'complete file bytes'
Assert-Cp6Clean
$Cp6ProofData = [ordered]@{
    status='passed'; checked_at_utc=[DateTime]::UtcNow.ToString('o'); kind='host-local-recovery'
    source_repository=$Cp6Url; source_sync_commit=$Cp6InputTip; commit=$Cp6Commit; tree=$Cp6Tree; direct_parent=$Cp6Base
    checkpoint_sha256=$Cp6SelfHash; artifact_hashes_verified=$Cp6ArtifactCount; files=$Cp6FileCount; file_bytes=$Cp6FileBytes
    original_package_zip_sha256=(Get-Cp6Hash -Path $Cp6Zip); bundle_sha256=$Cp6BundleHash
    manifest_sha256=(Get-Cp6Hash -Path $Cp6ManifestPath); original_readme_sha256=(Get-Cp6Hash -Path $Cp6OriginalReadme)
    verified_artifacts=$Cp6Checked; remote_main_verified=$false
}
[IO.File]::WriteAllText($Cp6Proof, ($Cp6ProofData | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
$Cp6SavedZipHash = Get-Cp6Hash -Path $Cp6Zip
$Cp6SavedProofHash = Get-Cp6Hash -Path $Cp6Proof
Write-Host ('All {0} canonical files verified. Keep original parts/package and proof at: {1}' -f $Cp6FileCount, $Cp6AuditDir)
```

这份主机证明说明实际执行的本地恢复结果，不冒充本项目之后的独立 GitHub 全量回读证明。若已发布最终指南与 `verification.json`，另按最终指南保存其冻结的完整证明清单；不要只保存一个成功状态字符串。

## 6. 用户在主机 fast-forward main 并普通推送

仅当上述核验全部成功后执行。本地/远端 main 都必须是 CP6 的祖先或 CP6 本身；出现 CP6 未包含的提交时停止，保留现有工作。推送权限和分支保护继续生效，不使用强制更新。

```powershell
Assert-Cp6Clean
Assert-Cp6Origin
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6Zip) $Cp6SavedZipHash 'saved original package'
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6Proof) $Cp6SavedProofHash 'saved local verification'
$Cp6MainBefore = Get-Cp6RemoteRef -Ref 'refs/heads/main'
if ($null -eq $Cp6MainBefore) { throw 'Remote main missing; stop.' }
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'fetch','--no-tags','origin','refs/heads/main')
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','FETCH_HEAD')) $Cp6MainBefore 'fetched main'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'merge-base','--is-ancestor',$Cp6MainBefore,$Cp6Commit)
$cp6LocalMain = @(Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'for-each-ref','--format=%(refname)','refs/heads/main'))
if ($cp6LocalMain.Count -eq 0) {
    Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'checkout','-b','main',$Cp6MainBefore)
} elseif ($cp6LocalMain.Count -eq 1 -and $cp6LocalMain[0] -ceq 'refs/heads/main') {
    Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'merge-base','--is-ancestor','refs/heads/main',$Cp6Commit)
    Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'checkout','main')
} else { throw 'Unexpected local main state.' }
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'merge','--ff-only',$Cp6Commit)
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','HEAD')) $Cp6Commit 'main HEAD'
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'show','-s','--format=%T','HEAD')) $Cp6Tree 'main tree'
Assert-Cp6Clean
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref 'refs/heads/main') $Cp6MainBefore 'main before ordinary push'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'-c','push.followTags=false','push','origin','HEAD:refs/heads/main')
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref 'refs/heads/main') $Cp6Commit 'remote main after push'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'fetch','--no-tags','origin','refs/heads/main')
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','FETCH_HEAD')) $Cp6Commit 'read-back main'
$Cp6ProofData.remote_main_verified = $true
$Cp6ProofData['remote_main_commit'] = $Cp6Commit
$Cp6ProofData['remote_main_checked_at_utc'] = [DateTime]::UtcNow.ToString('o')
[IO.File]::WriteAllText($Cp6Proof, ($Cp6ProofData | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
$Cp6SavedProofHash = Get-Cp6Hash -Path $Cp6Proof
```

## 7. 可选：有原包、有证明且 main 包含 CP6 后，条件删除本轮两分支

只删除本轮 `research/p3-p6-cp6` 与 `sync/cp6-checkpoint-import`。精确 SHA lease 仅用于**条件删除**，`--atomic` 要求两项一起成功或失败；没有 main 强制更新。若运输分支已经新增最终指南或证明，下面会因 tip 与已保存原包不同而停止：先按新的最终指南完整保存证明，再清理。不要删掉保护参数重试。

```powershell
Assert-Cp6Clean
Assert-Cp6Origin
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6Zip) $Cp6SavedZipHash 'retained package ZIP'
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6Proof) $Cp6SavedProofHash 'retained verification'
$cp6SavedProof = Get-Content -LiteralPath $Cp6Proof -Raw -Encoding UTF8 | ConvertFrom-Json
if ($cp6SavedProof.status -cne 'passed' -or $cp6SavedProof.remote_main_verified -ne $true) { throw 'Main verification proof missing.' }
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref 'refs/heads/main') $Cp6Commit 'verified main before cleanup'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'fetch','--no-tags','origin','refs/heads/main')
Assert-Cp6Equal (Get-Cp6GitLine -GitArgs @('-C',$Cp6Repo,'rev-parse','FETCH_HEAD')) $Cp6Commit 'fetched verified main'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'merge-base','--is-ancestor',$Cp6Commit,'FETCH_HEAD')
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref $Cp6ResearchRef) $Cp6Commit 'only exact CP6 research target'
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref $Cp6SyncRef) $Cp6InputTip 'transport tip equals archived input'
Invoke-Cp6Git -GitArgs @('-C',$Cp6Repo,'-c','push.followTags=false','push','--atomic',
    ('--force-with-lease=' + $Cp6ResearchRef + ':' + $Cp6Commit),
    ('--force-with-lease=' + $Cp6SyncRef + ':' + $Cp6InputTip),
    'origin',(':' + $Cp6ResearchRef),(':' + $Cp6SyncRef))
if ($null -ne (Get-Cp6RemoteRef -Ref $Cp6ResearchRef) -or $null -ne (Get-Cp6RemoteRef -Ref $Cp6SyncRef)) { throw 'Named temporary ref still exists.' }
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref 'refs/heads/main') $Cp6Commit 'main retained after cleanup'
```

## 8. 可选：只删除本会话的独立解包目录

完整原始分块包 ZIP 和主机证明已保留在 `audit-keep`，可选择只删除新建的 `package` 子目录；也可保留它以便离线恢复。**不要删除研究仓库中的 temp、partitions、检查点或 QA。** 不删除恢复出的仓库、`audit-keep`、输入 Git 库或其他目录。`audit-keep` 的原始 ZIP 包含所有原二进制块和冻结 manifest；保留它即可再次按相同清单拼接，不能只保留一次成功状态。

```powershell
Assert-Cp6Equal (Get-Cp6RemoteRef -Ref 'refs/heads/main') $Cp6Commit 'verified main before local cleanup'
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6Zip) $Cp6SavedZipHash 'retained original ZIP'
Assert-Cp6Equal (Get-Cp6Hash -Path $Cp6Proof) $Cp6SavedProofHash 'retained proof'
$cp6ExpectedPackage = [IO.Path]::GetFullPath((Join-Path $Cp6Root 'package'))
Assert-Cp6Equal ([IO.Path]::GetFullPath($Cp6PackageDir)) $cp6ExpectedPackage 'only this session package path'
if (Test-Path -LiteralPath $Cp6PackageDir) {
    if ((Get-Item -LiteralPath $Cp6PackageDir).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refuse reparse-point cleanup.' }
    Remove-Item -LiteralPath $Cp6PackageDir -Recurse
}
Write-Host ('Keep canonical repository: ' + $Cp6Repo)
Write-Host ('Keep original package and verification: ' + $Cp6AuditDir)
```

最终同步状态以之后发布的固定 Actions 日志和 `verification.json` 为准。本初始文档中的“尚未完成”只描述创建时点，不代表后续同步失败；后置证明不改写已冻结的 CP6 本身。
