#!/usr/bin/env python3
"""Assemble a private CP6 QA receipt with exact before/after input binding.

Run only after full data audit, determinism and UI validation complete. No
canonical or remote write is performed; root archives the resulting originals.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import audit_cp6 as audit_tools

BASE = Path(__file__).resolve().parent
RAW_NAMES = ['data-audit-final.json', 'cp6-determinism.json', 'ui-audit-final.json',
             'html-browser-check.json', 'html-desktop.png', 'html-topic.png',
             'html-mobile.png', 'html-mobile-controls.png']


def require(condition, message):
    if not condition: raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=BASE.parent / 'insect-project')
    parser.add_argument('--qa', type=Path, default=BASE)
    args = parser.parse_args(); repo, qa = args.repo.resolve(), args.qa.resolve()
    require(not qa.is_relative_to(repo), 'QA outputs must remain outside canonical repository')
    audit = read(qa / 'data-audit-final.json')
    det, ui = read(qa / 'cp6-determinism.json'), read(qa / 'ui-audit-final.json')
    candidate_path = repo / 'temp/snapshots/checkpoints/CP-0006.json'
    candidate = read(candidate_path)
    expected = candidate['validation_results']['canonical_input_hashes']
    binding = audit['statistics']['cp6_input_binding']
    require(audit['status'] == 'passed' and audit['error_count'] == 0 and audit['changed_inputs'] == [], 'Data audit failed')
    require(binding['passed'] is True and binding['input_frozen_at_utc'] == candidate['validation_results']['input_frozen_at_utc'], 'Audit/candidate freeze differs')
    current = audit_tools.input_snapshot(repo, expected)
    digest = audit_tools.input_digest(current)
    candidate_hash = audit_tools.cp5.cp4.original.sha(candidate_path)
    require(current == expected == binding['before_input_hashes'] == binding['after_input_hashes'], 'Exact current/audit/candidate input maps differ')
    require(digest == binding['before_digest_sha256'] == binding['after_digest_sha256']
            == binding['expected_digest_sha256'] == candidate['validation_results']['canonical_input_digest_sha256'], 'Input digests differ')
    require(candidate_hash == binding['candidate_sha256'] == binding['candidate_sha256_after'], 'Candidate bytes changed since audit')
    require(audit_tools.required_input_names(repo).issubset(expected), 'Unbound logical input appeared')
    require(det['status'] == 'passed' and det['checkpoint_id'] == 'CP-0006'
            and det['artifact_count'] == len(det['checks']) == 7 and det['changed_inputs'] == [], 'Determinism failed')
    for row in det['checks']:
        require(row['byte_equal'] is True and audit_tools.cp5.cp4.original.sha(repo / row['artifact'])
                == row['canonical_sha256'] == row['independent_export_sha256'], 'Export changed after deterministic check')
    require(ui['checkpoint_id'] == 'CP-0006' and ui['passed'] is True and len(ui['checks']) == 10
            and all(value is True for value in ui['checks'].values()) and not ui['errors'] and ui['input_changed'] is False,
            'UI validation failed')
    require(audit_tools.cp5.cp4.original.sha(repo / 'ref.html') == ui['html_sha256'] == ui['html_sha256_after'], 'HTML changed since UI validation')
    raw = {name: {'bytes': (qa / name).stat().st_size, 'sha256': audit_tools.cp5.cp4.original.sha(qa / name)} for name in RAW_NAMES}
    result = {'status': 'passed', 'checkpoint_id': 'CP-0006', 'scope_id': 'SCOPE-0001',
        'completed_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'canonical_writes_performed': False, 'candidate_promotion_performed': False, 'remote_write_performed': False,
        'data_audit': {key: audit[key] for key in ['status', 'error_count', 'warning_count', 'duration_seconds', 'changed_inputs']},
        'audit_counters': audit['counters'], 'warning_categories': {key: value['count'] for key,value in audit['findings']['warning'].items()},
        'determinism': {'status': det['status'], 'artifacts': len(det['checks']), 'all_byte_equal': True, 'changed_inputs': det['changed_inputs']},
        'ui': {'passed': ui['passed'], 'checks': ui['checks'], 'javascript_errors': ui['errors'], 'input_changed': ui['input_changed']},
        'html': {'bytes': ui['html_bytes'], 'sha256': ui['html_sha256']},
        'canonical_input_binding': binding, 'receipt_input_digest_sha256': digest,
        'receipt_candidate_sha256': candidate_hash, 'raw_evidence_files': raw,
        'scope_note': 'Complete exact candidate/current/audit input binding retained in this private receipt. Root must archive original report bytes, finalize the candidate and verify remote publication separately.'}
    output = qa / 'qa-final-receipt.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'receipt': str(output), 'input_digest_sha256': digest,
                      'candidate_sha256': candidate_hash, 'bytes': output.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__': main()
