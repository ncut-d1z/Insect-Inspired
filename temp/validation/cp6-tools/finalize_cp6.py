#!/usr/bin/env python3
"""Finalize the frozen CP6 candidate only after all archived QA checks pass.

Default: read-only validation plus a private plan receipt. --apply writes exactly
the same six-path whitelist as checkpoint_cp6.py. QA evidence must already be
archived byte-for-byte by the root agent; this script does not copy new files
into canonical data, modify exports, or perform remote operations.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import checkpoint_cp6 as build

ROOT, PRIVATE = build.ROOT, Path(__file__).resolve().parent
RAW_NAMES = {'data-audit-final.json', 'cp6-determinism.json', 'ui-audit-final.json',
             'html-browser-check.json', 'html-desktop.png', 'html-topic.png',
             'html-mobile.png', 'html-mobile-controls.png'}
UI_CHECKS = {'ten_fixed_tables', 'search_and_theme', 'abstract_expand_collapse',
             'evidence_expand_collapse', 'back_to_top', 'clear', 'counter_evidence_filter',
             'year_sort', 'mobile_no_document_overflow', 'no_javascript_errors'}


def load_qa(repo, qa, candidate, state):
    audit = build.read_json(qa / 'data-audit-final.json')
    det = build.read_json(qa / 'cp6-determinism.json')
    ui = build.read_json(qa / 'ui-audit-final.json')
    receipt = build.read_json(qa / 'qa-final-receipt.json')
    require = build.require
    require(audit['status'] == 'passed' and audit['error_count'] == 0 and audit['changed_inputs'] == [],
            'Full data audit did not pass with stable inputs')
    require(audit.get('read_only') is True and Path(audit['repository']).resolve() == repo,
            'Audit refers to another repository or is not read-only')
    validation = candidate['validation_results']
    frozen = validation['input_frozen_at_utc']
    require(build.utc(audit['audited_at_utc']) >= build.utc(frozen), 'Audit predates the current input freeze')
    expected_inputs = validation['canonical_input_hashes']
    binding = audit['statistics']['cp6_input_binding']
    require(binding['passed'] is True and binding['checkpoint_id'] == build.CP
            and binding['input_frozen_at_utc'] == frozen
            and build.utc(binding['audit_started_at_utc']) >= build.utc(frozen),
            'Audit is not bound to this exact candidate freeze')
    require(binding['candidate_sha256'] == binding['candidate_sha256_after'] == build.sha(repo / build.CP_PATH)
            and binding['candidate_bytes'] == (repo / build.CP_PATH).stat().st_size,
            'Audited candidate bytes differ from current candidate')
    current_inputs = build.file_snapshot(repo, expected_inputs)
    require(binding['before_input_hashes'] == binding['after_input_hashes'] == expected_inputs == current_inputs,
            'Candidate/audit/current exact canonical input maps differ')
    digest = build.input_digest(expected_inputs)
    require(binding['before_digest_sha256'] == binding['after_digest_sha256'] == binding['expected_digest_sha256']
            == validation['canonical_input_digest_sha256'] == digest, 'Canonical input-map digests differ')
    export_meta = audit['statistics']['export_metadata']
    require(len(export_meta) == 5 and all(row[1] == 'SCOPE-0001' and row[2] == build.CP for row in export_meta),
            'Full data audit did not inspect five CP6 views')
    old_audit = json.loads(build.git_bytes(repo, 'temp/validation/cp5-data-audit.json'))
    require(audit['findings']['warning'] == old_audit['findings']['warning']
            and audit['warning_count'] == old_audit['warning_count'],
            'Warning population differs from CP5; review explicitly before finalization')
    old_manifest = json.loads(build.git_bytes(repo, 'temp/partitions/manifest.json'))
    old_assessments = [r for r, _ in build.baseline_rows(repo, 'assessments', old_manifest)]
    expected = {'explicit_manual_reassessments': 1,
                'cp4_protected_assessments_compared': old_audit['counters']['cp4_protected_assessments_compared'],
                'cp4_manual_rejections_preserved': old_audit['counters']['cp4_manual_rejections_preserved'],
                'cp4_manual_counterevidence_preserved': old_audit['counters']['cp4_manual_counterevidence_preserved'],
                'cp5_assessments_compared': len(old_assessments),
                'cp5_assessments_byte_preserved': len(old_assessments),
                'cp5_manual_rejections_preserved': sum(a['evidence_admission_status'] == 'insufficient_evidence' for a in old_assessments),
                'cp5_manual_counterevidence_preserved': sum(a['counter_evidence'] for a in old_assessments),
                'cp5_frozen_files_byte_preserved': len(build.FROZEN)}
    for key, value in expected.items(): require(audit['counters'].get(key) == value, 'Scientific preservation gate differs: ' + key)
    for item in state['preservation']['checks']:
        require(audit['statistics'][item['dataset'] + '.jsonl'] == item['new_records'],
                'Audit canonical population differs: ' + item['dataset'])
    require(audit['statistics']['canonical_works'] == candidate['counts']['canonical_works']
            and audit['statistics']['active_assessments'] == candidate['counts']['assessments']
            and audit['statistics']['unresolved_tasks'] == candidate['counts']['unresolved_tasks'],
            'Audit/candidate counts differ')
    require(det['status'] == 'passed' and det['checkpoint_id'] == build.CP and det['changed_inputs'] == []
            and det['artifact_count'] == len(det['checks']) == len(build.EXPORTS)
            and {row['artifact'] for row in det['checks']} == set(build.EXPORTS), 'Seven-export determinism did not pass')
    for row in det['checks']:
        path = repo / row['artifact']
        require(row['byte_equal'] is True and build.sha(path) == row['canonical_sha256'] == row['independent_export_sha256']
                and path.stat().st_size == row['bytes'], 'Determinism input changed: ' + row['artifact'])
    require(ui['checkpoint_id'] == build.CP and ui['passed'] is True and ui['input_changed'] is False
            and not ui['errors'] and set(ui['checks']) == UI_CHECKS and all(value is True for value in ui['checks'].values()),
            'Ten-check UI validation did not pass')
    require(build.sha(repo / 'ref.html') == ui['html_sha256'] == ui['html_sha256_after']
            and (repo / 'ref.html').stat().st_size == ui['html_bytes'], 'UI HTML changed')
    require((qa / 'ui-audit-final.json').read_bytes() == (qa / 'html-browser-check.json').read_bytes(), 'Raw UI report alias differs')
    require(receipt['status'] == 'passed' and receipt['checkpoint_id'] == build.CP
            and receipt['scope_id'] == 'SCOPE-0001' and set(receipt['raw_evidence_files']) == RAW_NAMES,
            'QA receipt population/identity differs')
    require(receipt['canonical_input_binding'] == binding
            and receipt['receipt_input_digest_sha256'] == digest
            and receipt['receipt_candidate_sha256'] == binding['candidate_sha256'],
            'Final QA receipt lost the exact before/after candidate input binding')
    archive = repo / 'temp/validation/cp6-qa'
    for name, metadata in receipt['raw_evidence_files'].items():
        path, archived = qa / name, archive / name
        require(path.is_file() and archived.is_file() and path.stat().st_size == metadata['bytes']
                and archived.stat().st_size == metadata['bytes']
                and build.sha(path) == build.sha(archived) == metadata['sha256'], 'QA original/archive differs: ' + name)
    require((qa / 'qa-final-receipt.json').read_bytes() == (archive / 'qa-final-receipt.json').read_bytes(),
            'Original final QA receipt was not archived exactly')
    for source, target in [('data-audit-final.json', 'cp6-data-audit.json'),
                           ('cp6-determinism.json', 'cp6-determinism.json'),
                           ('ui-audit-final.json', 'cp6-ui-validation.json')]:
        require((qa / source).read_bytes() == (repo / 'temp/validation' / target).read_bytes(),
                'Canonical QA report alias differs: ' + target)
    preserved = build.read_json(repo / 'temp/validation/cp6-delta-preservation.json')
    require(preserved['status'] == 'passed' and preserved['checkpoint_id'] == build.CP
            and preserved['baseline_commit'] == build.BASE_COMMIT and preserved['existing_records_lost'] == 0,
            'Canonical delta preservation report did not pass')
    for key in ['checks', 'old_scientific_assessments_preserved', 'raw_reference_text_and_fingerprints_preserved']:
        require(preserved[key] == state['preservation'][key], 'Archived delta preservation differs from current truth: ' + key)
    exported = build.read_json(repo / 'temp/validation/cp6-export-validation.json')
    require(exported['checkpoint_id'] == build.CP and not exported['schema_errors'], 'Export validation checkpoint/schema result differs')
    for name, expected_hash in exported['artifact_hashes'].items():
        require(name in build.EXPORTS and build.sha(repo / name) == expected_hash,
                'Export validation artifact hash differs: ' + name)
    return audit, det, ui, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT / 'insect-project')
    parser.add_argument('--qa', type=Path, default=ROOT / 'cp6_qa')
    parser.add_argument('--apply', action='store_true', help='Finalize the six authorized canonical paths')
    args = parser.parse_args(); repo, qa = args.repo.resolve(), args.qa.resolve()
    require = build.require
    candidate = build.read_json(repo / build.CP_PATH)
    require(candidate['checkpoint_id'] == build.CP and candidate['parent_checkpoint_id'] == build.PARENT
            and candidate['status'] == 'invalid' and candidate['artifact_hashes'] == {}, 'Expected an invalid unpublished CP6 candidate')
    build.verify_snapshot(repo, candidate['validation_results']['canonical_input_hashes'])
    now = datetime.now(timezone.utc)
    state = build.collect(repo, now)
    require(candidate['counts'] == state['counts'], 'Current computed counts differ from frozen candidate')
    require(candidate['coverage']['derived_views']['artifacts'] == state['exports'],
            'Candidate export inventory differs from current seven exact artifacts')
    require(candidate['task_cursor_state'] == {tid: {f: t.get(f) for f in ['event_sequence', 'task_state', 'cursor', 'query_ids', 'attempt_count', 'error_code', 'failure_reason', 'retry_at', 'review_condition']}
            for tid,t in sorted(state['latest'].items())}, 'Current task cursor state differs from frozen candidate')
    require(candidate['query_log_high_watermark'] == state['counts']['queries']
            and candidate['unresolved_tasks'] == sorted(tid for tid,t in state['latest'].items() if t['task_state'] not in build.TERMINAL),
            'Frozen candidate query watermark/open queue differs')
    audit, det, ui, receipt = load_qa(repo, qa, candidate, state)
    stamp = now.isoformat().replace('+00:00', 'Z')
    cp = candidate
    for phase in ['P3', 'P4', 'P5', 'P6']: cp['coverage']['phase_status'][phase] = 'iterated_partial_checkpointed'
    cp['coverage']['derived_views']['state'] = 'validated_seven_artifacts'
    validation = cp['validation_results']
    validation.update(state='passed', data_audit='passed', determinism='passed', ui_validation='passed',
        final_artifact_hashes='verified', final_remote_verification='post_commit_external_receipt_required',
        post_commit_verification_url=build.SYNC_URL, validation_completed_at_utc=stamp,
        data_audit_errors=audit['error_count'], data_audit_warnings=audit['warning_count'],
        seven_exports_byte_identical=True, ten_ui_checks_passed=True, existing_records_lost=0,
        cp5_scientific_records_unchanged=audit['counters']['cp5_assessments_byte_preserved'],
        manual_rejections_preserved=audit['counters']['cp5_manual_rejections_preserved'],
        counter_evidence_baseline_preserved=audit['counters']['cp5_manual_counterevidence_preserved'])
    reports = ['cp6-export-validation.json', 'cp6-data-audit.json', 'cp6-determinism.json',
               'cp6-ui-validation.json', 'cp6-delta-preservation.json', 'cp6-qa/qa-final-receipt.json']
    for name in reports:
        path = repo / 'temp/validation' / name
        validation[name] = {'report': 'temp/validation/' + name, 'sha256': build.sha(path)}
    cp['failure_reasons'] = [reason for reason in cp['failure_reasons'] if not reason.startswith('Candidate invalid until')]
    cp['status'] = 'valid'
    outputs = build.documents(state, valid=True, qa=audit)
    run = dict(state['run'])
    elapsed = (now - build.utc(run['started_at_utc'])).total_seconds() / 3600
    exhausted = (elapsed >= run['budget']['wall_clock_hours'] or run['external_requests_used'] >= run['budget']['external_requests']
                 or run['manual_review_items_used'] >= run['budget']['manual_review_items'])
    run.update(status='checkpointed_open', end_checkpoint_id=build.CP, checkpoint_status='valid',
        checkpoint_validation_state='passed', checkpoint_completed_at_utc=stamp,
        checkpoint_wall_clock_hours=round(elapsed, 4), budget_exhausted=exhausted,
        pause_reason='Bounded research batch consolidated into an audited checkpoint; post-commit remote verification must pass before the next research batch. Research closure remains open.',
        sync_state='At snapshot creation the final canonical commit and remote readback are later events. Their independent receipt does not rewrite this frozen checkpoint or turn this historical pending observation into a later failure.',
        post_commit_verification_url=build.SYNC_URL)
    outputs['temp/runs/RUN-0004.json'] = build.json_text(run)
    # Compute final hashes against the planned exact six-file result before any write.
    hashes = {}
    for path in sorted(repo.rglob('*')):
        relative = path.relative_to(repo)
        if '.git' in relative.parts or str(relative) == build.CP_PATH: continue
        require(not path.is_symlink(), 'Unexpected symlink in snapshot: ' + str(relative))
        if path.is_file():
            name = str(relative)
            hashes[name] = build.sha_bytes(outputs[name].encode()) if name in outputs else build.sha(path)
    for name, text in outputs.items(): hashes[name] = build.sha_bytes(text.encode())
    cp['artifact_hashes'] = hashes
    outputs[build.CP_PATH] = build.json_text(cp, True)
    build.validate_checkpoint(repo, cp)
    build.verify_snapshot(repo, candidate['validation_results']['canonical_input_hashes'])
    require(set(outputs) == build.ALLOWED, 'Final write whitelist differs')
    if args.apply:
        build.write_outputs(repo, outputs)
        for name, expected in hashes.items(): require(build.sha(repo / name) == expected, 'Final artifact changed: ' + name)
        require({str(p.relative_to(repo)) for p in repo.rglob('*') if p.is_file() and '.git' not in p.relative_to(repo).parts}
                == set(hashes) | {build.CP_PATH}, 'Snapshot file set changed during finalization')
    for name, expected in state['frozen'].items(): require(build.sha(repo / name) == expected, 'Historical file changed: ' + name)
    result = {'status': 'valid' if args.apply else 'finalization_plan_verified', 'checkpoint_id': build.CP,
        'artifact_hashes': len(hashes), 'file_count': len(hashes) + 1,
        'checkpoint_bytes': len(outputs[build.CP_PATH].encode()), 'checkpoint_sha256': build.sha_bytes(outputs[build.CP_PATH].encode()),
        'validation_completed_at_utc': stamp, 'canonical_written': args.apply, 'canonical_write_whitelist': sorted(build.ALLOWED),
        'data_audit_errors': audit['error_count'], 'data_audit_warnings': audit['warning_count'],
        'remote_write_performed': False, 'remote_verification': 'post_commit_external_receipt_required',
        'post_commit_verification_url': build.SYNC_URL, 'research_closure_established': False}
    (PRIVATE / 'final-checkpoint-result.json').write_text(build.json_text(result), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
