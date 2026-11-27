#!/usr/bin/env python3
"""Prepare the frozen CP7 increment outside the canonical repository; never push.

python -B scripts/prepare_cp7_transport.py --repo PATH --base-commit SHA \
    --target-commit SHA --output-dir OUTSIDE_REPO [--part-size-bytes 524288]
Run only after the valid CP7 checkpoint and this script are committed.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import textwrap

REPOSITORY = "ncut-d1z/Insect-Inspired"
REMOTE = "https://github.com/" + REPOSITORY + ".git"
TARGET = "refs/heads/research/p3-p6-cp7"
SYNC = "refs/heads/sync/cp7-checkpoint-import"
CP6 = "a1303b6b6c38692b4f57da5cfb342289c6dc17e5"
CHECKPOINT = "temp/snapshots/checkpoints/CP-0007.json"
PARTITIONS = "temp/partitions/manifest.json"
PACKAGE = "temp/sync/CP-0007"
TEMPLATE = "temp/validation/cp6-sync-tools/import-cp6.template.yml"
TEMPLATE_SHA256 = "7db6ea4269d24c8d0682c4cc0faabcaff463a98f72de08b77b9792ced3682ab0"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
         "-c", "core.fsmonitor=false", "-c", "gc.auto=0", *args])


def line(repo, *args):
    return git(repo, *args).decode().strip()


def safe_path(path):
    require(isinstance(path, str) and path and "\\" not in path
            and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts, "Unsafe path: " + str(path))
    return path


def header(bundle, base, target):
    with bundle.open("rb") as stream:
        require(stream.readline() == b"# v2 git bundle\n", "Expected SHA-1 bundle v2")
        lines = []
        while True:
            item = stream.readline(65537)
            require(item and len(item) <= 65536, "Invalid bundle header")
            if item == b"\n":
                break
            lines.append(item.decode().rstrip("\n"))
    prerequisites = [x[1:].split(" ", 1)[0] for x in lines if x.startswith("-")]
    heads = [x for x in lines if not x.startswith("-")]
    require(prerequisites == [base], "Bundle must have exactly the requested prerequisite")
    require(heads == [target + " " + TARGET], "Bundle advertises unexpected refs")


def snapshot(repo, commit):
    entries = {}
    for item in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not item:
            continue
        meta, name = item.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        path = safe_path(name.decode())
        require(kind == "blob" and mode in ("100644", "100755"), "Unsupported tree mode")
        entries[path] = oid
    require(not any(p.startswith(PACKAGE + "/") or p == ".github/workflows/import-cp7.yml"
                    for p in entries), "Transport files must not enter the canonical CP7 tree")
    require({p for p in entries if p.endswith("/partitions/manifest.json")} == {PARTITIONS},
            "Inspect additional partition manifests before adapting this bounded CP7 tool")
    reader = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def blob(path):
        reader.stdin.write((entries[path] + "\n").encode())
        reader.stdin.flush()
        oid, kind, size = reader.stdout.readline().decode().split()
        require(oid == entries[path] and kind == "blob", "Unexpected blob response")
        data = reader.stdout.read(int(size))
        require(len(data) == int(size) and reader.stdout.read(1) == b"\n", "Truncated blob")
        return data

    try:
        cp_raw = blob(CHECKPOINT)
        cp = json.loads(cp_raw)
        require(cp["checkpoint_id"] == "CP-0007" and cp["parent_checkpoint_id"] == "CP-0006"
                and cp["scope_id"] == "SCOPE-0001" and cp["status"] == "valid",
                "A valid frozen CP7 checkpoint is required")
        hashes = cp["artifact_hashes"]
        require(set(hashes) | {CHECKPOINT} == set(entries) and CHECKPOINT not in hashes,
                "Checkpoint hashes do not cover every tree file except self")
        total = len(cp_raw)
        for path, expected in hashes.items():
            data = blob(path)
            require(sha(data) == expected, "Artifact SHA256 differs: " + path)
            total += len(data)
        pm_raw = blob(PARTITIONS)
        pm = json.loads(pm_raw)
        seen = set()
        for name, dataset in pm["datasets"].items():
            digest, records = hashlib.sha256(), 0
            require(dataset["parts"] and dataset["parts"][0]["path"] == name,
                    "Unexpected logical dataset layout")
            for part in dataset["parts"]:
                path = "temp/" + safe_path(part["path"])
                require(path not in seen, "Repeated partition")
                seen.add(path)
                data = blob(path)
                require(len(data) == part["bytes"] and sha(data) == part["sha256"]
                        and len(data.splitlines()) == part["records"], "Partition differs: " + path)
                digest.update(data)
                records += part["records"]
            require(digest.hexdigest() == dataset["logical_sha256"]
                    and records == dataset["logical_records"], "Logical dataset differs: " + name)
        require({p for p in entries if p.startswith("temp/partitions/") and p.endswith(".jsonl")}
                <= seen, "Unlisted logical partition")
        template = blob(TEMPLATE)
        require(sha(template) == TEMPLATE_SHA256, "Published CP6 template changed")
        return {
            "checkpoint_sha256": sha(cp_raw), "canonical_file_count": len(entries),
            "canonical_file_bytes": total, "artifact_hash_count": len(hashes),
            "partition_dataset_count": len(pm["datasets"]),
            "partition_manifest_sha256": sha(pm_raw),
        }, template.decode()
    finally:
        reader.stdin.close()
        reader.stdout.close()
        require(reader.wait() == 0, "Git blob reader failed")


PART_INPUT = r'''
assert m['bundle_storage'] == 'ordered_binary_parts'
assert m['part_size_bytes'] == int('__PART_SIZE_BYTES__')
parts = m['parts']
assert isinstance(parts, list) and len(parts) == int('__PART_COUNT__')
paths, declared = set(), 0
for ordinal, part in enumerate(parts, 1):
    assert type(part['index']) is int and part['index'] == ordinal
    expected_path = 'parts/recovery.bundle.part-'+format(ordinal, '04d')
    assert part['path'] == expected_path and expected_path not in paths
    assert type(part['bytes']) is int and 0 < part['bytes'] <= m['part_size_bytes']
    assert ordinal == len(parts) or part['bytes'] == m['part_size_bytes']
    assert re.fullmatch('[0-9a-f]{64}', part['sha256'])
    paths.add(expected_path)
    declared += part['bytes']
assert declared == m['bundle_bytes']
prefix = 'temp/sync/CP-0007/parts/'
actual = subprocess.check_output(['git', '--git-dir='+repo, 'ls-tree', '-r',
                                 '-z', '--name-only', commit, '--', prefix])
assert {x.decode()[len('temp/sync/CP-0007/'):] for x in actual.split(b'\0') if x} == paths
digest, size = hashlib.sha256(), 0
with open(output, 'xb') as stream:
    for part in parts:
        chunk = blob(part['path'])
        assert len(chunk) == part['bytes']
        assert hashlib.sha256(chunk).hexdigest() == part['sha256']
        stream.write(chunk)
        digest.update(chunk)
        size += len(chunk)
assert size == m['bundle_bytes'] and digest.hexdigest() == m['bundle_sha256']
with open(output, 'rb') as stream:
    assert stream.readline() == b'# v2 git bundle\n'
    lines = []
    while True:
        item = stream.readline(65537)
        assert item and len(item) <= 65536
        if item == b'\n':
            break
        lines.append(item.decode().rstrip('\n'))
assert [x[1:].split(' ', 1)[0] for x in lines if x.startswith('-')] == [base]
assert [x for x in lines if not x.startswith('-')] == [cp7+' '+target]
print(json.dumps({'stage':'verified_transport', 'parts':len(parts),
                  'bundle_bytes':size, 'bundle_sha256':digest.hexdigest(),
                  'manifest_sha256':'__CP7_MANIFEST_SHA256__'}))
'''


README = r'''# CP7 增量数据恢复与主机合并

此目录保存 __PART_COUNT__ 个原始二进制块，默认每块 512 KiB；实际块大小以 manifest.json 为准。按清单顺序拼接可恢复 recovery.bundle。增量仅声明 research/p3-p6-cp7，必须先取得 prerequisite __BASE_SHA__。目标提交 __CP7_SHA__，树 __CP7_TREE__，直接 Git 父提交 __PARENT_SHA__；检查点父项为 CP-0006。分块、manifest、此说明和导入 workflow 位于独立 sync 分支，不进入研究快照。

Actions 只接受固定仓库、固定 sync ref 和这些已冻结字节；普通 fast-forward 更新 research/p3-p6-cp7，随后从 GitHub 新建独立仓库回读全部 artifact SHA256 和分区逻辑哈希。成功摘要及验证阶段记录见对应 Actions run 的日志。主机恢复无需执行仓库里的 Python 代码。

以下适用于 Windows PowerShell 5.1 或更新版本及 Git。先把 $Cp7Repo 改成你的现有仓库绝对路径，在同一个 PowerShell 会话依次运行。命令在仓库外建立独立恢复目录；不把运输分支合并到 main。Git 操作失败就停止，保留现场。

## 1. 拉取两个分支并提取包

~~~powershell
$ErrorActionPreference = 'Stop'
$Cp7Repo = 'C:\path\to\Insect-Inspired'
$Cp7Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp7ResearchRef = 'refs/heads/research/p3-p6-cp7'
$Cp7SyncRef = 'refs/heads/sync/cp7-checkpoint-import'
$Cp7Base = '__BASE_SHA__'
$Cp7Commit = '__CP7_SHA__'
$Cp7Parent = '__PARENT_SHA__'
$Cp7Tree = '__CP7_TREE__'
$Cp7BundleHash = '__CP7_BUNDLE_SHA256__'
$Cp7CheckpointHash = '__CP7_CHECKPOINT_SHA256__'
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
Assert-Cp7Equal $Cp7Manifest.bundle_bytes __CP7_BUNDLE_SIZE_BYTES__ 'bundle length'
Assert-Cp7Equal (@($Cp7Manifest.bundle_prerequisites) -join ',') $Cp7Base 'sole prerequisite'
Assert-Cp7Hash (Join-Path $Cp7PackageData 'README.md') $Cp7Manifest.readme_sha256
~~~

## 2. 逐片核验、流式拼接及 bundle prerequisite 检查

~~~powershell
$Cp7Parts = @($Cp7Manifest.parts)
Assert-Cp7Equal $Cp7Parts.Count __PART_COUNT__ 'part count'
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
Assert-Cp7Equal $Cp7PartBytes __CP7_BUNDLE_SIZE_BYTES__ 'sum of part lengths'
Assert-Cp7Equal (Get-Item -LiteralPath $Cp7Bundle).Length __CP7_BUNDLE_SIZE_BYTES__ 'assembled length'
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
Assert-Cp7Equal (@($Cp7Checkpoint.artifact_hashes.PSObject.Properties).Count) __CP7_ARTIFACT_HASH_COUNT__ 'artifact count'
Assert-Cp7Equal (@(Invoke-Cp7Git ls-tree -r --name-only $Cp7Commit).Count) __CP7_FILE_COUNT__ 'tree file count'
foreach ($cp7Artifact in $Cp7Checkpoint.artifact_hashes.PSObject.Properties) {
    if ([IO.Path]::IsPathRooted($cp7Artifact.Name) -or $cp7Artifact.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe artifact path' }
    Assert-Cp7Hash (Join-Path $Cp7VerifiedTree $cp7Artifact.Name) ([string]$cp7Artifact.Value)
}
$Cp7Evidence = [ordered]@{
    status = 'passed'; target_commit = $Cp7Commit; target_tree = $Cp7Tree
    sync_commit = $Cp7SyncTip; bundle_sha256 = $Cp7BundleHash
    manifest_sha256 = (Get-FileHash -LiteralPath $Cp7ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    canonical_files = __CP7_FILE_COUNT__; checkpoint_sha256 = $Cp7CheckpointHash
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
'''


def fill(text, values):
    for name, value in values.items():
        text = text.replace("__" + name + "__", str(value))
    require(not re.search(r"__[A-Z][A-Z0-9_]+__", text), "Unfilled frozen placeholder")
    return text


def once(text, old, new):
    require(text.count(old) == 1, "CP6 template anchor differs: " + old[:70])
    return text.replace(old, new, 1)


def workflow(template, values):
    result = template.replace("CP6", "CP7").replace("cp6", "cp7")
    result = result.replace("CP-0006", "CP-0007").replace("CP-0005", "CP-0006")
    result = result.replace("Import reviewed CP7 increment", "Import reviewed CP7 chunked increment")
    result = result.replace("Fixed upload commit and fixed three-file directory",
                            "Fixed upload commit, manifest, README and ordered binary parts")
    result = once(result, "assert m['expected_baseline_commit'] == m['expected_parent_commit'] == base",
                  "assert m['expected_baseline_commit'] == base\n"
                  "          assert m['expected_parent_commit'] == '__PARENT_SHA__'")
    start = result.index("          data = blob('recovery.bundle')\n")
    end = result.index("          PYINPUT\n", start)
    result = result[:start] + textwrap.indent(PART_INPUT.strip() + "\n", "          ") + result[end:]
    result = once(result, '[[ "$(git --git-dir="$git_dir" show -s --format=%P "$CP7")" == "$BASE" ]]',
                  '[[ "$(git --git-dir="$git_dir" show -s --format=%P "$CP7")" == "__PARENT_SHA__" ]]')
    result = once(result, "'Direct parent: " + chr(96) + "__BASE_SHA__" + chr(96) + "'",
                  "'Direct parent: " + chr(96) + "__PARENT_SHA__" + chr(96) + "'")
    result = once(result, "          pm_raw = read_blob('temp/partitions/manifest.json')",
                  "          assert {p for p in entries if p.endswith('/partitions/manifest.json')} == {'temp/partitions/manifest.json'}\n"
                  "          pm_raw = read_blob('temp/partitions/manifest.json')")
    result = once(result, "          for name, dataset in pm['datasets'].items():",
                  "          all_parts = set()\n          for name, dataset in pm['datasets'].items():")
    result = once(result, "                  seen.add(part['path'])",
                  "                  seen.add(part['path'])\n"
                  "                  assert 'temp/'+part['path'] not in all_parts\n"
                  "                  all_parts.add('temp/'+part['path'])")
    result = once(result, "          reader.stdin.close()",
                  "          assert {p for p in entries if p.startswith('temp/partitions/') and p.endswith('.jsonl')} <= all_parts\n"
                  "          reader.stdin.close()")
    result = once(result, "          print('Verified every canonical file, CP7 self hash, and all complete partitioned logical datasets.')",
                  "          print(json.dumps({'stage':'verified_snapshot', 'independent_remote_readback':repo.endswith('remote-verify.git'),"
                  " 'commit':commit, 'tree':'__CP7_TREE__', 'canonical_files':len(entries),"
                  " 'artifact_hashes':len(hashes), 'logical_datasets':len(pm['datasets']),"
                  " 'partition_files':len(all_parts), 'checkpoint_sha256':'__CP7_CHECKPOINT_SHA256__'}))")
    return fill(result, values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--part-size-bytes", type=int, default=512 * 1024)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output_dir.resolve()
    require(all(re.fullmatch("[0-9a-f]{40}", x) for x in [args.base_commit, args.target_commit]),
            "Use full lowercase 40-character commit IDs")
    require(4096 <= args.part_size_bytes <= 8 * 1024 * 1024, "Part size must be 4 KiB to 8 MiB")
    require(not output.is_relative_to(repo) and not repo.is_relative_to(output),
            "Output must be a separate directory outside the repository")
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())),
            "Output directory must be absent or empty")
    require(line(repo, "rev-parse", "--show-toplevel") == str(repo), "--repo must name the repository root")
    require(line(repo, "rev-parse", "--show-object-format") == "sha1", "Expected SHA-1 Git repository")
    require(line(repo, "rev-parse", "--is-shallow-repository") == "false", "Full prerequisite history required")
    require(not git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "Canonical worktree must be clean")
    require(line(repo, "rev-parse", "HEAD") == args.target_commit
            and line(repo, "rev-parse", TARGET) == args.target_commit, "Freeze HEAD and the CP7 ref at target")
    require(args.base_commit != args.target_commit, "Increment must advance its prerequisite")
    git(repo, "merge-base", "--is-ancestor", CP6, args.base_commit)
    git(repo, "merge-base", "--is-ancestor", args.base_commit, args.target_commit)
    parent = line(repo, "show", "-s", "--format=%P", args.target_commit)
    require(bool(re.fullmatch("[0-9a-f]{40}", parent)), "CP7 must have one frozen direct Git parent")
    stats, template = snapshot(repo, args.target_commit)
    tree = line(repo, "show", "-s", "--format=%T", args.target_commit)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cp7-build-", dir=output.parent) as scratch:
        scratch = Path(scratch)
        bundle = scratch / "recovery.bundle"
        git(repo, "bundle", "create", "--version=2", str(bundle), TARGET, "^" + args.base_commit)
        header(bundle, args.base_commit, args.target_commit)
        git(repo, "bundle", "verify", str(bundle))
        require(line(repo, "bundle", "list-heads", str(bundle)) == args.target_commit + " " + TARGET,
                "Unexpected bundle ref")
        staged = scratch / "prepared"
        package = staged / PACKAGE
        (package / "parts").mkdir(parents=True)
        parts, digest, size = [], hashlib.sha256(), 0
        with bundle.open("rb") as stream:
            while chunk := stream.read(args.part_size_bytes):
                ordinal = len(parts) + 1
                name = "parts/recovery.bundle.part-" + format(ordinal, "04d")
                (package / name).write_bytes(chunk)
                parts.append({"index": ordinal, "path": name, "bytes": len(chunk), "sha256": sha(chunk)})
                digest.update(chunk)
                size += len(chunk)
        values = {"BASE_SHA": args.base_commit, "PARENT_SHA": parent, "CP7_SHA": args.target_commit,
                  "CP7_TREE": tree, "CP7_BUNDLE_SIZE_BYTES": size, "CP7_BUNDLE_SHA256": digest.hexdigest(),
                  "PART_COUNT": len(parts), "PART_SIZE_BYTES": args.part_size_bytes,
                  "CP7_CHECKPOINT_SHA256": stats["checkpoint_sha256"],
                  "CP7_FILE_COUNT": stats["canonical_file_count"],
                  "CP7_ARTIFACT_HASH_COUNT": stats["artifact_hash_count"],
                  "CP7_PARTITION_DATASET_COUNT": stats["partition_dataset_count"],
                  "CP7_PARTITION_MANIFEST_SHA256": stats["partition_manifest_sha256"]}
        readme = fill(README, values).encode()
        (package / "README.md").write_bytes(readme)
        manifest = {"format_version": 1, "repository": REPOSITORY, "checkpoint_id": "CP-0007",
                    "scope_id": "SCOPE-0001", "source_sync_ref": SYNC, "target_ref": TARGET,
                    "expected_baseline_commit": args.base_commit, "expected_parent_commit": parent,
                    "expected_commit": args.target_commit, "expected_tree": tree,
                    "parent_checkpoint_id": "CP-0006", "checkpoint_path": CHECKPOINT,
                    "bundle_kind": "incremental", "bundle_name": "recovery.bundle",
                    "bundle_prerequisites": [args.base_commit], "bundle_bytes": size,
                    "bundle_sha256": digest.hexdigest(), "bundle_storage": "ordered_binary_parts",
                    "part_size_bytes": args.part_size_bytes, "parts": parts,
                    "readme_sha256": sha(readme), **stats}
        raw_manifest = encoded(manifest)
        (package / "manifest.json").write_bytes(raw_manifest)
        values.update(CP7_MANIFEST_SHA256=sha(raw_manifest), CP7_README_SHA256=sha(readme))
        workflow_path = staged / ".github/workflows/import-cp7.yml"
        workflow_path.parent.mkdir(parents=True)
        workflow_path.write_text(workflow(template, values), encoding="utf-8")
        (staged / ".gitattributes").write_text("/temp/sync/CP-0007/parts/* -text -diff\n", encoding="utf-8")
        require(line(repo, "rev-parse", "HEAD") == args.target_commit
                and not git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
                "Canonical repository changed during preparation")
        if output.exists():
            require(not any(output.iterdir()), "Output changed during preparation")
            output.rmdir()
        staged.rename(output)
    print(json.dumps({"status": "prepared_not_uploaded", "output_dir": str(output),
                      "target_commit": args.target_commit, "base_commit": args.base_commit,
                      "expected_parent_commit": parent, "bundle_bytes": size, "parts": len(parts),
                      "manifest_sha256": sha(raw_manifest), "canonical_repository_modified": False,
                      "network_requests": 0,
                      "upload_order": "Publish parts, README and manifest first; publish workflow last to trigger import.",
                      "remote_research_requirement": "The remote CP7 research ref must equal base or target; otherwise workflow stops."},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
