#!/usr/bin/env python3
"""Prepare a frozen CP10 incremental package outside the research repository.

Run only after valid CP10, all QA and this script have been committed and the
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
TARGET = 'refs/heads/research/p3-p6-cp10'
SYNC = 'refs/heads/sync/cp10-checkpoint-import'
BASE = '96ce04b268f648978581e87d3be551981f12917d'
BASE_TREE = '4e61e76e128b51c55c75bc0db1853376f549407e'
CHECKPOINT = 'temp/snapshots/checkpoints/CP-0010.json'
PARTITIONS = 'temp/partitions/manifest.json'
PACKAGE = 'temp/sync/CP-0010'
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
CP9 = {'checkpoint_id': 'CP-0009',
 'parent_checkpoint_id': 'CP-0008',
 'expected_baseline_commit': '2e749d4994bd3b8c66fcde59950779adc5d66085',
 'expected_parent_commit': '5881ca89952d5b83850a9c6f1131a4cce81fe0c5',
 'expected_commit': '96ce04b268f648978581e87d3be551981f12917d',
 'expected_tree': '4e61e76e128b51c55c75bc0db1853376f549407e',
 'target_ref': 'refs/heads/research/p3-p6-cp9',
 'source_sync_ref': 'refs/heads/sync/cp9-checkpoint-import',
 'checkpoint_path': 'temp/snapshots/checkpoints/CP-0009.json',
 'checkpoint_sha256': 'b1551bc78888c4df70569e81f9b8e95583d01fb22e996112db68b26087e9a172',
 'bundle_sha256': '343a4dc01117d6577005e9031201fa06605187463174b107b599db8da0e70411',
 'bundle_bytes': 18103498,
 'canonical_file_count': 1414,
 'canonical_file_bytes': 1346716802,
 'artifact_hash_count': 1413,
 'partition_dataset_count': 8,
 'partition_manifest_sha256': '892df8bbd8e5facf6586478d8f4b67761d337f1dc0b550b4c3fbbaf925299fe8',
 'readme_sha256': 'af2340f0c6a6a971d7b30dd97379750f22bdfe694c26a418f76ddec0d1357bae',
 'package_path': 'temp/sync/CP-0009',
 'manifest_sha256': '697db1031529b2d8dcdc40ec18965f2d53c82c0cade9cbacd42188e97451d947',
 'part_count': 35}

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
            'CP10 bundle must have CP9 as its sole prerequisite')
    require([x for x in headers if not x.startswith('-')] == [target + ' ' + TARGET],
            'CP10 bundle must advertise only the fixed research branch')


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
    require(not any(name.startswith('temp/sync/') or name.startswith('.github/workflows/import-cp10')
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
        require(cp['checkpoint_id'] == 'CP-0010' and cp['parent_checkpoint_id'] == 'CP-0009'
                and cp['scope_id'] == 'SCOPE-0001' and cp['status'] == 'valid',
                'A frozen valid CP10 with CP9 parent is required')
        validation = cp['validation_results']
        require(all(validation[key] == 'passed' for key in ('data_audit', 'determinism', 'ui_validation'))
                and validation['final_artifact_hashes'] == 'verified', 'CP10 QA has not passed')
        hashes = cp['artifact_hashes']
        require(CHECKPOINT not in hashes and set(hashes) | {CHECKPOINT} == set(entries),
                'Checkpoint hashes must cover every canonical file except self')
        total = len(cp_raw)
        for name, expected in hashes.items():
            raw = blob(name)
            require(sha(raw) == expected, 'Canonical artifact SHA256 differs: ' + name)
            total += len(raw)
        frozen = [f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 10)]
        frozen += ['temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json',
                   'temp/seed-manifest.jsonl', 'temp/schema.json']
        for name in frozen:
            require(blob(name) == git(repo, 'show', BASE + ':' + name),
                    'Frozen CP9 predecessor/scope/seed/schema changed: ' + name)
        require(sha(blob(CP9['checkpoint_path'])) == CP9['checkpoint_sha256'],
                'Inherited CP9 checkpoint bytes differ')
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


README = r'''# CP10 增量恢复、完整性核验与主机合并

本目录包含 __PART_COUNT__ 个二进制分片，每片至多 512 KiB。目标提交 `__CP10_COMMIT__`，树 `__CP10_TREE__`，直接 Git 父项 `__CP10_PARENT__`。CP10 的唯一 bundle prerequisite 是冻结 CP9 `96ce04b268f648978581e87d3be551981f12917d`。检查点父项为 CP-0009。

运输分支 `sync/cp10-checkpoint-import` 同时保留 CP7、CP8、CP9 和 CP10 的完整包。以下 PowerShell 命令从真实 GitHub prerequisite 开始依次恢复四个检查点，校验分片、bundle、提交、树、全部规范文件及检查点自哈希。运输分支含打包目录，不能直接合并到 main。此目录不提供 Actions workflow。

需要 Git 和 **PowerShell 7 或更新版本（pwsh）**。修改 `$Cp10Repo` 为本机已有仓库的绝对路径，在同一会话按顺序运行。任何校验、快进或推送失败都会停止；保留数据并检查，不得改为强制覆盖 main。

## 1. 拉取运输分支并保留原始包

~~~powershell
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 or newer is required.' }
$Cp10Repo = 'C:\path\to\Insect-Inspired'
$Cp10Url = 'https://github.com/ncut-d1z/Insect-Inspired.git'
$Cp10SyncRef = 'refs/heads/sync/cp10-checkpoint-import'
$Cp10ResearchRef = 'refs/heads/research/p3-p6-cp10'
$Cp10RemoteBase = '0ee3b7de167a70933bc9884b9217142c2661c374'
$Cp10Commit = '__CP10_COMMIT__'
function Invoke-Cp10Git {
    $cp10Rows = @(& git -C $Cp10Repo -c core.hooksPath=/dev/null -c push.followTags=false @args)
    if ($LASTEXITCODE -ne 0) { throw ('Git failed: ' + ($args -join ' ')) }
    $cp10Rows
}
function Assert-Cp10Equal($Actual, $Expected, [string]$Label) {
    if ([string]$Actual -cne [string]$Expected) { throw ('Mismatch: ' + $Label) }
}
function Assert-Cp10Hash([string]$Path, [string]$Expected) {
    Assert-Cp10Equal (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() $Expected $Path
}
function Get-Cp10Remote([string]$Ref) {
    $cp10Rows = @(Invoke-Cp10Git ls-remote --heads origin $Ref)
    if ($cp10Rows.Count -eq 0) { return $null }
    if ($cp10Rows.Count -ne 1) { throw 'Unexpected remote ref count.' }
    $cp10Columns = $cp10Rows[0] -split '\s+'
    Assert-Cp10Equal $cp10Columns[1] $Ref 'remote ref name'
    return $cp10Columns[0]
}
Assert-Cp10Equal (Invoke-Cp10Git remote get-url origin) $Cp10Url 'repository origin'
if (@(Invoke-Cp10Git status --porcelain).Count) { throw 'Preserve local changes first.' }
Invoke-Cp10Git fetch --no-tags origin $Cp10SyncRef
$Cp10SyncTip = [string](Invoke-Cp10Git rev-parse FETCH_HEAD)
$Cp10HostRoot = Join-Path (Split-Path -Parent $Cp10Repo) ('cp10-recovery-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $Cp10HostRoot
$Cp10Zip = Join-Path $Cp10HostRoot 'cp7-cp8-cp9-cp10-transport.zip'
$Cp10Package = Join-Path $Cp10HostRoot 'package'
Invoke-Cp10Git archive --format=zip ('--output=' + $Cp10Zip) $Cp10SyncTip -- temp/sync/CP-0007 temp/sync/CP-0008 temp/sync/CP-0009 temp/sync/CP-0010
Expand-Archive -LiteralPath $Cp10Zip -DestinationPath $Cp10Package
$Cp10Expected = @'
__EXPECTED_JSON__
'@ | ConvertFrom-Json
~~~

## 2. 逐片校验、拼接，并依次导入四个检查点

~~~powershell
function Join-Cp10Parts([string]$Folder, $Manifest, [string]$Output, $Expected) {
    $cp10Parts = @($Manifest.parts)
    Assert-Cp10Equal $cp10Parts.Count $Expected.part_count 'part count'
    Assert-Cp10Equal (@(Get-ChildItem -LiteralPath (Join-Path $Folder 'parts') -File).Count) $Expected.part_count 'actual part count'
    $cp10Output = [IO.File]::Open($Output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    [long]$cp10Total = 0
    try {
        for ($cp10Index = 0; $cp10Index -lt $cp10Parts.Count; $cp10Index++) {
            $cp10Part = $cp10Parts[$cp10Index]
            $cp10Name = 'parts/recovery.bundle.part-{0:D4}' -f ($cp10Index + 1)
            Assert-Cp10Equal $cp10Part.index ($cp10Index + 1) 'part ordinal'
            Assert-Cp10Equal $cp10Part.path $cp10Name 'exact part name'
            if ($cp10Part.bytes -le 0 -or $cp10Part.bytes -gt 524288) { throw 'Invalid part size.' }
            if ($cp10Index -lt ($cp10Parts.Count - 1)) { Assert-Cp10Equal $cp10Part.bytes 524288 'full part size' }
            $cp10Path = Join-Path $Folder $cp10Name
            Assert-Cp10Equal (Get-Item -LiteralPath $cp10Path).Length $cp10Part.bytes 'part bytes'
            Assert-Cp10Hash $cp10Path $cp10Part.sha256
            $cp10Input = [IO.File]::OpenRead($cp10Path)
            try { $cp10Input.CopyTo($cp10Output) } finally { $cp10Input.Dispose() }
            $cp10Total += [long]$cp10Part.bytes
        }
    } finally { $cp10Output.Dispose() }
    Assert-Cp10Equal $cp10Total $Expected.bundle_bytes 'sum of part bytes'
    Assert-Cp10Equal (Get-Item -LiteralPath $Output).Length $Expected.bundle_bytes 'assembled bytes'
    Assert-Cp10Hash $Output $Expected.bundle_sha256
}
Invoke-Cp10Git fetch --no-tags origin $Cp10RemoteBase
Assert-Cp10Equal (Invoke-Cp10Git rev-parse FETCH_HEAD) $Cp10RemoteBase 'real GitHub prerequisite'
foreach ($cp10ExpectedItem in $Cp10Expected) {
    $cp10Folder = Join-Path $Cp10Package $cp10ExpectedItem.package_path
    $cp10ManifestPath = Join-Path $cp10Folder 'manifest.json'
    if ($cp10ExpectedItem.PSObject.Properties.Name -contains 'manifest_sha256') {
        Assert-Cp10Hash $cp10ManifestPath $cp10ExpectedItem.manifest_sha256
    }
    $cp10Manifest = Get-Content -LiteralPath $cp10ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Cp10Equal $cp10Manifest.format_version 1 'manifest format'
    Assert-Cp10Equal $cp10Manifest.repository 'ncut-d1z/Insect-Inspired' 'repository'
    Assert-Cp10Equal $cp10Manifest.scope_id 'SCOPE-0001' 'scope'
    Assert-Cp10Equal $cp10Manifest.bundle_kind 'incremental' 'bundle kind'
    Assert-Cp10Equal $cp10Manifest.bundle_storage 'ordered_binary_parts' 'storage'
    Assert-Cp10Equal $cp10Manifest.bundle_name 'recovery.bundle' 'bundle name'
    Assert-Cp10Equal $cp10Manifest.part_size_bytes 524288 'part size'
    foreach ($cp10Key in @('checkpoint_id','parent_checkpoint_id','source_sync_ref','target_ref','expected_baseline_commit','expected_parent_commit','expected_commit','expected_tree','checkpoint_path','checkpoint_sha256','bundle_bytes','bundle_sha256','canonical_file_count','canonical_file_bytes','artifact_hash_count','partition_dataset_count','partition_manifest_sha256')) {
        Assert-Cp10Equal $cp10Manifest.$cp10Key $cp10ExpectedItem.$cp10Key $cp10Key
    }
    Assert-Cp10Equal (@($cp10Manifest.bundle_prerequisites) -join ',') $cp10ExpectedItem.expected_baseline_commit 'sole prerequisite'
    Assert-Cp10Hash (Join-Path $cp10Folder 'README.md') $cp10Manifest.readme_sha256
    if ($cp10ExpectedItem.PSObject.Properties.Name -contains 'readme_sha256') {
        Assert-Cp10Hash (Join-Path $cp10Folder 'README.md') $cp10ExpectedItem.readme_sha256
    }
    $cp10Bundle = Join-Path $Cp10HostRoot ($cp10ExpectedItem.checkpoint_id + '-recovery.bundle')
    Join-Cp10Parts $cp10Folder $cp10Manifest $cp10Bundle $cp10ExpectedItem
    Invoke-Cp10Git bundle verify $cp10Bundle
    Assert-Cp10Equal (Invoke-Cp10Git bundle list-heads $cp10Bundle) ($cp10ExpectedItem.expected_commit + ' ' + $cp10ExpectedItem.target_ref) 'sole bundle head'
    # Fetch objects only: do not overwrite any existing local predecessor branch.
    Invoke-Cp10Git fetch --no-tags $cp10Bundle $cp10ExpectedItem.target_ref
    Assert-Cp10Equal (Invoke-Cp10Git rev-parse FETCH_HEAD) $cp10ExpectedItem.expected_commit 'restored commit'
    Assert-Cp10Equal (Invoke-Cp10Git show -s --format=%T $cp10ExpectedItem.expected_commit) $cp10ExpectedItem.expected_tree 'restored tree'
    Assert-Cp10Equal (Invoke-Cp10Git show -s --format=%P $cp10ExpectedItem.expected_commit) $cp10ExpectedItem.expected_parent_commit 'direct parent'
    Invoke-Cp10Git merge-base --is-ancestor $cp10ExpectedItem.expected_baseline_commit $cp10ExpectedItem.expected_commit
}
Invoke-Cp10Git fsck --full --strict --no-reflogs $Cp10Commit
~~~

## 3. 按 Git 原始字节验证全部规范文件，再发布研究分支

~~~powershell
function Assert-Cp10Snapshot($Expected) {
    $cp10Zip = Join-Path $Cp10HostRoot ($Expected.checkpoint_id + '-canonical.zip')
    $cp10Extract = Join-Path $Cp10HostRoot ($Expected.checkpoint_id + '-verified-canonical')
    Invoke-Cp10Git archive --format=zip ('--output=' + $cp10Zip) $Expected.expected_commit
    Expand-Archive -LiteralPath $cp10Zip -DestinationPath $cp10Extract
    $cp10CheckpointPath = Join-Path $cp10Extract $Expected.checkpoint_path
    Assert-Cp10Hash $cp10CheckpointPath $Expected.checkpoint_sha256
    $cp10Checkpoint = Get-Content -LiteralPath $cp10CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Cp10Equal $cp10Checkpoint.status 'valid' 'checkpoint validity'
    Assert-Cp10Equal $cp10Checkpoint.checkpoint_id $Expected.checkpoint_id 'checkpoint identity'
    Assert-Cp10Equal $cp10Checkpoint.parent_checkpoint_id $Expected.parent_checkpoint_id 'checkpoint parent'
    Assert-Cp10Equal $cp10Checkpoint.scope_id 'SCOPE-0001' 'checkpoint scope'
    $cp10Artifacts = @($cp10Checkpoint.artifact_hashes.PSObject.Properties)
    Assert-Cp10Equal $cp10Artifacts.Count $Expected.artifact_hash_count 'artifact count'
    $cp10TreePaths = @(Invoke-Cp10Git -c core.quotePath=false ls-tree -r --name-only $Expected.expected_commit)
    Assert-Cp10Equal $cp10TreePaths.Count $Expected.canonical_file_count 'tree file count'
    $cp10DeclaredPaths = @($cp10Artifacts | ForEach-Object { $_.Name }) + @($Expected.checkpoint_path)
    if (@(Compare-Object -CaseSensitive -ReferenceObject $cp10TreePaths -DifferenceObject $cp10DeclaredPaths).Count) { throw 'Artifact paths differ from tree.' }
    [long]$cp10Total = (Get-Item -LiteralPath $cp10CheckpointPath).Length
    foreach ($cp10Artifact in $cp10Artifacts) {
        if ([IO.Path]::IsPathRooted($cp10Artifact.Name) -or $cp10Artifact.Name -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Unsafe artifact path.' }
        $cp10File = Join-Path $cp10Extract $cp10Artifact.Name
        Assert-Cp10Hash $cp10File ([string]$cp10Artifact.Value)
        $cp10Total += [long](Get-Item -LiteralPath $cp10File).Length
    }
    Assert-Cp10Equal $cp10Total $Expected.canonical_file_bytes 'all file bytes'
    Assert-Cp10Hash (Join-Path $cp10Extract 'temp/partitions/manifest.json') $Expected.partition_manifest_sha256
    Write-Host ('Verified ' + $Expected.checkpoint_id + ': ' + $Expected.canonical_file_count + ' complete files.')
}
foreach ($cp10ExpectedItem in $Cp10Expected) { Assert-Cp10Snapshot $cp10ExpectedItem }
$Cp10Evidence = [ordered]@{
    status = 'passed'; sync_commit = $Cp10SyncTip
    prerequisite_fetched_from_github = $Cp10RemoteBase
    snapshots = $Cp10Expected
    verified_at_utc = [DateTime]::UtcNow.ToString('o')
}
[IO.File]::WriteAllText((Join-Path $Cp10HostRoot 'host-verification.json'), ($Cp10Evidence | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
if ([string](Invoke-Cp10Git branch --show-current) -eq 'research/p3-p6-cp10') { Invoke-Cp10Git switch --detach }
$Cp10Bundle10 = Join-Path $Cp10HostRoot 'CP-0010-recovery.bundle'
Invoke-Cp10Git fetch --no-tags $Cp10Bundle10 ($Cp10ResearchRef + ':' + $Cp10ResearchRef)
Assert-Cp10Equal (Invoke-Cp10Git rev-parse $Cp10ResearchRef) $Cp10Commit 'local research ref'
Invoke-Cp10Git push origin ($Cp10Commit + ':' + $Cp10ResearchRef)
Assert-Cp10Equal (Get-Cp10Remote $Cp10ResearchRef) $Cp10Commit 'remote research after normal push'
~~~

`git archive` 避免 Windows checkout 换行转换影响哈希。保留原始 ZIP、四个 bundle、四个 verified-canonical 目录及 host-verification.json。已有本地研究分支若不能快进，fetch 会停止，不覆盖分叉。

## 4. 快进合并 main 并普通推送

~~~powershell
if (@(Invoke-Cp10Git status --porcelain).Count) { throw 'Working tree must remain clean.' }
Invoke-Cp10Git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
if (@(Invoke-Cp10Git for-each-ref --format='%(refname)' refs/heads/main).Count -eq 0) {
    Invoke-Cp10Git switch -c main --track origin/main
} else { Invoke-Cp10Git switch main }
Invoke-Cp10Git merge --ff-only refs/remotes/origin/main
Invoke-Cp10Git merge --ff-only $Cp10ResearchRef
Invoke-Cp10Git merge-base --is-ancestor $Cp10Commit HEAD
Invoke-Cp10Git push origin HEAD:refs/heads/main
$Cp10Main = Get-Cp10Remote 'refs/heads/main'
Invoke-Cp10Git fetch --no-tags origin refs/heads/main
Assert-Cp10Equal (Invoke-Cp10Git rev-parse FETCH_HEAD) $Cp10Main 'verified remote main'
Invoke-Cp10Git merge-base --is-ancestor $Cp10Commit $Cp10Main
~~~

## 5. main 已包含目标后，可选删除本轮临时分支和提取目录

~~~powershell
if (-not (Test-Path -LiteralPath (Join-Path $Cp10HostRoot 'host-verification.json'))) { throw 'Preserve verification first.' }
Assert-Cp10Equal (Get-Cp10Remote 'refs/heads/main') $Cp10Main 'main before cleanup'
Invoke-Cp10Git fetch --no-tags origin refs/heads/main
Assert-Cp10Equal (Invoke-Cp10Git rev-parse FETCH_HEAD) $Cp10Main 'fetched main before cleanup'
Invoke-Cp10Git merge-base --is-ancestor $Cp10Commit $Cp10Main
Assert-Cp10Equal (Get-Cp10Remote $Cp10ResearchRef) $Cp10Commit 'research deletion lease'
Assert-Cp10Equal (Get-Cp10Remote $Cp10SyncRef) $Cp10SyncTip 'sync deletion lease'
Invoke-Cp10Git push --atomic ('--force-with-lease=' + $Cp10ResearchRef + ':' + $Cp10Commit) ('--force-with-lease=' + $Cp10SyncRef + ':' + $Cp10SyncTip) origin (':' + $Cp10ResearchRef) (':' + $Cp10SyncRef)
Assert-Cp10Equal (Get-Cp10Remote $Cp10ResearchRef) $null 'research deleted'
Assert-Cp10Equal (Get-Cp10Remote $Cp10SyncRef) $null 'sync deleted'
Assert-Cp10Equal (Get-Cp10Remote 'refs/heads/main') $Cp10Main 'main retained'
# Optional: delete only this newly extracted package; retain bundles and verification.
Assert-Cp10Equal ([IO.Path]::GetFullPath($Cp10Package)) ([IO.Path]::GetFullPath((Join-Path $Cp10HostRoot 'package'))) 'exact cleanup path'
if ((Get-Item -LiteralPath $Cp10Package).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Do not clean a reparse point.' }
Remove-Item -LiteralPath $Cp10Package -Recurse
~~~

精确 lease 只用于本轮两个临时分支的条件删除；远端有新提交时删除失败并停止。CP7、CP8、CP9 等更早分支不在本段自动删除。不要删除规范 `temp/`、`temp/partitions/` 或历史归档。主机上的推送、main 合并与可选清理由上述命令执行，打包工具仅生成恢复材料，不执行这些操作。
'''


def fill(text, values):
    for key, value in values.items():
        text = text.replace('__' + key + '__', str(value))
    require(not re.search(r'__[A-Z][A-Z0-9_]+__', text), 'Unfilled frozen README placeholder')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--target-commit', required=True, help='Exact final CP10 HEAD, full 40-character SHA')
    parser.add_argument('--out-dir', '--output-dir', dest='output_dir', required=True, type=Path)
    args = parser.parse_args()
    repo, output, target = args.repo.resolve(), args.output_dir.resolve(), args.target_commit
    require(re.fullmatch('[0-9a-f]{40}', target) and target != BASE, 'Use the exact new CP10 commit')
    require(not output.is_relative_to(repo) and not repo.is_relative_to(output), 'Output must be separate from the repository')
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), 'Output must be absent or empty')
    require(line(repo, 'rev-parse', '--show-toplevel') == str(repo), 'Repository root required')
    require(line(repo, 'remote', 'get-url', 'origin') == REMOTE, 'Unexpected repository origin')
    require(line(repo, 'rev-parse', '--show-object-format') == 'sha1', 'Expected SHA-1 Git objects')
    require(line(repo, 'rev-parse', '--is-shallow-repository') == 'false', 'Complete history required')
    require(not git(repo, 'status', '--porcelain=v1', '--untracked-files=all'), 'Canonical worktree must be clean')
    require(line(repo, 'symbolic-ref', '-q', 'HEAD') == TARGET
            and line(repo, 'rev-parse', 'HEAD') == target and line(repo, 'rev-parse', TARGET) == target,
            'Freeze the CP10 research branch and HEAD at the requested commit')
    require(line(repo, 'rev-parse', BASE + '^{tree}') == BASE_TREE, 'Fixed CP9 base tree differs')
    git(repo, 'merge-base', '--is-ancestor', BASE, target)
    parent = line(repo, 'show', '-s', '--format=%P', target)
    require(re.fullmatch('[0-9a-f]{40}', parent), 'CP10 must have one direct Git parent')
    tree = line(repo, 'show', '-s', '--format=%T', target)
    stats = snapshot(repo, target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cp10-package-', dir=output.parent) as temporary:
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
        values = {'CP10_COMMIT': target, 'CP10_TREE': tree, 'CP10_PARENT': parent,
                  'BUNDLE_BYTES': size, 'BUNDLE_HASH': digest.hexdigest(), 'PART_COUNT': len(parts),
                  'CP10_CHECKPOINT_HASH': stats['checkpoint_sha256'], 'CP10_FILE_COUNT': stats['canonical_file_count'],
                  'CP10_FILE_BYTES': stats['canonical_file_bytes'], 'CP10_ARTIFACT_COUNT': stats['artifact_hash_count'],
                  'CP10_PARTITION_HASH': stats['partition_manifest_sha256']}
        current = {'checkpoint_id': 'CP-0010', 'parent_checkpoint_id': 'CP-0009',
                   'package_path': PACKAGE, 'source_sync_ref': SYNC, 'target_ref': TARGET,
                   'expected_baseline_commit': BASE, 'expected_commit': target,
                   'expected_tree': tree, 'expected_parent_commit': parent,
                   'checkpoint_path': CHECKPOINT, 'bundle_bytes': size,
                   'bundle_sha256': digest.hexdigest(), 'part_count': len(parts), **stats}
        values['EXPECTED_JSON'] = json.dumps([CP7, CP8, CP9, current], ensure_ascii=False, indent=2)
        readme = fill(README, values).encode('utf-8')
        (package / 'README.md').write_bytes(readme)
        manifest = {'format_version': 1, 'repository': REPOSITORY, 'checkpoint_id': 'CP-0010',
                    'parent_checkpoint_id': 'CP-0009', 'scope_id': 'SCOPE-0001',
                    'source_sync_ref': SYNC, 'target_ref': TARGET, 'expected_baseline_commit': BASE,
                    'expected_commit': target, 'expected_tree': tree, 'expected_parent_commit': parent,
                    'checkpoint_path': CHECKPOINT, 'bundle_kind': 'incremental', 'bundle_name': 'recovery.bundle',
                    'bundle_prerequisites': [BASE], 'bundle_storage': 'ordered_binary_parts',
                    'bundle_bytes': size, 'bundle_sha256': digest.hexdigest(), 'part_size_bytes': PART_SIZE,
                    'parts': parts, 'readme_sha256': sha(readme), **stats,
                    'inherited_cp7_package': CP7, 'inherited_cp8_package': CP8, 'inherited_cp9_package': CP9,
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
                      'required_existing_remote_packages': [CP7['package_path'], CP8['package_path'], CP9['package_path']],
                      'next_step': 'Publish the exact CP10 package on the sync branch retaining the frozen CP7, CP8 and CP9 packages; independently recover and verify all four snapshots before further research.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
