#!/usr/bin/env python3
"""Read-only CP6 audit, inheriting every CP5 rule and freezing all CP5 claims.

The exact CP5 Git commit supplies the baseline; its manifest is followed before
reading Assessment blobs. No canonical data, historical validator, or admission
rule is changed. The sole historical S19 reassessment remains inherited.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

BASE = Path(__file__).resolve().parent
CP5_ADAPTER = BASE.parent / 'cp5_qa/audit_cp5.py'
CP5_COMMIT = '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
CP5_TREE = '27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
CP5_MANIFEST_SHA256 = '97e1286420002f40bcf599c350b3c96081eb7dc2dff35c11179b7c7d1e099bf6'
CP5_ASSESSMENTS_SHA256 = '9eff3da3ef8a4e72418693f0882c8204ae97ac3e644f089434421768fe9e2828'
FROZEN_PATHS = tuple(f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 6)) + (
    'temp/snapshots/scope.json',
    'temp/snapshots/scopes/SCOPE-0001.json',
    'temp/seed-manifest.jsonl',
)
spec = importlib.util.spec_from_file_location('unchanged_cp5_adapter', CP5_ADAPTER)
cp5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp5)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_relative(path):
    value = PurePosixPath(path)
    if value.is_absolute() or '..' in value.parts:
        raise ValueError('Unsafe baseline/partition path: ' + str(path))
    return str(value)


def git_bytes(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def blob_bytes(repo, relative):
    return git_bytes(repo, 'show', CP5_COMMIT + ':' + safe_relative(relative))


def blob_digest(repo, relative):
    """Stream large checkpoint blobs without retaining another full copy."""
    p = subprocess.Popen(['git', '-C', str(repo), 'show',
                          CP5_COMMIT + ':' + safe_relative(relative)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    h, size = hashlib.sha256(), 0
    for chunk in iter(lambda: p.stdout.read(1024 * 1024), b''):
        h.update(chunk)
        size += len(chunk)
    error = p.stderr.read()
    if p.wait() != 0:
        raise ValueError('Cannot read frozen Git blob: ' + relative + ': ' + error.decode(errors='replace'))
    return {'path': relative, 'bytes': size, 'sha256': h.hexdigest()}


def parse_assessment_lines(raw):
    result = {}
    for line in raw.splitlines(keepends=True):
        if not line.strip():
            continue
        record = json.loads(line)
        aid = record['assessment_id']
        if aid in result:
            raise ValueError('Duplicate Assessment in baseline/current bytes: ' + aid)
        result[aid] = (record, line)
    return result


def logical_assessment_bytes(read_file):
    manifest_raw = read_file('temp/partitions/manifest.json')
    manifest = json.loads(manifest_raw)
    dataset = manifest['datasets'].get('assessments.jsonl')
    if dataset is None:
        return read_file('temp/assessments.jsonl'), manifest_raw
    chunks = []
    for part in dataset['parts']:
        raw = read_file('temp/' + safe_relative(part['path']))
        if not (sha(raw) == part['sha256'] and len(raw) == part['bytes']
                and sum(bool(line.strip()) for line in raw.splitlines()) == part['records']):
            raise ValueError('Assessment partition hash/count mismatch: ' + part['path'])
        chunks.append(raw)
    raw = b''.join(chunks)
    if not (sha(raw) == dataset['logical_sha256']
            and len(parse_assessment_lines(raw)) == dataset['logical_records']):
        raise ValueError('Assessment logical manifest reconciliation failed')
    return raw, manifest_raw


def cp5_baseline(repo):
    tree = git_bytes(repo, 'rev-parse', CP5_COMMIT + '^{tree}').decode().strip()
    if tree != CP5_TREE:
        raise ValueError('Frozen CP5 commit/tree mismatch')
    raw, manifest_raw = logical_assessment_bytes(lambda p: blob_bytes(repo, p))
    if sha(manifest_raw) != CP5_MANIFEST_SHA256 or sha(raw) != CP5_ASSESSMENTS_SHA256:
        raise ValueError('Frozen CP5 manifest/Assessment logical bytes differ')
    records = parse_assessment_lines(raw)
    active = [r for r, _ in records.values() if r['assessment_status'] == 'active']
    rejected = sorted(r['assessment_id'] for r in active
                      if r['evidence_admission_status'] == 'insufficient_evidence')
    counter = sorted(r['assessment_id'] for r in active if r['counter_evidence'])
    if not (len(records) == len(active) == 69 and len(rejected) == 9
            and len(counter) == 23 and len(set(rejected) | set(counter)) == 31):
        raise ValueError('Frozen CP5 Assessment population differs')
    certificate = {
        'source_commit': CP5_COMMIT, 'source_tree': CP5_TREE,
        'manifest_sha256': sha(manifest_raw), 'logical_sha256': sha(raw),
        'logical_bytes': len(raw), 'baseline_records': len(records),
        'active_records': len(active), 'insufficient_ids': rejected,
        'counter_evidence_ids': counter, 'protected_union': 31,
        'frozen_files': [blob_digest(repo, p) for p in FROZEN_PATHS],
        'rule': 'All 69 complete Assessment records and their original JSONL line bytes remain unchanged; new distinct claims use all inherited gates.',
        'additional_exceptions_allowed': 0,
    }
    return records, certificate


class AuditCP6(cp5.AuditCP5):
    def check_cp5_baseline(self):
        for path in (Path(__file__).resolve(), CP5_ADAPTER):
            self.watch(path)
        old_records, certificate = cp5_baseline(self.repo)

        def read_current(relative):
            path = (self.repo / safe_relative(relative)).resolve()
            if not path.is_relative_to(self.repo.resolve()):
                raise ValueError('Current partition path escapes repository')
            self.watch(path)
            return path.read_bytes()

        current_raw, _ = logical_assessment_bytes(read_current)
        current_lines = parse_assessment_lines(current_raw)
        current = self.indices.get('assessment', {})
        for aid, (old, old_line) in old_records.items():
            self.counts['cp5_assessments_compared'] += 1
            new = current.get(aid)
            same = self.require(new == old, 'cp5_assessment_record_changed',
                                'Preserve the complete frozen CP5 record, including all manual decisions', aid)
            same_bytes = self.require(aid in current_lines and current_lines[aid][1] == old_line,
                                      'cp5_assessment_raw_line_changed',
                                      'Preserve original JSONL line bytes for each CP5 Assessment', aid)
            if same and same_bytes:
                self.counts['cp5_assessments_byte_preserved'] += 1
                if old['evidence_admission_status'] == 'insufficient_evidence':
                    self.counts['cp5_manual_rejections_preserved'] += 1
                if old['counter_evidence']:
                    self.counts['cp5_manual_counterevidence_preserved'] += 1
        for frozen in certificate['frozen_files']:
            path = self.repo / frozen['path']
            self.watch(path)
            exists = self.require(path.is_file(), 'cp5_frozen_file_missing', frozen['path'])
            if exists and self.require(path.stat().st_size == frozen['bytes']
                                       and cp5.cp4.original.sha(path) == frozen['sha256'],
                                       'cp5_frozen_file_changed',
                                       'Preserve the prior checkpoint/scope/seed bytes', frozen['path']):
                self.counts['cp5_frozen_files_byte_preserved'] += 1
        self.stats['cp5_frozen_baseline'] = certificate

    def assessments(self):
        super().assessments()
        self.check_cp5_baseline()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--now')
    parser.add_argument('--max-examples', type=int, default=20)
    args = parser.parse_args()
    now = cp5.cp4.original.utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error('--now must be an ISO date-time with timezone')
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.is_relative_to(repo):
        parser.error('--out must be outside the canonical repository')
    return AuditCP6(repo, out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
