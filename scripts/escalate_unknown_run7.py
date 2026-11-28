#!/usr/bin/env python3
"""Restore overdue unknown review state for RUN7/CP9 without new research.

Default: inspect the complete logical datasets and print a read-only preview.
--apply: require a clean committed worktree, use the actual UTC evaluation time,
archive the exact published CP8 originals, replace only due FieldState.status
string tokens, and append complete next task events. No network or Git write is
performed. The root operator must commit/synchronize this transaction before
further research. Each apply is idempotent until another original clock expires.

JSONL line hashes include the original line terminator. line_index means the
zero-based nonempty record ordinal in the complete manifest-ordered dataset.
Change/event manifests are split below 4 MiB; they never duplicate full entities.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

from storage import read_logical
from checkpoint_cp8 import latest_tasks, TERMINAL

ROOT = Path(__file__).resolve().parents[1]
BASE = '2e749d4994bd3b8c66fcde59950779adc5d66085'
BASE_TREE = '6428de0a5ac1e7c288928462eb9c768d08dfff4c'
RUN, CP, SCOPE = 'RUN-0007', 'CP-0009', 'SCOPE-0001'
INDEX = 'temp/reports/RUN-0007-integration.json'
RUN_PATH = 'temp/runs/RUN-0007.json'
CONTRACT = 'temp/reports/RUN-0007-recovery-contract.json'
CAP = 4 * 1024 * 1024
ARCHIVES = {
    'assessments': ('e92f21afe162bc6bf5d207e7294ab9e71ee72649773541afbacfe74977789a80', 3719058),
    'merged-work-audit': ('45c8a88ad5bb024e0a576e27d5f9a8bf2a0bc75831b79dbf9415567d5128213f', 927703),
    'queries': ('c9e6038e1053747d11c89bcc97042a92bb0631109d688edfa0af0bc26173cc20', 2733758),
}
IDS = {
    'works': 'work_id', 'merged-work-audit': 'work_id',
    'versions': 'version_id', 'authors': 'person_id',
    'organizations': 'org_id', 'projects': 'project_id',
    'assessments': 'assessment_id', 'aliases': 'alias_id',
    'reference-occurrences': 'occurrence_id', 'citation-edges': 'edge_id',
    'queries': 'query_id', 'tasks': 'task_id', 'uploads': 'upload_id',
    'source-observations': 'observation_id', 'manual-reviews': 'review_id',
    'citation-context-audit': 'context_id', 'discovery-paths': 'discovery_id',
    'author-publication-leads': 'discovery_id', 'institution-project-leads': 'lead_id',
    'project-relations': 'relation_id', 'work-relations': 'relation_id',
    'source-list-coverage': 'coverage_id', 'reference-coverage': 'work_id',
    'new-fulltext-reference-audit': 'occurrence_id',
    'official-person-review-facts': 'person_id', 'privacy-redactions': 'redaction_id',
    'work-merge-events': 'event_id', 'cascade-events': 'cascade_event_id',
}
TASK_ALLOWED = {'event_sequence', 'checkpoint_id', 'updated_at_utc', 'overdue', 'priority'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def utc(value):
    require(isinstance(value, str) and value.endswith('Z'), 'Expected original UTC clock: ' + str(value))
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.utcoffset() == timedelta(0), 'Non-UTC clock')
    return result


def safe(value):
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and '.git' not in path.parts,
            'Unsafe relative path: ' + str(value))
    return str(path)


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def info(raw):
    return {'bytes': len(raw), 'sha256': sha(raw)}


def logical_names(repo, manifest):
    names = {p.stem for p in (repo / 'temp').glob('*.jsonl')}
    names.update(Path(name).stem for name in manifest['datasets'])
    return sorted(names)


def parts_for(name, manifest):
    filename = name if name.endswith(('.jsonl', '.log')) else name + '.jsonl'
    entry = manifest['datasets'].get(filename)
    return entry['parts'] if entry else [{'path': filename}]


def logical_lines(repo, name, manifest, bindings=None):
    """Read every ordered physical part; preserve its exact line bytes."""
    for part in parts_for(name, manifest):
        relative = 'temp/' + safe(part['path'])
        path = repo / relative
        require(path.resolve().is_relative_to(repo) and not path.is_symlink(),
                'Escaping/symlink logical input: ' + relative)
        raw = path.read_bytes()
        if 'sha256' in part:
            require(len(raw) == part['bytes'] and sha(raw) == part['sha256']
                    and sum(bool(line.strip()) for line in raw.splitlines()) == part['records'],
                    'Physical partition mismatch: ' + relative)
        if bindings is not None:
            bindings[relative] = info(raw)
        yield from raw.splitlines(keepends=True)


def binding_of(lines):
    digest, size, count = hashlib.sha256(), 0, 0
    for raw in lines:
        digest.update(raw); size += len(raw); count += bool(raw.strip())
    return {'bytes': size, 'sha256': digest.hexdigest(), 'records': count}


def baseline_bindings(repo):
    manifest = json.loads(git(repo, 'show', BASE + ':temp/partitions/manifest.json'))
    paths = git(repo, 'ls-tree', '-r', '--name-only', BASE, '--', 'temp').decode().splitlines()
    names = {Path(p).stem for p in paths if p.startswith('temp/')
             and p.count('/') == 1 and p.endswith('.jsonl')}
    names.update(Path(p).stem for p in manifest['datasets'])
    result = {}
    for name in sorted(names):
        item = manifest['datasets'].get(name + '.jsonl')
        if item:
            result[name] = {'bytes': sum(x['bytes'] for x in item['parts']),
                            'sha256': item['logical_sha256'], 'records': item['logical_records']}
        else:
            raw = git(repo, 'show', BASE + ':temp/' + name + '.jsonl')
            result[name] = {**info(raw), 'records': sum(bool(x.strip()) for x in raw.splitlines())}
    return manifest, result


def row_id(dataset, row, ordinal):
    value = row.get(IDS.get(dataset, ''))
    return str(value) if value is not None else dataset + ':line:' + str(ordinal)


def pointer_key(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def objects_with_paths(value):
    stack = [('', value)]
    while stack:
        pointer, current = stack.pop()
        if isinstance(current, dict):
            yield pointer, current
            stack.extend((pointer + '/' + pointer_key(k), v) for k, v in current.items()
                         if isinstance(v, (dict, list)))
        elif isinstance(current, list):
            stack.extend((pointer + '/' + str(i), v) for i, v in enumerate(current)
                         if isinstance(v, (dict, list)))


def replace_status_tokens(raw, pointers):
    """Locate JSON string tokens, replacing no whitespace or other leaf bytes."""
    text, decoder, found = raw.decode('utf-8'), json.JSONDecoder(), {}
    wanted = set(pointers)

    def whitespace(i):
        while i < len(text) and text[i] in ' \t\r\n':
            i += 1
        return i

    def visit(i, pointer):
        i = whitespace(i)
        if text[i] == '{':
            i = whitespace(i + 1)
            if text[i] == '}':
                return i + 1
            while True:
                key, end = decoder.raw_decode(text, i)
                require(isinstance(key, str), 'Non-string JSON key')
                end = whitespace(end); require(text[end] == ':', 'Invalid JSON object')
                i = whitespace(visit(end + 1, pointer + '/' + pointer_key(key)))
                if text[i] == '}':
                    return i + 1
                require(text[i] == ',', 'Invalid JSON object separator'); i = whitespace(i + 1)
        if text[i] == '[':
            i = whitespace(i + 1); item = 0
            if text[i] == ']':
                return i + 1
            while True:
                i = whitespace(visit(i, pointer + '/' + str(item)))
                if text[i] == ']':
                    return i + 1
                require(text[i] == ',', 'Invalid JSON array separator')
                i = whitespace(i + 1); item += 1
        value, end = decoder.raw_decode(text, i)
        if pointer in wanted:
            require(value == 'unknown' and pointer not in found,
                    'Status pointer does not uniquely locate unknown: ' + pointer)
            found[pointer] = (i, end)
        return end

    end = visit(0, '')
    require(not text[end:].strip() and set(found) == wanted, 'Unresolved status pointer')
    for start, end in sorted(found.values(), reverse=True):
        text = text[:start] + '"unknown_review_required"' + text[end:]
    return text.encode('utf-8')


def next_event(before, evaluated):
    require(before.get('priority') in {'normal', 'high', 'critical'},
            'Invalid task priority; do not silently repair an unrelated schema error')
    after = deepcopy(before)
    after.update(event_sequence=before['event_sequence'] + 1, checkpoint_id=CP,
                 updated_at_utc=evaluated, overdue=True,
                 priority=before['priority'] if before['priority'] in {'high', 'critical'} else 'high')
    require({k for k in set(before) | set(after) if before.get(k) != after.get(k)} <= TASK_ALLOWED,
            'Unexpected automatic task mutation')
    return after


def write_parts(stage, directory, prefix, records):
    result, buffer, count = [], bytearray(), 0

    def flush():
        nonlocal buffer, count
        if not buffer:
            return
        path = f'{directory}/{prefix}-{len(result) + 1:04d}.jsonl'
        target = stage / 'files' / path; target.parent.mkdir(parents=True, exist_ok=True)
        raw = bytes(buffer); target.write_bytes(raw)
        result.append({'path': path, **info(raw), 'records': count})
        buffer, count = bytearray(), 0

    for record in records:
        raw = encoded(record); require(len(raw) <= CAP, 'One manifest record exceeds 4 MiB')
        if buffer and len(buffer) + len(raw) > CAP:
            flush()
        buffer.extend(raw); count += 1
    flush()
    return result


def stage_dataset(stage, name, lines, old_manifest, new_manifest):
    chunks, buffer, count, total, digest = [], bytearray(), 0, 0, hashlib.sha256()

    def flush():
        nonlocal buffer, count
        if not buffer:
            return
        raw = bytes(buffer); h = sha(raw)
        relative = name + '.jsonl' if not chunks else 'partitions/' + name + '/' + h + '.jsonl'
        target = stage / 'files/temp' / relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        chunks.append({'path': relative, 'sha256': h, 'bytes': len(raw), 'records': count})
        buffer, count = bytearray(), 0

    for raw in lines:
        require(len(raw) <= CAP, 'One canonical JSONL record exceeds 4 MiB')
        if buffer and len(buffer) + len(raw) > CAP:
            flush()
        buffer.extend(raw); count += bool(raw.strip()); total += bool(raw.strip()); digest.update(raw)
    flush()
    require(chunks, 'Refusing to create an empty logical dataset')
    value = {'logical_records': total, 'logical_sha256': digest.hexdigest(), 'parts': chunks}
    if len(chunks) > 1 or name + '.jsonl' in old_manifest['datasets']:
        new_manifest['datasets'][name + '.jsonl'] = value
    return {'bytes': sum(c['bytes'] for c in chunks), 'sha256': digest.hexdigest(), 'records': total}


def publish(repo, stage, deletions, expected_head, guards):
    """Replace staged files with rollback copies; commit/synchronization is external."""
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == expected_head, 'HEAD changed during preview/staging')
    require(not git(repo, 'status', '--porcelain', '--untracked-files=all').strip(),
            'Worktree changed during staging; nothing published')
    for path, binding in guards.items():
        require(info((repo / path).read_bytes()) == binding, 'Input changed during staging: ' + path)
    staged = {str(p.relative_to(stage / 'files')): p for p in (stage / 'files').rglob('*') if p.is_file()}
    changed = {p: f for p, f in staged.items() if not (repo / p).exists()
               or info((repo / p).read_bytes()) != info(f.read_bytes())}
    names = sorted(set(changed) | set(deletions), key=lambda x: (x in {'temp/partitions/manifest.json', INDEX}, x))
    backups, done = {}, []
    for name in names:
        target = repo / safe(name)
        require(target.resolve().is_relative_to(repo) and not target.is_symlink(), 'Unsafe output: ' + name)
        if target.exists():
            backup = stage / 'before' / name; backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, backup); backups[name] = backup
    try:
        for name in names:
            target = repo / name; target.parent.mkdir(parents=True, exist_ok=True)
            if name in changed:
                os.replace(changed[name], target)
            else:
                target.unlink()
            done.append(name)
        for name in names:
            if name in staged:
                require((repo / name).exists(), 'Published output missing: ' + name)
    except BaseException:
        for name in reversed(done):
            target = repo / name
            if name in backups:
                os.replace(backups[name], target)
            elif target.exists():
                target.unlink()
        raise
    return len(changed), len(deletions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(); repo = args.repo.resolve()
    before_commit = git(repo, 'rev-parse', 'HEAD').decode().strip()
    require(git(repo, 'rev-parse', BASE + '^{tree}').decode().strip() == BASE_TREE, 'Published CP8 tree differs')
    git(repo, 'merge-base', '--is-ancestor', BASE, before_commit)
    if args.apply:
        require(not git(repo, 'status', '--porcelain', '--untracked-files=all').strip(),
                '--apply requires all scripts, run authorization and prior data committed first')
    evaluated_dt = datetime.now(timezone.utc); evaluated = evaluated_dt.isoformat().replace('+00:00', 'Z')
    guards = {}

    def current(path):
        raw = (repo / path).read_bytes(); guards[path] = info(raw); return raw

    manifest = json.loads(current('temp/partitions/manifest.json'))
    run = json.loads(current(RUN_PATH))
    require(run['run_id'] == RUN and run['scope_id'] == SCOPE
            and run['start_checkpoint_id'] == 'CP-0008', 'RUN7 authorization/baseline differs')
    if (repo / CONTRACT).exists():
        current(CONTRACT)
    frozen = {}
    for i in range(1, 9):
        name = f'temp/snapshots/checkpoints/CP-{i:04d}.json'
        original = git(repo, 'show', BASE + ':' + name)
        require(current(name) == original, 'Frozen checkpoint differs: ' + name)
        frozen[name] = info(original)
    _, baseline = baseline_bindings(repo)
    index = json.loads(current(INDEX)) if (repo / INDEX).exists() else None
    if index:
        require(index.get('maintenance_only') is True and index['baseline_commit'] == BASE
                and index['run_id'] == RUN and index['checkpoint_id'] == CP,
                'Existing integration is not this maintenance transaction')
        for part in index['maintenance_migrations']:
            require(info(current(safe(part['path']))) == {k: part[k] for k in ('bytes', 'sha256')},
                    'Existing migration manifest differs')
    histories, archive_bytes = {}, {}
    for name, (expected_sha, expected_bytes) in ARCHIVES.items():
        raw = git(repo, 'show', BASE + ':temp/' + name + '.jsonl')
        require(sha(raw) == expected_sha and len(raw) == expected_bytes, 'CP8 archive source differs: ' + name)
        path = f'temp/history/CP-0008/{name}.jsonl'
        histories[name] = {'path': path, **info(raw)}; archive_bytes[name] = raw
        if (repo / path).exists():
            require(current(path) == raw, 'Immutable history differs: ' + path)
        else:
            require(index is None, 'A prior maintenance batch lost its immutable archive')

    task_rows = read_logical('tasks.jsonl', base=repo / 'temp')
    latest = latest_tasks(task_rows); del task_rows
    latest_locations, due, selected = {}, [], []
    for tid, task in latest.items():
        if not task.get('unknown_since_utc') or task['task_state'] in TERMINAL:
            continue
        since, deadline = utc(task['unknown_since_utc']), utc(task['deadline_at_utc'])
        require(since <= deadline <= since + timedelta(hours=24), 'Invalid original deadline: ' + tid)
        if evaluated_dt >= deadline:
            due.append(tid)
            if task.get('overdue') is not True or task['priority'] not in {'high', 'critical'}:
                selected.append(tid)
    selected.sort()
    changes, before = {}, {}
    for name in logical_names(repo, manifest):
        records, digest, size, ordinal = [], hashlib.sha256(), 0, 0
        for raw in logical_lines(repo, name, manifest, guards):
            digest.update(raw); size += len(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            if name == 'tasks':
                latest_locations[row['task_id']] = (ordinal, sha(raw))
            leaves = []
            for pointer, state in objects_with_paths(row):
                if state.get('status') not in {'unknown', 'unknown_review_required'} or not (
                        'unknown_since_utc' in state or 'review_task_id' in state):
                    continue
                tid = state.get('review_task_id'); require(tid in latest, 'Unknown field lacks original task')
                task = latest[tid]; since = utc(state.get('unknown_since_utc'))
                require(task['task_state'] not in TERMINAL and task['scope_id'] == SCOPE
                        and state['unknown_since_utc'] == task.get('unknown_since_utc'),
                        'Unknown field/task original clock, scope or state differs: ' + str(tid))
                deadline = utc(task['deadline_at_utc'])
                require(since <= deadline <= since + timedelta(hours=24), 'Invalid field deadline')
                if state['status'] == 'unknown' and evaluated_dt >= since + timedelta(hours=24):
                    leaves.append({'pointer': pointer + '/status', 'before': 'unknown',
                                   'after': 'unknown_review_required', 'unknown_since_utc': state['unknown_since_utc'],
                                   'deadline_at_utc': task['deadline_at_utc'], 'review_task_id': tid})
            if leaves:
                require(name != 'tasks', 'Cannot mutate an old task event; explicit recovery review required')
                leaves.sort(key=lambda x: x['pointer'])
                newraw = replace_status_tokens(raw, [x['pointer'] for x in leaves])
                records.append({'dataset': name, 'id': row_id(name, row, ordinal), 'line_index': ordinal,
                                'before_line_sha256': sha(raw), 'after_line_sha256': sha(newraw), 'changes': leaves})
            ordinal += 1
        before[name] = {'bytes': size, 'sha256': digest.hexdigest(), 'records': ordinal}
        item = manifest['datasets'].get(name + '.jsonl')
        if item:
            require(before[name]['sha256'] == item['logical_sha256'] and ordinal == item['logical_records'],
                    'Logical partition digest/count mismatch: ' + name)
        if records:
            changes[name] = records
    require(set(before) == set(baseline), 'Unexpected logical dataset universe')
    if index:
        previous = json.loads((repo / index['maintenance_migrations'][-1]['path']).read_bytes())
        require(before == {name: value['after'] for name, value in previous['dataset_bindings'].items()},
                'Current logical bytes differ from preceding committed maintenance batch')
    else:
        require(before == baseline, 'First migration must begin from exact CP8 logical data')

    events = []
    for n, tid in enumerate(selected):
        task = latest[tid]; after = next_event(task, evaluated); raw = encoded(after)
        line_index, oldhash = latest_locations[tid]
        events.append({'task_id': tid, 'event_sequence': after['event_sequence'],
                       'before_event_sequence': task['event_sequence'], 'line_index': before['tasks']['records'] + n,
                       'before_line_index': line_index, 'before_line_sha256': oldhash,
                       'after_line_sha256': sha(raw), 'unknown_since_utc': task['unknown_since_utc'],
                       'deadline_at_utc': task['deadline_at_utc']})
    summary = {'run_id': RUN, 'checkpoint_id': CP, 'apply': args.apply, 'evaluated_at_utc': evaluated,
               'before_commit': before_commit, 'due_open_unknown_tasks': len(due),
               'task_events_to_append': len(events), 'field_status_changes': sum(len(r['changes']) for v in changes.values() for r in v),
               'changed_records': sum(map(len, changes.values())),
               'changed_datasets': sorted(set(changes) | ({'tasks'} if events else set())),
               'external_requests': 0, 'cache_reuse_events': 0, 'manual_review_activities': 0,
               'new_assessments': 0, 'history_archives': histories, 'noop': not changes and not events}
    if not args.apply or summary['noop']:
        print(json.dumps(summary, ensure_ascii=False)); return

    stage = Path(tempfile.mkdtemp(prefix='run7-unknown-stage-', dir=repo.parent))
    try:
        new_manifest, after = deepcopy(manifest), deepcopy(before)
        for name in summary['changed_datasets']:
            replacements = {r['line_index']: r for r in changes.get(name, [])}

            def output_lines():
                ordinal, prefix_hash, prefix_size, last = 0, hashlib.sha256(), 0, b''
                for raw in logical_lines(repo, name, manifest):
                    prefix_hash.update(raw); prefix_size += len(raw); last = raw
                    entry = replacements.get(ordinal) if raw.strip() else None
                    if entry:
                        require(sha(raw) == entry['before_line_sha256'], 'Line changed while staging')
                        raw = replace_status_tokens(raw, [x['pointer'] for x in entry['changes']])
                        require(sha(raw) == entry['after_line_sha256'], 'Staged status result differs')
                    yield raw
                    ordinal += bool(raw.strip())
                require(prefix_hash.hexdigest() == before[name]['sha256'] and prefix_size == before[name]['bytes'],
                        'Input changed while staging: ' + name)
                if name == 'tasks':
                    require(not last or last.endswith(b'\n'), 'Original task stream lacks final newline')
                    for entry in events:
                        raw = encoded(next_event(latest[entry['task_id']], evaluated))
                        require(sha(raw) == entry['after_line_sha256'], 'Task event differs while staging')
                        yield raw

            after[name] = stage_dataset(stage, name, output_lines(), manifest, new_manifest)
        manifest_path = stage / 'files/temp/partitions/manifest.json'
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes((json.dumps(new_manifest, ensure_ascii=False, indent=2) + '\n').encode())
        for name, binding in histories.items():
            if not (repo / binding['path']).exists():
                path = stage / 'files' / binding['path']; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive_bytes[name])
        batch = len(index['maintenance_migrations']) + 1 if index else 1
        prefix = f'temp/reports/RUN-0007-unknown-escalation-{batch:04d}'
        require(not (repo / (prefix + '.json')).exists() and not (repo / prefix).exists(), 'Batch output already exists')
        change_parts = write_parts(stage, prefix, 'changes', (r for name in sorted(changes) for r in changes[name]))
        event_parts = write_parts(stage, prefix, 'task-events', events)
        report = {'schema_version': '1.1.1', 'run_id': RUN, 'checkpoint_id': CP, 'scope_id': SCOPE,
                  'baseline_checkpoint_id': 'CP-0008', 'baseline_commit': BASE, 'before_commit': before_commit,
                  'evaluated_at_utc': evaluated, 'maintenance_only': True, 'history_archives': histories,
                  'dataset_bindings': {name: {'before': before[name], 'after': after[name]} for name in sorted(before)},
                  'counts_before': {name: x['records'] for name, x in before.items()},
                  'counts_after': {name: x['records'] for name, x in after.items()},
                  'change_parts': change_parts, 'task_event_parts': event_parts,
                  'field_status_changes': summary['field_status_changes'], 'changed_records': summary['changed_records'],
                  'appended_task_events': len(events), 'due_open_unknown_tasks': len(due),
                  'tasks_original_prefix': {**before['tasks'], 'preserved': True},
                  'frozen_checkpoints': frozen, 'input_files_before': guards,
                  'line_hash_basis': 'Exact UTF-8 JSONL record bytes including its original newline; line_index is zero-based nonempty logical record ordinal.',
                  'task_changed_field_whitelist': sorted(TASK_ALLOWED), 'new_query_rows': 0,
                  'external_requests': 0, 'cache_reuse_events': 0, 'manual_review_activities': 0,
                  'new_assessments': 0, 'scientific_gate_exemptions': 0, 'research_closure': False}
        report_path = prefix + '.json'; report_raw = encoded(report)
        (stage / 'files' / report_path).write_bytes(report_raw)
        migrations = deepcopy(index['maintenance_migrations']) if index else []
        migrations.append({'path': report_path, **info(report_raw)})
        integrated = {'schema_version': '1.1.1', 'run_id': RUN, 'checkpoint_id': CP, 'scope_id': SCOPE,
                      'baseline_checkpoint_id': 'CP-0008', 'baseline_commit': BASE, 'maintenance_only': True,
                      'created_at_utc': index['created_at_utc'] if index else evaluated, 'updated_at_utc': evaluated,
                      'status': 'integrated_pending_full_qa_and_remote_sync', 'maintenance_migrations': migrations,
                      'history_archives': histories, 'counts_before': {name: x['records'] for name, x in baseline.items()},
                      'counts_after': {name: x['records'] for name, x in after.items()}, 'changed_records': [],
                      'new_query_rows': 0, 'external_requests': 0, 'cache_reuse_events': 0,
                      'manual_review_activities': 0, 'new_assessments': 0, 'research_closure': False}
        (stage / 'files' / INDEX).write_bytes(encoded(integrated))
        oldparts = {'temp/' + p['path'] for d in manifest['datasets'].values() for p in d['parts'] if p['path'].startswith('partitions/')}
        liveparts = {'temp/' + p['path'] for d in new_manifest['datasets'].values() for p in d['parts']}
        written, removed = publish(repo, stage, oldparts - liveparts, before_commit, guards)
        summary.update(migration_manifest=report_path, migration_manifest_sha256=sha(report_raw),
                       integration_path=INDEX, files_written=written, obsolete_partition_files_removed=removed)
        shutil.rmtree(stage)
        print(json.dumps(summary, ensure_ascii=False))
    except BaseException:
        print('Staging/rollback material retained at ' + str(stage), file=__import__('sys').stderr)
        raise


if __name__ == '__main__':
    main()
