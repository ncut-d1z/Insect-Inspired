#!/usr/bin/env python3
"""Read-only CP5 audit: unchanged CP4 rules plus frozen CP4 manual vetoes.

The inherited S19 exception remains the exact historical CP4 exception. This
adapter adds no reassessment exception and never changes canonical records.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
CP4_ADAPTER = BASE.parent / 'cp4_qa/audit_cp4.py'
BASELINE = BASE / 'cp4-assessments.jsonl'
CERTIFICATE = BASE / 'cp4-assessment-baseline.json'
BASELINE_SHA256 = '80429e385bce83bbd7e5a42f2aac417b8afb39253b731b3eb4098b3f401eb6df'
CERTIFICATE_SHA256 = 'f6d208a673d2d440491edbe158a382bf0f9380f9648bf375141feec0fcb1a18d'
CP4_COMMIT = 'bb7726c2ef334df0d7069165156b1cbc2c4e2fd8'
spec = importlib.util.spec_from_file_location('unchanged_cp4_adapter', CP4_ADAPTER)
cp4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp4)


def baseline_records():
    raw = BASELINE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError('Frozen CP4 Assessment bytes changed')
    certificate_raw = CERTIFICATE.read_bytes()
    if hashlib.sha256(certificate_raw).hexdigest() != CERTIFICATE_SHA256:
        raise ValueError('Frozen CP4 baseline certificate changed')
    certificate = json.loads(certificate_raw)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    active = [a for a in rows if a['assessment_status'] == 'active']
    rejected = sorted(a['assessment_id'] for a in active
                      if a['evidence_admission_status'] == 'insufficient_evidence')
    counter = sorted(a['assessment_id'] for a in active if a['counter_evidence'])
    if not (certificate['source_commit'] == CP4_COMMIT
            and certificate['logical_sha256'] == BASELINE_SHA256
            and len(rows) == certificate['records'] == 68
            and len(active) == certificate['active_records'] == 68
            and rejected == certificate['insufficient_ids'] and len(rejected) == 9
            and counter == certificate['counter_evidence_ids'] and len(counter) == 22
            and len(set(rejected) | set(counter)) == certificate['protected_union_count'] == 30):
        raise ValueError('CP4 baseline identity/count reconciliation failed')
    return rows, certificate


class AuditCP5(cp4.AuditCP4):
    def check_cp4_baseline(self):
        for path in (CP4_ADAPTER, BASELINE, CERTIFICATE):
            self.watch(path)
        rows, certificate = baseline_records()
        protected = [a for a in rows if a['assessment_status'] == 'active'
                     and (a['evidence_admission_status'] == 'insufficient_evidence'
                          or a['counter_evidence'])]
        current = self.indices.get('assessment', {})
        for old in protected:
            aid = old['assessment_id']
            new = current.get(aid)
            if not self.require(new is not None, 'cp4_manual_record_missing',
                                'Frozen manual rejection/counter-evidence must remain traceable', aid):
                continue
            self.counts['cp4_protected_assessments_compared'] += 1
            self.require(new.get('assessment_status') == 'active', 'cp4_manual_record_inactivated',
                         'This CP5 batch has no approved disposal/supersession of a CP4 protected claim', aid)
            for field in ('assessment_id', 'work_id', 'claim_id', 'limitation_id', 'claim_type'):
                self.require(new.get(field) == old.get(field), 'cp4_manual_claim_identity_changed',
                             field, aid)
            if old['evidence_admission_status'] == 'insufficient_evidence':
                admitted = self.require(new.get('evidence_admission_status') == 'insufficient_evidence',
                                        'cp4_manual_rejection_upgraded',
                                        'No CP5 exception permits upgrading a frozen CP4 manual rejection', aid)
                handling = self.require(new.get('handling_level') == 'insufficient_evidence',
                                        'cp4_manual_rejection_handling_changed',
                                        'Retain the original insufficiency handling level', aid)
                codes = self.require(set(old['rejection_codes']).issubset(new.get('rejection_codes', [])),
                                     'cp4_manual_rejection_codes_removed', old['rejection_codes'], aid)
                if admitted and handling and codes:
                    self.counts['cp4_manual_rejections_preserved'] += 1
            if old['counter_evidence']:
                flag = self.require(new.get('counter_evidence') is True,
                                    'cp4_manual_counterevidence_lost', 'Preserve the CP4 counter-evidence flag', aid)
                kinds = self.require(set(old['counter_evidence_types']).issubset(new.get('counter_evidence_types', [])),
                                     'cp4_manual_counterevidence_types_removed', old['counter_evidence_types'], aid)
                evidence = self.require(all(loc in new.get('evidence_locator', []) for loc in old['evidence_locator']),
                                        'cp4_manual_counterevidence_locators_removed',
                                        'Retain all frozen counter-evidence locators', aid)
                provenance = True
                for field in ('provenance_upload_ids', 'provenance_version_ids'):
                    provenance = self.require(set(old[field]).issubset(new.get(field, [])),
                                              'cp4_manual_counterevidence_provenance_removed', field, aid) and provenance
                if flag and kinds and evidence and provenance:
                    self.counts['cp4_manual_counterevidence_preserved'] += 1
        self.stats['cp4_frozen_manual_baseline'] = {
            'source_commit': CP4_COMMIT, 'logical_sha256': BASELINE_SHA256,
            'certificate_sha256': CERTIFICATE_SHA256,
            'baseline_records': certificate['records'], 'protected_union': len(protected),
            'expected_insufficient': 9, 'expected_counter_evidence': 22,
            'additional_exceptions_allowed': 0,
            'rule': 'Preserve CP4 active claim identity, manual insufficiency/rejection codes, and counter-evidence with its locators/provenance.'}

    def assessments(self):
        super().assessments()
        self.check_cp4_baseline()
        self.require(self.counts['explicit_manual_reassessments'] == 1,
                     'historical_s19_exception_count',
                     'Exactly the unchanged historical S19 CP4 reassessment is permitted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--now')
    parser.add_argument('--max-examples', type=int, default=20)
    args = parser.parse_args()
    now = cp4.original.utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error('--now must be an ISO date-time with timezone')
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.is_relative_to(repo):
        parser.error('--out must be outside the canonical repository')
    return AuditCP5(repo, out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
