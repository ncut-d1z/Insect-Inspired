from pathlib import Path
import hashlib, json, os, subprocess, sys

ROOT = Path('/workspace/scratch/2e518600ca4c')
REPO = ROOT / 'insect-project'
OUT = ROOT / 'cp5_qa/determinism'
OUT.mkdir(parents=True, exist_ok=True)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def input_snapshot():
    return {str(p.relative_to(REPO)): sha(p) for p in sorted(REPO.rglob('*'))
            if p.is_file() and '.git' not in p.relative_to(REPO).parts}

before = input_snapshot()
env = dict(os.environ)
env['PYTHONPATH'] = '/workspace/scratch/9d487ee78414/p3p6_work'
commands = [
    [sys.executable, str(ROOT / 'cp5_qa/export_run.py'), '--repo', str(REPO),
     '--output-dir', str(OUT), '--checkpoint', 'CP-0005',
     '--report', str(OUT / 'export-validation.json')],
    [sys.executable, str(ROOT / 'cp5_qa/render_html.py'), '--base', str(REPO / 'temp'),
     '--output', str(OUT / 'ref.html'), '--checkpoint', 'CP-0005',
     '--summary-output', str(OUT / 'html-summary.json')],
]
for index, command in enumerate(commands):
    with (OUT / f'command-{index + 1}.log').open('w') as handle:
        subprocess.run(command, env=env, check=True, stdout=handle, stderr=subprocess.STDOUT)

names = ['ref.bib', 'ref.html'] + [str(p.relative_to(REPO)) for p in sorted((REPO / 'temp/exports').glob('*'))]
assert len(names) == 7, 'Expected exactly BibTeX, HTML and five research views'
checks = []
for name in names:
    first, second = sha(REPO / name), sha(OUT / name)
    checks.append({'artifact': name, 'canonical_sha256': first,
                   'independent_export_sha256': second, 'byte_equal': first == second,
                   'bytes': (REPO / name).stat().st_size})
after = input_snapshot()
changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
report = {'scope_id': 'SCOPE-0001', 'checkpoint_id': 'CP-0005',
          'method': 'Independently regenerate BibTeX, five research views and ten-table HTML from the same frozen logical datasets; compare SHA-256 byte identity.',
          'artifact_count': len(checks), 'checks': checks, 'changed_inputs': changed,
          'status': 'passed' if not changed and all(x['byte_equal'] for x in checks) else 'failed'}
(ROOT / 'cp5_qa/cp5-determinism.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
assert report['status'] == 'passed'
