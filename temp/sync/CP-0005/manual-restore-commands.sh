PS4='+ line ${LINENO}: '
set -x
set -euo pipefail
cp5_recovery_root="$(mktemp -d "$PWD/insect-cp5-recovery.XXXXXX")"
cp5_package_dir="$cp5_recovery_root/package"
mkdir "$cp5_package_dir"
printf '请将 README.md、manifest.json、recovery.bundle 下载到：%s\n' "$cp5_package_dir"
cp -- /workspace/scratch/2e518600ca4c/cp5_sync/README.md /workspace/scratch/2e518600ca4c/cp5_sync/manifest.json /workspace/scratch/2e518600ca4c/cp5_sync/recovery.bundle "$cp5_package_dir/"
printf '%s\n' "$cp5_recovery_root" > /workspace/scratch/2e518600ca4c/cp5_sync/manual-restore-run-hs_11ne1/recovery-root.txt
python3 - "$cp5_package_dir" <<'PYCHECK'
from pathlib import Path
import hashlib, json, sys
p = Path(sys.argv[1])
manifest_raw = (p / 'manifest.json').read_bytes()
m = json.loads(manifest_raw)
assert m['repository'] == 'ncut-d1z/Insect-Inspired'
assert m['target_ref'] == 'refs/heads/research/p3-p6-cp5'
assert m['expected_baseline_commit'] == m['expected_parent_commit'] == '95a0a218667333967f4a6c18f8b8b71df8b464e0'
assert m['bundle_prerequisites'] == ['95a0a218667333967f4a6c18f8b8b71df8b464e0']
assert m['expected_commit'] == '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006' and m['expected_tree'] == '27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
assert m['bundle_name'] == 'recovery.bundle' and m['bundle_kind'] == 'incremental'
bundle = (p / 'recovery.bundle').read_bytes()
assert type(m['bundle_bytes']) is int
assert len(bundle) == m['bundle_bytes'] == int('19638061')
assert hashlib.sha256(bundle).hexdigest() == m['bundle_sha256'] == '29eefe39d95fecd6cbcb909a8cc8242fed6bb168bd42452d3232d881a386738e'
assert hashlib.sha256((p / 'README.md').read_bytes()).hexdigest() == m['readme_sha256']
assert m['checkpoint_sha256'] == 'ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270'
print('输入文件校验通过；manifest SHA-256:', hashlib.sha256(manifest_raw).hexdigest())
PYCHECK
set -euo pipefail
cp5_repo_url='https://github.com/ncut-d1z/Insect-Inspired.git'
cp5_expected_base='95a0a218667333967f4a6c18f8b8b71df8b464e0'
cp5_expected_commit='82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
cp5_expected_tree='27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
cp5_restore_dir="$cp5_recovery_root/restored-cp5"
test ! -e "$cp5_restore_dir"
git clone -c core.autocrlf=false -c core.eol=lf -c core.hooksPath=/dev/null --no-checkout --no-tags "$cp5_repo_url" "$cp5_restore_dir"
git -C "$cp5_restore_dir" fetch --no-tags origin "$cp5_expected_base"
test "$(git -C "$cp5_restore_dir" rev-parse 'FETCH_HEAD^{commit}')" = "$cp5_expected_base"
test ! -s "$cp5_restore_dir/.git/shallow"
test ! -s "$cp5_restore_dir/.git/objects/info/alternates"
git -C "$cp5_restore_dir" bundle verify "$cp5_package_dir/recovery.bundle"
test "$(git -C "$cp5_restore_dir" bundle list-heads "$cp5_package_dir/recovery.bundle")" = "$cp5_expected_commit refs/heads/research/p3-p6-cp5"
test -z "$(git -C "$cp5_restore_dir" for-each-ref --format='%(refname)' refs/heads/restored-cp5)"
git -C "$cp5_restore_dir" fetch --no-tags "$cp5_package_dir/recovery.bundle" 'refs/heads/research/p3-p6-cp5:refs/heads/restored-cp5'
test "$(git -C "$cp5_restore_dir" rev-parse 'refs/heads/restored-cp5^{commit}')" = "$cp5_expected_commit"
test "$(git -C "$cp5_restore_dir" show -s --format=%T restored-cp5)" = "$cp5_expected_tree"
test "$(git -C "$cp5_restore_dir" show -s --format=%P restored-cp5)" = "$cp5_expected_base"
git -C "$cp5_restore_dir" checkout restored-cp5
git -C "$cp5_restore_dir" fsck --full --strict
test -z "$(git -C "$cp5_restore_dir" status --porcelain=v1 --untracked-files=all)"
python3 - "$cp5_restore_dir" <<'PYCP'
from pathlib import Path
import hashlib, json, sys
p = Path(sys.argv[1]) / 'temp/snapshots/checkpoints/CP-0005.json'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'ed0fa6a00066a82d1a9635cf6306b74a1982d3659911ded42c4087ddc443e270'
cp = json.loads(raw)
assert cp['checkpoint_id'] == 'CP-0005' and cp['scope_id'] == 'SCOPE-0001'
assert cp['status'] == 'valid' and cp['parent_checkpoint_id'] == 'CP-0004'
print('本地恢复与检查点哈希校验通过：', p.parent.parent.parent.parent)
PYCP
