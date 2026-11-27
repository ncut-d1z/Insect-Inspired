#!/usr/bin/env python3
"""Independently regenerate the seven CP10 deliverables and compare their bytes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import audit_cp10 as audit


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def repository_snapshot(repo):
    return {str(path.relative_to(repo)): {'bytes': path.stat().st_size, 'sha256': sha(path)}
            for path in sorted(repo.rglob('*'))
            if path.is_file() and '.git' not in path.relative_to(repo).parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--checkpoint', default=audit.CHECKPOINT)
    args = parser.parse_args()
    repo, out, report_path = args.repo.resolve(), args.out_dir.resolve(), args.report.resolve()
    if out.is_relative_to(repo) or report_path.is_relative_to(repo):
        parser.error('All independent outputs must be outside the repository')
    if out.exists():
        parser.error('--out-dir must be a new directory; do not reuse old generated results')
    if args.checkpoint != audit.CHECKPOINT:
        parser.error('This project-specific verifier is pinned to CP-0010')
    before = repository_snapshot(repo)
    candidate_path = repo / audit.CP_PATH
    candidate_hash = sha(candidate_path)
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    expected = candidate['validation_results']['canonical_input_hashes']
    if audit.input_snapshot(repo, expected) != expected:
        raise ValueError('Canonical inputs no longer equal the candidate freeze')
    out.mkdir(parents=True)
    commands = [
        [sys.executable, '-B', str(repo / 'scripts/export_run.py'), '--repo', str(repo),
         '--output-dir', str(out), '--checkpoint', args.checkpoint,
         '--report', str(out / 'export-validation.json')],
        [sys.executable, '-B', str(repo / 'scripts/render_html.py'), '--base', str(repo / 'temp'),
         '--output', str(out / 'ref.html'), '--checkpoint', args.checkpoint,
         '--summary-output', str(out / 'html-summary.json')],
    ]
    for index, command in enumerate(commands, 1):
        with (out / f'command-{index}.log').open('w', encoding='utf-8') as handle:
            subprocess.run(command, check=True, stdout=handle, stderr=subprocess.STDOUT)
    checks = []
    for name in audit.EXPORTS:
        first, second = sha(repo / name), sha(out / name)
        checks.append({'artifact': name, 'canonical_sha256': first,
                       'independent_export_sha256': second, 'byte_equal': first == second,
                       'bytes': (repo / name).stat().st_size})
    after = repository_snapshot(repo)
    changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
    same_candidate = sha(candidate_path) == candidate_hash
    result = {
        'scope_id': 'SCOPE-0001', 'checkpoint_id': args.checkpoint,
        'checked_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'method': 'Regenerate BibTeX, five research views and ten-table HTML in a fresh external directory; compare every output byte through SHA-256.',
        'candidate_sha256': candidate_hash, 'candidate_unchanged': same_candidate,
        'canonical_input_digest_sha256': audit.input_digest(expected),
        'artifact_count': len(checks), 'checks': checks, 'changed_inputs': changed,
        'status': 'passed' if not changed and same_candidate and all(x['byte_equal'] for x in checks) else 'failed',
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'artifacts': len(checks), 'report': str(report_path)}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
