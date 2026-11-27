#!/usr/bin/env python3
"""Read-only CP9 maintenance audit against the published CP8 scientific baseline.

All general schema, evidence, scale, topology, query, export and partition rules
are inherited from audit_run. The historical S19 decision is inherited only as
the exact already-verified CP8 record and its published certificate; unavailable
private PDFs are not claimed to have been read again. Original CP8 scientific,
query and merge-audit bytes are archived; current rows may contain only exactly
bound overdue unknown -> unknown_review_required transitions. No overlay or new
scientific exception exists, and the unchanged common gates inspect raw current
records.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from itertools import zip_longest
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

import audit_run as original

CHECKPOINT = 'CP-0009'
PARENT = 'CP-0008'
RUN = 'RUN-0007'
BASE_COMMIT = '2e749d4994bd3b8c66fcde59950779adc5d66085'
BASE_TREE = '6428de0a5ac1e7c288928462eb9c768d08dfff4c'
BASE_MANIFEST_SHA256 = 'af1d5f3f7551119c3d68a56d522fe4ce03583acac673ca3351d5b9ab7de77c34'
BASE_ASSESSMENTS_SHA256 = 'e92f21afe162bc6bf5d207e7294ab9e71ee72649773541afbacfe74977789a80'
S19_ID = 'AS-S19-L05-baseline-receptive-field'
S19_PROOF = 'temp/validation/cp4-explicit-manual-reassessment-evidence.json'
S19_PROOF_SHA256 = '2326bf4aa991fe1b990a93eeacbe1b6d3d3e833db59aa15f4b8c21f873806f88'
S19_RECORD_SHA256 = '75774b00032035fe24d28133f79fbbb4fb4cb7e44fa9a463c34523b53ab81cf6'
CP_PATH = 'temp/snapshots/checkpoints/CP-0009.json'
INTEGRATION_PATH = 'temp/reports/RUN-0007-integration.json'
RUN_PATH = 'temp/runs/RUN-0007.json'
RUN_FINALIZATION_FIELDS = frozenset({
    'status', 'end_checkpoint_id', 'checkpoint_status', 'checkpoint_validation_state',
    'checkpoint_candidate_created_at_utc', 'checkpoint_completed_at_utc',
    'checkpoint_wall_clock_hours', 'budget_exhausted', 'pause_reason', 'sync_state',
    'post_commit_verification_url', 'last_completed_batch', 'qa_completed_at_utc',
})
FROZEN_PATHS = tuple(f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 9)) + (
    'temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json',
    'temp/seed-manifest.jsonl', 'temp/schema.json', S19_PROOF,
    'temp/validation/cp6-data-audit.json', 'temp/validation/cp7-data-audit.json',
    'temp/validation/cp8-data-audit.json',
)
EXPORTS = (
    'ref.bib', 'ref.html', 'temp/exports/citation_graph.json',
    'temp/exports/evidence_matrix.csv', 'temp/exports/research_entities.json',
    'temp/exports/research_implications.csv', 'temp/exports/research_paths.json',
)
REQUEST_COUNT_BASIS = (
    'Count explicit source operations in each retained receipt, including every operation '
    'in a multi-operation tool batch; cache reuse counts zero; Git synchronization is excluded.'
)


def external_request_count(observation):
    count = observation.get('external_request_count')
    flag = observation.get('external_request_performed')
    if type(count) is not int or count < 0:
        raise ValueError('RUN7 source observation requires an explicit nonnegative integer request count')
    if type(flag) is not bool or flag != (count > 0):
        raise ValueError('Source execution flag differs from the explicit request count')
    if observation.get('cache_hit') is True and count != 0:
        raise ValueError('Cache reuse cannot consume external requests')
    return count


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_digest(value):
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False).encode('utf-8'))


def input_digest(snapshot):
    return canonical_digest(snapshot)


def run_accounting_projection(run):
    """Freeze every run field except an explicit finalization-status whitelist."""
    required = {'run_id', 'scope_id', 'start_checkpoint_id', 'start_commit_sha',
                'started_at_utc', 'authorization', 'authorized_stages', 'budget',
                'branch', 'external_requests_used', 'manual_review_items_used',
                'cache_reuse_events', 'paid_spend', 'research_cutoff_at_utc'}
    if not required.issubset(run):
        raise ValueError('RUN7 is missing immutable authorization/accounting fields')
    return {key: value for key, value in run.items() if key not in RUN_FINALIZATION_FIELDS}


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '.git' in path.parts or not path.parts:
        raise ValueError('Unsafe repository-relative input path: ' + str(value))
    return str(path)


def input_snapshot(repo, names, watch=None):
    """Return the exact map shared by the candidate builder and this audit."""
    repo = Path(repo).resolve()
    result = {}
    for name in sorted(names):
        relative = safe_relative(name)
        path = (repo / relative).resolve()
        if not path.is_relative_to(repo) or not path.is_file():
            raise ValueError('Missing or escaping bound input: ' + relative)
        if watch:
            watch(path)
        result[relative] = {'bytes': path.stat().st_size, 'sha256': original.sha(path)}
    return result


def required_input_names(repo):
    """Include logical inputs, reviewed RUN7 evidence, tooling and seven exports.

    CP9 itself is bound separately so that it can contain this map. QA reports
    are written outside the repository and are not mutable inputs to their own
    audit. The caller may freeze additional inputs; this set is the minimum.
    """
    repo = Path(repo).resolve()
    names = {'temp/partitions/manifest.json', INTEGRATION_PATH, *FROZEN_PATHS, *EXPORTS}
    manifest = json.loads((repo / 'temp/partitions/manifest.json').read_bytes())
    logical = {p.name for p in (repo / 'temp').glob('*.jsonl')}
    logical.update(manifest['datasets'])
    for name in logical:
        names.add('temp/' + safe_relative(name))
        for part in manifest['datasets'].get(name, {}).get('parts', []):
            names.add('temp/' + safe_relative(part['path']))
    for pattern in ('temp/reports/RUN-0007*.json', 'temp/query-results/Q-RUN07*.json',
                    'scripts/*.py', 'scripts/*.css', 'scripts/*.mjs', 'scripts/README.md'):
        names.update(str(p.relative_to(repo)) for p in repo.glob(pattern) if p.is_file())
    for root in (repo / 'temp/history/CP-0008', repo / 'temp/reports'):
        if root.exists():
            names.update(str(p.relative_to(repo)) for p in root.rglob('*')
                         if p.is_file() and (root.name == 'CP-0008' or 'RUN-0007' in str(p.relative_to(root))))
    return names


def git_bytes(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def baseline_bytes(repo, relative):
    return git_bytes(repo, 'show', BASE_COMMIT + ':' + safe_relative(relative))


def baseline_file_digest(repo, relative):
    relative = safe_relative(relative)
    process = subprocess.Popen(['git', '-C', str(repo), 'show', BASE_COMMIT + ':' + relative],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: process.stdout.read(1024 * 1024), b''):
        digest.update(block)
        size += len(block)
    error = process.stderr.read()
    if process.wait() != 0:
        raise ValueError('Cannot read frozen baseline: ' + relative + ': ' + error.decode(errors='replace'))
    return {'path': relative, 'bytes': size, 'sha256': digest.hexdigest()}


def assessment_lines(raw):
    rows = {}
    for line in raw.splitlines(keepends=True):
        if not line.strip():
            continue
        row = json.loads(line)
        identifier = row['assessment_id']
        if identifier in rows:
            raise ValueError('Duplicate Assessment ID: ' + identifier)
        rows[identifier] = (row, line)
    return rows


def logical_assessment_bytes(read_file):
    manifest_raw = read_file('temp/partitions/manifest.json')
    manifest = json.loads(manifest_raw)
    item = manifest['datasets'].get('assessments.jsonl')
    if item is None:
        return read_file('temp/assessments.jsonl'), manifest_raw
    parts = []
    for part in item['parts']:
        raw = read_file('temp/' + safe_relative(part['path']))
        if not (len(raw) == part['bytes'] and sha_bytes(raw) == part['sha256']
                and sum(bool(line.strip()) for line in raw.splitlines()) == part['records']):
            raise ValueError('Assessment partition differs: ' + part['path'])
        parts.append(raw)
    raw = b''.join(parts)
    if sha_bytes(raw) != item['logical_sha256'] or len(assessment_lines(raw)) != item['logical_records']:
        raise ValueError('Assessment logical manifest differs')
    return raw, manifest_raw


def published_cp8_baseline(repo):
    tree = git_bytes(repo, 'rev-parse', BASE_COMMIT + '^{tree}').decode().strip()
    if tree != BASE_TREE:
        raise ValueError('CP8 commit/tree differs from the independently verified baseline')
    raw, manifest = logical_assessment_bytes(lambda name: baseline_bytes(repo, name))
    if sha_bytes(raw) != BASE_ASSESSMENTS_SHA256 or sha_bytes(manifest) != BASE_MANIFEST_SHA256:
        raise ValueError('Frozen CP8 Assessment or partition bytes differ')
    rows = assessment_lines(raw)
    active = [row for row, _ in rows.values() if row['assessment_status'] == 'active']
    rejected = sorted(row['assessment_id'] for row in active
                      if row['evidence_admission_status'] == 'insufficient_evidence')
    counter = sorted(row['assessment_id'] for row in active if row['counter_evidence'])
    if not (len(rows) == len(active) == 72 and len(rejected) == 9 and len(counter) == 23):
        raise ValueError('Frozen CP8 scientific population differs')
    proof_raw = baseline_bytes(repo, S19_PROOF)
    proof = json.loads(proof_raw)
    if not (sha_bytes(proof_raw) == S19_PROOF_SHA256
            and proof['assessment_id'] == S19_ID
            and proof['canonical_after_sha256'] == S19_RECORD_SHA256
            and canonical_digest(rows[S19_ID][0]) == S19_RECORD_SHA256
            and proof['decision'] == 'explicit_manual_reassessment'):
        raise ValueError('Published historical S19 decision differs')
    audited = json.loads(baseline_bytes(repo, 'temp/validation/cp8-data-audit.json'))
    if not (audited['status'] == 'passed' and audited['error_count'] == 0
            and audited['statistics']['active_assessments'] == 72
            and audited['counters']['cp7_assessments_byte_preserved'] == 71
            and audited['statistics']['historical_s19_decision']['status'] == 'inherited_exact_published_record'
            and audited['statistics']['historical_s19_decision']['canonical_record_sha256'] == S19_RECORD_SHA256
            and audited['statistics']['historical_s19_decision']['new_exception_granted'] is False):
        raise ValueError('Published CP8 scientific audit did not establish this baseline')
    certificate = {
        'source_commit': BASE_COMMIT, 'source_tree': BASE_TREE,
        'manifest_sha256': sha_bytes(manifest), 'logical_sha256': sha_bytes(raw),
        'logical_bytes': len(raw), 'baseline_records': len(rows), 'active_records': len(active),
        'insufficient_ids': rejected, 'counter_evidence_ids': counter,
        'historical_s19_proof_sha256': sha_bytes(proof_raw),
        'historical_s19_record_sha256': S19_RECORD_SHA256,
        'frozen_files': [baseline_file_digest(repo, path) for path in FROZEN_PATHS],
        'additional_scientific_exceptions_allowed': 0,
        'historical_primary_files_reread': False,
        'rule': 'Archive all 72 published CP8 Assessment original JSONL bytes; preserve all scientific content and permit only fully bound unknown-to-unknown_review_required status migration in current records. General scientific gates are unchanged.',
    }
    return rows, certificate


MAINTENANCE_ARCHIVES = ('assessments', 'merged-work-audit', 'queries')
MIGRATION_IDS = {
    'works': 'work_id', 'merged-work-audit': 'work_id', 'assessments': 'assessment_id',
    'authors': 'person_id', 'organizations': 'org_id', 'versions': 'version_id',
    'queries': 'query_id', 'source-observations': 'observation_id',
}
TASK_MIGRATION_KEYS = frozenset({'event_sequence', 'checkpoint_id', 'updated_at_utc', 'overdue', 'priority'})
PRIORITIES = {'low': 0, 'normal': 1, 'high': 2, 'urgent': 3, 'critical': 4}


def maintenance_require(ok, message):
    if not ok:
        raise ValueError('CP9 maintenance: ' + message)


def bound_file(repo, binding, watch=None):
    name = safe_relative(binding['path'])
    path = (Path(repo) / name).resolve()
    maintenance_require(path.is_relative_to(Path(repo).resolve()) and path.is_file(), 'Missing bound file: ' + name)
    if watch:
        watch(path)
    raw = path.read_bytes()
    maintenance_require(type(binding['bytes']) is int and len(raw) == binding['bytes']
                        and sha_bytes(raw) == binding['sha256'], 'Bound file bytes/hash differ: ' + name)
    return raw


def migration_rows(repo, parts, watch=None):
    maintenance_require(isinstance(parts, list), 'Migration parts must be a list')
    seen = set()
    for part in parts:
        name = safe_relative(part['path'])
        maintenance_require(name.startswith('temp/reports/RUN-0007') and name not in seen,
                            'Unexpected or repeated migration part: ' + name)
        seen.add(name)
        raw = bound_file(repo, part, watch)
        lines = raw.splitlines(keepends=True)
        maintenance_require(type(part['records']) is int and len(lines) == part['records']
                            and all(line.strip() and line.endswith(b'\n') for line in lines),
                            'Migration part record count/line ending differs: ' + name)
        for line in lines:
            row = json.loads(line)
            maintenance_require(isinstance(row, dict), 'Migration record must be an object')
            yield row


def logical_manifest_at(repo, commit=None, watch=None):
    name = 'temp/partitions/manifest.json'
    if commit:
        return json.loads(git_bytes(repo, 'show', commit + ':' + name))
    path = Path(repo) / name
    if watch:
        watch(path)
    return json.loads(path.read_bytes())


def logical_names_at(repo, commit=None):
    if commit:
        names = git_bytes(repo, 'ls-tree', '--name-only', commit + ':temp').decode().splitlines()
        return {name.removesuffix('.jsonl') for name in names if name.endswith('.jsonl')}
    return {path.stem for path in (Path(repo) / 'temp').glob('*.jsonl')}


def logical_lines_at(repo, name, manifest, commit=None, watch=None):
    filename = name + '.jsonl'
    item = manifest['datasets'].get(filename)
    parts = item['parts'] if item else [{'path': filename}]
    digest, count = hashlib.sha256(), 0
    for part in parts:
        relative = 'temp/' + safe_relative(part['path'])
        if commit:
            raw = git_bytes(repo, 'show', commit + ':' + relative)
        else:
            path = Path(repo) / relative
            if watch:
                watch(path)
            raw = path.read_bytes()
        lines = raw.splitlines(keepends=True)
        maintenance_require(all(line.strip() and line.endswith(b'\n') for line in lines),
                            'Unexpected empty/unterminated logical line: ' + relative)
        if item:
            maintenance_require(len(raw) == part['bytes'] and sha_bytes(raw) == part['sha256']
                                and len(lines) == part['records'], 'Logical partition differs: ' + relative)
        digest.update(raw)
        count += len(lines)
        for line in lines:
            yield json.loads(line), line
    if item:
        maintenance_require(count == item['logical_records'] and digest.hexdigest() == item['logical_sha256'],
                            'Logical dataset differs: ' + filename)


def logical_stats_at(repo, name, manifest, commit=None, watch=None):
    digest, size, records = hashlib.sha256(), 0, 0
    for _, line in logical_lines_at(repo, name, manifest, commit, watch):
        digest.update(line); size += len(line); records += 1
    return {'bytes': size, 'sha256': digest.hexdigest(), 'records': records}


def migration_pointer_parent(record, pointer):
    maintenance_require(isinstance(pointer, str) and pointer.startswith('/') and pointer.endswith('/status'),
                        'Only an explicit JSON-pointer status leaf may change')
    keys = pointer[1:].split('/')
    maintenance_require(all('~' not in key.replace('~0', '').replace('~1', '') for key in keys),
                        'Invalid JSON-pointer escape')
    keys = [key.replace('~1', '/').replace('~0', '~') for key in keys]
    node = record
    for key in keys[:-1]:
        if isinstance(node, list):
            maintenance_require(key.isdigit() and str(int(key)) == key and int(key) < len(node), 'Invalid array pointer')
            node = node[int(key)]
        else:
            maintenance_require(isinstance(node, dict) and key in node, 'Migration pointer is absent')
            node = node[key]
    maintenance_require(isinstance(node, dict) and keys[-1] == 'status' and 'status' in node,
                        'Migration pointer must identify an existing FieldState status')
    return node


def verify_legacy_artifacts(repo, base_manifest, watch=None):
    """Keep CP8 receipts, evidence, old tools, runs and QA at their original hashes.

    Only the complete logical data checked by verify_maintenance, its physical
    partition manifest, regenerated exports and three execution-status documents
    may differ. New CP9 files never replace a historical artifact.
    """
    checkpoint_path = 'temp/snapshots/checkpoints/CP-0008.json'
    raw = baseline_bytes(repo, checkpoint_path)
    parent = json.loads(raw)
    maintenance_require(parent['checkpoint_id'] == PARENT and parent['status'] == 'valid'
                        and sha_bytes(raw) == '85e5312505b14862df28c4193b74aeaf4767bb3b56942786f3948b172edcedb0',
                        'Frozen CP8 artifact inventory differs')
    expected = dict(parent['artifact_hashes'])
    expected[checkpoint_path] = sha_bytes(raw)
    logical = {'temp/' + name + '.jsonl' for name in logical_names_at(repo, BASE_COMMIT)}
    logical.update('temp/' + safe_relative(part['path'])
                   for dataset in base_manifest['datasets'].values() for part in dataset['parts'])
    excluded = logical | set(EXPORTS) | {
        'temp/partitions/manifest.json', 'README.md', 'temp/progress.md', 'temp/change-log.md',
    }
    checked = size = 0
    for name, expected_hash in expected.items():
        if name in excluded:
            continue
        path = Path(repo) / safe_relative(name)
        maintenance_require(path.is_file() and not path.is_symlink(), 'Historical artifact missing or replaced: ' + name)
        if watch:
            watch(path)
        maintenance_require(original.sha(path) == expected_hash, 'Historical artifact bytes changed: ' + name)
        checked += 1
        size += path.stat().st_size
    return {'status': 'passed', 'source_commit': BASE_COMMIT, 'checked_files': checked,
            'checked_bytes': size, 'excluded_paths': sorted(set(expected) & excluded),
            'original_query_receipts_and_evidence_preserved': True,
            'old_scripts_runs_and_qa_preserved': True}


def verify_maintenance(repo, now, watch=None):
    """Independently prove complete CP8 -> current bytes through bounded batches.

    This changes no state and grants no scientific exception. Every original
    task event is retained. The common audit validates the upgraded current
    FieldStates directly; no projected or historical-clock substitute is used.
    """
    repo = Path(repo).resolve()
    report_path = repo / INTEGRATION_PATH
    if watch:
        watch(report_path)
    report = json.loads(report_path.read_bytes())
    maintenance_require(report.get('maintenance_only') is True
                        and report['run_id'] == RUN and report['checkpoint_id'] == CHECKPOINT
                        and report['scope_id'] == 'SCOPE-0001'
                        and report['baseline_checkpoint_id'] == PARENT and report['baseline_commit'] == BASE_COMMIT,
                        'Integration identity or maintenance declaration differs')
    maintenance_require(report.get('changed_records') == [] and all(
        type(report.get(key)) is int and report[key] == 0 for key in
        ('new_query_rows', 'external_requests', 'cache_reuse_events', 'manual_review_activities')),
        'Maintenance cannot introduce research queries, reviews, or generic record mutations')
    for key in ('counts_before', 'counts_after'):
        maintenance_require(isinstance(report.get(key), dict) and all(
            isinstance(name, str) and type(count) is int and count >= 0
            for name, count in report[key].items()), 'Logical counts must be explicit nonnegative integers')
    bindings = report['maintenance_migrations']
    maintenance_require(isinstance(bindings, list) and bindings, 'At least one exact migration batch is required')
    batches, paths = [], set()
    for binding in bindings:
        name = safe_relative(binding['path'])
        maintenance_require(name.startswith('temp/reports/RUN-0007-unknown-escalation-') and name not in paths,
                            'Unexpected or duplicate batch manifest')
        paths.add(name)
        batch = json.loads(bound_file(repo, binding, watch))
        for key, expected in (('run_id', RUN), ('checkpoint_id', CHECKPOINT), ('scope_id', 'SCOPE-0001')):
            maintenance_require(batch.get(key) == expected, 'Batch identity differs: ' + key)
        evaluated = original.utc(batch['evaluated_at_utc'])
        maintenance_require(evaluated is not None and evaluated <= now, 'Batch time is unavailable or in the future')
        commit = batch['before_commit']
        maintenance_require(isinstance(commit, str) and len(commit) == 40 and set(commit) <= set('0123456789abcdef'),
                            'Batch needs an exact before commit')
        git_bytes(repo, 'merge-base', '--is-ancestor', BASE_COMMIT, commit)
        if batches:
            maintenance_require(evaluated >= batches[-1][1], 'Batch times are not chronological')
            git_bytes(repo, 'merge-base', '--is-ancestor', batches[-1][0]['before_commit'], commit)
        batches.append((batch, evaluated))
    base_manifest = logical_manifest_at(repo, BASE_COMMIT)
    legacy = verify_legacy_artifacts(repo, base_manifest, watch)
    names = logical_names_at(repo, BASE_COMMIT)
    base_stats = {name: logical_stats_at(repo, name, base_manifest, BASE_COMMIT) for name in sorted(names)}
    maintenance_require(report['counts_before'] == {name: item['records'] for name, item in base_stats.items()},
                        'Integration baseline counts differ from complete CP8')
    archives = {}
    for name in MAINTENANCE_ARCHIVES:
        path = 'temp/history/CP-0008/' + name + '.jsonl'
        expected = base_stats[name]
        binding = {'path': path, 'bytes': expected['bytes'], 'sha256': expected['sha256']}
        bound_file(repo, binding, watch)
        archives[name] = binding
    first_commit = batches[0][0]['before_commit']
    first_manifest = logical_manifest_at(repo, first_commit)
    maintenance_require(logical_names_at(repo, first_commit) == names, 'Initial logical dataset set differs from CP8')
    for name in names:
        maintenance_require(logical_stats_at(repo, name, first_manifest, first_commit) == base_stats[name],
                            'Unrecorded change before first maintenance batch: ' + name)
    totals = Counter()
    final_stats = None
    for batch_index, (batch, evaluated) in enumerate(batches):
        before_commit = batch['before_commit']
        after_commit = batches[batch_index + 1][0]['before_commit'] if batch_index + 1 < len(batches) else None
        before_manifest = logical_manifest_at(repo, before_commit)
        after_manifest = logical_manifest_at(repo, after_commit, watch)
        maintenance_require(logical_names_at(repo, before_commit) == logical_names_at(repo, after_commit) == names,
                            'Maintenance cannot add or remove logical datasets')
        maintenance_require(batch['history_archives'] == archives, 'Historical archive bindings differ')
        changed, events = {}, {}
        for row in migration_rows(repo, batch['change_parts'], watch):
            name, index = row['dataset'], row['line_index']
            maintenance_require(name in names and name != 'tasks' and type(index) is int and index >= 0
                                and (name, index) not in changed and isinstance(row['id'], str) and row['id']
                                and isinstance(row['changes'], list) and row['changes'],
                                'Invalid or repeated changed-record identity')
            changed[name, index] = row
        for row in migration_rows(repo, batch['task_event_parts'], watch):
            index = row['line_index']
            maintenance_require(type(index) is int and index >= 0 and index not in events
                                and isinstance(row['task_id'], str) and row['task_id']
                                and all(type(row[key]) is int and row[key] >= 0 for key in
                                        ('before_line_index', 'before_event_sequence', 'event_sequence')),
                                'Invalid or repeated appended task index')
            events[index] = row
        needed = {change['review_task_id'] for row in changed.values() for change in row['changes']}
        needed.update(row['task_id'] for row in events.values())
        previous = {}
        for index, (row, raw) in enumerate(logical_lines_at(repo, 'tasks', before_manifest, before_commit)):
            if row['task_id'] in needed:
                previous[row['task_id']] = (row, raw, index)
        maintenance_require(needed <= set(previous), 'A migration has no original review task')
        seen_changes, seen_events, changed_datasets = set(), set(), set()
        batch_stats = {}
        for name in sorted(names):
            before_digest, after_digest = hashlib.sha256(), hashlib.sha256()
            before_size = after_size = before_count = after_count = 0
            before_iter = logical_lines_at(repo, name, before_manifest, before_commit)
            after_iter = logical_lines_at(repo, name, after_manifest, after_commit, watch)
            for index, pair in enumerate(zip_longest(before_iter, after_iter)):
                before, after = pair
                if before is not None:
                    old, old_raw = before
                    before_digest.update(old_raw); before_size += len(old_raw); before_count += 1
                if after is not None:
                    new, new_raw = after
                    after_digest.update(new_raw); after_size += len(new_raw); after_count += 1
                maintenance_require(after is not None, 'Historical record was removed: ' + name)
                if name == 'tasks':
                    if before is not None:
                        maintenance_require(old_raw == new_raw, 'Original task-event bytes changed')
                        continue
                    event = events.get(index)
                    maintenance_require(event is not None and event['task_id'] == new['task_id'], 'Unbound appended task event')
                    old, old_raw, old_index = previous[new['task_id']]
                    maintenance_require(event['before_line_index'] == old_index
                                        and event['before_line_sha256'] == sha_bytes(old_raw)
                                        and event['after_line_sha256'] == sha_bytes(new_raw)
                                        and event['before_event_sequence'] == old['event_sequence']
                                        and event['event_sequence'] == new['event_sequence'] == old['event_sequence'] + 1,
                                        'Task event sequence or raw hashes differ')
                    maintenance_require(all(event[key] == old[key] == new[key] for key in ('unknown_since_utc', 'deadline_at_utc')),
                                        'Original task clock or deadline changed')
                    maintenance_require(canonical_digest({k: v for k, v in old.items() if k not in TASK_MIGRATION_KEYS})
                                        == canonical_digest({k: v for k, v in new.items() if k not in TASK_MIGRATION_KEYS}),
                                        'Task migration changed a protected field')
                    since, deadline, updated = (original.utc(new[key]) for key in
                                               ('unknown_since_utc', 'deadline_at_utc', 'updated_at_utc'))
                    maintenance_require(since is not None and deadline is not None and updated is not None
                                        and since <= deadline <= since + timedelta(hours=24) <= evaluated
                                        and updated == evaluated and new['checkpoint_id'] == CHECKPOINT
                                        and new['task_state'] not in original.TERMINAL and new['overdue'] is True
                                        and PRIORITIES.get(new['priority'], -1) >= max(2, PRIORITIES.get(old['priority'], -1)),
                                        'Task escalation time, priority or unresolved status differs')
                    seen_events.add(index); changed_datasets.add(name)
                    continue
                maintenance_require(before is not None, 'Maintenance cannot append scientific or source records: ' + name)
                entry = changed.get((name, index))
                if old_raw == new_raw:
                    maintenance_require(entry is None, 'Declared migration did not change its row')
                    continue
                maintenance_require(entry is not None and entry['before_line_sha256'] == sha_bytes(old_raw)
                                    and entry['after_line_sha256'] == sha_bytes(new_raw), 'Changed row is not bound to exact bytes')
                identifier = old.get(MIGRATION_IDS.get(name, ''), name + ':line:' + str(index))
                maintenance_require(entry['id'] == identifier, 'Changed row identifier differs')
                transformed, pointers = deepcopy(old), set()
                for change in entry['changes']:
                    pointer = change['pointer']
                    maintenance_require(pointer not in pointers and change['before'] == 'unknown'
                                        and change['after'] == 'unknown_review_required', 'Unexpected/repeated status transition')
                    pointers.add(pointer)
                    state = migration_pointer_parent(transformed, pointer)
                    task = previous[change['review_task_id']][0]
                    since, deadline = original.utc(change['unknown_since_utc']), original.utc(change['deadline_at_utc'])
                    maintenance_require(state['status'] == 'unknown' and state['review_task_id'] == change['review_task_id']
                                        and state['unknown_since_utc'] == change['unknown_since_utc'] == task['unknown_since_utc']
                                        and change['deadline_at_utc'] == task['deadline_at_utc']
                                        and since is not None and deadline is not None
                                        and since <= deadline <= since + timedelta(hours=24) <= evaluated,
                                        'Field escalation lacks the exact original clock/task or is premature')
                    state['status'] = 'unknown_review_required'
                    totals['field_status_transitions'] += 1
                maintenance_require(canonical_digest(transformed) == canonical_digest(new),
                                    'Migration changed a value, evidence, identity, reason, clock or undeclared field')
                seen_changes.add((name, index)); changed_datasets.add(name)
            stats = {
                'before': {'bytes': before_size, 'sha256': before_digest.hexdigest(), 'records': before_count},
                'after': {'bytes': after_size, 'sha256': after_digest.hexdigest(), 'records': after_count},
            }
            if name in batch['dataset_bindings']:
                for stage in ('before', 'after'):
                    item = batch['dataset_bindings'][name][stage]
                    maintenance_require(all(type(item[key]) is int and item[key] >= 0 for key in ('bytes', 'records'))
                                        and isinstance(item['sha256'], str), 'Malformed logical dataset binding')
                maintenance_require(batch['dataset_bindings'][name] == stats, 'Full dataset before/after binding differs: ' + name)
            batch_stats[name] = stats['after']
        maintenance_require(seen_changes == set(changed) and seen_events == set(events), 'A declared migration row/event is unused')
        maintenance_require(changed_datasets <= set(batch['dataset_bindings']) <= names,
                            'Changed dataset is unbound or manifest names an unknown dataset')
        maintenance_require(len({row['task_id'] for row in events.values()}) == len(events),
                            'Multiple escalations of one task in one batch')
        totals['changed_record_events'] += len(changed)
        totals['appended_task_events'] += len(events)
        final_stats = batch_stats
    counts_after = {name: item['records'] for name, item in final_stats.items()}
    maintenance_require(report['counts_after'] == counts_after, 'Integration final counts differ')
    maintenance_require(all(counts_after[name] == base_stats[name]['records'] for name in names if name != 'tasks'),
                        'Maintenance changed the scientific/source population')
    maintenance_require(counts_after['tasks'] - base_stats['tasks']['records'] == totals['appended_task_events'],
                        'Task append population differs')
    return {'status': 'passed', 'maintenance_only': True, 'baseline_commit': BASE_COMMIT,
            'verified_at_utc': now.isoformat().replace('+00:00', 'Z'), 'batches': len(batches),
            **dict(totals), 'history_archives': archives, 'original_task_events_preserved': True,
            'unchanged_cp8_artifacts': legacy,
            'original_clocks_preserved': True, 'scientific_values_and_evidence_unchanged': True,
            'counts_before': report['counts_before'], 'counts_after': counts_after,
            'logical_after': final_stats, 'new_scientific_claims': 0, 'new_queries': 0,
            'external_requests': 0, 'manual_reviews': 0}


class AuditCP9(original.Audit):
    def load(self):
        candidate_path = self.repo / CP_PATH
        self.watch(candidate_path)
        raw = candidate_path.read_bytes()
        candidate_hash, candidate_size = sha_bytes(raw), len(raw)
        candidate = json.loads(raw)
        validation = candidate['validation_results']
        expected = validation['canonical_input_hashes']
        run_path = self.repo / RUN_PATH
        self.watch(run_path)
        run_raw = run_path.read_bytes()
        run = json.loads(run_raw)
        projection = run_accounting_projection(run)
        self.require(projection == validation['run_accounting_projection']
                     and canonical_digest(projection) == validation['run_accounting_projection_sha256'],
                     'cp9_run_accounting_binding', 'Run authorization, baseline, budget, clock or accounting changed')
        self.require(run_accounting_projection(validation['run_record_at_freeze']) == projection,
                     'cp9_run_frozen_record_differs', 'Run changes exceed the finalization whitelist')
        self.stats['run_accounting_binding'] = {
            'expected_projection_sha256': canonical_digest(projection),
            'before_run_sha256': sha_bytes(run_raw),
            'mutable_finalization_fields': sorted(RUN_FINALIZATION_FIELDS),
        }
        frozen = original.utc(validation['input_frozen_at_utc'])
        began = datetime.now(timezone.utc)
        self.require(candidate['checkpoint_id'] == CHECKPOINT and candidate['parent_checkpoint_id'] == PARENT,
                     'cp9_input_binding_checkpoint', 'Expected CP9 with CP8 parent')
        self.require(frozen is not None and began >= frozen and self.now >= frozen,
                     'cp9_audit_predates_freeze', validation['input_frozen_at_utc'])
        self.require(required_input_names(self.repo).issubset(expected),
                     'cp9_input_universe_unbound', 'Every required canonical input must be frozen')
        before = input_snapshot(self.repo, expected, self.watch)
        self.require(before == expected and input_digest(expected) == validation['canonical_input_digest_sha256'],
                     'cp9_before_inputs_differ', 'Current bytes or frozen input-map digest differ')
        self.stats['cp9_input_binding'] = {
            'checkpoint_id': CHECKPOINT, 'input_frozen_at_utc': validation['input_frozen_at_utc'],
            'candidate_sha256': candidate_hash, 'candidate_bytes': candidate_size,
            'audit_started_at_utc': began.isoformat().replace('+00:00', 'Z'),
            'expected_digest_sha256': input_digest(expected), 'before_input_hashes': before,
            'before_digest_sha256': input_digest(before),
        }
        self._cp9_expected_inputs = expected
        self._cp8_records, self._cp8_certificate = published_cp8_baseline(self.repo)
        self._manual_assessment_baselines = [
            (BASE_COMMIT + ':temp/assessments.jsonl', [row for row, _ in self._cp8_records.values()])
        ]
        super().load()
        self._maintenance = verify_maintenance(self.repo, self.now, self.watch)
        self.stats['cp9_maintenance_migration'] = self._maintenance

    def task_queries(self):
        super().task_queries()
        queries = {qid: row for qid, row in self.indices.get('query', {}).items()
                   if row.get('checkpoint_id') == CHECKPOINT}
        observations = [row for row in self.datasets.get('source-observations.jsonl', [])
                        if row.get('query_id') in queries]
        self.require(Counter(row['query_id'] for row in observations) == Counter({qid: 1 for qid in queries}),
                     'cp9_request_observation_cardinality', 'Each RUN7 query needs one exact source observation')
        total = 0
        for observation in observations:
            qid = observation['query_id']
            try:
                count = external_request_count(observation)
                q = queries[qid]
                self.require(observation.get('cache_hit') == q.get('cache_hit')
                             and (not q.get('cache_hit') or count == 0),
                             'cp9_request_cache_count', 'Query/cache accounting differs', qid)
                path = self.repo / safe_relative(observation['receipt_path'])
                self.watch(path)
                raw = path.read_bytes()
                receipt = json.loads(raw)
                self.require(sha_bytes(raw) == observation['receipt_sha256']
                             and receipt['query_id'] == qid
                             and type(receipt['external_requests_performed']) is int
                             and receipt['external_requests_performed'] == count,
                             'cp9_request_receipt_count', 'Source operation count differs from exact receipt', qid)
                if 'external_request_count' in q.get('normalized_parameters', {}):
                    self.require(q['normalized_parameters']['external_request_count'] == count,
                                 'cp9_request_query_count', 'Normalized query count differs', qid)
                self.require(observation.get('external_request_count_basis') == REQUEST_COUNT_BASIS,
                             'cp9_request_count_basis', 'Explicit operation-count scope is missing', qid)
                total += count
            except Exception as error:
                self.note('cp9_request_count_invalid', str(error), qid)
        run = json.loads((self.repo / RUN_PATH).read_bytes())
        self.require(run['external_requests_used'] == total <= run['budget']['external_requests'],
                     'cp9_request_budget_reconciliation', 'RUN7 total/budget differs from source operation counts')
        self.stats['run7_external_request_accounting'] = {
            'query_rows': len(queries), 'source_operations': total,
            'externally_executed_receipts': sum(row.get('external_request_performed') is True for row in observations),
            'cache_receipts': sum(row.get('cache_hit') is True for row in observations),
            'count_basis': REQUEST_COUNT_BASIS,
        }

    def assessments(self):
        super().assessments()

        def read_current(relative):
            path = (self.repo / safe_relative(relative)).resolve()
            if not path.is_relative_to(self.repo.resolve()):
                raise ValueError('Current input escapes the repository')
            self.watch(path)
            return path.read_bytes()

        current_raw, _ = logical_assessment_bytes(read_current)
        current_lines = assessment_lines(current_raw)
        current = self.indices.get('assessment', {})
        self.require(self._maintenance['status'] == 'passed', 'cp9_migration_unverified', 'Complete status migration is required')
        self.require(set(current_lines) == set(self._cp8_records), 'cp9_maintenance_claim_population', 'Maintenance cannot add/remove scientific claims')
        for identifier, (old, old_line) in self._cp8_records.items():
            self.counts['cp8_assessments_compared'] += 1
            # verify_maintenance has already compared each complete current row
            # against CP8 and its exact archived line, allowing only declared
            # JSON-pointer status upgrades. All common scientific gates run above.
            if self.require(identifier in current, 'cp8_assessment_missing', 'Preserve every CP8 claim', identifier):
                self.counts['cp8_assessments_scientific_preserved'] += 1
                self.counts['cp8_assessment_original_rows_archived'] += 1
                if old['evidence_admission_status'] == 'insufficient_evidence':
                    self.counts['cp8_manual_rejections_preserved'] += 1
                if old['counter_evidence']:
                    self.counts['cp8_manual_counterevidence_preserved'] += 1
        for frozen in self._cp8_certificate['frozen_files']:
            path = self.repo / frozen['path']
            self.watch(path)
            if self.require(path.is_file(), 'cp8_frozen_file_missing', frozen['path']):
                if self.require(path.stat().st_size == frozen['bytes'] and original.sha(path) == frozen['sha256'],
                                'cp8_frozen_file_changed', 'Preserve historical checkpoint/scope/schema/evidence bytes', frozen['path']):
                    self.counts['cp8_frozen_files_byte_preserved'] += 1
        self.stats['cp8_frozen_scientific_baseline'] = self._cp8_certificate
        self.stats['historical_s19_decision'] = {
            'assessment_id': S19_ID, 'status': 'inherited_exact_published_record',
            'canonical_record_sha256': S19_RECORD_SHA256, 'proof_sha256': S19_PROOF_SHA256,
            'original_pdf_or_images_reread': False, 'new_exception_granted': False,
        }

    def finish(self):
        binding = self.stats.get('cp9_input_binding')
        if binding is None:
            self.note('cp9_input_binding_missing', 'No CP9 candidate/input freeze was established')
        else:
            try:
                after = input_snapshot(self.repo, self._cp9_expected_inputs, self.watch)
                binding.update(after_input_hashes=after, after_digest_sha256=input_digest(after),
                               candidate_sha256_after=original.sha(self.repo / CP_PATH),
                               audit_completed_at_utc=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
                self.require(required_input_names(self.repo).issubset(self._cp9_expected_inputs),
                             'cp9_input_universe_changed', 'New input appeared outside the frozen map')
                same = self.require(after == binding['before_input_hashes'] == self._cp9_expected_inputs,
                                    'cp9_after_inputs_differ', 'Canonical inputs changed during the audit')
                cp_same = self.require(binding['candidate_sha256_after'] == binding['candidate_sha256'],
                                       'cp9_candidate_changed_during_audit', 'Candidate changed during the audit')
                binding['passed'] = same and cp_same and (
                    binding['before_digest_sha256'] == binding['after_digest_sha256'] == binding['expected_digest_sha256'])
                run_raw = (self.repo / RUN_PATH).read_bytes()
                run_binding = self.stats['run_accounting_binding']
                run_binding['after_run_sha256'] = sha_bytes(run_raw)
                run_binding['after_projection_sha256'] = canonical_digest(run_accounting_projection(json.loads(run_raw)))
                run_binding['passed'] = self.require(
                    run_binding['before_run_sha256'] == run_binding['after_run_sha256']
                    and run_binding['expected_projection_sha256'] == run_binding['after_projection_sha256'],
                    'cp9_run_changed_during_audit', 'Run bytes/accounting changed during the read-only audit')
            except Exception as error:
                binding['passed'] = False
                self.note('cp9_input_binding_finish_error', str(error))
        return super().finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--now', help='Explicit UTC audit time; omit for the actual current clock')
    parser.add_argument('--max-examples', type=int, default=20)
    args = parser.parse_args()
    now = original.utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error('--now must include a timezone')
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.is_relative_to(repo):
        parser.error('--out must be outside the repository; the audit is read-only')
    return AuditCP9(repo, out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
