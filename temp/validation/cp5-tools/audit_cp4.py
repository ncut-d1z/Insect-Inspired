#!/usr/bin/env python3
"""Private CP4 adapter for one independently re-reviewed historical rejection.

Every original Audit method runs unchanged. Only the historical-manual-veto
require call may recognize a fully documented, exact manual reassessment.
This is not a mechanical admission rule and grants no exception to any other
scientific, schema, reference, date, export or hash check.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ORIGINAL = Path('/workspace/scratch/9d487ee78414/p3p6_work/audit_run.py')
EVIDENCE = Path(__file__).with_name('explicit-manual-reassessment-evidence.json')
SUPPORTED_ID = 'AS-S19-L05-baseline-receptive-field'
EVIDENCE_SHA256 = '2326bf4aa991fe1b990a93eeacbe1b6d3d3e833db59aa15f4b8c21f873806f88'
sys.path.insert(0, str(ORIGINAL.parent))
spec = importlib.util.spec_from_file_location('unchanged_cp3_audit', ORIGINAL)
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def ensure(condition, reason):
    if not condition:
        raise ValueError(reason)


def normalize_source_ids(value, aliases):
    if isinstance(value, list):
        return [normalize_source_ids(v, aliases) for v in value]
    if isinstance(value, dict):
        return {k: aliases.get(v, v) if k == 'source_id' and isinstance(v, str)
                else normalize_source_ids(v, aliases) for k, v in value.items()}
    return value


class AuditCP4(original.Audit):
    def checked_reassessment(self, entity, baseline_path):
        ensure(entity == SUPPORTED_ID, 'No independent reassessment proof for this ID')
        self.watch(EVIDENCE)
        ensure(original.sha(EVIDENCE) == EVIDENCE_SHA256,
               'Independent review certificate differs from the reviewed artifact')
        proof = self.load_json(EVIDENCE)
        ensure(proof['decision'] == 'explicit_manual_reassessment'
               and proof['assessment_id'] == entity, 'Proof identity or decision differs')
        ensure(Path(baseline_path).resolve() == Path(proof['legacy_manual_baseline_path']).resolve(),
               'Historical veto came from a different manual baseline')
        roles = {a['role'] for a in proof['artifact_hashes']}
        ensure(roles == {'unchanged_original_audit', 'unchanged_legacy_manual_baseline',
                         'original_Krapp1998_PDF', 'visually_reviewed_Krapp_methods_page',
                         'visually_reviewed_S19_data_reuse_page'}, 'Incomplete reviewed source artifacts')
        for artifact in proof['artifact_hashes']:
            path = Path(artifact['path'])
            self.watch(path)
            ensure(path.is_file() and original.sha(path) == artifact['sha256'],
                   'Reviewed source or original validator bytes changed: ' + artifact['role'])
        report = self.load_json(self.temp / 'validation/cp4-scientific-repairs.json')
        ensure(report['scope_id'] == proof['scope_id'] == 'SCOPE-0001'
               and report['checkpoint_id'] == proof['checkpoint_id'] == 'CP-0004',
               'Repair checkpoint/scope mismatch')
        matching = [e for e in report['events'] if e.get('assessment_id') == entity]
        ensure(len(matching) == 1, 'Missing or ambiguous full before/after repair event')
        event = matching[0]
        before, after = event['before'], event['after']
        old = [r for r in self.load_json(Path(baseline_path))
               if r.get('assessment_id') == entity]
        ensure(len(old) == 1 and before == old[0], 'Before is not the complete original manual record')
        ensure(digest(before) == proof['repair_event_before_sha256']
               == proof['legacy_manual_assessment_sha256']
               and digest(after) == proof['repair_event_after_sha256'],
               'Before/after differs from independently inspected reassessment')
        ensure(event['run_id'] == 'RUN-0002' and event['reason'].strip()
               and event['reason'] == proof['repair_reason'], 'Missing explicit manual reason')
        reviewed = original.utc(event['reviewed_at_utc'])
        independently_reviewed = original.utc(proof['independently_reviewed_at_utc'])
        ensure(reviewed is not None and independently_reviewed is not None
               and reviewed <= independently_reviewed <= self.now
               and event['reviewed_at_utc'] == proof['repair_reviewed_at_utc']
               and original.utc(after['date']) == reviewed
               and after['reviewer'].strip() and proof['independent_reviewer'].strip(),
               'Missing, changed or future manual-review date/reviewer')
        alias_report = self.load_json(self.temp / 'reports/cp4-focused-evidence.json')
        aliases = alias_report['canonical_source_alias_map']
        ensure(aliases == proof['canonical_alias_map'], 'Canonical source alias map changed')
        canonical_after = normalize_source_ids(after, aliases)
        current = self.indices.get('assessment', {}).get(entity)
        ensure(current == canonical_after and digest(current) == proof['canonical_after_sha256'],
               'Alias-normalized after is not the complete current Assessment')
        ensure(before['evidence_admission_status'] == 'insufficient_evidence'
               and before['rejection_codes'] == ['missing_critical_conditions']
               and after['evidence_admission_status'] == 'eligible'
               and after['rejection_codes'] == [], 'Rejection transition exceeds reviewed condition repair')
        ensure(before['species']['status'] == 'not_reported' and before['species']['value'] is None,
               'Historical missing condition was not the inspected species gap')
        species = current['species']
        ensure(current['conditions']['species'] == species and species['status'] == 'reported'
               and len(species['value']) == 1
               and species['value'][0]['scientific_name'] == proof['resolved_species']
               == 'Calliphora erythrocephala'
               and set(species['value'][0]['cell_identifiers']) == {'VS' + str(i) for i in range(1, 11)},
               'Critical species/cell condition is not the original-methods evidence reviewed')
        unchanged = ['assessment_id', 'work_id', 'work_key', 'claim_id', 'limitation_id',
                     'claim_type', 'evidence_route', 'relation_type', 'dataset_records',
                     'baseline_records', 'metric_records', 'counter_evidence',
                     'counter_evidence_types', 'claims_absolute_scale']
        ensure(all(before[k] == after[k] for k in unchanged),
               'Claim identity, data, metrics, scale or counter-evidence was changed')
        ensure(current['counter_evidence'] is True and current['remaining_limitations'].strip(),
               'Counter-evidence or applicability limits were lost')
        before_locs = normalize_source_ids(before['evidence_locator'], aliases)
        new_locs = [loc for loc in current['evidence_locator'] if loc not in before_locs]
        ensure(new_locs == proof['new_evidence_locators'] and new_locs,
               'No exact newly inspected primary-source evidence locator')
        source = proof['source_original']
        ensure(source['species_locator'] in new_locs
               and source['species_locator'] in species['evidence_locator']
               and source['species_locator']['source_id'] == 'institutional_repository'
               and source['species_locator']['identifier'] == '10.1152/jn.1998.79.4.1902'
               and source['species_locator']['page'] == 4
               and source['species_locator']['url'] == source['source_url']
               and original.utc(source['accessed_at_utc']) <= reviewed,
               'New original Methods locator or acquisition date differs')
        version = self.indices.get('version', {}).get(source['version_id'], {})
        upload = self.indices.get('upload', {}).get(source['upload_id'], {})
        ensure(version.get('work_id') == source['work_id']
               and any(f.get('sha256') == source['sha256'] for f in version.get('file_records', []))
               and upload.get('sha256') == source['sha256'],
               'Original source PDF is not hash-linked to the canonical version/upload')
        manual = proof['linked_manual_review']
        ensure(manual in self.datasets.get('manual-reviews.jsonl', [])
               and manual['entity_id'] == entity and manual['review_type'] == 'cross_source_patch'
               and original.utc(manual['recorded_at_utc']) <= self.now,
               'Explicit source-cross-check activity is not in the manual review ledger')
        return {'assessment_id': entity, 'decision': proof['decision'],
                'proof_file': str(EVIDENCE), 'proof_sha256': EVIDENCE_SHA256,
                'repair_reviewed_at_utc': event['reviewed_at_utc'],
                'independently_reviewed_at_utc': proof['independently_reviewed_at_utc'],
                'canonical_after_sha256': proof['canonical_after_sha256'],
                'resolved_condition': 'species', 'counter_evidence_preserved': True}

    def require(self, condition, category, message, entity=None, path=None):
        if not condition and category == 'manual_rejection_mechanically_upgraded':
            try:
                proof = self.checked_reassessment(entity, message)
            except Exception as error:
                self.stats.setdefault('manual_reassessment_not_accepted', []).append(
                    {'assessment_id': entity, 'reason': str(error)})
            else:
                self.counts['explicit_manual_reassessments'] += 1
                self.stats.setdefault('explicit_manual_reassessments', []).append(proof)
                return super().require(True, category, message, entity, path)
        return super().require(condition, category, message, entity, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--now')
    parser.add_argument('--max-examples', type=int, default=20)
    args = parser.parse_args()
    now = original.utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error('--now must be an ISO date-time with timezone')
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.is_relative_to(repo):
        parser.error('--out must be outside the canonical repository; this audit is read-only')
    return AuditCP4(repo, out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
