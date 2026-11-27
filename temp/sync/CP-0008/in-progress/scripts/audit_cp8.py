#!/usr/bin/env python3
"""Read-only CP8 audit against the complete, published CP7 scientific baseline.

All general schema, evidence, scale, topology, query, export and partition rules
are inherited from audit_run. The historical S19 decision is inherited only as
the exact already-verified CP7 record and its published certificate; unavailable
private PDFs are not claimed to have been read again. No new exception exists.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

import audit_run as original

CHECKPOINT = 'CP-0008'
PARENT = 'CP-0007'
RUN = 'RUN-0006'
BASE_COMMIT = '3a6d834ffa9606efa873ac8d60dd35f2c7cd2d0f'
BASE_TREE = 'c5d5f03ce399961429288e1ffb7ce3565e278fbf'
BASE_MANIFEST_SHA256 = 'e3e537a4817e8d7f735685f54e3c674329e4241f9d23c73e789195251caac0a6'
BASE_ASSESSMENTS_SHA256 = 'b7fb800842184df7daf1ca2af1ce8fd4ebab36023bc0793ab1478a0d04b50d3b'
S19_ID = 'AS-S19-L05-baseline-receptive-field'
S19_PROOF = 'temp/validation/cp4-explicit-manual-reassessment-evidence.json'
S19_PROOF_SHA256 = '2326bf4aa991fe1b990a93eeacbe1b6d3d3e833db59aa15f4b8c21f873806f88'
S19_RECORD_SHA256 = '75774b00032035fe24d28133f79fbbb4fb4cb7e44fa9a463c34523b53ab81cf6'
CP_PATH = 'temp/snapshots/checkpoints/CP-0008.json'
INTEGRATION_PATH = 'temp/reports/RUN-0006-integration.json'
RUN_PATH = 'temp/runs/RUN-0006.json'
RUN_FINALIZATION_FIELDS = frozenset({
    'status', 'end_checkpoint_id', 'checkpoint_status', 'checkpoint_validation_state',
    'checkpoint_candidate_created_at_utc', 'checkpoint_completed_at_utc',
    'checkpoint_wall_clock_hours', 'budget_exhausted', 'pause_reason', 'sync_state',
    'post_commit_verification_url', 'last_completed_batch', 'qa_completed_at_utc',
})
FROZEN_PATHS = tuple(f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 8)) + (
    'temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json',
    'temp/seed-manifest.jsonl', 'temp/schema.json', S19_PROOF,
    'temp/validation/cp6-data-audit.json', 'temp/validation/cp7-data-audit.json',
)
EXPORTS = (
    'ref.bib', 'ref.html', 'temp/exports/citation_graph.json',
    'temp/exports/evidence_matrix.csv', 'temp/exports/research_entities.json',
    'temp/exports/research_implications.csv', 'temp/exports/research_paths.json',
)


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
        raise ValueError('RUN6 is missing immutable authorization/accounting fields')
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
    """Include logical inputs, reviewed RUN6 evidence, tooling and seven exports.

    CP8 itself is bound separately so that it can contain this map. QA reports
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
    for pattern in ('temp/reports/RUN-0006*.json', 'temp/query-results/Q-RUN06*.json',
                    'scripts/*.py', 'scripts/*.css', 'scripts/*.mjs', 'scripts/README.md'):
        names.update(str(p.relative_to(repo)) for p in repo.glob(pattern) if p.is_file())
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


def published_cp7_baseline(repo):
    tree = git_bytes(repo, 'rev-parse', BASE_COMMIT + '^{tree}').decode().strip()
    if tree != BASE_TREE:
        raise ValueError('CP7 commit/tree differs from the independently verified baseline')
    raw, manifest = logical_assessment_bytes(lambda name: baseline_bytes(repo, name))
    if sha_bytes(raw) != BASE_ASSESSMENTS_SHA256 or sha_bytes(manifest) != BASE_MANIFEST_SHA256:
        raise ValueError('Frozen CP7 Assessment or partition bytes differ')
    rows = assessment_lines(raw)
    active = [row for row, _ in rows.values() if row['assessment_status'] == 'active']
    rejected = sorted(row['assessment_id'] for row in active
                      if row['evidence_admission_status'] == 'insufficient_evidence')
    counter = sorted(row['assessment_id'] for row in active if row['counter_evidence'])
    if not (len(rows) == len(active) == 71 and len(rejected) == 9 and len(counter) == 23):
        raise ValueError('Frozen CP7 scientific population differs')
    proof_raw = baseline_bytes(repo, S19_PROOF)
    proof = json.loads(proof_raw)
    if not (sha_bytes(proof_raw) == S19_PROOF_SHA256
            and proof['assessment_id'] == S19_ID
            and proof['canonical_after_sha256'] == S19_RECORD_SHA256
            and canonical_digest(rows[S19_ID][0]) == S19_RECORD_SHA256
            and proof['decision'] == 'explicit_manual_reassessment'):
        raise ValueError('Published historical S19 decision differs')
    audited = json.loads(baseline_bytes(repo, 'temp/validation/cp7-data-audit.json'))
    if not (audited['status'] == 'passed' and audited['error_count'] == 0
            and audited['statistics']['active_assessments'] == 71
            and audited['counters']['cp6_assessments_byte_preserved'] == 70
            and audited['statistics']['historical_s19_decision']['status'] == 'inherited_exact_published_record'
            and audited['statistics']['historical_s19_decision']['canonical_record_sha256'] == S19_RECORD_SHA256
            and audited['statistics']['historical_s19_decision']['new_exception_granted'] is False):
        raise ValueError('Published CP7 scientific audit did not establish this baseline')
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
        'rule': 'Retain all 71 published CP7 Assessment records and original JSONL line bytes, including every rejection and counter-evidence record; apply unchanged general gates to all current records.',
    }
    return rows, certificate


class AuditCP8(original.Audit):
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
                     'cp8_run_accounting_binding', 'Run authorization, baseline, budget, clock or accounting changed')
        self.require(run_accounting_projection(validation['run_record_at_freeze']) == projection,
                     'cp8_run_frozen_record_differs', 'Run changes exceed the finalization whitelist')
        self.stats['run_accounting_binding'] = {
            'expected_projection_sha256': canonical_digest(projection),
            'before_run_sha256': sha_bytes(run_raw),
            'mutable_finalization_fields': sorted(RUN_FINALIZATION_FIELDS),
        }
        frozen = original.utc(validation['input_frozen_at_utc'])
        began = datetime.now(timezone.utc)
        self.require(candidate['checkpoint_id'] == CHECKPOINT and candidate['parent_checkpoint_id'] == PARENT,
                     'cp8_input_binding_checkpoint', 'Expected CP8 with CP7 parent')
        self.require(frozen is not None and began >= frozen and self.now >= frozen,
                     'cp8_audit_predates_freeze', validation['input_frozen_at_utc'])
        self.require(required_input_names(self.repo).issubset(expected),
                     'cp8_input_universe_unbound', 'Every required canonical input must be frozen')
        before = input_snapshot(self.repo, expected, self.watch)
        self.require(before == expected and input_digest(expected) == validation['canonical_input_digest_sha256'],
                     'cp8_before_inputs_differ', 'Current bytes or frozen input-map digest differ')
        self.stats['cp8_input_binding'] = {
            'checkpoint_id': CHECKPOINT, 'input_frozen_at_utc': validation['input_frozen_at_utc'],
            'candidate_sha256': candidate_hash, 'candidate_bytes': candidate_size,
            'audit_started_at_utc': began.isoformat().replace('+00:00', 'Z'),
            'expected_digest_sha256': input_digest(expected), 'before_input_hashes': before,
            'before_digest_sha256': input_digest(before),
        }
        self._cp8_expected_inputs = expected
        self._cp7_records, self._cp7_certificate = published_cp7_baseline(self.repo)
        self._manual_assessment_baselines = [
            (BASE_COMMIT + ':temp/assessments.jsonl', [row for row, _ in self._cp7_records.values()])
        ]
        super().load()

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
        for identifier, (old, old_line) in self._cp7_records.items():
            self.counts['cp7_assessments_compared'] += 1
            same = self.require(current.get(identifier) == old,
                                'cp7_assessment_record_changed', 'Preserve complete published CP7 claim', identifier)
            raw_same = self.require(identifier in current_lines and current_lines[identifier][1] == old_line,
                                    'cp7_assessment_raw_line_changed', 'Preserve original CP7 JSONL line bytes', identifier)
            if same and raw_same:
                self.counts['cp7_assessments_byte_preserved'] += 1
                if old['evidence_admission_status'] == 'insufficient_evidence':
                    self.counts['cp7_manual_rejections_preserved'] += 1
                if old['counter_evidence']:
                    self.counts['cp7_manual_counterevidence_preserved'] += 1
        for frozen in self._cp7_certificate['frozen_files']:
            path = self.repo / frozen['path']
            self.watch(path)
            if self.require(path.is_file(), 'cp7_frozen_file_missing', frozen['path']):
                if self.require(path.stat().st_size == frozen['bytes'] and original.sha(path) == frozen['sha256'],
                                'cp7_frozen_file_changed', 'Preserve historical checkpoint/scope/schema/evidence bytes', frozen['path']):
                    self.counts['cp7_frozen_files_byte_preserved'] += 1
        self.stats['cp7_frozen_scientific_baseline'] = self._cp7_certificate
        self.stats['historical_s19_decision'] = {
            'assessment_id': S19_ID, 'status': 'inherited_exact_published_record',
            'canonical_record_sha256': S19_RECORD_SHA256, 'proof_sha256': S19_PROOF_SHA256,
            'original_pdf_or_images_reread': False, 'new_exception_granted': False,
        }

    def finish(self):
        binding = self.stats.get('cp8_input_binding')
        if binding is None:
            self.note('cp8_input_binding_missing', 'No CP8 candidate/input freeze was established')
        else:
            try:
                after = input_snapshot(self.repo, self._cp8_expected_inputs, self.watch)
                binding.update(after_input_hashes=after, after_digest_sha256=input_digest(after),
                               candidate_sha256_after=original.sha(self.repo / CP_PATH),
                               audit_completed_at_utc=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
                self.require(required_input_names(self.repo).issubset(self._cp8_expected_inputs),
                             'cp8_input_universe_changed', 'New input appeared outside the frozen map')
                same = self.require(after == binding['before_input_hashes'] == self._cp8_expected_inputs,
                                    'cp8_after_inputs_differ', 'Canonical inputs changed during the audit')
                cp_same = self.require(binding['candidate_sha256_after'] == binding['candidate_sha256'],
                                       'cp8_candidate_changed_during_audit', 'Candidate changed during the audit')
                binding['passed'] = same and cp_same and (
                    binding['before_digest_sha256'] == binding['after_digest_sha256'] == binding['expected_digest_sha256'])
                run_raw = (self.repo / RUN_PATH).read_bytes()
                run_binding = self.stats['run_accounting_binding']
                run_binding['after_run_sha256'] = sha_bytes(run_raw)
                run_binding['after_projection_sha256'] = canonical_digest(run_accounting_projection(json.loads(run_raw)))
                run_binding['passed'] = self.require(
                    run_binding['before_run_sha256'] == run_binding['after_run_sha256']
                    and run_binding['expected_projection_sha256'] == run_binding['after_projection_sha256'],
                    'cp8_run_changed_during_audit', 'Run bytes/accounting changed during the read-only audit')
            except Exception as error:
                binding['passed'] = False
                self.note('cp8_input_binding_finish_error', str(error))
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
    return AuditCP8(repo, out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
