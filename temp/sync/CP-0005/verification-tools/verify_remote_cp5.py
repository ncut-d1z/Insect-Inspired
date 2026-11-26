#!/usr/bin/env python3
"""Read-only, independent CP5 verification after its frozen commit is published.

Only a new HTTPS GitHub clone is accepted. No repository code, hooks, credential
helpers, LFS filters, local object alternates, or local clones are executed/used.
The frozen head, tree and trusted local-manifest SHA256 are explicit CLI inputs.
This module also supplies pure inspection helpers to make_local_integrity_cp5.py.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
LOCAL_REPO = HERE.parent / 'insect-project'
URL = 'https://github.com/ncut-d1z/Insect-Inspired.git'
BRANCH = 'research/p3-p6-cp5'
GIT_PARENT = '95a0a218667333967f4a6c18f8b8b71df8b464e0'
CP4 = 'bb7726c2ef334df0d7069165156b1cbc2c4e2fd8'
CP3 = '595e92532c84b08ed79e3ac8ae533390e000b776'
CP2 = 'f50d697f42ce20e77b33499b0f615f2114ca13bf'
CP_PATH = 'temp/snapshots/checkpoints/CP-0005.json'
PARTITION_PATH = 'temp/partitions/manifest.json'


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def redact(text):
    text = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[redacted]@', str(text))
    text = re.sub(r'(?i)(authorization:\s*)[^\r\n]+', r'\1[redacted]', text)
    return re.sub(r'\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+', '[redacted]', text)


def strict_json(body):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + str(key))
            out[key] = value
        return out
    return json.loads(body, object_pairs_hook=pairs)


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def safe_relative(path):
    if (not isinstance(path, str) or not path or '\\' in path or '\0' in path
            or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/'))
            or any(p.lower() == '.git' for p in path.split('/'))):
        raise ValueError('Unsafe repository-relative path: ' + repr(path))
    return path


def sha_arg(value, size=40):
    if not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
        raise argparse.ArgumentTypeError('Expected a full lowercase hexadecimal digest')
    return value


def file_hashes(path):
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(size).encode('ascii') + b'\0')
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha256.update(chunk)
            blob.update(chunk)
    return size, sha256.hexdigest(), blob.hexdigest()


class Checks:
    def __init__(self):
        self.checks, self.failures = {}, []

    def check(self, name, ok, detail=None):
        if name in self.checks:
            raise ValueError('Duplicate check name: ' + name)
        self.checks[name] = bool(ok)
        if not ok:
            self.failures.append({'check': name, 'detail': detail})
        return bool(ok)

    def require(self, name, ok, detail=None):
        if not self.check(name, ok, detail):
            raise ValueError('Required verification failed: ' + name)


class Git:
    def __init__(self, repo):
        self.repo = Path(repo).resolve()
        self.env = os.environ.copy()
        # Discard inherited Git configuration/object overrides without printing
        # or examining their values. Environment network policy is not changed.
        for key in list(self.env):
            if key.startswith('GIT_') or key == 'SSH_ASKPASS':
                self.env.pop(key, None)
        self.env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_SYSTEM': os.devnull,
                         'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_ATTR_NOSYSTEM': '1',
                         'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false',
                         'SSH_ASKPASS': '/bin/false', 'GIT_NO_REPLACE_OBJECTS': '1',
                         'GIT_NO_LAZY_FETCH': '1', 'GIT_LFS_SKIP_SMUDGE': '1',
                         'GIT_OPTIONAL_LOCKS': '0', 'GIT_TRACE': '0',
                         'GIT_TRACE_CURL': '0', 'GIT_CURL_VERBOSE': '0',
                         'GIT_TRACE_PACKET': '0', 'GIT_TRACE2': '0'})

    def run(self, args, *, data=None, check=True, timeout=300, in_repo=True):
        command = ['git', '--no-optional-locks', '-c', 'protocol.file.allow=never',
                   '-c', 'protocol.ext.allow=never', '-c', 'credential.helper=',
                   '-c', 'core.askPass=/bin/false', '-c', 'core.hooksPath=/dev/null',
                   '-c', 'core.fsmonitor=false', '-c', 'core.autocrlf=false',
                   '-c', 'core.eol=lf', '-c', 'http.followRedirects=false']
        if in_repo:
            command += ['-C', str(self.repo)]
        result = subprocess.run(command + list(args), input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self.env, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError('git ' + str(args[0]) + ' failed: '
                               + redact(result.stderr.decode(errors='replace'))[-4000:])
        return result

    def text(self, args):
        return self.run(args).stdout.decode('utf-8').strip()

    def blob(self, revision, path):
        return self.run(['cat-file', 'blob', revision + ':' + safe_relative(path)]).stdout


def tree_entries(git, revision):
    entries = []
    for row in git.run(['ls-tree', '-rzl', revision]).stdout.split(b'\0'):
        if not row:
            continue
        info, raw_path = row.split(b'\t', 1)
        mode, kind, oid, size = info.decode('ascii').split()
        path = safe_relative(raw_path.decode('utf-8'))
        entries.append({'path': path, 'mode': mode, 'type': kind, 'sha': oid,
                        'bytes': None if size == '-' else int(size)})
    if len(entries) != len({x['path'] for x in entries}):
        raise ValueError('Repeated paths in Git tree')
    return entries


def object_independence(git, audit):
    audit.require('object_format_sha1', git.text(['rev-parse', '--show-object-format']) == 'sha1')
    audit.require('full_not_shallow', git.text(['rev-parse', '--is-shallow-repository']) == 'false')
    partial = git.run(['config', '--local', '--get-regexp',
                       '^(extensions\\.partialclone|remote\\..*\\.promisor|remote\\..*\\.partialclonefilter)$'],
                      check=False)
    audit.require('no_partial_clone_configuration', partial.returncode == 1 and not partial.stdout)
    git_dir = Path(git.text(['rev-parse', '--absolute-git-dir'])).resolve()
    common_dir = Path(git.text(['rev-parse', '--git-common-dir']))
    if not common_dir.is_absolute():
        common_dir = git.repo / common_dir
    audit.require('object_store_inside_repository', git_dir.is_relative_to(git.repo)
                  and common_dir.resolve() == git_dir)
    object_dir = git_dir / 'objects'
    audit.require('no_alternates', not any((object_dir / x).exists()
                  for x in ['info/alternates', 'info/http-alternates']))
    audit.require('no_promisor_pack', not list((object_dir / 'pack').glob('*.promisor')))
    audit.require('no_object_store_symlinks', not object_dir.is_symlink()
                  and not any(p.is_symlink() for p in object_dir.rglob('*')))
    audit.require('no_object_store_hardlinks', not any(p.is_file() and p.stat().st_nlink != 1
                  for p in object_dir.rglob('*')))
    audit.require('no_grafts', not (git_dir / 'info/grafts').exists())
    audit.require('no_replace_refs', not git.text(['for-each-ref', '--format=%(refname)', 'refs/replace']))
    return git_dir


def inspect_history(git, head, audit):
    chain = []
    for commit, parent in [(head, GIT_PARENT), (CP4, CP3), (CP3, CP2)]:
        parents = git.text(['show', '-s', '--format=%P', commit]).split()
        chain.append({'commit': commit, 'parents': parents})
        audit.require('git_parent_' + commit, parents == [parent], {'expected': parent, 'actual': parents})
    for name, commit in [('cp4', CP4), ('cp3_invalid', CP3), ('cp2', CP2), ('immediate_parent', GIT_PARENT)]:
        audit.require(name + '_is_ancestor',
                      git.run(['merge-base', '--is-ancestor', commit, head], check=False).returncode == 0)
    audit.require('cp4_precedes_immediate_parent',
                  git.run(['merge-base', '--is-ancestor', CP4, GIT_PARENT], check=False).returncode == 0)
    prior = []
    for cid, commit, status, parent in [('CP-0004', CP4, 'valid', 'CP-0002'),
                                       ('CP-0003', CP3, 'invalid', 'CP-0002'),
                                       ('CP-0002', CP2, 'valid', 'CP-0001')]:
        path = 'temp/snapshots/checkpoints/' + cid + '.json'
        original = git.blob(commit, path)
        current = git.blob(head, path)
        record = strict_json(current)
        audit.require('historical_checkpoint_unchanged_' + cid, current == original)
        audit.require('historical_checkpoint_identity_' + cid,
                      record.get('checkpoint_id') == cid and record.get('status') == status
                      and record.get('parent_checkpoint_id') == parent)
        prior.append({'checkpoint_id': cid, 'commit': commit, 'status': status,
                      'parent_checkpoint_id': parent, 'sha256': hashlib.sha256(current).hexdigest()})
    return {'git_parent_chain': chain, 'preserved_checkpoints': prior,
            'cp5_valid_checkpoint_parent': 'CP-0004', 'cp5_git_parent': GIT_PARENT}


def inspect_files(git, entries, audit):
    audit.require('regular_file_tree_only', all(x['type'] == 'blob' and x['mode'] in ('100644', '100755')
                                               for x in entries))
    files, attributes = [], []
    for entry in entries:
        path = git.repo / entry['path']
        audit.require('regular_file_' + entry['path'], path.is_file() and not path.is_symlink())
        audit.require('path_stays_in_repository_' + entry['path'], path.resolve().is_relative_to(git.repo))
        size, sha256, blob = file_hashes(path)
        mode_ok = bool(path.stat().st_mode & stat.S_IXUSR) == (entry['mode'] == '100755')
        ok = size == entry['bytes'] and blob == entry['sha'] and mode_ok
        audit.check('file_bytes_mode_' + entry['path'], ok)
        files.append({'path': entry['path'], 'mode': entry['mode'], 'bytes': size,
                      'blob_sha': blob, 'sha256': sha256, 'matched': ok})
        if path.name == '.gitattributes':
            attributes += [{'path': entry['path'], 'line': line} for line in path.read_text().splitlines()
                           if not line.lstrip().startswith('#') and 'filter=lfs' in line]
    audit.check('no_lfs_attributes', not attributes)
    audit.check('all_file_bytes_modes_match_git_tree', len(files) == len(entries) and all(x['matched'] for x in files))
    return files, attributes


def inspect_checkpoint(git, files, audit):
    actual = {x['path']: x for x in files}
    audit.require('checkpoint_file_present', CP_PATH in actual)
    cp = strict_json((git.repo / CP_PATH).read_bytes())
    audit.require('checkpoint_valid_and_parent', cp.get('checkpoint_id') == 'CP-0005'
                  and cp.get('status') == 'valid' and cp.get('parent_checkpoint_id') == 'CP-0004'
                  and cp.get('scope_id') == 'SCOPE-0001')
    hashes = {safe_relative(k): v.get('sha256') if isinstance(v, dict) else v
              for k, v in cp['artifact_hashes'].items()}
    audit.require('checkpoint_hash_set_is_all_files_except_self', set(hashes) == set(actual) - {CP_PATH})
    audit.require('checkpoint_self_hash_exclusion_recorded',
                  cp['validation_results'].get('checkpoint_self_hash_excluded') is True)
    verified = []
    for path, sha in sorted(hashes.items()):
        ok = bool(re.fullmatch('[0-9a-f]{64}', str(sha))) and actual[path]['sha256'] == sha
        audit.check('checkpoint_hash_' + path, ok)
        verified.append({'path': path, 'bytes': actual[path]['bytes'], 'sha256': actual[path]['sha256'],
                         'expected_sha256': sha, 'matched': ok})
    return {'checkpoint_id': cp['checkpoint_id'], 'status': cp['status'],
            'parent_checkpoint_id': cp['parent_checkpoint_id'], 'counts': cp['counts'],
            'artifact_hash_count': len(hashes), 'artifact_hash_matched_count': sum(x['matched'] for x in verified),
            'mismatches': [x for x in verified if not x['matched']],
            'tracked_paths_not_in_artifact_hashes': [CP_PATH], 'manifest_paths_not_tracked': [],
            'self_hash_excluded': True, 'checkpoint_file_sha256': actual[CP_PATH]['sha256'],
            'artifact_hashes_verified': verified}


def inspect_partitions(git, entries, audit):
    tracked = {x['path'] for x in entries}
    manifests = sorted(p for p in tracked if p.endswith('/partitions/manifest.json'))
    audit.require('current_partition_manifest_present', PARTITION_PATH in manifests)
    results = []
    for manifest_path in manifests:
        manifest = strict_json((git.repo / manifest_path).read_bytes())
        audit.require('partition_format_' + manifest_path, manifest.get('encoding') == 'UTF-8'
                      and manifest.get('record_format') == 'JSONL' and isinstance(manifest.get('datasets'), dict))
        base = PurePosixPath(manifest_path).parent.parent
        dataset_results, all_parts = [], set()
        for logical_name, specification in sorted(manifest['datasets'].items()):
            safe_relative(logical_name)
            parts = specification['parts']
            audit.require('partition_nonempty_' + manifest_path + ':' + logical_name,
                          bool(parts) and parts[0]['path'] == logical_name)
            logical_hash, logical_count, logical_bytes = hashlib.sha256(), 0, 0
            part_results = []
            for part in parts:
                relative = safe_relative(part['path'])
                path = safe_relative(str(base / relative))
                audit.require('partition_tracked_unique_' + path, path in tracked and path not in all_parts)
                all_parts.add(path)
                part_hash, part_count, part_bytes = hashlib.sha256(), 0, 0
                with (git.repo / path).open('rb') as stream:
                    for line in stream:
                        if not line.endswith(b'\n') or not line.strip():
                            raise ValueError('Empty/non-terminated JSONL record in ' + path)
                        if not isinstance(strict_json(line), dict):
                            raise ValueError('Non-object JSONL record in ' + path)
                        part_hash.update(line); logical_hash.update(line)
                        part_count += 1; part_bytes += len(line)
                ok = (part_hash.hexdigest() == part['sha256'] and part_count == part['records']
                      and part_bytes == part['bytes'])
                audit.check('partition_bytes_hash_count_' + path, ok)
                logical_count += part_count; logical_bytes += part_bytes
                part_results.append({'path': path, 'bytes': part_bytes, 'records': part_count,
                                     'sha256': part_hash.hexdigest(), 'matched': ok})
            ok = (logical_hash.hexdigest() == specification['logical_sha256']
                  and logical_count == specification['logical_records'])
            audit.check('logical_concat_hash_count_' + manifest_path + ':' + logical_name, ok)
            dataset_results.append({'logical_name': logical_name, 'logical_sha256': logical_hash.hexdigest(),
                                    'logical_records': logical_count, 'logical_bytes': logical_bytes,
                                    'matched': ok, 'parts': part_results})
        # Every tracked data shard under this manifest's partition directory must
        # be named by the manifest; reject retained/accidentally omitted shards.
        prefix = str(PurePosixPath(manifest_path).parent) + '/'
        shards = {p for p in tracked if p.startswith(prefix) and p.endswith('.jsonl')}
        audit.check('no_unlisted_partition_shards_' + manifest_path, shards <= all_parts)
        results.append({'manifest_path': manifest_path,
                        'manifest_sha256': hashlib.sha256((git.repo / manifest_path).read_bytes()).hexdigest(),
                        'dataset_count': len(dataset_results), 'part_count': len(all_parts),
                        'datasets': dataset_results})
    return results


def inspect_objects(git, head, attributes, audit):
    fsck = git.run(['fsck', '--full', '--strict', '--no-reflogs', '--no-dangling'], check=False)
    audit.require('git_fsck_passed', fsck.returncode == 0, redact(fsck.stderr.decode(errors='replace'))[-4000:])
    reachable = sorted(set(git.text(['rev-list', '--objects', '--no-object-names', head]).splitlines()))
    rows = git.run(['cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'],
                   data=('\n'.join(reachable) + '\n').encode()).stdout.decode().splitlines()
    objects, missing = [], []
    for row in rows:
        bits = row.split()
        if len(bits) != 3 or not bits[2].isdigit():
            missing.append(row)
        else:
            objects.append({'sha': bits[0], 'type': bits[1], 'bytes': int(bits[2])})
    audit.require('all_reachable_objects_present', not missing and len(objects) == len(reachable))
    blobs = [x for x in objects if x['type'] == 'blob']
    oversized = [x for x in blobs if x['bytes'] > 100 * 1024 * 1024]
    audit.check('no_blob_above_100MiB', not oversized)
    pointers = []
    small = [x for x in blobs if x['bytes'] <= 4096]
    if small:
        payload = git.run(['cat-file', '--batch'], data=('\n'.join(x['sha'] for x in small) + '\n').encode()).stdout
        offset = 0
        for item in small:
            stop = payload.index(b'\n', offset)
            header = payload[offset:stop].decode('ascii').split()
            if header != [item['sha'], 'blob', str(item['bytes'])]:
                raise ValueError('Unexpected cat-file batch header')
            start, end = stop + 1, stop + 1 + item['bytes']
            if payload[end:end + 1] != b'\n':
                raise ValueError('Truncated cat-file batch output')
            if payload[start:end].startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                pointers.append(item['sha'])
            offset = end + 1
        if offset != len(payload):
            raise ValueError('Unexpected trailing cat-file batch bytes')
    audit.check('no_lfs_pointers_in_reachable_history', not pointers)
    return {'reachable_objects': len(objects), 'reachable_blobs': len(blobs),
            'reachable_inventory_sha256': digest_json(objects), 'by_type': dict(Counter(x['type'] for x in objects)),
            'missing_objects': missing, 'largest_blob': max(blobs, key=lambda x: x['bytes']) if blobs else None,
            'blobs_above_100MiB': oversized, 'git_fsck_exit_code': fsck.returncode,
            'git_fsck_stdout': redact(fsck.stdout.decode(errors='replace'))[-4000:],
            'git_fsck_stderr': redact(fsck.stderr.decode(errors='replace'))[-4000:],
            'shallow': False, 'partial_clone_config': [], 'lfs_pointer_blobs': pointers,
            'head_lfs_attributes': attributes, 'lfs_pointer_scan_completed': True}


def inspect_snapshot(git, head, tree, audit):
    # A local pre-existing repository may have local filter commands even though
    # global/system configuration is disabled. Reject those before git status
    # could invoke a clean filter. Inspect only these non-credential key names;
    # never print values or read any credential store.
    filters = git.run(['config', '--local', '--name-only', '--get-regexp',
                       '^filter\\..*\\.(clean|smudge|process)$'], check=False)
    audit.require('no_local_external_filter_commands', filters.returncode == 1 and not filters.stdout)
    before = git.text(['status', '--porcelain=v1', '--untracked-files=all'])
    audit.require('worktree_clean_before', not before, before)
    audit.require('head_matches', git.text(['rev-parse', 'HEAD']) == head)
    audit.require('tree_matches', git.text(['rev-parse', 'HEAD^{tree}']) == tree)
    object_independence(git, audit)
    history = inspect_history(git, head, audit)
    entries = tree_entries(git, head)
    files, attributes = inspect_files(git, entries, audit)
    checkpoint = inspect_checkpoint(git, files, audit)
    partitions = inspect_partitions(git, entries, audit)
    objects = inspect_objects(git, head, attributes, audit)
    after = git.text(['status', '--porcelain=v1', '--untracked-files=all'])
    unchanged = git.text(['rev-parse', 'HEAD']) == head
    audit.check('worktree_clean_after', not after, after)
    audit.check('head_unchanged', unchanged)
    unique_blobs = {x['sha']: x['bytes'] for x in entries}
    return {'head_commit': head, 'head_tree': tree, 'baseline_commit': CP2,
            'baseline_tree': git.text(['rev-parse', CP2 + '^{tree}']), 'baseline_is_ancestor': True,
            'history': history, 'working_tree': {'clean_before': not before, 'clean_after': not after,
            'status_before': before, 'status_after': after, 'head_unchanged': unchanged,
            'raw_file_bytes_match_head': all(x['matched'] for x in files),
            'mismatches': [x for x in files if not x['matched']]},
            'checkpoint': checkpoint, 'head_snapshot': {'file_entries': len(entries),
            'distinct_blob_count': len(unique_blobs), 'file_bytes': sum(x['bytes'] for x in entries),
            'distinct_blob_bytes': sum(unique_blobs.values()), 'symlinks': [], 'tree_entries': entries},
            'verified_files': files, 'partition_integrity': partitions, 'object_integrity': objects}


def validate_trusted_manifest(expected, head, tree, audit):
    audit.require('trusted_manifest_identity', expected.get('status') == 'passed'
                  and expected.get('head_commit') == head and expected.get('head_tree') == tree
                  and expected.get('baseline_commit') == CP2
                  and expected.get('checkpoint', {}).get('checkpoint_id') == 'CP-0005'
                  and expected.get('checkpoint', {}).get('parent_checkpoint_id') == 'CP-0004')
    entries = expected['head_snapshot']['tree_entries']
    paths = [safe_relative(x['path']) for x in entries]
    audit.require('trusted_manifest_file_count_consistent', len(paths) == len(set(paths))
                  and expected['head_snapshot']['file_entries'] == len(paths))
    hashes = {x['path']: x['sha256'] for x in expected['checkpoint']['artifact_hashes_verified']}
    audit.require('trusted_manifest_artifact_count_consistent',
                  len(hashes) == len(expected['checkpoint']['artifact_hashes_verified'])
                  == expected['checkpoint']['artifact_hash_count']
                  and set(hashes) == set(paths) - {CP_PATH})
    hashes[CP_PATH] = expected['checkpoint']['checkpoint_file_sha256']
    audit.require('trusted_manifest_sha256_coverage', set(hashes) == set(paths)
                  and all(re.fullmatch('[0-9a-f]{64}', x) for x in hashes.values()))
    return entries, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    parser.add_argument('--expected-head', required=True, type=sha_arg)
    parser.add_argument('--expected-tree', required=True, type=sha_arg)
    parser.add_argument('--manifest-sha', required=True, type=lambda x: sha_arg(x, 64))
    parser.add_argument('--manifest', type=Path, default=HERE / 'local-integrity-cp5.json')
    parser.add_argument('--clone-dir', type=Path, default=HERE / ('remote-cp5-' + stamp + '-' + uuid.uuid4().hex[:8]))
    parser.add_argument('--out', type=Path, default=HERE / 'remote-verification-cp5.json')
    parser.add_argument('--clone-timeout', type=int, default=1800)
    args = parser.parse_args()
    clone_dir, out, manifest = args.clone_dir.resolve(), args.out.resolve(), args.manifest.resolve()
    if (clone_dir.is_relative_to(LOCAL_REPO.resolve()) or out.is_relative_to(LOCAL_REPO.resolve())
            or out.is_relative_to(clone_dir) or manifest.is_relative_to(clone_dir)
            or clone_dir == manifest or out == manifest):
        parser.error('Fresh clone, trusted input and output must be separate and outside the canonical repository')
    if args.clone_timeout <= 0:
        parser.error('--clone-timeout must be positive')
    audit, started = Checks(), time.monotonic()
    report = {'format_version': 2, 'started_at_utc': utc_now(), 'remote_url': URL,
              'remote_branch': BRANCH, 'expected_head': args.expected_head, 'expected_tree': args.expected_tree,
              'expected_manifest_sha256': args.manifest_sha, 'clone_directory': str(clone_dir),
              'existing_local_repository_modified': False, 'remote_mutations_performed': False,
              'local_objects_borrowed': False, 'research_code_executed': False}
    fatal = None
    try:
        manifest_bytes = manifest.read_bytes()
        audit.require('trusted_local_manifest_unchanged', hashlib.sha256(manifest_bytes).hexdigest() == args.manifest_sha)
        expected = strict_json(manifest_bytes)
        expected_entries, expected_hashes = validate_trusted_manifest(expected, args.expected_head, args.expected_tree, audit)
        report['expected_file_count'] = len(expected_entries)
        audit.require('fresh_clone_destination', not clone_dir.exists())
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        git = Git(clone_dir)
        clone_args = ['clone', '--no-local', '--no-checkout', '--template=', '--branch', BRANCH,
                      '--origin', 'origin', URL, str(clone_dir)]
        report['clone_arguments'] = clone_args
        print('Cloning the frozen CP5 branch from GitHub into a fresh independent repository...', flush=True)
        result = git.run(clone_args, check=False, timeout=args.clone_timeout, in_repo=False)
        audit.require('clone_succeeded', result.returncode == 0, redact(result.stderr.decode(errors='replace'))[-4000:])
        report['clone_exit_code'] = result.returncode
        audit.require('remote_url_matches', git.text(['config', '--local', '--get', 'remote.origin.url']) == URL)
        audit.require('remote_tracking_tip_matches', git.text(['rev-parse', 'refs/remotes/origin/' + BRANCH]) == args.expected_head)
        audit.require('frozen_clone_head_before_checkout', git.text(['rev-parse', 'HEAD']) == args.expected_head)
        audit.require('frozen_clone_tree_before_checkout', git.text(['rev-parse', 'HEAD^{tree}']) == args.expected_tree)
        entries = tree_entries(git, 'HEAD')
        audit.require('all_path_mode_blob_entries_match', entries == expected_entries)
        audit.require('no_symlinks_or_submodules_before_checkout',
                      all(x['type'] == 'blob' and x['mode'] in ('100644', '100755') for x in entries))
        # A fresh clone has no project-installed filter configuration; system and
        # global config, templates, hooks and fsmonitor are disabled above.
        git.run(['checkout', '--force', '--detach', args.expected_head])
        print('Verifying every file, checkpoint hash, logical partition and reachable Git object...', flush=True)
        observed = inspect_snapshot(git, args.expected_head, args.expected_tree, audit)
        report.update(observed)
        actual_hashes = {x['path']: x['sha256'] for x in observed['verified_files']}
        audit.check('all_sha256_match_trusted_snapshot', actual_hashes == expected_hashes)
        audit.check('checkpoint_counts_match_trusted_snapshot', observed['checkpoint']['counts'] == expected['checkpoint']['counts'])
        audit.check('partition_integrity_matches_trusted_snapshot', observed['partition_integrity'] == expected['partition_integrity'])
        for field in ['reachable_objects', 'reachable_blobs', 'reachable_inventory_sha256']:
            audit.check('object_' + field + '_matches_trusted_snapshot', observed['object_integrity'][field] == expected['object_integrity'][field])
        audit.check('clone_expected_file_count', len(observed['verified_files']) == len(expected_entries))
    except Exception as error:
        fatal = redact(str(error))
        audit.failures.append({'check': 'execution_completed', 'detail': fatal})
    report.update(status='passed' if not audit.failures else 'failed', checks=audit.checks,
                  failures=audit.failures, completed_at_utc=utc_now(), duration_seconds=round(time.monotonic() - started, 3))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'failed_checks': len(audit.failures),
                      'head': report.get('head_commit'), 'tree': report.get('head_tree'),
                      'report': str(out)}, ensure_ascii=False), flush=True)
    return 2 if fatal else 1 if audit.failures else 0


if __name__ == '__main__':
    sys.exit(main())
