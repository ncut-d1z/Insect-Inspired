# CP-0006 二进制分块包：主机 PowerShell 获取、恢复、合并与清理

本指南锁定 `research/p3-p6-cp6` 的恢复提交 `__CP6_SHA__`。验收范围为 `__CP6_REMOTE_CHECK_COUNT__` 项检查、`__CP6_FILE_COUNT__` 个文件、`__CP6_FILE_BYTES__` 字节、`__CP6_ARTIFACT_HASH_COUNT__` 项制品哈希，以及当前分片清单的 `__CP6_PARTITION_DATASET_COUNT__` 个逻辑数据集、`__CP6_PARTITION_PART_COUNT__` 个分片。实际结果以第 4 节固定证明提交中的 `verification.json` 和独立回读报告为准；代码会核对它们的哈希、目标提交和通过状态，失败即停止。

本次交付是重新构建的 CP6。运行环境切换导致上一版仅保存在本地的提交 `74a6a9b38fc02564d2782e30038eeda237bb7c9e` 及其 bundle 丢失，该提交未完成远端全量验收。已提交远端的规范数据、审阅记录和代码仍可恢复；本次据此重建，并重新通过完整数据审计、七项导出确定性和十项 UI 检查。当前恢复提交是 `__CP6_SHA__`，所有校验均以本次交付的 commit、tree 和哈希为准，不能把旧提交视为已找回。

本轮恢复准备时，远端 `main` 为 CP4：`bb7726c2ef334df0d7069165156b1cbc2c4e2fd8`。实际合并不依赖它始终停在 CP4：本地和远端 `main` 可以是 CP4、CP5、其他 CP6 祖先或精确 CP6；必须现场验证祖先关系，发生分歧就停止。以下合并、推送和条件删除由用户在自己的主机执行，助手没有执行。

传输采用 GitHub API 上传按顺序编号的原始二进制块。API 请求用 base64 表示字节，仓库中的 `recovery.bundle.part-0001` 等文件仍存放原始二进制内容；下载后直接按 manifest 顺序进行二进制拼接，不再做 base64 解码。GitHub Actions 验证每块和整包的字节数、SHA256、bundle 前提及目标提交，再将该提交普通快进写入 `research/p3-p6-cp6`。本轮助手没有合并、推送或删除 `main`；下文涉及 main 与分支清理的命令由用户在自己的主机执行。

主机恢复优先直接 fetch 指定研究分支；第 4 节继续核验完整远端证明与每个工作树文件。增量分块包提供备用恢复路径，不需要重复运行 Actions。本指南不要求新增令牌、权限、付费功能或 GitHub CLI。

## 1. 固定输入、数据内容与两种 README

有效数据检查点父项是 **CP-0005**，稳定 Git 锚点为 `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006`。CP6 的唯一直接 Git parent 则是 **`__BASE_SHA__`**：研究分支最后一次 API 写入且精确回读成功的 commit。两者含义不同，增量 bundle 的唯一 prerequisite 必须是该直接 Git parent。

`manifest.json` 的 `readme_sha256` 校验**导入时的原始 README**：固定输入提交 `__CP6_INPUT_COMMIT__` 中 `temp/sync/CP-0006/README.md` 的字节；下载时另存为 `README.import-input.md`。本文件是之后更新的操作指南，其哈希不能与 `manifest.readme_sha256` 比较。本操作指南的 SHA256 由独立交付回执记录；校验本指南使用该回执，校验原始导入 README 使用 manifest 中的对应哈希。

| 项目 | 冻结值 |
|---|---|
| 仓库 | `https://github.com/ncut-d1z/Insect-Inspired.git` |
| CP6 commit / tree | `__CP6_SHA__` / `__CP6_TREE__` |
| 唯一 Git parent / bundle prerequisite | `__BASE_SHA__` |
| 有效 checkpoint 父项 / 稳定锚点 | `CP-0005` / `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006` |
| bundle 字节数 / SHA256 | `__CP6_BUNDLE_SIZE_BYTES__` / `__CP6_BUNDLE_SHA256__` |
| manifest SHA256 | `__CP6_MANIFEST_SHA256__` |
| 原始导入 README SHA256 | `__CP6_README_SHA256__` |
| CP6 checkpoint SHA256 | `__CP6_CHECKPOINT_SHA256__` |
| 冻结导入输入提交 | `__CP6_INPUT_COMMIT__` |
| 后置验收证明提交 | `__CP6_PROOF_COMMIT__` |
| 验收总回执 verification.json SHA256 | `__CP6_VERIFICATION_SHA256__` |
| 明确归档的证明文件数 | `__CP6_PROOF_FILE_COUNT__` |
| 规范 Work / Assessment 总数 | `__CP6_CANONICAL_WORK_COUNT__` / `__CP6_ASSESSMENT_COUNT__` |

恢复内容包括规范 Work、Version、Person、机构、项目及关系数据，查询日志、任务、回执、证据、检查点、分片清单和七项导出：`ref.bib`、`ref.html`、`evidence_matrix.csv`、`research_entities.json`、`citation_graph.json`、`research_paths.json`、`research_implications.csv`。本轮记录的推进包括 9 个既有 Work 的身份补全、15 个按具体署名记录限定身份的 Person、13 条参考文献解析，以及 1 条 Jung2011 独立 L03 Assessment；最终总数见上表及冻结证明清单。原有科学记录与不足结论保留，不把该 L03 条目计作 L07 解决。本包不加入原始 PDF、受限全文或认证文件。

CP6 恢复的是完整规范工作树，`recovery.bundle` 只含 `__BASE_SHA__` 之后的增量 Git 对象。因此不能直接 `git clone recovery.bundle`；必须先从真实 GitHub 获取该 prerequisite。CP6 同步验收与 checkpoint 有效性不代表 P3–P6 研究闭合：四阶段仍为 `partial`，`closure=false`。

导入和验收记录：[Actions __CP6_ACTION_RUN_ID__](https://github.com/ncut-d1z/Insect-Inspired/actions/runs/__CP6_ACTION_RUN_ID__)。验收依据包括 [verification.json](verification.json)、[远端完整回读](remote-verification-cp6.json) 及下方冻结的完整证明清单。实际恢复验证状态与命令环境由这些证明记载；以下 PowerShell 代码按 Windows PowerShell 5.1 / PowerShell 7 兼容流程进行静态审阅。当前环境没有 PowerShell 运行时，未声称进行 PowerShell 实测。

## 2. 先执行一次：固定参数与失败即停

在主机打开 PowerShell。已安装 Git，并使用自己已有的 GitHub HTTPS 或 SSH 认证即可；本指南不要求 GitHub CLI。依次在**同一个 PowerShell 会话**运行本节、路径 A 或 B、保存证明、合并和清理各节。出现错误即停止，先检查原因，不跳过校验。

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$null = Get-Command git -ErrorAction Stop
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Cp6Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp6Commit = '__CP6_SHA__'
$Cp6Tree = '__CP6_TREE__'
$Cp6Base = '__BASE_SHA__'
$Cp5CheckpointAnchor = '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
$Cp6InputCommit = '__CP6_INPUT_COMMIT__'
$Cp6ProofCommit = '__CP6_PROOF_COMMIT__'
$Cp6ResearchRef = 'refs/heads/research/p3-p6-cp6'
$Cp6SyncRef = 'refs/heads/sync/cp6-checkpoint-import'
$Cp6Checkpoint = 'temp/snapshots/checkpoints/CP-0006.json'
$Cp6CheckpointHash = '__CP6_CHECKPOINT_SHA256__'
$Cp6BundleHash = '__CP6_BUNDLE_SHA256__'
$Cp6ManifestHash = '__CP6_MANIFEST_SHA256__'
$Cp6InputReadmeHash = '__CP6_README_SHA256__'
$Cp6VerificationHash = '__CP6_VERIFICATION_SHA256__'
$Cp6ProofNames = @('__CP6_PROOF_FILE_NAMES_PIPE__' -split '\|')
foreach ($cp6Digest in @($Cp6Commit, $Cp6Tree, $Cp6Base, $Cp5CheckpointAnchor, $Cp6InputCommit, $Cp6ProofCommit)) {
    if ($cp6Digest -cnotmatch '^[0-9a-f]{40}$') { throw 'Invalid documented Git SHA; stop.' }
}
foreach ($cp6Digest in @($Cp6CheckpointHash, $Cp6BundleHash, $Cp6ManifestHash, $Cp6InputReadmeHash, $Cp6VerificationHash)) {
    if ($cp6Digest -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid documented SHA256; stop.' }
}
$Cp6FileCount = [long]'__CP6_FILE_COUNT__'
$Cp6FileBytes = [long]'__CP6_FILE_BYTES__'
$Cp6ArtifactCount = [long]'__CP6_ARTIFACT_HASH_COUNT__'
$Cp6PartitionDatasetCount = [long]'__CP6_PARTITION_DATASET_COUNT__'
$Cp6BundleBytes = [long]'__CP6_BUNDLE_SIZE_BYTES__'
$Cp6ProofFileCount = [int]'__CP6_PROOF_FILE_COUNT__'
if ($Cp6FileCount -le 0 -or $Cp6FileBytes -le 0 -or $Cp6BundleBytes -le 0 -or
    $Cp6ArtifactCount -ne ($Cp6FileCount - 1) -or $Cp6PartitionDatasetCount -le 0) {
    throw 'Invalid frozen inventory counts.'
}
if ($Cp6ProofNames.Count -ne $Cp6ProofFileCount -or
    @($Cp6ProofNames | Sort-Object -Unique).Count -ne $Cp6ProofFileCount) {
    throw 'Frozen proof list count or uniqueness mismatch.'
}
foreach ($cp6Name in $Cp6ProofNames) {
    if ($cp6Name -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or $cp6Name.Contains('__')) {
        throw 'Invalid or unsafe documented proof filename.'
    }
}
foreach ($cp6RequiredName in @('verification.json', 'local-integrity-cp6.json', 'remote-verification-cp6.json')) {
    if ($Cp6ProofNames -cnotcontains $cp6RequiredName) { throw ('Missing required proof: ' + $cp6RequiredName) }
}
$Cp6AuditSaved = $false
$Cp6HostRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) ('insect-cp6-host-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp6HostRoot
$Cp6PackageDir = Join-Path $Cp6HostRoot 'package'
$Cp6AuditDir = Join-Path $Cp6HostRoot 'audit'

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

# Capture every external git exit code, including commands used in assignments.
function Invoke-GitChecked {
    $cp6NativeArgs = @($args)
    $cp6OldPreference = $ErrorActionPreference
    $cp6Exit = -1
    try {
        $ErrorActionPreference = 'Continue'
        & git @cp6NativeArgs
        $cp6Exit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $cp6OldPreference }
    if ($cp6Exit -ne 0) { throw ('git failed; exit code {0}. Stop here.' -f $cp6Exit) }
}
function Get-GitLine {
    $cp6Lines = @(Invoke-GitChecked @args)
    if ($cp6Lines.Count -ne 1) { throw 'Expected exactly one git output line.' }
    return ([string]$cp6Lines[0]).Trim()
}
function Assert-Cp6Equal {
    param($Actual, $Expected, [string]$Label)
    if ($Actual -ne $Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp6Clean {
    if (@(Invoke-GitChecked -C $Cp6Repo status --porcelain=v1 --untracked-files=all).Count -ne 0) {
        throw 'Working tree or index is not clean. Preserve your work before continuing.'
    }
}
function Get-Cp6RemoteRef {
    param([string]$Ref)
    $cp6Rows = @(Invoke-GitChecked -C $Cp6Repo ls-remote --heads origin $Ref)
    if ($cp6Rows.Count -eq 0) { return $null }
    if ($cp6Rows.Count -ne 1) { throw 'Unexpected remote ref count.' }
    $cp6Parts = ([string]$cp6Rows[0]) -split '\s+'
    if ($cp6Parts.Count -ne 2 -or $cp6Parts[0] -notmatch '^[0-9a-f]{40}$' -or $cp6Parts[1] -ne $Ref) {
        throw 'Unexpected remote ref response.'
    }
    return $cp6Parts[0]
}
function Assert-Cp6Origin {
    $cp6Origin = Get-GitLine -C $Cp6Repo remote get-url origin
    $cp6AllowedUrl = '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)ncut-d1z/Insect-Inspired(\.git)?/?$'
    if ($cp6Origin -notmatch $cp6AllowedUrl) {
        throw 'origin is not the expected GitHub repository.'
    }
    $cp6PushUrls = @(Invoke-GitChecked -C $Cp6Repo remote get-url --push --all origin)
    if ($cp6PushUrls.Count -ne 1 -or $cp6PushUrls[0] -notmatch $cp6AllowedUrl) {
        throw 'origin must have exactly one push URL for the expected GitHub repository.'
    }
}
function Assert-Cp6Hash {
    param([string]$Path, [string]$Hash)
    Assert-Cp6Equal ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()) $Hash $Path
}
function Assert-Cp6Snapshot {
    Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse HEAD) $Cp6Commit 'HEAD'
    Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse 'HEAD^{tree}') $Cp6Tree 'tree'
    Assert-Cp6Equal (Get-GitLine -C $Cp6Repo show -s --format=%P HEAD) $Cp6Base 'unique parent'
    Invoke-GitChecked -C $Cp6Repo merge-base --is-ancestor $Cp5CheckpointAnchor $Cp6Base
    Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse --is-shallow-repository) 'false' 'full history required'
    Invoke-GitChecked -C $Cp6Repo fsck --full --strict $Cp6Commit
    Assert-Cp6Clean
    # git itself writes ZIP bytes; this avoids PowerShell redirection and CRLF conversion.
    $cp6CheckDir = Join-Path $Cp6HostRoot ('checkpoint-' + [Guid]::NewGuid().ToString('N'))
    $cp6CheckZip = $cp6CheckDir + '.zip'
    Invoke-GitChecked -C $Cp6Repo archive --format=zip ('--output=' + $cp6CheckZip) $Cp6Commit -- $Cp6Checkpoint
    Expand-Archive -LiteralPath $cp6CheckZip -DestinationPath $cp6CheckDir
    $cp6CheckpointFile = Join-Path $cp6CheckDir $Cp6Checkpoint
    Assert-Cp6Hash $cp6CheckpointFile $Cp6CheckpointHash
    $cp6CheckpointData = Get-Content -LiteralPath $cp6CheckpointFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Cp6Equal $cp6CheckpointData.checkpoint_id 'CP-0006' 'checkpoint identity'
    Assert-Cp6Equal $cp6CheckpointData.status 'valid' 'checkpoint status'
    Assert-Cp6Equal $cp6CheckpointData.parent_checkpoint_id 'CP-0005' 'valid checkpoint parent'
    Assert-Cp6Equal $cp6CheckpointData.scope_id 'SCOPE-0001' 'checkpoint scope'
    Write-Host ('CP6 commit/tree/parent/checkpoint/fsck/clean checks passed: ' + $Cp6Repo)
}
Write-Host ('Host package and evidence directory: ' + $Cp6HostRoot)
```

## 3A. 推荐：直接 fetch 指定研究分支

在已有 `Insect-Inspired` clone 内打开 PowerShell，然后运行本节。若没有 clone，把第一行改成 `$Cp6UseExistingClone = $false`，代码会在新建的独立目录 clone。已有工作树、暂存区或未跟踪文件不干净时会停止；代码不自动 stash、reset 或覆盖原有分支。

```powershell
$Cp6UseExistingClone = $true
if ($Cp6UseExistingClone) {
    $Cp6Repo = Get-GitLine rev-parse --show-toplevel
} else {
    $Cp6Repo = Join-Path $Cp6HostRoot 'repository'
    Invoke-GitChecked clone --no-tags --config core.autocrlf=false --config core.eol=lf $Cp6Url $Cp6Repo
}
Assert-Cp6Origin
Assert-Cp6Clean
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6ResearchRef) $Cp6Commit 'remote research tip'
Invoke-GitChecked -C $Cp6Repo fetch --no-tags origin $Cp6ResearchRef
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse FETCH_HEAD) $Cp6Commit 'fetched research tip'
$Cp6ReviewBranch = 'review-cp6-' + [Guid]::NewGuid().ToString('N')
Invoke-GitChecked -C $Cp6Repo checkout -b $Cp6ReviewBranch $Cp6Commit
Assert-Cp6Snapshot
```

这里 checkout 后得到完整 CP6 数据，后续直接执行第 4 节。一般无需执行路径 B。

## 3B. 备选：下载固定二进制块并拼接增量 bundle，恢复到全新目录

本节可以代替 3A。输入按固定提交下载；当前操作指南即使后来更新，也不会改变原始输入校验。`Invoke-WebRequest -OutFile` 直接保存 manifest 指定的每个原二进制块。清单使用 `bundle_storage=ordered_binary_parts`，`parts` 记录按连续 `index` 列出 `path`、`bytes`、`sha256`；块数和块大小动态读取。下方通过 `[IO.File]` 流按清单顺序拼接，每块及完整 bundle 都核对字节数与 SHA256；不要使用 `git show ... > recovery.bundle`、`Out-File` 或 `Set-Content` 转存二进制。

```powershell
if (Test-Path -LiteralPath $Cp6PackageDir) { throw 'Package destination already exists. Start a fresh session/directory.' }
$null = New-Item -ItemType Directory -Path $Cp6PackageDir
$cp6InputBase = 'https://raw.githubusercontent.com/ncut-d1z/Insect-Inspired/' + $Cp6InputCommit + '/temp/sync/CP-0006/'
Invoke-WebRequest -UseBasicParsing -Uri ($cp6InputBase + 'manifest.json') -OutFile (Join-Path $Cp6PackageDir 'manifest.json')
Invoke-WebRequest -UseBasicParsing -Uri ($cp6InputBase + 'README.md') -OutFile (Join-Path $Cp6PackageDir 'README.import-input.md')
$Cp6Bundle = Join-Path $Cp6PackageDir 'recovery.bundle'
Assert-Cp6Hash (Join-Path $Cp6PackageDir 'manifest.json') $Cp6ManifestHash
Assert-Cp6Hash (Join-Path $Cp6PackageDir 'README.import-input.md') $Cp6InputReadmeHash
$cp6Manifest = Get-Content -LiteralPath (Join-Path $Cp6PackageDir 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp6Equal $cp6Manifest.expected_commit $Cp6Commit 'manifest commit'
Assert-Cp6Equal $cp6Manifest.expected_tree $Cp6Tree 'manifest tree'
Assert-Cp6Equal $cp6Manifest.expected_baseline_commit $Cp6Base 'manifest prerequisite'
Assert-Cp6Equal $cp6Manifest.expected_parent_commit $Cp6Base 'manifest parent'
Assert-Cp6Equal $cp6Manifest.repository 'ncut-d1z/Insect-Inspired' 'manifest repository'
Assert-Cp6Equal $cp6Manifest.checkpoint_id 'CP-0006' 'manifest checkpoint'
Assert-Cp6Equal $cp6Manifest.parent_checkpoint_id 'CP-0005' 'manifest checkpoint parent'
Assert-Cp6Equal $cp6Manifest.scope_id 'SCOPE-0001' 'manifest scope'
Assert-Cp6Equal $cp6Manifest.source_sync_ref $Cp6SyncRef 'manifest transport ref'
Assert-Cp6Equal $cp6Manifest.target_ref $Cp6ResearchRef 'manifest target'
Assert-Cp6Equal $cp6Manifest.bundle_kind 'incremental' 'manifest bundle kind'
Assert-Cp6Equal $cp6Manifest.bundle_bytes $Cp6BundleBytes 'manifest bundle bytes'
Assert-Cp6Equal $cp6Manifest.bundle_sha256 $Cp6BundleHash 'manifest bundle hash'
Assert-Cp6Equal $cp6Manifest.checkpoint_path $Cp6Checkpoint 'manifest checkpoint path'
Assert-Cp6Equal $cp6Manifest.checkpoint_sha256 $Cp6CheckpointHash 'manifest checkpoint hash'
Assert-Cp6Equal $cp6Manifest.canonical_file_count $Cp6FileCount 'manifest file count'
Assert-Cp6Equal $cp6Manifest.artifact_hash_count $Cp6ArtifactCount 'manifest artifact count'
Assert-Cp6Equal $cp6Manifest.partition_dataset_count $Cp6PartitionDatasetCount 'manifest dataset count'
Assert-Cp6Equal (@($cp6Manifest.bundle_prerequisites) -join ',') $Cp6Base 'sole bundle prerequisite'
Assert-Cp6Hash (Join-Path $Cp6PackageDir 'README.import-input.md') $cp6Manifest.readme_sha256
$cp6DownloadParts = @(Get-Cp6BundlePartPlan -Manifest $cp6Manifest -ExpectedSize $Cp6BundleBytes -ExpectedHash $Cp6BundleHash)
foreach ($cp6Part in $cp6DownloadParts) {
    $cp6PartName = [string]$cp6Part.path
    Invoke-WebRequest -UseBasicParsing -Uri ($cp6InputBase + $cp6PartName) -OutFile (Join-Path $Cp6PackageDir $cp6PartName)
}
Join-Cp6BundleParts -RootDir $Cp6PackageDir -Manifest $cp6Manifest -OutputPath $Cp6Bundle -ExpectedSize $Cp6BundleBytes -ExpectedHash $Cp6BundleHash

$Cp6Repo = Join-Path $Cp6HostRoot 'restored-repository'
if (Test-Path -LiteralPath $Cp6Repo) { throw 'Recovery directory already exists; do not overwrite it.' }
Invoke-GitChecked clone --no-checkout --no-tags --config core.autocrlf=false --config core.eol=lf $Cp6Url $Cp6Repo
Assert-Cp6Origin
# Fetch the real GitHub prerequisite before inspecting/importing the incremental bundle.
Invoke-GitChecked -C $Cp6Repo fetch --no-tags origin $Cp6Base
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse FETCH_HEAD) $Cp6Base 'actual remote baseline'
Invoke-GitChecked -C $Cp6Repo bundle verify $Cp6Bundle
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo bundle list-heads $Cp6Bundle) ($Cp6Commit + ' ' + $Cp6ResearchRef) 'bundle head'
Invoke-GitChecked -C $Cp6Repo fetch --no-tags $Cp6Bundle ($Cp6ResearchRef + ':refs/heads/restored-cp6')
Invoke-GitChecked -C $Cp6Repo checkout restored-cp6
Assert-Cp6Snapshot
```

这是新目录和新本地分支，不写远端。恢复检查成功后，第 4–7 节可以直接沿用此 `$Cp6Repo`。

## 4. 删除临时分支前，先保存固定验收证明

验收证明固定在 `__CP6_PROOF_COMMIT__`。第 2 节的 `$Cp6ProofNames` 明确列出本次需要归档的 `__CP6_PROOF_FILE_COUNT__` 个文件，覆盖 `verification.json` 及其全部 `evidence_files`，包括本地完整性清单和独立远端回读报告。它们是导入之后归档的文件，不属于原始 CP6 研究提交。

下面先从真实 GitHub fetch 固定证明提交，再用 Git 原生 `archive --output` 归档这份明确清单；先校验总回执 SHA256，再核对其列出的每份证明的字节数与 SHA256。同步分支实际 tip 也会记录，供后续精确条件删除使用。

```powershell
Assert-Cp6Origin
Assert-Cp6Clean
if (Test-Path -LiteralPath $Cp6AuditDir) { throw 'Audit destination already exists; keep it and use a fresh session.' }
$Cp6SavedSyncTip = Get-Cp6RemoteRef $Cp6SyncRef
if ($null -eq $Cp6SavedSyncTip) { throw 'Transport branch is absent; inspect existing archives before proceeding.' }
Invoke-GitChecked -C $Cp6Repo fetch --no-tags origin $Cp6SyncRef
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse FETCH_HEAD) $Cp6SavedSyncTip 'fetched transport tip'
Invoke-GitChecked -C $Cp6Repo fetch --no-tags origin $Cp6ProofCommit
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse FETCH_HEAD) $Cp6ProofCommit 'fetched proof commit'
Invoke-GitChecked -C $Cp6Repo merge-base --is-ancestor $Cp6ProofCommit $Cp6SavedSyncTip
$Cp6ProofPaths = @($Cp6ProofNames | ForEach-Object { 'temp/sync/CP-0006/' + $_ })
$Cp6ProofZip = Join-Path $Cp6HostRoot 'cp6-verification-documents.zip'
Invoke-GitChecked -C $Cp6Repo archive --format=zip ('--output=' + $Cp6ProofZip) $Cp6ProofCommit -- @Cp6ProofPaths
Expand-Archive -LiteralPath $Cp6ProofZip -DestinationPath $Cp6AuditDir
$Cp6ProofDir = Join-Path $Cp6AuditDir 'temp/sync/CP-0006'
Assert-Cp6Hash (Join-Path $Cp6ProofDir 'verification.json') $Cp6VerificationHash
$cp6Proof = Get-Content -LiteralPath (Join-Path $Cp6ProofDir 'verification.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp6Equal $cp6Proof.status 'passed' 'verification status'
Assert-Cp6Equal $cp6Proof.canonical_commit $Cp6Commit 'verified CP6 commit'
Assert-Cp6Equal $cp6Proof.canonical_tree $Cp6Tree 'verified CP6 tree'
Assert-Cp6Equal $cp6Proof.git_parent $Cp6Base 'verified direct Git parent'
Assert-Cp6Equal $cp6Proof.parent_checkpoint_id 'CP-0005' 'verified checkpoint parent'
$cp6EvidenceNames = @($cp6Proof.evidence_files | ForEach-Object { $_.path })
Assert-Cp6Equal (($cp6EvidenceNames | Sort-Object) -join "`n") (($Cp6ProofNames | Where-Object { $_ -ne 'verification.json' } | Sort-Object) -join "`n") 'complete frozen evidence list'
foreach ($cp6Name in $Cp6ProofNames) {
    $cp6File = Join-Path $Cp6ProofDir $cp6Name
    if (-not (Test-Path -LiteralPath $cp6File -PathType Leaf)) { throw ('Missing proof: ' + $cp6Name) }
    if ($cp6Name -ne 'verification.json') {
        $cp6Entry = @($cp6Proof.evidence_files | Where-Object { $_.path -eq $cp6Name })
        Assert-Cp6Equal $cp6Entry.Count 1 ('proof hash entry: ' + $cp6Name)
        Assert-Cp6Equal (Get-Item -LiteralPath $cp6File).Length $cp6Entry[0].bytes ('proof size: ' + $cp6Name)
        Assert-Cp6Hash $cp6File $cp6Entry[0].sha256
    }
}
# Check the actual checkout bytes as well as the Git objects (important on Windows).
$cp6Inventory = Get-Content -LiteralPath (Join-Path $Cp6ProofDir 'local-integrity-cp6.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp6Equal $cp6Inventory.status 'passed' 'trusted inventory status'
Assert-Cp6Equal $cp6Inventory.head_commit $Cp6Commit 'trusted inventory commit'
Assert-Cp6Equal $cp6Inventory.head_tree $Cp6Tree 'trusted inventory tree'
Assert-Cp6Equal $cp6Inventory.expected_git_parent $Cp6Base 'trusted inventory direct parent'
Assert-Cp6Equal $cp6Inventory.head_snapshot.file_entries $Cp6FileCount 'trusted tree file count'
Assert-Cp6Equal $cp6Inventory.head_snapshot.file_bytes $Cp6FileBytes 'trusted tree file bytes'
Assert-Cp6Equal (@($cp6Inventory.verified_files).Count) $Cp6FileCount 'trusted inventory file count'
Assert-Cp6Equal (@($cp6Inventory.verified_files.path | Sort-Object -Unique).Count) $Cp6FileCount 'unique inventory paths'
$cp6RemoteProof = Get-Content -LiteralPath (Join-Path $Cp6ProofDir 'remote-verification-cp6.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp6Equal $cp6RemoteProof.status 'passed' 'independent remote verification status'
Assert-Cp6Equal $cp6RemoteProof.head_commit $Cp6Commit 'independent remote commit'
Assert-Cp6Equal $cp6RemoteProof.head_tree $Cp6Tree 'independent remote tree'
Assert-Cp6Equal $cp6RemoteProof.expected_git_parent $Cp6Base 'independent remote direct parent'
[long]$cp6ActualTotalBytes = 0
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse HEAD) $Cp6Commit 'checkout before byte verification'
foreach ($cp6ExpectedFile in $cp6Inventory.verified_files) {
    $cp6ActualFile = Join-Path $Cp6Repo $cp6ExpectedFile.path
    if (-not (Test-Path -LiteralPath $cp6ActualFile -PathType Leaf)) {
        throw ('Missing CP6 file: ' + $cp6ExpectedFile.path)
    }
    $cp6ActualLength = (Get-Item -LiteralPath $cp6ActualFile).Length
    $cp6ActualTotalBytes += $cp6ActualLength
    if ($cp6ActualLength -ne $cp6ExpectedFile.bytes -or
        (Get-FileHash -LiteralPath $cp6ActualFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cp6ExpectedFile.sha256) {
        throw ('Checkout byte mismatch: ' + $cp6ExpectedFile.path + '. Stop. Preserve this clone; start a new session and use path A with $Cp6UseExistingClone = $false to get an LF checkout.')
    }
}
Assert-Cp6Clean
Assert-Cp6Equal $cp6ActualTotalBytes $Cp6FileBytes 'all checkout file bytes'
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse HEAD) $Cp6Commit 'checkout unchanged after byte verification'
Write-Host ('All {0} actual checkout files, totaling {1} bytes, match the verified SHA256 inventory.' -f $Cp6FileCount, $Cp6FileBytes)
$cp6ArchiveRecord = [ordered]@{
    proof_commit = $Cp6ProofCommit; transport_tip = $Cp6SavedSyncTip; cp6_commit = $Cp6Commit
    archive_sha256 = (Get-FileHash -LiteralPath $Cp6ProofZip -Algorithm SHA256).Hash.ToLowerInvariant()
    files = @($Cp6ProofNames | ForEach-Object {
        [ordered]@{ name = $_; sha256 = (Get-FileHash -LiteralPath (Join-Path $Cp6ProofDir $_) -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}
[IO.File]::WriteAllText((Join-Path $Cp6AuditDir 'host-archive-record.json'), ($cp6ArchiveRecord | ConvertTo-Json -Depth 6), ([Text.UTF8Encoding]::new($false)))
$Cp6AuditSaved = $true
Write-Host ('Verified evidence archive: ' + $Cp6AuditDir)
```

本节会使用已校验的完整清单，逐项检查实际工作树的全部 `__CP6_FILE_COUNT__` 个文件及合计 `__CP6_FILE_BYTES__` 字节；文件数、总大小和每项 SHA256 都必须一致。已有 Windows clone 的换行转换可能导致 Git 状态干净、对象正确但本地文件字节不同；遇到该情况时停止，保留原仓库，在新 PowerShell 会话中改用路径 A 的 `$Cp6UseExistingClone = $false`。不要通过自动 reset 或批量换行改写来覆盖原有文件。

请保留 `$Cp6AuditDir` 和 `$Cp6ProofZip`。若只在主机归档而不执行下一节的可选证明提交，删除同步分支后，这些验收文件不会出现在 `main` 中；不要把失去分支引用的旧提交链接当作持久归档承诺。

## 5. 用户在主机上 fast-forward 合并 main 并推送

本节开始会修改用户的本地 `main`，并将 CP6 普通推送到 GitHub `main`。现场检查本地和远端 `main` 都是 CP6 的祖先或精确 CP6，因此允许 CP4、CP5 以及其他已包含在 CP6 历史中的提交；本地 main 即使领先远端，只要仍是 CP6 祖先也可正常 fast-forward。任一 main 含有 CP6 尚未包含的提交时停止，保留现有工作。合并只使用 `--ff-only`，推送不使用 force，仓库权限及分支保护继续生效。

```powershell
Assert-Cp6Origin
Assert-Cp6Clean
if (-not $Cp6AuditSaved) { throw 'Save the audit evidence before proceeding.' }
$Cp6MainBefore = Get-Cp6RemoteRef 'refs/heads/main'
if ($null -eq $Cp6MainBefore) { throw 'Remote main is absent. Stop and inspect.' }
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6ResearchRef) $Cp6Commit 'remote research tip before merge'
Invoke-GitChecked -C $Cp6Repo fetch --no-tags origin refs/heads/main
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse FETCH_HEAD) $Cp6MainBefore 'fetched main'
Invoke-GitChecked -C $Cp6Repo merge-base --is-ancestor $Cp6MainBefore $Cp6Commit
$cp6LocalMain = @(Invoke-GitChecked -C $Cp6Repo for-each-ref '--format=%(refname)' refs/heads/main)
if ($cp6LocalMain.Count -eq 0) {
    Invoke-GitChecked -C $Cp6Repo checkout -b main $Cp6MainBefore
} elseif ($cp6LocalMain.Count -eq 1 -and $cp6LocalMain[0] -eq 'refs/heads/main') {
    Invoke-GitChecked -C $Cp6Repo merge-base --is-ancestor refs/heads/main $Cp6Commit
    Invoke-GitChecked -C $Cp6Repo checkout main
} else { throw 'Unexpected local main ref state.' }
Invoke-GitChecked -C $Cp6Repo merge --ff-only $Cp6Commit
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse HEAD) $Cp6Commit 'merged local main'
Assert-Cp6Clean
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6MainBefore 'remote main immediately before push'
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6ResearchRef) $Cp6Commit 'research immediately before push'
Invoke-GitChecked -C $Cp6Repo -c push.followTags=false push origin 'HEAD:refs/heads/main'
$Cp6ExpectedMain = $Cp6Commit
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'remote main after push'
```

### 可选：把固定清单中的可读验收证明也提交到 main

希望证明在临时分支删除后仍可从主仓库找到时，运行下面这一块。只复制已完整校验且明确列出的证明文件到 `temp/validation/cp6-remote-sync/`；不复制 bundle、workflow 或 manifest，也不合并运输分支。跳过这一块时，主机归档仍保留，但 main 只含原 CP6 研究快照。

```powershell
Assert-Cp6Clean
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo branch --show-current) 'main' 'current branch'
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse HEAD) $Cp6Commit 'main before audit-only addition'
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'remote main before audit-only addition'
$cp6AuditRelativeDir = 'temp/validation/cp6-remote-sync'
$cp6PublishDir = Join-Path $Cp6Repo $cp6AuditRelativeDir
if (Test-Path -LiteralPath $cp6PublishDir) { throw 'Audit publication directory already exists. Do not overwrite it.' }
$null = New-Item -ItemType Directory -Path $cp6PublishDir
foreach ($cp6Name in $Cp6ProofNames) {
    Copy-Item -LiteralPath (Join-Path $Cp6ProofDir $cp6Name) -Destination (Join-Path $cp6PublishDir $cp6Name)
}
$cp6PublishPaths = @($Cp6ProofNames | ForEach-Object { $cp6AuditRelativeDir + '/' + $_ })
Invoke-GitChecked -C $Cp6Repo -c core.autocrlf=false add -- @cp6PublishPaths
$cp6Staged = @(Invoke-GitChecked -C $Cp6Repo diff --cached --name-only)
Assert-Cp6Equal (($cp6Staged | Sort-Object) -join "`n") (($cp6PublishPaths | Sort-Object) -join "`n") 'exact audit-only staged paths'
Invoke-GitChecked -C $Cp6Repo commit -m 'Record CP6 remote synchronization verification'
$cp6AuditCommit = Get-GitLine -C $Cp6Repo rev-parse HEAD
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo show -s --format=%P HEAD) $Cp6Commit 'audit-only direct parent'
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'remote main immediately before audit push'
Invoke-GitChecked -C $Cp6Repo -c push.followTags=false push origin 'HEAD:refs/heads/main'
$Cp6ExpectedMain = $cp6AuditCommit
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'remote audit-only main'
Assert-Cp6Clean
```

## 6. 用户在主机上条件删除两条临时远端分支

先确认远端 main 仍是刚推送并验收的提交，且 CP6 是其祖先，再删除两个明确命名的临时分支。精确 SHA lease **只用于这两条分支的条件删除**，并以 `--atomic` 保证两项同时成功或同时失败；任何分支在检查后被其他人更新，删除都会被拒绝。目标仅为本轮 `research/p3-p6-cp6` 与 `sync/cp6-checkpoint-import`，不会删除 `main`、`research/p3-p6-cp5`、`sync/cp5-checkpoint-import` 或其他历史分支。这里没有通配符、宽泛 `--force`、main 强制更新或删除。

```powershell
Assert-Cp6Origin
Assert-Cp6Clean
if (-not $Cp6AuditSaved -or -not (Test-Path -LiteralPath (Join-Path $Cp6AuditDir 'host-archive-record.json'))) {
    throw 'Verified local audit archive is required before deleting transport refs.'
}
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'main before deletion'
Invoke-GitChecked -C $Cp6Repo fetch --no-tags origin refs/heads/main
Assert-Cp6Equal (Get-GitLine -C $Cp6Repo rev-parse FETCH_HEAD) $Cp6ExpectedMain 'fetched main before deletion'
Invoke-GitChecked -C $Cp6Repo merge-base --is-ancestor $Cp6Commit $Cp6ExpectedMain
Assert-Cp6Equal $Cp6ResearchRef 'refs/heads/research/p3-p6-cp6' 'only CP6 research deletion target'
Assert-Cp6Equal $Cp6SyncRef 'refs/heads/sync/cp6-checkpoint-import' 'only CP6 transport deletion target'
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6ResearchRef) $Cp6Commit 'research deletion expected tip'
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6SyncRef) $Cp6SavedSyncTip 'transport deletion expected tip'
Invoke-GitChecked -C $Cp6Repo -c push.followTags=false push --atomic `
    ('--force-with-lease=' + $Cp6ResearchRef + ':' + $Cp6Commit) `
    ('--force-with-lease=' + $Cp6SyncRef + ':' + $Cp6SavedSyncTip) `
    origin (':' + $Cp6ResearchRef) (':' + $Cp6SyncRef)
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6ResearchRef) $null 'research branch removed'
Assert-Cp6Equal (Get-Cp6RemoteRef $Cp6SyncRef) $null 'transport branch removed'
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'main retained after deletion'
Write-Host 'The two named remote temporary branches are removed; verified main is retained.'
```

若 lease、atomic、权限或分支保护检查失败，就停止，不去掉保护参数重试，不强制推送。若远端分支已不存在，也先确认是否由你或其他操作者完成了清理。

## 7. 可选：删除主机下载包，保留数据和证明

仅路径 B 会创建本节要删除的 `package` 子目录。以下清理只删除本会话新建的独立 `package` 子目录（下载的原二进制块、拼接的 bundle、manifest、原始 README），不删除恢复出的仓库、验收证明、归档 ZIP 或任何远端内容。研究数据中的 `temp/` 和 `temp/partitions/` 属于 canonical，必须保留；不要把它们当下载缓存清理。若希望保留原二进制块和离线恢复材料，可完全跳过；删除 package 前，固定验收证明已按第 4 节单独归档。

```powershell
Assert-Cp6Equal (Get-Cp6RemoteRef 'refs/heads/main') $Cp6ExpectedMain 'verified main before local package cleanup'
Invoke-GitChecked -C $Cp6Repo merge-base --is-ancestor $Cp6Commit $Cp6ExpectedMain
if (-not $Cp6AuditSaved) { throw 'Keep the verification evidence before package cleanup.' }
if (Test-Path -LiteralPath $Cp6PackageDir) {
    Assert-Cp6Equal ([IO.Path]::GetFullPath($Cp6PackageDir)) ([IO.Path]::GetFullPath((Join-Path $Cp6HostRoot 'package'))) 'exact package cleanup path'
    if ((Get-Item -LiteralPath $Cp6PackageDir).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Package cleanup path is a reparse point; stop.'
    }
    Remove-Item -LiteralPath $Cp6PackageDir -Recurse
}
Write-Host ('Keep the restored data at: ' + $Cp6Repo)
Write-Host ('Keep verification evidence at: ' + $Cp6AuditDir)
Write-Host ('Keep verification ZIP at: ' + $Cp6ProofZip)
```

## 说明来源

Git 官方文档说明 [增量 bundle 的 prerequisite 与 verify](https://git-scm.com/docs/git-bundle)、[fast-forward-only 合并](https://git-scm.com/docs/git-merge) 和 [精确 lease / atomic push](https://git-scm.com/docs/git-push)。Microsoft 文档说明 [Get-FileHash](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1) 与 [PowerShell 重定向](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection?view=powershell-5.1)。本指南直接把下载及 Git archive 写到文件，不依赖 PowerShell 文本管道保存原始二进制。
