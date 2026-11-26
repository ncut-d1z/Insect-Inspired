#!/usr/bin/env python3
"""Create the trusted CP5 local-integrity manifest only after the final commit freezes.

Reads the canonical repository; writes the manifest outside it. No remote access,
Git mutation, project-code execution, credential read, or scientific query occurs.
Use the printed manifest SHA256 as verify_remote_cp5.py --manifest-sha.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from verify_remote_cp5 import (Checks, Git, HERE, LOCAL_REPO, CP2, CP4, GIT_PARENT,
                              inspect_snapshot, redact, sha_arg, utc_now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=LOCAL_REPO)
    parser.add_argument('--expected-head', required=True, type=sha_arg)
    parser.add_argument('--expected-tree', required=True, type=sha_arg)
    parser.add_argument('--out', type=Path, default=HERE / 'local-integrity-cp5.json')
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    if out.is_relative_to(repo):
        parser.error('The integrity manifest must be outside the repository')
    audit, started = Checks(), time.monotonic()
    report = {'schema_version': 1, 'read_only_repository_check': True,
              'checked_at_utc': utc_now(), 'repository': str(repo),
              'remote_comparison_basis': 'Frozen local CP5 commit; no remote query or upload performed.',
              'expected_git_parent': GIT_PARENT, 'expected_valid_checkpoint_parent_commit': CP4,
              'canonical_repository_modified': False, 'remote_mutations_performed': False,
              'research_code_executed': False}
    fatal = None
    try:
        git = Git(repo)
        snapshot = inspect_snapshot(git, args.expected_head, args.expected_tree, audit)
        report.update(snapshot)
        commits = git.text(['rev-list', '--reverse', CP2 + '..' + args.expected_head]).splitlines()
        report['new_commits'] = []
        for sha in commits:
            tree, parents = git.text(['show', '-s', '--format=%T%n%P', sha]).split('\n', 1)
            report['new_commits'].append({'sha': sha, 'tree': tree, 'parents': parents.split()})
        # The shared inspector has already verified raw tree bytes and all
        # checkpoint artifacts; this is a frozen transfer manifest, not new QA.
    except Exception as error:
        fatal = redact(str(error))
        audit.failures.append({'check': 'execution_completed', 'detail': fatal})
    report.update(status='passed' if not audit.failures else 'failed', checks=audit.checks,
                  failures=audit.failures, duration_seconds=round(time.monotonic() - started, 3))
    data = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(json.dumps({'status': report['status'], 'failed_checks': len(audit.failures),
                      'head': report.get('head_commit'), 'tree': report.get('head_tree'),
                      'manifest': str(out), 'manifest_sha256': hashlib.sha256(data).hexdigest(),
                      'file_count': report.get('head_snapshot', {}).get('file_entries')}, ensure_ascii=False), flush=True)
    return 2 if fatal else 1 if audit.failures else 0


if __name__ == '__main__':
    sys.exit(main())
