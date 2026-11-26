# CP-0005：主机 PowerShell 获取、恢复、合并与清理

CP5 已完整同步到 `research/p3-p6-cp5`，提交为 `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006`。独立 GitHub clone 回读通过 5,069 项检查：1,188 个文件、828,160,944 字节、1,187 项制品哈希，以及 7 个逻辑数据集的 120 个分片。`main` 在这份说明发布时仍为 CP4：`bb7726c2ef334df0d7069165156b1cbc2c4e2fd8`。下面涉及合并、推送及删除远端分支的命令，由用户在自己的主机运行；助手没有执行这些操作。

本轮仍可通过已授权的 GitHub 连接器调用 API 创建、修改文本文件，README、清单和工作流就是这样提交的。采用增量包的具体原因是：当前执行器内 Git CLI 的写入认证未建立，连接器没有可用的本地二进制文件流直接上传接口，已有的大 blob 调用也曾超时。因此使用网页上传增量包，再由 GitHub Actions 导入原始提交。GitHub API 本身并非不能使用；本次受限的是当前环境的认证与传输通道。研究分支现在已经包含完整工作树，正常 `fetch` 即可取得数据，无需重复导入。

## 1. 固定输入与包内内容

当前 `README.md` 是导入完成后更新的主机操作指南。`manifest.json` 中的 `readme_sha256` 对应**导入时的原始 README**：固定提交 `d5ee82ff400cb907daa23ed2e3b332940ee92675` 下的 `README.md`，以及字节相同的备份 `README.import-input.md`；该哈希不用于校验当前指南。

| 项目 | 固定值 |
|---|---|
| 仓库 | `https://github.com/ncut-d1z/Insect-Inspired.git` |
| CP5 提交 | `82f759ce71e7b532f03cd4ba54a1fcc77c4f4006` |
| CP5 tree | `27b8ac91e5e86fca891dc24e0f08134aaab96ebd` |
| 唯一 parent / 增量包 prerequisite | `95a0a218667333967f4a6c18f8b8b71df8b464e0` |
| bundle 字节数 | `19638061` |
| bundle SHA256 | `29eefe39d95fecd6cbcb909a8cc8242fed6bb168bd42452d3232d881a386738e` |
| manifest SHA256 | `4a9faedaaf9463346292a3d5fd18ae3e6373deef8a7668372957b02d9e92bd39` |
| 原始 README SHA256 | `e47b4e9332f060742dac60ca7f2c2855ccc8dadb7b9c037fc3c7816d326055d3` |
| CP5 checkpoint SHA256 | `ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270` |
| 冻结导入输入提交 | `d5ee82ff400cb907daa23ed2e3b332940ee92675` |
| 后置验收证明提交 | `399507271e739dbae7c138d31ad1113cbb6c712e` |

恢复得到规范 Work、Version、Person、机构、项目及关系数据，查询日志、任务、回执、证据、检查点、分片清单和七项导出：`ref.bib`、`ref.html`、`evidence_matrix.csv`、`research_entities.json`、`citation_graph.json`、`research_paths.json`、`research_implications.csv`。本批增量包括 5 个现有 Work 的字段补全、20 个以具体署名记录限定身份的 Person、7 条参考文献解析与对应引用边，以及 1 条 L03 主张。本包不含原始 PDF、受限全文或认证文件。

CP5 恢复的是完整工作树，`recovery.bundle` 只含 `95a0a218…` 之后的 Git 对象。因此**不能直接 `git clone recovery.bundle`**；必须先从真实 GitHub 仓库取得该 prerequisite。CP5 同步完成不表示 P3–P6 研究闭环完成，四阶段仍为 partial。

导入记录：[Actions 45848216143](https://github.com/ncut-d1z/Insect-Inspired/actions/runs/45848216143)。验收依据：[verification.json](verification.json)、[远端完整回读](remote-verification-cp5.json)、[实际手工恢复记录](manual-restore-validation.json)。原 Bash 恢复方法已在全新目录实际执行通过；以下 PowerShell 代码按 Windows PowerShell 5.1 / PowerShell 7 语法静态审阅，本环境没有 PowerShell 运行时，未声称已进行 PowerShell 实测。

## 2. 先执行一次：固定参数与失败即停

在主机打开 PowerShell。已安装 Git，并使用自己已有的 GitHub HTTPS 或 SSH 认证即可；本指南不要求 GitHub CLI。依次在**同一个 PowerShell 会话**运行本节、路径 A 或 B、保存证明、合并和清理各节。出现错误即停止，先检查原因，不跳过校验。

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$null = Get-Command git -ErrorAction Stop
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Cp5Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp5Commit = '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
$Cp5Tree = '27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
$Cp5Base = '95a0a218667333967f4a6c18f8b8b71df8b464e0'
$Cp4Main = 'bb7726c2ef334df0d7069165156b1cbc2c4e2fd8'
$Cp5InputCommit = 'd5ee82ff400cb907daa23ed2e3b332940ee92675'
$Cp5ProofCommit = '399507271e739dbae7c138d31ad1113cbb6c712e'
$Cp5ResearchRef = 'refs/heads/research/p3-p6-cp5'
$Cp5SyncRef = 'refs/heads/sync/cp5-checkpoint-import'
$Cp5Checkpoint = 'temp/snapshots/checkpoints/CP-0005.json'
$Cp5CheckpointHash = 'ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270'
$Cp5HostRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) ('insect-cp5-host-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp5HostRoot
$Cp5PackageDir = Join-Path $Cp5HostRoot 'package'
$Cp5AuditDir = Join-Path $Cp5HostRoot 'audit'

# Capture every external git exit code, including commands used in assignments.
function Invoke-GitChecked {
    $cp5NativeArgs = @($args)
    $cp5OldPreference = $ErrorActionPreference
    $cp5Exit = -1
    try {
        $ErrorActionPreference = 'Continue'
        & git @cp5NativeArgs
        $cp5Exit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $cp5OldPreference }
    if ($cp5Exit -ne 0) { throw ('git failed; exit code {0}. Stop here.' -f $cp5Exit) }
}
function Get-GitLine {
    $cp5Lines = @(Invoke-GitChecked @args)
    if ($cp5Lines.Count -ne 1) { throw 'Expected exactly one git output line.' }
    return ([string]$cp5Lines[0]).Trim()
}
function Assert-Cp5Equal {
    param($Actual, $Expected, [string]$Label)
    if ($Actual -ne $Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp5Clean {
    if (@(Invoke-GitChecked -C $Cp5Repo status --porcelain=v1 --untracked-files=all).Count -ne 0) {
        throw 'Working tree or index is not clean. Preserve your work before continuing.'
    }
}
function Get-Cp5RemoteRef {
    param([string]$Ref)
    $cp5Rows = @(Invoke-GitChecked -C $Cp5Repo ls-remote --heads origin $Ref)
    if ($cp5Rows.Count -eq 0) { return $null }
    if ($cp5Rows.Count -ne 1) { throw 'Unexpected remote ref count.' }
    $cp5Parts = ([string]$cp5Rows[0]) -split '\s+'
    if ($cp5Parts.Count -ne 2 -or $cp5Parts[0] -notmatch '^[0-9a-f]{40}$' -or $cp5Parts[1] -ne $Ref) {
        throw 'Unexpected remote ref response.'
    }
    return $cp5Parts[0]
}
function Assert-Cp5Origin {
    $cp5Origin = Get-GitLine -C $Cp5Repo remote get-url origin
    $cp5AllowedUrl = '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)ncut-d1z/Insect-Inspired(\.git)?/?$'
    if ($cp5Origin -notmatch $cp5AllowedUrl) {
        throw 'origin is not the expected GitHub repository.'
    }
    $cp5PushUrls = @(Invoke-GitChecked -C $Cp5Repo remote get-url --push --all origin)
    if ($cp5PushUrls.Count -ne 1 -or $cp5PushUrls[0] -notmatch $cp5AllowedUrl) {
        throw 'origin must have exactly one push URL for the expected GitHub repository.'
    }
}
function Assert-Cp5Hash {
    param([string]$Path, [string]$Hash)
    Assert-Cp5Equal ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()) $Hash $Path
}
function Assert-Cp5Snapshot {
    Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse HEAD) $Cp5Commit 'HEAD'
    Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse 'HEAD^{tree}') $Cp5Tree 'tree'
    Assert-Cp5Equal (Get-GitLine -C $Cp5Repo show -s --format=%P HEAD) $Cp5Base 'unique parent'
    Invoke-GitChecked -C $Cp5Repo fsck --full --strict $Cp5Commit
    Assert-Cp5Clean
    # git itself writes ZIP bytes; this avoids PowerShell redirection and CRLF conversion.
    $cp5CheckDir = Join-Path $Cp5HostRoot ('checkpoint-' + [Guid]::NewGuid().ToString('N'))
    $cp5CheckZip = $cp5CheckDir + '.zip'
    Invoke-GitChecked -C $Cp5Repo archive --format=zip ('--output=' + $cp5CheckZip) $Cp5Commit -- $Cp5Checkpoint
    Expand-Archive -LiteralPath $cp5CheckZip -DestinationPath $cp5CheckDir
    Assert-Cp5Hash (Join-Path $cp5CheckDir $Cp5Checkpoint) $Cp5CheckpointHash
    Write-Host ('CP5 commit/tree/parent/checkpoint/fsck/clean checks passed: ' + $Cp5Repo)
}
Write-Host ('Host package and evidence directory: ' + $Cp5HostRoot)
```

## 3A. 推荐：直接 fetch 已同步的研究分支

在已有 `Insect-Inspired` clone 内打开 PowerShell，然后运行本节。若没有 clone，把第一行改成 `$Cp5UseExistingClone = $false`，代码会在新建的独立目录 clone。已有工作树、暂存区或未跟踪文件不干净时会停止；代码不自动 stash、reset 或覆盖原有分支。

```powershell
$Cp5UseExistingClone = $true
if ($Cp5UseExistingClone) {
    $Cp5Repo = Get-GitLine rev-parse --show-toplevel
} else {
    $Cp5Repo = Join-Path $Cp5HostRoot 'repository'
    Invoke-GitChecked clone --no-tags --config core.autocrlf=false --config core.eol=lf $Cp5Url $Cp5Repo
}
Assert-Cp5Origin
Assert-Cp5Clean
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5ResearchRef) $Cp5Commit 'remote research tip'
Invoke-GitChecked -C $Cp5Repo fetch --no-tags origin $Cp5ResearchRef
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse FETCH_HEAD) $Cp5Commit 'fetched research tip'
$Cp5ReviewBranch = 'review-cp5-' + [Guid]::NewGuid().ToString('N')
Invoke-GitChecked -C $Cp5Repo checkout -b $Cp5ReviewBranch $Cp5Commit
Assert-Cp5Snapshot
```

这里 checkout 后得到完整 CP5 数据，后续直接执行第 4 节。一般无需执行路径 B。

## 3B. 备选：从固定增量 bundle 恢复到全新目录

本节可以代替 3A。输入按固定提交下载；当前操作指南即使后来更新，也不会改变原始输入校验。`Invoke-WebRequest -OutFile` 直接保存响应字节；不要使用 `git show ... > recovery.bundle`、`Out-File` 或 `Set-Content` 转存二进制。

```powershell
if (Test-Path -LiteralPath $Cp5PackageDir) { throw 'Package destination already exists. Start a fresh session/directory.' }
$null = New-Item -ItemType Directory -Path $Cp5PackageDir
$cp5InputBase = 'https://raw.githubusercontent.com/ncut-d1z/Insect-Inspired/' + $Cp5InputCommit + '/temp/sync/CP-0005/'
Invoke-WebRequest -UseBasicParsing -Uri ($cp5InputBase + 'manifest.json') -OutFile (Join-Path $Cp5PackageDir 'manifest.json')
Invoke-WebRequest -UseBasicParsing -Uri ($cp5InputBase + 'recovery.bundle') -OutFile (Join-Path $Cp5PackageDir 'recovery.bundle')
Invoke-WebRequest -UseBasicParsing -Uri ($cp5InputBase + 'README.md') -OutFile (Join-Path $Cp5PackageDir 'README.import-input.md')
$Cp5Bundle = Join-Path $Cp5PackageDir 'recovery.bundle'
Assert-Cp5Equal (Get-Item -LiteralPath $Cp5Bundle).Length 19638061 'bundle bytes'
Assert-Cp5Hash $Cp5Bundle '29eefe39d95fecd6cbcb909a8cc8242fed6bb168bd42452d3232d881a386738e'
Assert-Cp5Hash (Join-Path $Cp5PackageDir 'manifest.json') '4a9faedaaf9463346292a3d5fd18ae3e6373deef8a7668372957b02d9e92bd39'
Assert-Cp5Hash (Join-Path $Cp5PackageDir 'README.import-input.md') 'e47b4e9332f060742dac60ca7f2c2855ccc8dadb7b9c037fc3c7816d326055d3'
$cp5Manifest = Get-Content -LiteralPath (Join-Path $Cp5PackageDir 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp5Equal $cp5Manifest.expected_commit $Cp5Commit 'manifest commit'
Assert-Cp5Equal $cp5Manifest.expected_tree $Cp5Tree 'manifest tree'
Assert-Cp5Equal $cp5Manifest.expected_baseline_commit $Cp5Base 'manifest prerequisite'
Assert-Cp5Equal $cp5Manifest.expected_parent_commit $Cp5Base 'manifest parent'
Assert-Cp5Equal $cp5Manifest.target_ref $Cp5ResearchRef 'manifest target'
Assert-Cp5Equal (@($cp5Manifest.bundle_prerequisites) -join ',') $Cp5Base 'sole bundle prerequisite'
Assert-Cp5Hash (Join-Path $Cp5PackageDir 'README.import-input.md') $cp5Manifest.readme_sha256

$Cp5Repo = Join-Path $Cp5HostRoot 'restored-repository'
if (Test-Path -LiteralPath $Cp5Repo) { throw 'Recovery directory already exists; do not overwrite it.' }
Invoke-GitChecked clone --no-checkout --no-tags --config core.autocrlf=false --config core.eol=lf $Cp5Url $Cp5Repo
Assert-Cp5Origin
# Fetch the real GitHub prerequisite before inspecting/importing the incremental bundle.
Invoke-GitChecked -C $Cp5Repo fetch --no-tags origin $Cp5Base
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse FETCH_HEAD) $Cp5Base 'actual remote baseline'
Invoke-GitChecked -C $Cp5Repo bundle verify $Cp5Bundle
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo bundle list-heads $Cp5Bundle) ($Cp5Commit + ' ' + $Cp5ResearchRef) 'bundle head'
Invoke-GitChecked -C $Cp5Repo fetch --no-tags $Cp5Bundle ($Cp5ResearchRef + ':refs/heads/restored-cp5')
Invoke-GitChecked -C $Cp5Repo checkout restored-cp5
Assert-Cp5Snapshot
```

这是新目录和新本地分支，不写远端。恢复检查成功后，第 4–7 节可以直接沿用此 `$Cp5Repo`。

## 4. 删除临时分支前，先保存固定验收证明

九份证明固定在 `399507271e739dbae7c138d31ad1113cbb6c712e`。它们是导入之后增加的文件，不在 CP5 研究提交中。下面从真实 GitHub fetch 该提交，使用 Git 原生 `archive --output` 归档**明确列出的九个文件**，并校验 `verification.json` 中记录的其余八份证明哈希。同步分支当前 tip 也会记录，用于后面的条件删除。

```powershell
Assert-Cp5Origin
Assert-Cp5Clean
if (Test-Path -LiteralPath $Cp5AuditDir) { throw 'Audit destination already exists; keep it and use a fresh session.' }
$Cp5SavedSyncTip = Get-Cp5RemoteRef $Cp5SyncRef
if ($null -eq $Cp5SavedSyncTip) { throw 'Transport branch is absent; inspect existing archives before proceeding.' }
Invoke-GitChecked -C $Cp5Repo fetch --no-tags origin $Cp5SyncRef
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse FETCH_HEAD) $Cp5SavedSyncTip 'fetched transport tip'
Invoke-GitChecked -C $Cp5Repo fetch --no-tags origin $Cp5ProofCommit
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse FETCH_HEAD) $Cp5ProofCommit 'fetched proof commit'
Invoke-GitChecked -C $Cp5Repo merge-base --is-ancestor $Cp5ProofCommit $Cp5SavedSyncTip
$Cp5ProofNames = @(
    'verification.json', 'local-integrity-cp5.json', 'remote-verification-cp5.json',
    'manual-restore-validation.json', 'manual-restore-commands.sh', 'manual-restore-commands.log',
    'action-run-cp5.json', 'action-job-cp5.log', 'upload-byte-verification.json'
)
$Cp5ProofPaths = @($Cp5ProofNames | ForEach-Object { 'temp/sync/CP-0005/' + $_ })
$Cp5ProofZip = Join-Path $Cp5HostRoot 'cp5-verification-documents.zip'
Invoke-GitChecked -C $Cp5Repo archive --format=zip ('--output=' + $Cp5ProofZip) $Cp5ProofCommit -- @Cp5ProofPaths
Expand-Archive -LiteralPath $Cp5ProofZip -DestinationPath $Cp5AuditDir
$Cp5ProofDir = Join-Path $Cp5AuditDir 'temp/sync/CP-0005'
$cp5Proof = Get-Content -LiteralPath (Join-Path $Cp5ProofDir 'verification.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp5Equal $cp5Proof.status 'passed' 'verification status'
Assert-Cp5Equal $cp5Proof.canonical_commit $Cp5Commit 'verified CP5 commit'
foreach ($cp5Name in $Cp5ProofNames) {
    $cp5File = Join-Path $Cp5ProofDir $cp5Name
    if (-not (Test-Path -LiteralPath $cp5File -PathType Leaf)) { throw ('Missing proof: ' + $cp5Name) }
    if ($cp5Name -ne 'verification.json') {
        $cp5Entry = @($cp5Proof.evidence_files | Where-Object { $_.path -eq $cp5Name })
        Assert-Cp5Equal $cp5Entry.Count 1 ('proof hash entry: ' + $cp5Name)
        Assert-Cp5Equal (Get-Item -LiteralPath $cp5File).Length $cp5Entry[0].bytes ('proof size: ' + $cp5Name)
        Assert-Cp5Hash $cp5File $cp5Entry[0].sha256
    }
}
# Check the actual checkout bytes as well as the Git objects (important on Windows).
$cp5Inventory = Get-Content -LiteralPath (Join-Path $Cp5ProofDir 'local-integrity-cp5.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Cp5Equal $cp5Inventory.status 'passed' 'trusted inventory status'
Assert-Cp5Equal $cp5Inventory.head_commit $Cp5Commit 'trusted inventory commit'
Assert-Cp5Equal $cp5Inventory.head_tree $Cp5Tree 'trusted inventory tree'
Assert-Cp5Equal (@($cp5Inventory.verified_files).Count) 1188 'trusted inventory file count'
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse HEAD) $Cp5Commit 'checkout before byte verification'
foreach ($cp5ExpectedFile in $cp5Inventory.verified_files) {
    $cp5ActualFile = Join-Path $Cp5Repo $cp5ExpectedFile.path
    if (-not (Test-Path -LiteralPath $cp5ActualFile -PathType Leaf)) {
        throw ('Missing CP5 file: ' + $cp5ExpectedFile.path)
    }
    if ((Get-Item -LiteralPath $cp5ActualFile).Length -ne $cp5ExpectedFile.bytes -or
        (Get-FileHash -LiteralPath $cp5ActualFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cp5ExpectedFile.sha256) {
        throw ('Checkout byte mismatch: ' + $cp5ExpectedFile.path + '. Stop. Preserve this clone; start a new session and use path A with $Cp5UseExistingClone = $false to get an LF checkout.')
    }
}
Assert-Cp5Clean
Write-Host 'All 1188 actual checkout files match the independently verified byte counts and SHA256 hashes.'
$cp5ArchiveRecord = [ordered]@{
    proof_commit = $Cp5ProofCommit; transport_tip = $Cp5SavedSyncTip; cp5_commit = $Cp5Commit
    archive_sha256 = (Get-FileHash -LiteralPath $Cp5ProofZip -Algorithm SHA256).Hash.ToLowerInvariant()
    files = @($Cp5ProofNames | ForEach-Object {
        [ordered]@{ name = $_; sha256 = (Get-FileHash -LiteralPath (Join-Path $Cp5ProofDir $_) -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
}
[IO.File]::WriteAllText((Join-Path $Cp5AuditDir 'host-archive-record.json'), ($cp5ArchiveRecord | ConvertTo-Json -Depth 6), ([Text.UTF8Encoding]::new($false)))
$Cp5AuditSaved = $true
Write-Host ('Verified evidence archive: ' + $Cp5AuditDir)
```

本节还会用已校验的 1.4 MB 文件清单检查实际工作树的全部 1,188 个文件。已有 Windows clone 的换行转换可能导致 Git 状态干净、对象正确但本地文件字节不同；遇到该情况时停止，保留原仓库，在新 PowerShell 会话中改用路径 A 的 `$Cp5UseExistingClone = $false`。不要通过自动 reset 或批量换行改写来覆盖原有文件。

请保留 `$Cp5AuditDir` 和 `$Cp5ProofZip`。若只在主机归档而不执行下一节的可选证明提交，删除同步分支后，这些验收文件不会出现在 `main` 中；不要把失去分支引用的旧提交链接当作持久归档承诺。

## 5. 用户在主机上 fast-forward 合并 main 并推送

本节开始会修改用户的本地 `main`，并将 CP5 推送到 GitHub `main`。仅接受远端 main 为上表 CP4 或已是精确 CP5。已有本地 main 若落后于刚读取的远端 main，会先 fast-forward 更新；若超前或分叉则停止，保留现有提交。两次合并均使用 `--ff-only`。推送为普通非强制推送，受仓库权限和分支保护约束。

```powershell
Assert-Cp5Origin
Assert-Cp5Clean
if (-not $Cp5AuditSaved) { throw 'Save the audit evidence before proceeding.' }
$Cp5MainBefore = Get-Cp5RemoteRef 'refs/heads/main'
if ($Cp5MainBefore -ne $Cp4Main -and $Cp5MainBefore -ne $Cp5Commit) {
    throw 'Remote main changed from the documented CP4/CP5 state. Stop and inspect.'
}
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5ResearchRef) $Cp5Commit 'remote research tip before merge'
Invoke-GitChecked -C $Cp5Repo fetch --no-tags origin refs/heads/main
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse FETCH_HEAD) $Cp5MainBefore 'fetched main'
Invoke-GitChecked -C $Cp5Repo merge-base --is-ancestor $Cp5MainBefore $Cp5Commit
$cp5LocalMain = @(Invoke-GitChecked -C $Cp5Repo for-each-ref '--format=%(refname)' refs/heads/main)
if ($cp5LocalMain.Count -eq 0) {
    Invoke-GitChecked -C $Cp5Repo checkout -b main $Cp5MainBefore
} elseif ($cp5LocalMain.Count -eq 1 -and $cp5LocalMain[0] -eq 'refs/heads/main') {
    Invoke-GitChecked -C $Cp5Repo merge-base --is-ancestor refs/heads/main $Cp5MainBefore
    Invoke-GitChecked -C $Cp5Repo checkout main
    Invoke-GitChecked -C $Cp5Repo merge --ff-only $Cp5MainBefore
} else { throw 'Unexpected local main ref state.' }
Invoke-GitChecked -C $Cp5Repo merge --ff-only $Cp5Commit
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse HEAD) $Cp5Commit 'merged local main'
Assert-Cp5Clean
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5MainBefore 'remote main immediately before push'
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5ResearchRef) $Cp5Commit 'research immediately before push'
Invoke-GitChecked -C $Cp5Repo push origin 'HEAD:refs/heads/main'
$Cp5ExpectedMain = $Cp5Commit
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'remote main after push'
```

### 可选：把九份可读验收证明也提交到 main

希望证明在临时分支删除后仍可从主仓库找到时，运行下面这一块。只复制九个明确列出的验收文件到 `temp/validation/cp5-remote-sync/`；不复制 bundle、workflow 或 manifest，也不合并运输分支。跳过这一块时，主机归档仍保留，但 main 只含原 CP5 研究快照。

```powershell
Assert-Cp5Clean
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo branch --show-current) 'main' 'current branch'
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse HEAD) $Cp5Commit 'main before audit-only addition'
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'remote main before audit-only addition'
$cp5AuditRelativeDir = 'temp/validation/cp5-remote-sync'
$cp5PublishDir = Join-Path $Cp5Repo $cp5AuditRelativeDir
if (Test-Path -LiteralPath $cp5PublishDir) { throw 'Audit publication directory already exists. Do not overwrite it.' }
$null = New-Item -ItemType Directory -Path $cp5PublishDir
foreach ($cp5Name in $Cp5ProofNames) {
    Copy-Item -LiteralPath (Join-Path $Cp5ProofDir $cp5Name) -Destination (Join-Path $cp5PublishDir $cp5Name)
}
$cp5PublishPaths = @($Cp5ProofNames | ForEach-Object { $cp5AuditRelativeDir + '/' + $_ })
Invoke-GitChecked -C $Cp5Repo -c core.autocrlf=false add -- @cp5PublishPaths
$cp5Staged = @(Invoke-GitChecked -C $Cp5Repo diff --cached --name-only)
Assert-Cp5Equal (($cp5Staged | Sort-Object) -join "`n") (($cp5PublishPaths | Sort-Object) -join "`n") 'exact audit-only staged paths'
Invoke-GitChecked -C $Cp5Repo commit -m 'Record CP5 remote synchronization verification'
$cp5AuditCommit = Get-GitLine -C $Cp5Repo rev-parse HEAD
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo show -s --format=%P HEAD) $Cp5Commit 'audit-only direct parent'
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'remote main immediately before audit push'
Invoke-GitChecked -C $Cp5Repo push origin 'HEAD:refs/heads/main'
$Cp5ExpectedMain = $cp5AuditCommit
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'remote audit-only main'
Assert-Cp5Clean
```

## 6. 用户在主机上条件删除两条临时远端分支

先确认远端 main 仍是刚推送并验收的提交，且 CP5 是其祖先，再删除两个明确命名的临时分支。精确 SHA lease **只用于这两条分支的条件删除**，并以 `--atomic` 保证两项同时成功或同时失败；任何分支在检查后被其他人更新，删除都会被拒绝。这里没有通配符、宽泛 `--force`、main 强制更新或删除。

```powershell
Assert-Cp5Origin
Assert-Cp5Clean
if (-not $Cp5AuditSaved -or -not (Test-Path -LiteralPath (Join-Path $Cp5AuditDir 'host-archive-record.json'))) {
    throw 'Verified local audit archive is required before deleting transport refs.'
}
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'main before deletion'
Invoke-GitChecked -C $Cp5Repo fetch --no-tags origin refs/heads/main
Assert-Cp5Equal (Get-GitLine -C $Cp5Repo rev-parse FETCH_HEAD) $Cp5ExpectedMain 'fetched main before deletion'
Invoke-GitChecked -C $Cp5Repo merge-base --is-ancestor $Cp5Commit $Cp5ExpectedMain
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5ResearchRef) $Cp5Commit 'research deletion expected tip'
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5SyncRef) $Cp5SavedSyncTip 'transport deletion expected tip'
Invoke-GitChecked -C $Cp5Repo push --atomic `
    ('--force-with-lease=' + $Cp5ResearchRef + ':' + $Cp5Commit) `
    ('--force-with-lease=' + $Cp5SyncRef + ':' + $Cp5SavedSyncTip) `
    origin (':' + $Cp5ResearchRef) (':' + $Cp5SyncRef)
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5ResearchRef) $null 'research branch removed'
Assert-Cp5Equal (Get-Cp5RemoteRef $Cp5SyncRef) $null 'transport branch removed'
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'main retained after deletion'
Write-Host 'The two named remote temporary branches are removed; verified main is retained.'
```

若 lease、atomic、权限或分支保护检查失败，就停止，不去掉保护参数重试，不强制推送。若远端分支已不存在，也先确认是否由你或其他操作者完成了清理。

## 7. 可选：删除主机下载包，保留数据和证明

仅路径 B 会创建本节要删除的 `package` 子目录。以下清理只删除本会话创建的下载包（bundle、manifest、原始 README），不删除恢复出的仓库、验收证明、归档 ZIP 或任何远端内容。若希望保留离线恢复材料，可完全跳过。

```powershell
Assert-Cp5Equal (Get-Cp5RemoteRef 'refs/heads/main') $Cp5ExpectedMain 'verified main before local package cleanup'
Invoke-GitChecked -C $Cp5Repo merge-base --is-ancestor $Cp5Commit $Cp5ExpectedMain
if (-not $Cp5AuditSaved) { throw 'Keep the verification evidence before package cleanup.' }
if (Test-Path -LiteralPath $Cp5PackageDir) {
    Assert-Cp5Equal ([IO.Path]::GetFullPath($Cp5PackageDir)) ([IO.Path]::GetFullPath((Join-Path $Cp5HostRoot 'package'))) 'exact package cleanup path'
    Remove-Item -LiteralPath $Cp5PackageDir -Recurse
}
Write-Host ('Keep the restored data at: ' + $Cp5Repo)
Write-Host ('Keep verification evidence at: ' + $Cp5AuditDir)
Write-Host ('Keep verification ZIP at: ' + $Cp5ProofZip)
```

## 说明来源

Git 官方文档说明 [增量 bundle 的 prerequisite 与 verify](https://git-scm.com/docs/git-bundle)、[fast-forward-only 合并](https://git-scm.com/docs/git-merge) 和 [精确 lease / atomic push](https://git-scm.com/docs/git-push)。Microsoft 文档说明 [Get-FileHash](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1) 与 [PowerShell 重定向](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection?view=powershell-5.1)。本指南直接把下载及 Git archive 写到文件，不依赖 PowerShell 文本管道保存原始二进制。
