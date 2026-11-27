#!/usr/bin/env python3
"""Prepare a frozen CP9 incremental package outside the research repository.

Run only after valid CP9, all QA and this script have been committed and the
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
TARGET = 'refs/heads/research/p3-p6-cp9'
SYNC = 'refs/heads/sync/cp9-checkpoint-import'
BASE = '2e749d4994bd3b8c66fcde59950779adc5d66085'
BASE_TREE = '6428de0a5ac1e7c288928462eb9c768d08dfff4c'
CHECKPOINT = 'temp/snapshots/checkpoints/CP-0009.json'
PARTITIONS = 'temp/partitions/manifest.json'
PACKAGE = 'temp/sync/CP-0009'
PART_SIZE = 512 * 1024
CP7 = {'checkpoint_id': 'CP-0007',
 'parent_checkpoint_id': 'CP-0006',
 'package_path': 'temp/sync/CP-0007',
 'manifest_sha256': 'a16a7cc1cb908e7c187300cfb18d83e83ae7fcd0cc0cdd6c1b7a55e3bcc131cd',
 'readme_sha256': 'd98418bdd0383dd0cbea1b7663b71ee8ab8f911789e44295c94bdd58636d72bf',
 'expected_baseline_commit': '0ee3b7de167a70933bc9884b9217142c2661c374',
 'expected_parent_commit': '0ee3b7de167a70933bc9884b9217142c2661c374',
 'expected_commit': '3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f',
 'expected_tree': 'c5d5f03ce399961429288e1ffb7ce3565e278fbf',
 'target_ref': 'refs/heads/research/p3-p6-cp7',
 'source_sync_ref': 'refs/heads/sync/cp7-checkpoint-import',
 'checkpoint_path': 'temp/snapshots/checkpoints/CP-0007.json',
 'checkpoint_sha256': 'c5d42d65a8d7b373a6dc6e6ccf5b27d67d09ba85af51b89f468a97795c5223e0',
 'bundle_sha256': '6477f3bd02d46ea494c6f08069e23d0eba4b2e74fdb32de92bc238ee829d87b6',
 'bundle_bytes': 31221121,
 'part_count': 60,
 'canonical_file_count': 1317,
 'canonical_file_bytes': 1045568594,
 'artifact_hash_count': 1316,
 'partition_dataset_count': 7,
 'partition_manifest_sha256': 'e3e537a4817e8d7f735685f54e3c674329e4241f9d23c73e789195251caac0a6'}
CP8 = {'checkpoint_id': 'CP-0008',
 'parent_checkpoint_id': 'CP-0007',
 'package_path': 'temp/sync/CP-0008',
 'manifest_sha256': '897f5dbf90c8cee21f67952e9a2fd65ac02b1c645415bd144be7577996e40974',
 'readme_sha256': '282aa145d2722b7144f27161e88662c62bffeed366e351bf663d111afb2ae6ad',
 'expected_baseline_commit': '3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f',
 'expected_parent_commit': '81cbe9940a1464be8483d859857d589883f388e5',
 'expected_commit': '2e749d4994bd3b8c66fcde59950779adc5d66085',
 'expected_tree': '6428de0a5ac1e7c288928462eb9c768d08dfff4c',
 'target_ref': 'refs/heads/research/p3-p6-cp8',
 'source_sync_ref': 'refs/heads/sync/cp8-checkpoint-import',
 'checkpoint_path': 'temp/snapshots/checkpoints/CP-0008.json',
 'checkpoint_sha256': '85e5312505b14862df28c4193b74aeaf4767bb3b56942786f3948b172edcedb0',
 'bundle_sha256': '2520e20dfead3375c33489033c08b65437d0caf47b4a446ab0475fd942ebdf50',
 'bundle_bytes': 28210811,
 'part_count': 54,
 'canonical_file_count': 1361,
 'canonical_file_bytes': 1150803660,
 'artifact_hash_count': 1360,
 'partition_dataset_count': 7,
 'partition_manifest_sha256': 'af1d5f3f7551119c3d68a56d522fe4ce03583acac673ca3351d5b9ab7de77c34'}

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
            'CP9 bundle must have CP8 as its sole prerequisite')
    require([x for x in headers if not x.startswith('-')] == [target + ' ' + TARGET],
            'CP9 bundle must advertise only the fixed research branch')


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
    require(not any(name.startswith('temp/sync/') or name.startswith('.github/workflows/import-cp9')
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
        require(cp['checkpoint_id'] == 'CP-0009' and cp['parent_checkpoint_id'] == 'CP-0008'
                and cp['scope_id'] == 'SCOPE-0001' and cp['status'] == 'valid',
                'A frozen valid CP9 with CP8 parent is required')
        validation = cp['validation_results']
        require(all(validation[key] == 'passed' for key in ('data_audit', 'determinism', 'ui_validation'))
                and validation['final_artifact_hashes'] == 'verified', 'CP9 QA has not passed')
        hashes = cp['artifact_hashes']
        require(CHECKPOINT not in hashes and set(hashes) | {CHECKPOINT} == set(entries),
                'Checkpoint hashes must cover every canonical file except self')
        total = len(cp_raw)
        for name, expected in hashes.items():
            raw = blob(name)
            require(sha(raw) == expected, 'Canonical artifact SHA256 differs: ' + name)
            total += len(raw)
        frozen = [f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 9)]
        frozen += ['temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json',
                   'temp/seed-manifest.jsonl', 'temp/schema.json']
        for name in frozen:
            require(blob(name) == git(repo, 'show', BASE + ':' + name),
                    'Frozen CP8 predecessor/scope/seed/schema changed: ' + name)
        require(sha(blob(CP8['checkpoint_path'])) == CP8['checkpoint_sha256'],
                'Inherited CP8 checkpoint bytes differ')
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


README = r'''# CP9 增量恢复、完整性核验与主机合并

本目录包含 __PART_COUNT__ 个二进制分片，每片至多 512 KiB。目标提交 `__CP9_COMMIT__`，树 `__CP9_TREE__`，直接 Git 父项 `__CP9_PARENT__`。CP9 的唯一 bundle prerequisite 是冻结 CP8 `2e749d4994bd3b8c66fcde59950779adc5d66085`。检查点父项为 CP-0008。

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
$Cp9Commit = '__CP9_COMMIT__'
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
__EXPECTED_JSON__
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
'''


def fill(text, values):
    for key, value in values.items():
        text = text.replace('__' + key + '__', str(value))
    require(not re.search(r'__[A-Z][A-Z0-9_]+__', text), 'Unfilled frozen README placeholder')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--target-commit', required=True, help='Exact final CP9 HEAD, full 40-character SHA')
    parser.add_argument('--out-dir', '--output-dir', dest='output_dir', required=True, type=Path)
    args = parser.parse_args()
    repo, output, target = args.repo.resolve(), args.output_dir.resolve(), args.target_commit
    require(re.fullmatch('[0-9a-f]{40}', target) and target != BASE, 'Use the exact new CP9 commit')
    require(not output.is_relative_to(repo) and not repo.is_relative_to(output), 'Output must be separate from the repository')
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), 'Output must be absent or empty')
    require(line(repo, 'rev-parse', '--show-toplevel') == str(repo), 'Repository root required')
    require(line(repo, 'remote', 'get-url', 'origin') == REMOTE, 'Unexpected repository origin')
    require(line(repo, 'rev-parse', '--show-object-format') == 'sha1', 'Expected SHA-1 Git objects')
    require(line(repo, 'rev-parse', '--is-shallow-repository') == 'false', 'Complete history required')
    require(not git(repo, 'status', '--porcelain=v1', '--untracked-files=all'), 'Canonical worktree must be clean')
    require(line(repo, 'symbolic-ref', '-q', 'HEAD') == TARGET
            and line(repo, 'rev-parse', 'HEAD') == target and line(repo, 'rev-parse', TARGET) == target,
            'Freeze the CP9 research branch and HEAD at the requested commit')
    require(line(repo, 'rev-parse', BASE + '^{tree}') == BASE_TREE, 'Fixed CP8 base tree differs')
    git(repo, 'merge-base', '--is-ancestor', BASE, target)
    parent = line(repo, 'show', '-s', '--format=%P', target)
    require(re.fullmatch('[0-9a-f]{40}', parent), 'CP9 must have one direct Git parent')
    tree = line(repo, 'show', '-s', '--format=%T', target)
    stats = snapshot(repo, target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cp9-package-', dir=output.parent) as temporary:
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
        values = {'CP9_COMMIT': target, 'CP9_TREE': tree, 'CP9_PARENT': parent,
                  'BUNDLE_BYTES': size, 'BUNDLE_HASH': digest.hexdigest(), 'PART_COUNT': len(parts),
                  'CP9_CHECKPOINT_HASH': stats['checkpoint_sha256'], 'CP9_FILE_COUNT': stats['canonical_file_count'],
                  'CP9_FILE_BYTES': stats['canonical_file_bytes'], 'CP9_ARTIFACT_COUNT': stats['artifact_hash_count'],
                  'CP9_PARTITION_HASH': stats['partition_manifest_sha256']}
        current = {'checkpoint_id': 'CP-0009', 'parent_checkpoint_id': 'CP-0008',
                   'package_path': PACKAGE, 'source_sync_ref': SYNC, 'target_ref': TARGET,
                   'expected_baseline_commit': BASE, 'expected_commit': target,
                   'expected_tree': tree, 'expected_parent_commit': parent,
                   'checkpoint_path': CHECKPOINT, 'bundle_bytes': size,
                   'bundle_sha256': digest.hexdigest(), 'part_count': len(parts), **stats}
        values['EXPECTED_JSON'] = json.dumps([CP7, CP8, current], ensure_ascii=False, indent=2)
        readme = fill(README, values).encode('utf-8')
        (package / 'README.md').write_bytes(readme)
        manifest = {'format_version': 1, 'repository': REPOSITORY, 'checkpoint_id': 'CP-0009',
                    'parent_checkpoint_id': 'CP-0008', 'scope_id': 'SCOPE-0001',
                    'source_sync_ref': SYNC, 'target_ref': TARGET, 'expected_baseline_commit': BASE,
                    'expected_commit': target, 'expected_tree': tree, 'expected_parent_commit': parent,
                    'checkpoint_path': CHECKPOINT, 'bundle_kind': 'incremental', 'bundle_name': 'recovery.bundle',
                    'bundle_prerequisites': [BASE], 'bundle_storage': 'ordered_binary_parts',
                    'bundle_bytes': size, 'bundle_sha256': digest.hexdigest(), 'part_size_bytes': PART_SIZE,
                    'parts': parts, 'readme_sha256': sha(readme), **stats,
                    'inherited_cp7_package': CP7, 'inherited_cp8_package': CP8,
                    'restore_requires_remote_research_heads': False,
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
                      'required_existing_remote_packages': [CP7['package_path'], CP8['package_path']],
                      'next_step': 'Publish the exact CP9 package on the sync branch retaining the frozen CP7 and CP8 packages; independently recover and verify all three snapshots before further research.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
