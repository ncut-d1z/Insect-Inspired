#!/usr/bin/env python3
"""Prepare a frozen CP8 incremental package outside the research repository.

Run only after valid CP8, all QA and this script have been committed and the
canonical worktree is clean. This tool does not fetch, push, edit refs, generate
or run Actions, execute project hooks, or claim remote synchronization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

REPOSITORY = 'ncut-d1z/Insect-Inspired'
REMOTE = 'https://github.com/' + REPOSITORY + '.git'
TARGET = 'refs/heads/research/p3-p6-cp8'
SYNC = 'refs/heads/sync/cp8-checkpoint-import'
BASE = '3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f'
BASE_TREE = 'c5d5f03ce399961429288e1ffb7ce3565e278fbf'
CHECKPOINT = 'temp/snapshots/checkpoints/CP-0008.json'
PARTITIONS = 'temp/partitions/manifest.json'
PACKAGE = 'temp/sync/CP-0008'
PART_SIZE = 512 * 1024
CP7 = {
    'checkpoint_id': 'CP-0007', 'parent_checkpoint_id': 'CP-0006',
    'package_path': 'temp/sync/CP-0007',
    'manifest_sha256': '3c38d37b51a90171ad5e92226911629a9404a86e777c226641ba603463d02957',
    'readme_sha256': '6855334512f1a97c7491516def341ffdd344cedf249f6ffe064b075f49424261',
    'expected_baseline_commit': '0ee3b7de167a70933bc9884b9217142c2661c374',
    'expected_parent_commit': '0ee3b7de167a70933bc9884b9217142c2661c374',
    'expected_commit': BASE, 'expected_tree': BASE_TREE,
    'target_ref': 'refs/heads/research/p3-p6-cp7',
    'source_sync_ref': 'refs/heads/sync/cp7-checkpoint-import',
    'checkpoint_path': 'temp/snapshots/checkpoints/CP-0007.json',
    'checkpoint_sha256': 'c5d42d65a8d7b373a6dc6e6ccf5b27d67d09ba85af51b89f468a97795c5223e0',
    'bundle_sha256': '6477f3bd02d46ea494c6f08069e23d0eba4b2e74fdb32de92bc238ee829d87b6',
    'bundle_bytes': 31221121, 'part_count': 60,
    'canonical_file_count': 1317, 'canonical_file_bytes': 1045568594,
    'artifact_hash_count': 1316, 'partition_dataset_count': 7,
    'partition_manifest_sha256': 'e3e537a4817e8d7f735685f54e3c674329e4241f9d23c73e789195251caac0a6',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), '-c', 'core.hooksPath=/dev/null',
                                   '-c', 'core.fsmonitor=false', '-c', 'gc.auto=0', *args])


def line(repo, *args):
    return git(repo, *args).decode('utf-8').strip()


def safe_path(value):
    require(isinstance(value, str) and value and '\\' not in value
            and not PurePosixPath(value).is_absolute()
            and not {'.git', '..'}.intersection(PurePosixPath(value).parts),
            'Unsafe repository-relative path: ' + str(value))
    return value


def check_bundle_header(path, target):
    with path.open('rb') as stream:
        require(stream.readline() == b'# v2 git bundle\n', 'Expected SHA-1 Git bundle v2')
        headers = []
        while True:
            item = stream.readline(65537)
            require(item and len(item) <= 65536, 'Invalid bundle header')
            if item == b'\n':
                break
            headers.append(item.decode('utf-8').rstrip('\n'))
    require([x[1:].split(' ', 1)[0] for x in headers if x.startswith('-')] == [BASE],
            'CP8 bundle must have CP7 as its sole prerequisite')
    require([x for x in headers if not x.startswith('-')] == [target + ' ' + TARGET],
            'CP8 bundle must advertise only the fixed research branch')


def snapshot(repo, commit):
    entries = {}
    for item in git(repo, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if not item:
            continue
        meta, raw_name = item.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        name = safe_path(raw_name.decode('utf-8'))
        require(name not in entries and kind == 'blob' and mode in {'100644', '100755'},
                'Unexpected or duplicate canonical tree entry')
        entries[name] = oid
    require(not any(name.startswith('temp/sync/') or name.startswith('.github/workflows/import-cp8')
                    for name in entries), 'Transport material must remain outside the canonical snapshot')
    require({name for name in entries if name.endswith('/partitions/manifest.json')} == {PARTITIONS},
            'Unexpected additional partition manifest')
    actual = {str(p.relative_to(repo)) for p in repo.rglob('*')
              if p.is_file() and '.git' not in p.relative_to(repo).parts}
    require(actual == set(entries), 'Untracked or ignored files are not part of the frozen snapshot')
    require(all(not (repo / name).is_symlink() for name in actual), 'Symlink in canonical worktree')
    reader = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def blob(name):
        reader.stdin.write((entries[name] + '\n').encode('ascii'))
        reader.stdin.flush()
        oid, kind, size = reader.stdout.readline().decode('ascii').split()
        require(oid == entries[name] and kind == 'blob', 'Unexpected Git blob response')
        raw = reader.stdout.read(int(size))
        require(len(raw) == int(size) and reader.stdout.read(1) == b'\n', 'Truncated Git blob')
        return raw

    try:
        cp_raw = blob(CHECKPOINT)
        cp = json.loads(cp_raw)
        require(cp['checkpoint_id'] == 'CP-0008' and cp['parent_checkpoint_id'] == 'CP-0007'
                and cp['scope_id'] == 'SCOPE-0001' and cp['status'] == 'valid',
                'A frozen valid CP8 with CP7 parent is required')
        validation = cp['validation_results']
        require(all(validation[key] == 'passed' for key in ('data_audit', 'determinism', 'ui_validation'))
                and validation['final_artifact_hashes'] == 'verified', 'CP8 QA has not passed')
        hashes = cp['artifact_hashes']
        require(CHECKPOINT not in hashes and set(hashes) | {CHECKPOINT} == set(entries),
                'Checkpoint hashes must cover every canonical file except self')
        total = len(cp_raw)
        for name, expected in hashes.items():
            raw = blob(name)
            require(sha(raw) == expected, 'Canonical artifact SHA256 differs: ' + name)
            total += len(raw)
        frozen = [f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 8)]
        frozen += ['temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json',
                   'temp/seed-manifest.jsonl', 'temp/schema.json']
        for name in frozen:
            require(blob(name) == git(repo, 'show', BASE + ':' + name),
                    'Frozen CP7 predecessor/scope/seed/schema changed: ' + name)
        require(sha(blob(CP7['checkpoint_path'])) == CP7['checkpoint_sha256'],
                'Inherited CP7 checkpoint bytes differ')
        pm_raw = blob(PARTITIONS)
        pm = json.loads(pm_raw)
        seen = set()
        for name, dataset in pm['datasets'].items():
            require(dataset['parts'] and dataset['parts'][0]['path'] == name,
                    'Unexpected logical partition root: ' + name)
            digest, records = hashlib.sha256(), 0
            for part in dataset['parts']:
                path = 'temp/' + safe_path(part['path'])
                require(path not in seen, 'Duplicate logical partition: ' + path)
                seen.add(path)
                raw = blob(path)
                require(len(raw) == part['bytes'] and sha(raw) == part['sha256']
                        and len(raw.splitlines()) == part['records'], 'Logical partition differs: ' + path)
                digest.update(raw)
                records += part['records']
            require(records == dataset['logical_records'] and digest.hexdigest() == dataset['logical_sha256'],
                    'Logical dataset reconciliation failed: ' + name)
        require({name for name in entries if name.startswith('temp/partitions/') and name.endswith('.jsonl')} <= seen,
                'Unlisted logical partition')
        return {'checkpoint_sha256': sha(cp_raw), 'canonical_file_count': len(entries),
                'canonical_file_bytes': total, 'artifact_hash_count': len(hashes),
                'partition_dataset_count': len(pm['datasets']), 'partition_manifest_sha256': sha(pm_raw)}
    finally:
        reader.stdin.close()
        reader.stdout.close()
        require(reader.wait() == 0, 'Git blob reader failed')


README = r'''# CP8 增量数据恢复与主机合并

本目录的 __PART_COUNT__ 个原始二进制块按顺序恢复一个 Git bundle；每块至多 512 KiB。CP8 目标提交为 `__CP8_COMMIT__`，树为 `__CP8_TREE__`，直接 Git 父项为 `__CP8_PARENT__`。唯一 bundle prerequisite 是已冻结 CP7 `3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f`，有效检查点父项也是 CP-0007。

`sync/cp8-checkpoint-import` 必须同时保留原样继承的 `temp/sync/CP-0007/` 完整包与本 CP8 包。以下命令先从真实 GitHub 获取 CP7 的 prerequisite `0ee3b7de167a70933bc9884b9217142c2661c374`，再依次恢复 CP7 和 CP8；不要求远端研究分支已经更新到 CP7/CP8。本目录不提供也不依赖任何 Actions workflow。运输分支只承载恢复材料，不能直接合并到 main。

需要 Git 和 Windows PowerShell 5.1 或更新版本。修改 `$Cp8Repo` 为现有仓库绝对路径，在同一 PowerShell 会话依次运行。每次恢复创建仓库外的新目录；任何错误都会停止。工作树必须干净。

## 1. 拉取运输分支并提取两个完整包

~~~powershell
$ErrorActionPreference = 'Stop'
$Cp8Repo = 'C:\path\to\Insect-Inspired'
$Cp8Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp8SyncRef = 'refs/heads/sync/cp8-checkpoint-import'
$Cp8ResearchRef = 'refs/heads/research/p3-p6-cp8'
$Cp8RemoteBase = '0ee3b7de167a70933bc9884b9217142c2661c374'
$Cp8Cp7 = '3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f'
$Cp8Commit = '__CP8_COMMIT__'
$Cp8Tree = '__CP8_TREE__'
$Cp8Parent = '__CP8_PARENT__'
function Invoke-Cp8Git {
    $cp8Result = @(& git -C $Cp8Repo -c core.hooksPath=/dev/null -c push.followTags=false @args)
    if ($LASTEXITCODE -ne 0) { throw ('Git failed: ' + ($args -join ' ')) }
    $cp8Result
}
function Assert-Cp8Equal($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -cne [string]$Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp8Hash([string]$Path, [string]$Expected) {
    Assert-Cp8Equal (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() $Expected $Path
}
function Get-Cp8Remote([string]$Ref) {
    $cp8Rows = @(Invoke-Cp8Git ls-remote --heads origin $Ref)
    if ($cp8Rows.Count -eq 0) { return $null }
    if ($cp8Rows.Count -ne 1) { throw 'Unexpected remote ref count' }
    $cp8Columns = $cp8Rows[0] -split '\s+'
    Assert-Cp8Equal $cp8Columns[1] $Ref 'remote ref name'
    return $cp8Columns[0]
}
Assert-Cp8Equal (Invoke-Cp8Git remote get-url origin) $Cp8Url 'origin'
if (@(Invoke-Cp8Git status --porcelain).Count) { throw 'Preserve local changes before restoration.' }
Invoke-Cp8Git fetch --no-tags origin $Cp8SyncRef
$Cp8SyncTip = [string](Invoke-Cp8Git rev-parse FETCH_HEAD)
$Cp8HostRoot = Join-Path (Split-Path -Parent $Cp8Repo) ('cp8-recovery-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp8HostRoot
$Cp8TransportZip = Join-Path $Cp8HostRoot 'cp7-and-cp8-transport.zip'
$Cp8Package = Join-Path $Cp8HostRoot 'package'
Invoke-Cp8Git archive --format=zip ('--output=' + $Cp8TransportZip) $Cp8SyncTip -- temp/sync/CP-0007 temp/sync/CP-0008
Expand-Archive -LiteralPath $Cp8TransportZip -DestinationPath $Cp8Package
$Cp8Package7 = Join-Path $Cp8Package 'temp/sync/CP-0007'
$Cp8Package8 = Join-Path $Cp8Package 'temp/sync/CP-0008'
$Cp8ManifestPath7 = Join-Path $Cp8Package7 'manifest.json'
$Cp8ManifestPath8 = Join-Path $Cp8Package8 'manifest.json'
Assert-Cp8Hash $Cp8ManifestPath7 '3c38d37b51a90171ad5e92226911629a9404a86e777c226641ba603463d02957'
$Cp8Manifest7 = Get-Content -LiteralPath $Cp8ManifestPath7 -Raw -Encoding UTF8 | ConvertFrom-Json
$Cp8Manifest8 = Get-Content -LiteralPath $Cp8ManifestPath8 -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($cp8Manifest in @($Cp8Manifest7, $Cp8Manifest8)) {
    Assert-Cp8Equal $cp8Manifest.format_version 1 'manifest format'
    Assert-Cp8Equal $cp8Manifest.repository 'ncut-d1z/Insect-Inspired' 'repository'
    Assert-Cp8Equal $cp8Manifest.scope_id 'SCOPE-0001' 'scope'
    Assert-Cp8Equal $cp8Manifest.bundle_kind 'incremental' 'bundle kind'
    Assert-Cp8Equal $cp8Manifest.bundle_storage 'ordered_binary_parts' 'storage'
    Assert-Cp8Equal $cp8Manifest.bundle_name 'recovery.bundle' 'bundle name'
    Assert-Cp8Equal $cp8Manifest.part_size_bytes 524288 'part size'
}
Assert-Cp8Equal $Cp8Manifest7.checkpoint_id 'CP-0007' 'CP7 identity'
Assert-Cp8Equal $Cp8Manifest7.expected_baseline_commit $Cp8RemoteBase 'CP7 prerequisite'
Assert-Cp8Equal $Cp8Manifest7.expected_parent_commit $Cp8RemoteBase 'CP7 direct parent'
Assert-Cp8Equal $Cp8Manifest7.expected_commit $Cp8Cp7 'CP7 target'
Assert-Cp8Equal $Cp8Manifest7.expected_tree 'c5d5f03ce399961429288e1ffb7ce3565e278fbf' 'CP7 tree'
Assert-Cp8Equal $Cp8Manifest7.source_sync_ref 'refs/heads/sync/cp7-checkpoint-import' 'inherited CP7 source ref'
Assert-Cp8Equal $Cp8Manifest7.target_ref 'refs/heads/research/p3-p6-cp7' 'CP7 bundle ref'
Assert-Cp8Equal (@($Cp8Manifest7.bundle_prerequisites) -join ',') $Cp8RemoteBase 'sole CP7 prerequisite'
Assert-Cp8Hash (Join-Path $Cp8Package7 'README.md') '6855334512f1a97c7491516def341ffdd344cedf249f6ffe064b075f49424261'
Assert-Cp8Equal $Cp8Manifest8.checkpoint_id 'CP-0008' 'CP8 identity'
Assert-Cp8Equal $Cp8Manifest8.parent_checkpoint_id 'CP-0007' 'CP8 parent checkpoint'
Assert-Cp8Equal $Cp8Manifest8.source_sync_ref $Cp8SyncRef 'CP8 sync ref'
Assert-Cp8Equal $Cp8Manifest8.target_ref $Cp8ResearchRef 'CP8 research ref'
Assert-Cp8Equal $Cp8Manifest8.expected_baseline_commit $Cp8Cp7 'CP8 prerequisite'
Assert-Cp8Equal $Cp8Manifest8.expected_commit $Cp8Commit 'CP8 target'
Assert-Cp8Equal $Cp8Manifest8.expected_tree $Cp8Tree 'CP8 tree'
Assert-Cp8Equal $Cp8Manifest8.expected_parent_commit $Cp8Parent 'CP8 direct parent'
Assert-Cp8Equal (@($Cp8Manifest8.bundle_prerequisites) -join ',') $Cp8Cp7 'sole CP8 prerequisite'
Assert-Cp8Equal $Cp8Manifest8.checkpoint_path 'temp/snapshots/checkpoints/CP-0008.json' 'CP8 checkpoint path'
Assert-Cp8Equal $Cp8Manifest8.checkpoint_sha256 '__CP8_CHECKPOINT_HASH__' 'CP8 self hash'
Assert-Cp8Equal $Cp8Manifest8.canonical_file_count __CP8_FILE_COUNT__ 'CP8 file count'
Assert-Cp8Equal $Cp8Manifest8.canonical_file_bytes __CP8_FILE_BYTES__ 'CP8 file bytes'
Assert-Cp8Equal $Cp8Manifest8.artifact_hash_count __CP8_ARTIFACT_COUNT__ 'CP8 artifact count'
Assert-Cp8Equal $Cp8Manifest8.partition_manifest_sha256 '__CP8_PARTITION_HASH__' 'CP8 partition hash'
Assert-Cp8Hash (Join-Path $Cp8Package8 'README.md') $Cp8Manifest8.readme_sha256
~~~

## 2. 逐片核验、顺序拼接，再从真实远端 prerequisite 恢复 CP7 和 CP8

~~~powershell
function Join-Cp8Parts([string]$Folder, $Manifest, [string]$Output, [long]$ExpectedBytes, [string]$ExpectedHash, [int]$ExpectedParts) {
    $cp8Parts = @($Manifest.parts)
    Assert-Cp8Equal $cp8Parts.Count $ExpectedParts 'part count'
    Assert-Cp8Equal $Manifest.bundle_bytes $ExpectedBytes 'declared bundle length'
    Assert-Cp8Equal $Manifest.bundle_sha256 $ExpectedHash 'declared bundle SHA256'
    Assert-Cp8Equal (@(Get-ChildItem -LiteralPath (Join-Path $Folder 'parts') -File).Count) $ExpectedParts 'actual part count'
    $cp8Output = [IO.File]::Open($Output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    [long]$cp8Bytes = 0
    try {
        for ($cp8Index = 0; $cp8Index -lt $cp8Parts.Count; $cp8Index++) {
            $cp8Part = $cp8Parts[$cp8Index]
            $cp8Name = 'parts/recovery.bundle.part-{0:D4}' -f ($cp8Index + 1)
            Assert-Cp8Equal $cp8Part.index ($cp8Index + 1) 'part ordinal'
            Assert-Cp8Equal $cp8Part.path $cp8Name 'exact part name'
            if ($cp8Part.bytes -le 0 -or $cp8Part.bytes -gt 524288) { throw 'Invalid part size' }
            if ($cp8Index -lt ($cp8Parts.Count - 1)) { Assert-Cp8Equal $cp8Part.bytes 524288 'full part size' }
            $cp8Path = Join-Path $Folder $cp8Name
            Assert-Cp8Equal (Get-Item -LiteralPath $cp8Path).Length $cp8Part.bytes 'part bytes'
            Assert-Cp8Hash $cp8Path $cp8Part.sha256
            $cp8Input = [IO.File]::OpenRead($cp8Path)
            try { $cp8Input.CopyTo($cp8Output) } finally { $cp8Input.Dispose() }
            $cp8Bytes += [long]$cp8Part.bytes
        }
    } finally { $cp8Output.Dispose() }
    Assert-Cp8Equal $cp8Bytes $ExpectedBytes 'sum of part lengths'
    Assert-Cp8Equal (Get-Item -LiteralPath $Output).Length $ExpectedBytes 'assembled length'
    Assert-Cp8Hash $Output $ExpectedHash
}
$Cp8Bundle7 = Join-Path $Cp8HostRoot 'cp7-recovery.bundle'
$Cp8Bundle8 = Join-Path $Cp8HostRoot 'cp8-recovery.bundle'
Join-Cp8Parts $Cp8Package7 $Cp8Manifest7 $Cp8Bundle7 31221121 '6477f3bd02d46ea494c6f08069e23d0eba4b2e74fdb32de92bc238ee829d87b6' 60
Join-Cp8Parts $Cp8Package8 $Cp8Manifest8 $Cp8Bundle8 __BUNDLE_BYTES__ '__BUNDLE_HASH__' __PART_COUNT__
Invoke-Cp8Git fetch --no-tags origin $Cp8RemoteBase
Assert-Cp8Equal (Invoke-Cp8Git rev-parse FETCH_HEAD) $Cp8RemoteBase 'real GitHub prerequisite'
Invoke-Cp8Git bundle verify $Cp8Bundle7
Assert-Cp8Equal (Invoke-Cp8Git bundle list-heads $Cp8Bundle7) ($Cp8Cp7 + ' refs/heads/research/p3-p6-cp7') 'sole CP7 bundle head'
Invoke-Cp8Git fetch --no-tags $Cp8Bundle7 refs/heads/research/p3-p6-cp7
Assert-Cp8Equal (Invoke-Cp8Git rev-parse FETCH_HEAD) $Cp8Cp7 'locally restored CP7'
Assert-Cp8Equal (Invoke-Cp8Git show -s --format=%T $Cp8Cp7) 'c5d5f03ce399961429288e1ffb7ce3565e278fbf' 'restored CP7 tree'
Assert-Cp8Equal (Invoke-Cp8Git show -s --format=%P $Cp8Cp7) $Cp8RemoteBase 'restored CP7 parent'
Invoke-Cp8Git bundle verify $Cp8Bundle8
Assert-Cp8Equal (Invoke-Cp8Git bundle list-heads $Cp8Bundle8) ($Cp8Commit + ' ' + $Cp8ResearchRef) 'sole CP8 bundle head'
if ([string](Invoke-Cp8Git branch --show-current) -eq 'research/p3-p6-cp8') { Invoke-Cp8Git switch --detach }
Invoke-Cp8Git fetch --no-tags $Cp8Bundle8 ($Cp8ResearchRef + ':' + $Cp8ResearchRef)
Assert-Cp8Equal (Invoke-Cp8Git rev-parse $Cp8ResearchRef) $Cp8Commit 'locally restored CP8'
Assert-Cp8Equal (Invoke-Cp8Git show -s --format=%T $Cp8Commit) $Cp8Tree 'restored CP8 tree'
Assert-Cp8Equal (Invoke-Cp8Git show -s --format=%P $Cp8Commit) $Cp8Parent 'restored CP8 direct parent'
Invoke-Cp8Git merge-base --is-ancestor $Cp8RemoteBase $Cp8Cp7
Invoke-Cp8Git merge-base --is-ancestor $Cp8Cp7 $Cp8Commit
Invoke-Cp8Git fsck --full --strict --no-reflogs $Cp8Commit
~~~

CP7 的导入只取得 Git 对象，不覆盖本机或远端的 CP7 分支。若已有本机 CP8 分支不能快进，上述 fetch 会停止，需先检查分叉。

## 3. 按原始 Git 字节导出两个快照并验证全部文件

~~~powershell
function Assert-Cp8Snapshot([string]$Commit, [string]$CheckpointId, [string]$ParentId, [string]$SelfHash, [int]$FileCount, [long]$FileBytes, [int]$ArtifactCount, [string]$PartitionHash) {
    $cp8Name = $CheckpointId.ToLowerInvariant()
    $cp8Zip = Join-Path $Cp8HostRoot ($cp8Name + '-canonical.zip')
    $cp8Extract = Join-Path $Cp8HostRoot ($cp8Name + '-verified-canonical')
    Invoke-Cp8Git archive --format=zip ('--output=' + $cp8Zip) $Commit
    Expand-Archive -LiteralPath $cp8Zip -DestinationPath $cp8Extract
    $cp8CheckpointRelative = 'temp/snapshots/checkpoints/' + $CheckpointId + '.json'
    $cp8CheckpointPath = Join-Path $cp8Extract $cp8CheckpointRelative
    Assert-Cp8Hash $cp8CheckpointPath $SelfHash
    $cp8Checkpoint = Get-Content -LiteralPath $cp8CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Cp8Equal $cp8Checkpoint.status 'valid' 'checkpoint validity'
    Assert-Cp8Equal $cp8Checkpoint.checkpoint_id $CheckpointId 'checkpoint identity'
    Assert-Cp8Equal $cp8Checkpoint.parent_checkpoint_id $ParentId 'checkpoint parent'
    Assert-Cp8Equal $cp8Checkpoint.scope_id 'SCOPE-0001' 'checkpoint scope'
    $cp8Artifacts = @($cp8Checkpoint.artifact_hashes.PSObject.Properties)
    Assert-Cp8Equal $cp8Artifacts.Count $ArtifactCount 'artifact count'
    $cp8TreePaths = @(Invoke-Cp8Git -c core.quotePath=false ls-tree -r --name-only $Commit)
    Assert-Cp8Equal $cp8TreePaths.Count $FileCount 'canonical tree file count'
    $cp8DeclaredPaths = @($cp8Artifacts | ForEach-Object { $_.Name }) + @($cp8CheckpointRelative)
    if (@(Compare-Object -CaseSensitive -ReferenceObject $cp8TreePaths -DifferenceObject $cp8DeclaredPaths).Count) { throw 'Artifact path set differs from tree' }
    [long]$cp8Total = (Get-Item -LiteralPath $cp8CheckpointPath).Length
    foreach ($cp8Artifact in $cp8Artifacts) {
        if ([IO.Path]::IsPathRooted($cp8Artifact.Name) -or $cp8Artifact.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe artifact path' }
        $cp8File = Join-Path $cp8Extract $cp8Artifact.Name
        Assert-Cp8Hash $cp8File ([string]$cp8Artifact.Value)
        $cp8Total += [long](Get-Item -LiteralPath $cp8File).Length
    }
    Assert-Cp8Equal $cp8Total $FileBytes 'all canonical file bytes'
    Assert-Cp8Hash (Join-Path $cp8Extract 'temp/partitions/manifest.json') $PartitionHash
    Write-Host ('Verified ' + $CheckpointId + ': ' + $FileCount + ' complete files.')
}
Assert-Cp8Snapshot $Cp8Cp7 'CP-0007' 'CP-0006' 'c5d42d65a8d7b373a6dc6e6ccf5b27d67d09ba85af51b89f468a97795c5223e0' 1317 1045568594 1316 'e3e537a4817e8d7f735685f54e3c674329e4241f9d23c73e789195251caac0a6'
Assert-Cp8Snapshot $Cp8Commit 'CP-0008' 'CP-0007' '__CP8_CHECKPOINT_HASH__' __CP8_FILE_COUNT__ __CP8_FILE_BYTES__ __CP8_ARTIFACT_COUNT__ '__CP8_PARTITION_HASH__'
$Cp8Evidence = [ordered]@{
    status = 'passed'; sync_commit = $Cp8SyncTip; prerequisite_fetched_from_github = $Cp8RemoteBase
    cp7_commit = $Cp8Cp7; cp7_files = 1317; cp7_bundle_sha256 = '6477f3bd02d46ea494c6f08069e23d0eba4b2e74fdb32de92bc238ee829d87b6'
    cp8_commit = $Cp8Commit; cp8_tree = $Cp8Tree; cp8_direct_parent = $Cp8Parent
    cp8_files = __CP8_FILE_COUNT__; cp8_bundle_sha256 = '__BUNDLE_HASH__'; cp8_checkpoint_sha256 = '__CP8_CHECKPOINT_HASH__'
    cp8_manifest_sha256 = (Get-FileHash -LiteralPath $Cp8ManifestPath8 -Algorithm SHA256).Hash.ToLowerInvariant()
    verified_at_utc = [DateTime]::UtcNow.ToString('o')
}
[IO.File]::WriteAllText((Join-Path $Cp8HostRoot 'host-verification.json'), ($Cp8Evidence | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Invoke-Cp8Git push origin ($Cp8Commit + ':' + $Cp8ResearchRef)
Assert-Cp8Equal (Get-Cp8Remote $Cp8ResearchRef) $Cp8Commit 'remote CP8 after normal push'
~~~

`git archive` 保留原始字节，避免 Windows checkout 的换行转换影响哈希。保留 ZIP、bundle、两份 verified-canonical 目录和 host-verification.json。以上证明对应本次实际恢复与核验，未借用某个尚不存在的 Actions 成功状态。

## 4. 在主机快进合并 main 并普通推送

~~~powershell
if (@(Invoke-Cp8Git status --porcelain).Count) { throw 'Working tree must remain clean.' }
Invoke-Cp8Git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
if (@(Invoke-Cp8Git for-each-ref --format='%(refname)' refs/heads/main).Count -eq 0) {
    Invoke-Cp8Git switch -c main --track origin/main
} else { Invoke-Cp8Git switch main }
Invoke-Cp8Git merge --ff-only refs/remotes/origin/main
Invoke-Cp8Git merge --ff-only $Cp8ResearchRef
Invoke-Cp8Git merge-base --is-ancestor $Cp8Commit HEAD
Invoke-Cp8Git push origin HEAD:refs/heads/main
$Cp8Main = Get-Cp8Remote 'refs/heads/main'
Invoke-Cp8Git fetch --no-tags origin refs/heads/main
Assert-Cp8Equal (Invoke-Cp8Git rev-parse FETCH_HEAD) $Cp8Main 'verified remote main'
Invoke-Cp8Git merge-base --is-ancestor $Cp8Commit $Cp8Main
~~~

任一快进或普通推送失败，保留分支并检查分叉；不得改为强制覆盖 main。

## 5. 可选：main 已含目标后，精确条件删除本轮临时分支并清理提取目录

~~~powershell
if (-not (Test-Path -LiteralPath (Join-Path $Cp8HostRoot 'host-verification.json'))) { throw 'Preserve verification first.' }
Assert-Cp8Equal (Get-Cp8Remote 'refs/heads/main') $Cp8Main 'main before cleanup'
Invoke-Cp8Git fetch --no-tags origin refs/heads/main
Assert-Cp8Equal (Invoke-Cp8Git rev-parse FETCH_HEAD) $Cp8Main 'fetched main before cleanup'
Invoke-Cp8Git merge-base --is-ancestor $Cp8Commit $Cp8Main
Assert-Cp8Equal (Get-Cp8Remote $Cp8ResearchRef) $Cp8Commit 'research deletion lease'
Assert-Cp8Equal (Get-Cp8Remote $Cp8SyncRef) $Cp8SyncTip 'sync deletion lease'
Invoke-Cp8Git push --atomic ('--force-with-lease=' + $Cp8ResearchRef + ':' + $Cp8Commit) ('--force-with-lease=' + $Cp8SyncRef + ':' + $Cp8SyncTip) origin (':' + $Cp8ResearchRef) (':' + $Cp8SyncRef)
Assert-Cp8Equal (Get-Cp8Remote $Cp8ResearchRef) $null 'research deleted'
Assert-Cp8Equal (Get-Cp8Remote $Cp8SyncRef) $null 'sync deleted'
Assert-Cp8Equal (Get-Cp8Remote 'refs/heads/main') $Cp8Main 'main retained'
# 可选，仅删除本次在仓库外建立的 package；保留 ZIP、bundle、已校验快照和验证记录。
Assert-Cp8Equal ([IO.Path]::GetFullPath($Cp8Package)) ([IO.Path]::GetFullPath((Join-Path $Cp8HostRoot 'package'))) 'exact cleanup path'
if ((Get-Item -LiteralPath $Cp8Package).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Do not clean a reparse point.' }
Remove-Item -LiteralPath $Cp8Package -Recurse
~~~

精确 lease 仅保护上述两个临时分支的条件删除，不用于更新 main。若分支已变动则删除失败并停止。不要删除仓库中的规范 temp/ 或 temp/partitions/；CP7 及更早分支也不由本段删除。以上网络写入、main 合并与清理由用户在主机执行；打包工具本身没有这些操作。
'''


def fill(text, values):
    for key, value in values.items():
        text = text.replace('__' + key + '__', str(value))
    require(not re.search(r'__[A-Z][A-Z0-9_]+__', text), 'Unfilled frozen README placeholder')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--target-commit', required=True, help='Exact final CP8 HEAD, full 40-character SHA')
    parser.add_argument('--out-dir', '--output-dir', dest='output_dir', required=True, type=Path)
    args = parser.parse_args()
    repo, output, target = args.repo.resolve(), args.output_dir.resolve(), args.target_commit
    require(re.fullmatch('[0-9a-f]{40}', target) and target != BASE, 'Use the exact new CP8 commit')
    require(not output.is_relative_to(repo) and not repo.is_relative_to(output), 'Output must be separate from the repository')
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), 'Output must be absent or empty')
    require(line(repo, 'rev-parse', '--show-toplevel') == str(repo), 'Repository root required')
    require(line(repo, 'remote', 'get-url', 'origin') == REMOTE, 'Unexpected repository origin')
    require(line(repo, 'rev-parse', '--show-object-format') == 'sha1', 'Expected SHA-1 Git objects')
    require(line(repo, 'rev-parse', '--is-shallow-repository') == 'false', 'Complete history required')
    require(not git(repo, 'status', '--porcelain=v1', '--untracked-files=all'), 'Canonical worktree must be clean')
    require(line(repo, 'symbolic-ref', '-q', 'HEAD') == TARGET
            and line(repo, 'rev-parse', 'HEAD') == target and line(repo, 'rev-parse', TARGET) == target,
            'Freeze the CP8 research branch and HEAD at the requested commit')
    require(line(repo, 'rev-parse', BASE + '^{tree}') == BASE_TREE, 'Fixed CP7 base tree differs')
    git(repo, 'merge-base', '--is-ancestor', BASE, target)
    parent = line(repo, 'show', '-s', '--format=%P', target)
    require(re.fullmatch('[0-9a-f]{40}', parent), 'CP8 must have one direct Git parent')
    tree = line(repo, 'show', '-s', '--format=%T', target)
    stats = snapshot(repo, target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cp8-package-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        bundle = temporary / 'recovery.bundle'
        git(repo, 'bundle', 'create', '--version=2', str(bundle), TARGET, '^' + BASE)
        check_bundle_header(bundle, target)
        git(repo, 'bundle', 'verify', str(bundle))
        require(line(repo, 'bundle', 'list-heads', str(bundle)) == target + ' ' + TARGET, 'Unexpected bundle ref')
        staged = temporary / 'prepared'
        package = staged / PACKAGE
        (package / 'parts').mkdir(parents=True)
        parts, digest, size = [], hashlib.sha256(), 0
        with bundle.open('rb') as stream:
            while chunk := stream.read(PART_SIZE):
                ordinal = len(parts) + 1
                name = 'parts/recovery.bundle.part-' + format(ordinal, '04d')
                (package / name).write_bytes(chunk)
                parts.append({'index': ordinal, 'path': name, 'bytes': len(chunk), 'sha256': sha(chunk)})
                digest.update(chunk)
                size += len(chunk)
        values = {'CP8_COMMIT': target, 'CP8_TREE': tree, 'CP8_PARENT': parent,
                  'BUNDLE_BYTES': size, 'BUNDLE_HASH': digest.hexdigest(), 'PART_COUNT': len(parts),
                  'CP8_CHECKPOINT_HASH': stats['checkpoint_sha256'], 'CP8_FILE_COUNT': stats['canonical_file_count'],
                  'CP8_FILE_BYTES': stats['canonical_file_bytes'], 'CP8_ARTIFACT_COUNT': stats['artifact_hash_count'],
                  'CP8_PARTITION_HASH': stats['partition_manifest_sha256']}
        readme = fill(README, values).encode('utf-8')
        (package / 'README.md').write_bytes(readme)
        manifest = {'format_version': 1, 'repository': REPOSITORY, 'checkpoint_id': 'CP-0008',
                    'parent_checkpoint_id': 'CP-0007', 'scope_id': 'SCOPE-0001',
                    'source_sync_ref': SYNC, 'target_ref': TARGET, 'expected_baseline_commit': BASE,
                    'expected_commit': target, 'expected_tree': tree, 'expected_parent_commit': parent,
                    'checkpoint_path': CHECKPOINT, 'bundle_kind': 'incremental', 'bundle_name': 'recovery.bundle',
                    'bundle_prerequisites': [BASE], 'bundle_storage': 'ordered_binary_parts',
                    'bundle_bytes': size, 'bundle_sha256': digest.hexdigest(), 'part_size_bytes': PART_SIZE,
                    'parts': parts, 'readme_sha256': sha(readme), **stats,
                    'inherited_cp7_package': CP7, 'restore_requires_remote_cp7_research_head': False,
                    'workflow_generated': False, 'remote_verification_performed': False}
        raw_manifest = encoded(manifest)
        (package / 'manifest.json').write_bytes(raw_manifest)
        require(line(repo, 'rev-parse', 'HEAD') == target and line(repo, 'rev-parse', TARGET) == target
                and not git(repo, 'status', '--porcelain=v1', '--untracked-files=all'),
                'Canonical repository changed during preparation')
        if output.exists():
            require(not any(output.iterdir()), 'Output changed during preparation')
            output.rmdir()
        staged.rename(output)
    print(json.dumps({'status': 'prepared_not_uploaded', 'output_dir': str(output),
                      'target_commit': target, 'target_tree': tree, 'direct_parent': parent,
                      'base_commit': BASE, 'bundle_bytes': size, 'parts': len(parts),
                      'manifest_sha256': sha(raw_manifest), 'canonical_repository_modified': False,
                      'network_requests': 0, 'workflow_generated': False,
                      'required_existing_remote_package': CP7['package_path'],
                      'next_step': 'Publish the exact CP8 package on the sync branch retaining the frozen CP7 package; independently recover and verify both snapshots before further research.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
