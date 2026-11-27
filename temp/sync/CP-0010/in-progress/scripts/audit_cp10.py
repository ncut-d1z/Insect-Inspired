#!/usr/bin/env python3
"""Read-only CP10 audit against the complete, published CP9 scientific baseline.

All general schema, evidence, scale, topology, query, export and partition rules
are inherited from audit_run. The historical S19 decision is inherited only as
the exact already-verified CP9 record and its published certificate; unavailable
private PDFs are not claimed to have been read again. No new exception exists.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

import audit_run as original

CHECKPOINT = 'CP-0010'
PARENT = 'CP-0009'
RUN = 'RUN-0008'
BASE_COMMIT = '96ce04b268f648978581e87d3be551981f12917d'
BASE_TREE = '4e61e76e128b51c55c75bc0db1853376f549407e'
BASE_MANIFEST_SHA256 = '892df8bbd8e5facf6586478d8f4b67761d337f1dc0b550b4c3fbbaf925299fe8'
BASE_ASSESSMENTS_SHA256 = '4d3e9fa6aafa57d58536c0ab989c73220b177a3c22700282f09542afb04b3c06'
S19_ID = 'AS-S19-L05-baseline-receptive-field'
S19_PROOF = 'temp/validation/cp4-explicit-manual-reassessment-evidence.json'
S19_PROOF_SHA256 = '2326bf4aa991fe1b990a93eeacbe1b6d3d3e833db59aa15f4b8c21f873806f88'
S19_RECORD_SHA256 = '75774b00032035fe24d28133f79fbbb4fb4cb7e44fa9a463c34523b53ab81cf6'
CP_PATH = 'temp/snapshots/checkpoints/CP-0010.json'
INTEGRATION_PATH = 'temp/reports/RUN-0008-integration.json'
RUN_PATH = 'temp/runs/RUN-0008.json'
RUN_FINALIZATION_FIELDS = frozenset({
    'status', 'end_checkpoint_id', 'checkpoint_status', 'checkpoint_validation_state',
    'checkpoint_candidate_created_at_utc', 'checkpoint_completed_at_utc',
    'checkpoint_wall_clock_hours', 'budget_exhausted', 'pause_reason', 'sync_state',
    'post_commit_verification_url', 'last_completed_batch', 'qa_completed_at_utc',
})
FROZEN_PATHS = tuple(f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 10)) + (
    'temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json',
    'temp/seed-manifest.jsonl', 'temp/schema.json', S19_PROOF,
    'temp/validation/cp6-data-audit.json', 'temp/validation/cp7-data-audit.json',
    'temp/validation/cp8-data-audit.json', 'temp/validation/cp9-data-audit.json',
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
        raise ValueError('RUN8 source observation requires an explicit nonnegative integer request count')
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
        raise ValueError('RUN8 is missing immutable authorization/accounting fields')
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
    """Include logical inputs, reviewed RUN8 evidence, tooling and seven exports.

    CP10 itself is bound separately so that it can contain this map. QA reports
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
    for pattern in ('temp/reports/RUN-0008*.json', 'temp/query-results/Q-RUN08*.json',
                    'scripts/*.py', 'scripts/*.css', 'scripts/*.mjs', 'scripts/README.md'):
        names.update(str(p.relative_to(repo)) for p in repo.glob(pattern) if p.is_file())
    archive = repo / 'temp/history/CP-0009/assessments.jsonl'
    if archive.exists():
        names.add(str(archive.relative_to(repo)))
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


def published_cp9_baseline(repo):
    tree = git_bytes(repo, 'rev-parse', BASE_COMMIT + '^{tree}').decode().strip()
    if tree != BASE_TREE:
        raise ValueError('CP9 commit/tree differs from the independently verified baseline')
    raw, manifest = logical_assessment_bytes(lambda name: baseline_bytes(repo, name))
    if sha_bytes(raw) != BASE_ASSESSMENTS_SHA256 or sha_bytes(manifest) != BASE_MANIFEST_SHA256:
        raise ValueError('Frozen CP9 Assessment or partition bytes differ')
    rows = assessment_lines(raw)
    active = [row for row, _ in rows.values() if row['assessment_status'] == 'active']
    rejected = sorted(row['assessment_id'] for row in active
                      if row['evidence_admission_status'] == 'insufficient_evidence')
    counter = sorted(row['assessment_id'] for row in active if row['counter_evidence'])
    if not (len(rows) == len(active) == 72 and len(rejected) == 9 and len(counter) == 23):
        raise ValueError('Frozen CP9 scientific population differs')
    proof_raw = baseline_bytes(repo, S19_PROOF)
    proof = json.loads(proof_raw)
    if not (sha_bytes(proof_raw) == S19_PROOF_SHA256
            and proof['assessment_id'] == S19_ID
            and proof['canonical_after_sha256'] == S19_RECORD_SHA256
            and canonical_digest(rows[S19_ID][0]) == S19_RECORD_SHA256
            and proof['decision'] == 'explicit_manual_reassessment'):
        raise ValueError('Published historical S19 decision differs')
    audited = json.loads(baseline_bytes(repo, 'temp/validation/cp9-data-audit.json'))
    if not (audited['status'] == 'passed' and audited['error_count'] == 0
            and audited['statistics']['active_assessments'] == 72
            and audited['counters']['cp8_assessments_scientific_preserved'] == 72
            and audited['counters']['cp8_assessment_original_rows_archived'] == 72
            and audited['statistics']['historical_s19_decision']['status'] == 'inherited_exact_published_record'
            and audited['statistics']['historical_s19_decision']['canonical_record_sha256'] == S19_RECORD_SHA256
            and audited['statistics']['historical_s19_decision']['new_exception_granted'] is False):
        raise ValueError('Published CP9 scientific audit did not establish this baseline')
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
        'rule': 'Archive all 72 CP9 Assessment original lines; retain current lines exactly except the two explicitly reviewed Tanaka species corrections bound to source receipts, complete before/after objects, manual review and original task preconditions. All general scientific gates remain unchanged.',
    }
    return rows, certificate


ARCHIVED_ASSESSMENTS = 'temp/history/CP-0009/assessments.jsonl'
REVIEWABLE_ASSESSMENTS = frozenset({
    'A-P6-B204-L04-world_motion_rejection', 'A-P6-B204-L03-counterevidence_onset',
})


def require_review(ok, message):
    if not ok:
        raise ValueError('CP10 explicit review: ' + message)


def baseline_logical_rows(repo, name):
    manifest = json.loads(baseline_bytes(repo, 'temp/partitions/manifest.json'))
    parts = manifest['datasets'].get(name + '.jsonl', {'parts': [{'path': name + '.jsonl'}]})['parts']
    for part in parts:
        for line in baseline_bytes(repo, 'temp/' + safe_relative(part['path'])).splitlines():
            if line.strip():
                yield json.loads(line)


def reviewed_assessment_revisions(repo, data, candidate_paths=None, require_archive=True):
    """Validate exact source-backed species corrections; an empty set is normal.

    No other old scientific field can change through this adapter. The current
    records still pass every unchanged generic, quantitative and scale gate.
    """
    repo = Path(repo).resolve()
    raw = baseline_bytes(repo, 'temp/assessments.jsonl')
    require_review(sha_bytes(raw) == BASE_ASSESSMENTS_SHA256, 'Baseline Assessment bytes differ')
    archive = repo / ARCHIVED_ASSESSMENTS
    if require_archive or archive.exists():
        require_review(archive.is_file() and archive.read_bytes() == raw, 'Exact CP9 Assessment archive is required')
    old_rows = {key: row for key, (row, _) in assessment_lines(raw).items()}
    rows = lambda name: data.get(name, data.get(name + '.jsonl', []))
    current = {row['assessment_id']: row for row in rows('assessments')}
    manuals = {row['review_id']: row for row in rows('manual-reviews')}
    queries = {row['query_id']: row for row in rows('queries')}
    latest = {}
    for row in rows('tasks'):
        latest[row['task_id']] = row
    if candidate_paths is None:
        integration = json.loads((repo / INTEGRATION_PATH).read_bytes())
        candidate_paths = [item['path'] for item in integration['reviewed_input_bindings']
                           if item['path'].startswith('temp/reports/RUN-0008')]
    found, previous = {}, None
    for name in dict.fromkeys(candidate_paths):
        name = safe_relative(name)
        require_review(name.startswith('temp/reports/RUN-0008') and name.endswith('.json'), 'Unexpected review path')
        saved = git_bytes(repo, 'show', 'HEAD:' + name)
        require_review((repo / name).read_bytes() == saved, 'Review is not the exact committed bytes: ' + name)
        candidate = json.loads(saved)
        for review in candidate.get('assessment_revision_reviews', []):
            aid = review['assessment_id']
            require_review(aid in REVIEWABLE_ASSESSMENTS and aid not in found,
                           'Unapproved or repeated historical Assessment review')
            require_review(candidate['run_id'] == RUN and candidate['checkpoint_id'] == CHECKPOINT
                           and candidate['scope_id'] == 'SCOPE-0001', 'Review scope differs')
            changes = [x for x in candidate.get('changed_records', [])
                       if x['dataset'].removesuffix('.jsonl') == 'assessments' and x['id'] == aid]
            require_review(len(changes) == 1, 'Review needs one complete before/after Assessment change')
            change = changes[0]; before, after = change['before'], change['after']
            require_review(before == old_rows[aid] and after == current.get(aid) and before != after,
                           'Assessment before/after does not match the fixed baseline/current row')
            require_review(sorted(review['allowed_fields']) == ['conditions.species', 'species']
                           and sorted(change['changed_field_names']) == ['conditions', 'species'],
                           'Only the declared mirrored species Condition may be revised')
            condition = after['conditions']['species']
            require_review(after['species'] == condition and condition['status'] == 'reported'
                           and condition['value'] and condition['evidence_locator']
                           and condition['unknown_since_utc'] is None and condition['review_task_id'] is None,
                           'A corrected species requires typed positive evidence and matching projections')
            expected = deepcopy(before)
            expected['species'] = deepcopy(condition)
            expected['conditions']['species'] = deepcopy(condition)
            require_review(canonical_digest(expected) == canonical_digest(after),
                           'Review changed another scientific value, independent evidence or classification')
            manual = next((x for x in candidate.get('additions', {}).get('manual-reviews', [])
                           if x['review_id'] == review['review_id']), None)
            require_review(manual is not None and manuals.get(manual['review_id']) == manual
                           and manual['run_id'] == RUN and manual['entity_id'] in {aid, before['work_id']}
                           and manual['artifact'] == name and bool(manual['reviewer']) and bool(manual['notes'])
                           and original.utc(manual['recorded_at_utc']) is not None and bool(review['reason']),
                           'The specific real manual-review object is missing or differs')
            qids = review['query_ids']
            require_review(isinstance(qids, list) and qids and len(qids) == len(set(qids)), 'Source queries are required')
            receipt_bindings = []
            for qid in qids:
                q = queries.get(qid)
                require_review(q is not None and q['checkpoint_id'] == CHECKPOINT and q['scope_id'] == 'SCOPE-0001',
                               'Review source query is not part of this checkpoint')
                relative = safe_relative(q['cache_path'])
                require_review(relative.startswith('temp/query-results/Q-RUN08'), 'Unexpected review receipt path')
                receipt = git_bytes(repo, 'show', 'HEAD:' + relative)
                require_review((repo / relative).read_bytes() == receipt and json.loads(receipt)['query_id'] == qid,
                               'Review source receipt was not preserved exactly')
                receipt_bindings.append({'path': relative, 'bytes': len(receipt), 'sha256': sha_bytes(receipt)})
            tids = {before['species']['review_task_id'], before['conditions']['species']['review_task_id']}
            require_review(None not in tids and isinstance(review['task_ids'], list)
                           and len(review['task_ids']) == len(tids) and set(review['task_ids']) == tids,
                           'The original species review tasks must be identified exactly')
            if previous is None:
                previous = {}
                for task in baseline_logical_rows(repo, 'tasks'):
                    previous[task['task_id']] = task
            for tid in tids:
                old = previous[tid]
                guards = [x for x in candidate.get('task_event_preconditions', []) if x['task_id'] == tid]
                events = [x for x in candidate.get('additions', {}).get('tasks', []) if x['task_id'] == tid]
                require_review(len(guards) == len(events) == 1 and guards[0]['before'] == old,
                               'Original review task precondition is missing or differs')
                event = events[0]
                require_review(latest.get(tid) == event and event['task_state'] == 'verified_complete'
                               and old['task_state'] not in original.TERMINAL
                               and event['event_sequence'] == old['event_sequence'] + 1
                               and event['checkpoint_id'] == CHECKPOINT
                               and event['unknown_since_utc'] == old['unknown_since_utc']
                               and event['deadline_at_utc'] == old['deadline_at_utc']
                               and set(qids) <= set(event['query_ids']),
                               'Evidence-backed closure lacks the original task identity, clock, source or sequence')
            found[aid] = {'assessment_id': aid, 'before': before, 'after': after,
                          'candidate_path': name, 'candidate_sha256': sha_bytes(saved),
                          'manual_review_id': manual['review_id'], 'manual_review_sha256': canonical_digest(manual),
                          'receipt_bindings': receipt_bindings, 'task_ids': sorted(tids),
                          'allowed_fields': ['conditions.species', 'species']}
    return found


def verify_legacy_artifacts(repo, watch=None):
    """Protect every old nonmutable CP9 artifact, including evidence and old tools."""
    cp_path = 'temp/snapshots/checkpoints/CP-0009.json'
    raw = baseline_bytes(repo, cp_path)
    require_review(sha_bytes(raw) == 'b1551bc78888c4df70569e81f9b8e95583d01fb22e996112db68b26087e9a172',
                   'CP9 checkpoint self hash differs')
    expected = dict(json.loads(raw)['artifact_hashes']); expected[cp_path] = sha_bytes(raw)
    manifest_raw = baseline_bytes(repo, 'temp/partitions/manifest.json')
    require_review(sha_bytes(manifest_raw) == BASE_MANIFEST_SHA256, 'CP9 partition manifest differs')
    manifest = json.loads(manifest_raw)
    names = git_bytes(repo, 'ls-tree', '--name-only', BASE_COMMIT + ':temp').decode().splitlines()
    excluded = {'temp/' + name for name in names if name.endswith('.jsonl')}
    excluded.update('temp/' + safe_relative(part['path'])
                    for dataset in manifest['datasets'].values() for part in dataset['parts'])
    excluded.update(EXPORTS)
    excluded.update({'temp/partitions/manifest.json', 'README.md', 'temp/progress.md', 'temp/change-log.md'})
    count = size = 0
    for name, expected_hash in expected.items():
        if name in excluded:
            continue
        path = Path(repo) / safe_relative(name)
        require_review(path.is_file() and not path.is_symlink(), 'Old artifact missing: ' + name)
        if watch:
            watch(path)
        require_review(original.sha(path) == expected_hash, 'Old artifact bytes changed: ' + name)
        count += 1; size += path.stat().st_size
    # Task events are append-only. Object equality alone would allow silent
    # reserialization of an old event, so retain CP9's exact logical byte prefix.
    task_base = manifest['datasets']['tasks.jsonl']
    original_bytes = sum(part['bytes'] for part in task_base['parts'])
    current_manifest_path = Path(repo) / 'temp/partitions/manifest.json'
    if watch:
        watch(current_manifest_path)
    current_manifest = json.loads(current_manifest_path.read_bytes())
    task_parts = current_manifest['datasets'].get('tasks.jsonl', {'parts': [{'path': 'tasks.jsonl'}]})['parts']
    remaining, task_digest = original_bytes, hashlib.sha256()
    for part in task_parts:
        if not remaining:
            break
        path = Path(repo) / 'temp' / safe_relative(part['path'])
        require_review(path.is_file() and not path.is_symlink(), 'Task prefix part missing: ' + str(path))
        if watch:
            watch(path)
        with path.open('rb') as source:
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    break
                task_digest.update(block)
                remaining -= len(block)
    require_review(remaining == 0 and task_digest.hexdigest() == task_base['logical_sha256'],
                   'CP9 task events lost their exact original byte prefix')
    return {'status': 'passed', 'source_commit': BASE_COMMIT, 'checked_files': count,
            'checked_bytes': size, 'old_receipts_evidence_scripts_and_qa_unchanged': True,
            'task_original_prefix': {'status': 'passed', 'bytes': original_bytes,
                                     'sha256': task_base['logical_sha256'],
                                     'records': task_base['logical_records']}}


class AuditCP10(original.Audit):
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
                     'cp10_run_accounting_binding', 'Run authorization, baseline, budget, clock or accounting changed')
        self.require(run_accounting_projection(validation['run_record_at_freeze']) == projection,
                     'cp10_run_frozen_record_differs', 'Run changes exceed the finalization whitelist')
        self.stats['run_accounting_binding'] = {
            'expected_projection_sha256': canonical_digest(projection),
            'before_run_sha256': sha_bytes(run_raw),
            'mutable_finalization_fields': sorted(RUN_FINALIZATION_FIELDS),
        }
        frozen = original.utc(validation['input_frozen_at_utc'])
        began = datetime.now(timezone.utc)
        self.require(candidate['checkpoint_id'] == CHECKPOINT and candidate['parent_checkpoint_id'] == PARENT,
                     'cp10_input_binding_checkpoint', 'Expected CP10 with CP9 parent')
        self.require(frozen is not None and began >= frozen and self.now >= frozen,
                     'cp10_audit_predates_freeze', validation['input_frozen_at_utc'])
        self.require(required_input_names(self.repo).issubset(expected),
                     'cp10_input_universe_unbound', 'Every required canonical input must be frozen')
        before = input_snapshot(self.repo, expected, self.watch)
        self.require(before == expected and input_digest(expected) == validation['canonical_input_digest_sha256'],
                     'cp10_before_inputs_differ', 'Current bytes or frozen input-map digest differ')
        self.stats['cp10_input_binding'] = {
            'checkpoint_id': CHECKPOINT, 'input_frozen_at_utc': validation['input_frozen_at_utc'],
            'candidate_sha256': candidate_hash, 'candidate_bytes': candidate_size,
            'audit_started_at_utc': began.isoformat().replace('+00:00', 'Z'),
            'expected_digest_sha256': input_digest(expected), 'before_input_hashes': before,
            'before_digest_sha256': input_digest(before),
        }
        self._cp10_expected_inputs = expected
        self._cp9_records, self._cp9_certificate = published_cp9_baseline(self.repo)
        self._manual_assessment_baselines = [
            (BASE_COMMIT + ':temp/assessments.jsonl', [row for row, _ in self._cp9_records.values()])
        ]
        super().load()
        self._assessment_revisions = reviewed_assessment_revisions(self.repo, self.datasets)
        self.stats['cp10_assessment_revision_bindings'] = self._assessment_revisions
        self.stats['cp9_unchanged_artifacts'] = verify_legacy_artifacts(self.repo, self.watch)

    def task_queries(self):
        super().task_queries()
        queries = {qid: row for qid, row in self.indices.get('query', {}).items()
                   if row.get('checkpoint_id') == CHECKPOINT}
        observations = [row for row in self.datasets.get('source-observations.jsonl', [])
                        if row.get('query_id') in queries]
        self.require(Counter(row['query_id'] for row in observations) == Counter({qid: 1 for qid in queries}),
                     'cp10_request_observation_cardinality', 'Each RUN8 query needs one exact source observation')
        total = 0
        for observation in observations:
            qid = observation['query_id']
            try:
                count = external_request_count(observation)
                q = queries[qid]
                self.require(observation.get('cache_hit') == q.get('cache_hit')
                             and (not q.get('cache_hit') or count == 0),
                             'cp10_request_cache_count', 'Query/cache accounting differs', qid)
                path = self.repo / safe_relative(observation['receipt_path'])
                self.watch(path)
                raw = path.read_bytes()
                receipt = json.loads(raw)
                self.require(sha_bytes(raw) == observation['receipt_sha256']
                             and receipt['query_id'] == qid
                             and type(receipt['external_requests_performed']) is int
                             and receipt['external_requests_performed'] == count,
                             'cp10_request_receipt_count', 'Source operation count differs from exact receipt', qid)
                if 'external_request_count' in q.get('normalized_parameters', {}):
                    self.require(q['normalized_parameters']['external_request_count'] == count,
                                 'cp10_request_query_count', 'Normalized query count differs', qid)
                self.require(observation.get('external_request_count_basis') == REQUEST_COUNT_BASIS,
                             'cp10_request_count_basis', 'Explicit operation-count scope is missing', qid)
                total += count
            except Exception as error:
                self.note('cp10_request_count_invalid', str(error), qid)
        run = json.loads((self.repo / RUN_PATH).read_bytes())
        self.require(run['external_requests_used'] == total <= run['budget']['external_requests'],
                     'cp10_request_budget_reconciliation', 'RUN8 total/budget differs from source operation counts')
        self.stats['run8_external_request_accounting'] = {
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
        for identifier, (old, old_line) in self._cp9_records.items():
            self.counts['cp9_assessments_compared'] += 1
            revision = self._assessment_revisions.get(identifier)
            expected = revision['after'] if revision else old
            same = self.require(current.get(identifier) == expected,
                                'cp9_assessment_record_changed', 'Only an exact bound reassessment may change an old row', identifier)
            if revision:
                raw_same = self.require(identifier in current_lines,
                                        'cp9_reviewed_assessment_missing', 'Reviewed row is absent', identifier)
                if same and raw_same:
                    self.counts['cp9_assessments_explicitly_reassessed'] += 1
            else:
                raw_same = self.require(identifier in current_lines and current_lines[identifier][1] == old_line,
                                        'cp9_assessment_raw_line_changed', 'Unreviewed CP9 lines remain exact', identifier)
                if same and raw_same:
                    self.counts['cp9_assessments_byte_preserved'] += 1
            if same and raw_same:
                self.counts['cp9_assessments_accounted'] += 1
                self.counts['cp9_assessment_original_rows_archived'] += 1
                if old['evidence_admission_status'] == 'insufficient_evidence':
                    self.counts['cp9_manual_rejections_preserved'] += 1
                if old['counter_evidence']:
                    self.counts['cp9_manual_counterevidence_preserved'] += 1
        for frozen in self._cp9_certificate['frozen_files']:
            path = self.repo / frozen['path']
            self.watch(path)
            if self.require(path.is_file(), 'cp9_frozen_file_missing', frozen['path']):
                if self.require(path.stat().st_size == frozen['bytes'] and original.sha(path) == frozen['sha256'],
                                'cp9_frozen_file_changed', 'Preserve historical checkpoint/scope/schema/evidence bytes', frozen['path']):
                    self.counts['cp9_frozen_files_byte_preserved'] += 1
        self.stats['cp9_frozen_scientific_baseline'] = self._cp9_certificate
        self.stats['historical_s19_decision'] = {
            'assessment_id': S19_ID, 'status': 'inherited_exact_published_record',
            'canonical_record_sha256': S19_RECORD_SHA256, 'proof_sha256': S19_PROOF_SHA256,
            'original_pdf_or_images_reread': False, 'new_exception_granted': False,
        }

    def finish(self):
        binding = self.stats.get('cp10_input_binding')
        if binding is None:
            self.note('cp10_input_binding_missing', 'No CP10 candidate/input freeze was established')
        else:
            try:
                after = input_snapshot(self.repo, self._cp10_expected_inputs, self.watch)
                binding.update(after_input_hashes=after, after_digest_sha256=input_digest(after),
                               candidate_sha256_after=original.sha(self.repo / CP_PATH),
                               audit_completed_at_utc=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
                self.require(required_input_names(self.repo).issubset(self._cp10_expected_inputs),
                             'cp10_input_universe_changed', 'New input appeared outside the frozen map')
                same = self.require(after == binding['before_input_hashes'] == self._cp10_expected_inputs,
                                    'cp10_after_inputs_differ', 'Canonical inputs changed during the audit')
                cp_same = self.require(binding['candidate_sha256_after'] == binding['candidate_sha256'],
                                       'cp10_candidate_changed_during_audit', 'Candidate changed during the audit')
                binding['passed'] = same and cp_same and (
                    binding['before_digest_sha256'] == binding['after_digest_sha256'] == binding['expected_digest_sha256'])
                run_raw = (self.repo / RUN_PATH).read_bytes()
                run_binding = self.stats['run_accounting_binding']
                run_binding['after_run_sha256'] = sha_bytes(run_raw)
                run_binding['after_projection_sha256'] = canonical_digest(run_accounting_projection(json.loads(run_raw)))
                run_binding['passed'] = self.require(
                    run_binding['before_run_sha256'] == run_binding['after_run_sha256']
                    and run_binding['expected_projection_sha256'] == run_binding['after_projection_sha256'],
                    'cp10_run_changed_during_audit', 'Run bytes/accounting changed during the read-only audit')
            except Exception as error:
                binding['passed'] = False
                self.note('cp10_input_binding_finish_error', str(error))
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
    return AuditCP10(repo, out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
