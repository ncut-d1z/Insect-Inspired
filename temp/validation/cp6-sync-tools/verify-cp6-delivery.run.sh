set -euo pipefail
readonly REMOTE='https://github.com/ncut-d1z/Insect-Inspired.git'
readonly TARGET='refs/heads/research/p3-p6-cp6'
readonly BASE='fc43ccb0582611292811bbe4d2b7fb3ea0c9bcc0'
readonly CP6='a1303b6b6c38692b4f57da5cfb342289c6dc17e5'
readonly TREE='32a732212b9151c2ee1ee75a91081ffcbca60d9b'
readonly INPUT='1b46308cab46fe7611c6af465cb338c65549275b'
readonly SYNC='refs/heads/sync/cp6-checkpoint-import'
readonly MAIN='bb7726c2ef334df0d7069165156b1cbc2c4e2fd8'
[[ "$GITHUB_REPOSITORY" == 'ncut-d1z/Insect-Inspired' ]]
[[ "$GITHUB_REF" == 'refs/heads/sync/cp6-checkpoint-import' ]]
[[ "$GITHUB_EVENT_NAME" == 'push' ]]
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$BASE" =~ ^[0-9a-f]{40}$ && "$CP6" =~ ^[0-9a-f]{40}$ && "$TREE" =~ ^[0-9a-f]{40}$ ]]
[[ "$CP6" != "$BASE" ]]
command -v git >/dev/null
command -v python3 >/dev/null

# The job token remains only in ephemeral process configuration.
set +x
auth_header="$(printf 'x-access-token:%s' "$DELIVERY_TOKEN" | base64 -w 0)"
printf '::add-mask::%s\n' "$auth_header"
export GIT_CONFIG_COUNT=3
export GIT_CONFIG_KEY_0='http.https://github.com/.extraheader'
export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $auth_header"
export GIT_CONFIG_KEY_1='core.hooksPath'
export GIT_CONFIG_VALUE_1='/dev/null'
export GIT_CONFIG_KEY_2='push.followTags'
export GIT_CONFIG_VALUE_2='false'
unset DELIVERY_TOKEN auth_header

import_tmp="$(mktemp -d "$RUNNER_TEMP/cp6-sync.XXXXXX")"
input_repo="$import_tmp/input.git"
import_repo="$import_tmp/import.git"
verify_repo="$import_tmp/remote-verify.git"
bundle_path="$import_tmp/recovery.bundle"

# Fixed upload commit, manifest, README, and ordered binary parts; no checkout or project code.
git init --bare --quiet "$input_repo"
git --git-dir="$input_repo" fetch --quiet --no-tags --depth=1 "$REMOTE" "$INPUT"
[[ "$(git --git-dir="$input_repo" rev-parse FETCH_HEAD)" == "$INPUT" ]]
python3 - "$input_repo" "$INPUT" "$bundle_path" <<'PYINPUT'
import hashlib, json, re, subprocess, sys
from datetime import datetime, timezone
repo, commit, output = sys.argv[1:]
base = 'fc43ccb0582611292811bbe4d2b7fb3ea0c9bcc0'
cp6 = 'a1303b6b6c38692b4f57da5cfb342289c6dc17e5'
target = 'refs/heads/research/p3-p6-cp6'
def blob(path):
    return subprocess.check_output(['git', '--git-dir='+repo, 'cat-file', 'blob', commit+':temp/sync/CP-0006/'+path])
def unique_keys(items):
    result = {}
    for key, value in items:
        assert key not in result, 'duplicate JSON key: '+str(key)
        result[key] = value
    return result
manifest_raw = blob('manifest.json')
assert hashlib.sha256(manifest_raw).hexdigest() == 'c3e4cbe60d80a7a6cfb451c600693677fc5d7e3ded547aafaf890e1f6ce5c77f', 'manifest SHA-256 mismatch'
m = json.loads(manifest_raw, object_pairs_hook=unique_keys)
assert m['format_version'] == 1
assert m['repository'] == 'ncut-d1z/Insect-Inspired'
assert m['checkpoint_id'] == 'CP-0006' and m['scope_id'] == 'SCOPE-0001'
assert m['source_sync_ref'] == 'refs/heads/sync/cp6-checkpoint-import'
assert m['target_ref'] == target
assert m['expected_baseline_commit'] == m['expected_parent_commit'] == base
assert m['expected_commit'] == cp6 and m['expected_tree'] == '32a732212b9151c2ee1ee75a91081ffcbca60d9b'
assert m['bundle_name'] == 'recovery.bundle' and m['bundle_kind'] == 'incremental'
assert m['bundle_prerequisites'] == [base]
assert type(m['bundle_bytes']) is int and m['bundle_bytes'] == int('26519358')
assert m['bundle_sha256'] == 'cc53dbbe5ddc1045214c38a0aafe088e9c869836219e3c65707adab2c397a142'
assert m['checkpoint_path'] == 'temp/snapshots/checkpoints/CP-0006.json'
assert m['checkpoint_sha256'] == '43c11e7465404e956274fdaadef74f7bd0d27177111de5200f127f36c8c7d47d'
assert m['parent_checkpoint_id'] == 'CP-0005'
assert m['canonical_file_count'] == int('1256')
assert m['artifact_hash_count'] == int('1255')
assert m['partition_dataset_count'] == int('7')
assert m['partition_manifest_sha256'] == '6b75621b4b7db90a36a3858e315df3ad46d77d262cf4f63041fccabb82fedab8'
assert m['readme_sha256'] == '33e87bee12602b8a02775a0010bd566d702e2852d65054ec5547a42e80dd2473'
assert hashlib.sha256(blob('README.md')).hexdigest() == m['readme_sha256']
# The manifest pins the bytes of each original binary blob, not base64 text.
assert m['bundle_storage'] == 'ordered_binary_parts'
parts = m['parts']
assert isinstance(parts, list) and parts, 'missing ordered binary parts'
seen_paths, declared_bytes = set(), 0
for ordinal, part in enumerate(parts, 1):
    assert isinstance(part, dict), 'invalid part record'
    assert type(part['index']) is int and part['index'] == ordinal, 'parts must be consecutive and ordered from 1'
    path = part['path']
    assert isinstance(path, str) and re.fullmatch(r'recovery\.bundle\.part-[0-9]{4,}', path), 'unsafe part path'
    assert path == 'recovery.bundle.part-'+format(ordinal, '04d'), 'part name/index mismatch'
    assert path not in seen_paths, 'duplicate part path'
    seen_paths.add(path)
    assert type(part['bytes']) is int and part['bytes'] > 0, 'invalid part byte count'
    assert isinstance(part['sha256'], str) and re.fullmatch('[0-9a-f]{64}', part['sha256']), 'invalid part SHA-256'
    declared_bytes += part['bytes']
assert declared_bytes == m['bundle_bytes'], 'part byte sum mismatch'
prefix = 'temp/sync/CP-0006/'
input_paths = subprocess.check_output(['git', '--git-dir='+repo, 'ls-tree', '-r', '-z', '--name-only', commit, '--', prefix]).split(b'\0')
actual_parts = set()
for raw_path in input_paths:
    if not raw_path:
        continue
    full_path = raw_path.decode('utf-8')
    assert full_path.startswith(prefix)
    relative_path = full_path[len(prefix):]
    if relative_path.startswith('recovery.bundle.part-'):
        actual_parts.add(relative_path)
assert actual_parts == seen_paths, 'missing or unlisted binary part'
chunks = []
for part in parts:
    chunk = blob(part['path'])
    assert len(chunk) == part['bytes'], 'binary part length mismatch: '+part['path']
    assert hashlib.sha256(chunk).hexdigest() == part['sha256'], 'binary part SHA-256 mismatch: '+part['path']
    chunks.append(chunk)
data = b''.join(chunks)
del chunks
assert len(data) == m['bundle_bytes'], 'bundle length mismatch'
assert hashlib.sha256(data).hexdigest() == m['bundle_sha256'], 'bundle SHA-256 mismatch'
# Require the one advertised target and the exact remote prerequisite.
signature, _, remainder = data.partition(b'\n')
assert signature in (b'# v2 git bundle', b'# v3 git bundle'), 'unexpected bundle format'
header, separator, _ = remainder.partition(b'\n\n')
assert separator, 'missing bundle header terminator'
prerequisites, heads = [], []
for line in header.decode('utf-8').splitlines():
    if line.startswith('@'):
        assert line == '@object-format=sha1', 'unexpected bundle capability'
    elif line.startswith('-'):
        sha = line[1:].split(' ', 1)[0]
        assert re.fullmatch('[0-9a-f]{40}', sha)
        prerequisites.append(sha)
    else:
        heads.append(line)
assert prerequisites == [base], 'bundle prerequisite mismatch'
assert heads == [cp6+' '+target], 'unexpected or additional bundle head'
with open(output, 'xb') as f:
    f.write(data)
proof = {'schema_version': 1, 'status': 'passed', 'checked_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'), 'source_input_commit': commit, 'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(), 'readme_sha256': m['readme_sha256'], 'bundle_bytes': len(data), 'bundle_sha256': hashlib.sha256(data).hexdigest(), 'parts': parts, 'part_count': len(parts), 'reassembly_method': 'original binary bytes in manifest order', 'bundle_prerequisites': prerequisites, 'bundle_heads': heads}
with open(output+'.verification.json','x',encoding='utf-8') as f:
    json.dump(proof,f,ensure_ascii=False,indent=2); f.write('\n')
print('Verified fixed manifest, README, every ordered binary part, assembled bundle bytes/hash, head, and prerequisite.')
PYINPUT


readonly CHECKED_SOURCE='a1303b6b6c38692b4f57da5cfb342289c6dc17e5'
tools_dir="$import_tmp/tools"
reports="$import_tmp/reports"
restored="$import_tmp/restored"
independent="$import_tmp/independent-remote-clone"
publish_repo="$import_tmp/proof-publication.git"
mkdir "$tools_dir" "$reports"
cp "$bundle_path.verification.json" "$reports/package-input-verification.json"

# Original validation helpers, pinned by bytes, run outside every canonical tree.
python3 - "$input_repo" "$INPUT" "$tools_dir" <<'PYTOOLS'
from pathlib import Path
import hashlib,subprocess,sys
repo,commit,out=sys.argv[1:]
expected={'make_local_integrity_cp6.py':'6f76daeebf043832cdf4ef6ca9b53e6118c40a39c6cb38f7301395c1ea6c213d',
          'verify_remote_cp6.py':'509f33cc28fb9cee5f33f1f22722d2d83d6b24e19229e3a16f1a357492812962'}
for name,wanted in expected.items():
    data=subprocess.check_output(['git','--git-dir='+repo,'cat-file','blob',commit+':temp/validation/cp6-sync-tools/'+name])
    assert hashlib.sha256(data).hexdigest()==wanted, 'validation helper changed'
    (Path(out)/name).write_bytes(data)
PYTOOLS

# Restore the same pinned bundle using only the true remote prerequisite.
git -c init.defaultBranch=restore-init init --quiet "$restored"
git -C "$restored" remote add origin "$REMOTE"
git -C "$restored" config core.autocrlf false
git -C "$restored" config core.eol lf
git -C "$restored" fetch --quiet --no-tags origin "$BASE:refs/heads/cp6-prerequisite"
[[ "$(git -C "$restored" rev-parse refs/heads/cp6-prerequisite)" == "$BASE" ]]
[[ ! -s "$restored/.git/shallow" && ! -s "$restored/.git/objects/info/alternates" ]]
git -C "$restored" bundle verify "$bundle_path"
git -C "$restored" fetch --quiet --no-tags "$bundle_path" "$TARGET:$TARGET"
git -C "$restored" checkout --quiet research/p3-p6-cp6
[[ "$(git -C "$restored" rev-parse HEAD)" == "$CP6" ]]
[[ "$(git -C "$restored" rev-parse 'HEAD^{tree}')" == "$TREE" ]]
[[ "$(git -C "$restored" show -s --format=%P HEAD)" == "$BASE" ]]
python3 -B "$tools_dir/make_local_integrity_cp6.py" --repo "$restored" \
  --expected-head "$CP6" --expected-tree "$TREE" --expected-parent "$BASE" \
  --out "$reports/local-integrity-cp6.json"
inventory_hash="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$reports/local-integrity-cp6.json")"

# Truly separate public HTTPS clone: no objects borrowed from the bundle restore.
python3 -B "$tools_dir/verify_remote_cp6.py" \
  --expected-head "$CP6" --expected-tree "$TREE" --expected-parent "$BASE" \
  --manifest "$reports/local-integrity-cp6.json" --manifest-sha "$inventory_hash" \
  --clone-dir "$independent" --out "$reports/remote-verification-cp6.json" --clone-timeout 900

# Capture all actual remote heads and recheck every restored worktree byte.
git -C "$restored" fetch --quiet --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
python3 - "$restored" "$reports" "$CP6" "$TREE" "$BASE" "$MAIN" "$GITHUB_SHA" <<'PYFINAL'
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,stat,subprocess,sys
repo,out,head,tree,parent,main,source=sys.argv[1:]; root=Path(repo); reports=Path(out)
def git(*args): return subprocess.check_output(['git','-C',repo,*args])
def text(*args): return git(*args).decode().strip()
local=json.loads((reports/'local-integrity-cp6.json').read_text())
remote=json.loads((reports/'remote-verification-cp6.json').read_text())
assert local['status']==remote['status']=='passed' and not local['failures'] and not remote['failures']
assert local['head_commit']==remote['head_commit']==head and local['head_tree']==remote['head_tree']==tree
assert local['expected_git_parent']==remote['expected_git_parent']==parent
def heads():
    result={}
    for line in text('ls-remote','--heads','origin').splitlines():
        sha,ref=line.split();result[ref]=sha
    return result
before=heads()
assert before['refs/heads/research/p3-p6-cp6']==head
assert before['refs/heads/main']==main
assert before['refs/heads/sync/cp6-checkpoint-import']==source
assert text('rev-parse','HEAD')==head and text('rev-parse','HEAD^{tree}')==tree
assert text('show','-s','--format=%P','HEAD')==parent
assert git('status','--porcelain=v1','--untracked-files=all','--ignored=matching')==b''
assert git('diff','--exit-code')==b'' and git('diff','--cached','--exit-code')==b''
expected={x['path']:x for x in local['verified_files']}
actual={}
for path in root.rglob('*'):
    rel=path.relative_to(root)
    if '.git' in rel.parts: continue
    assert not path.is_symlink()
    if path.is_file():
        name=rel.as_posix();data=path.read_bytes();mode='100755' if path.stat().st_mode&stat.S_IXUSR else '100644'
        item=expected[name]
        assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
        actual[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'mode':mode}
assert set(actual)==set(expected) and len(actual)==1256
index={}
for line in git('ls-files','--stage','-z').split(b'\0'):
    if line:
        meta,name=line.split(b'\t',1);mode,sha,stage=meta.decode().split()
        assert stage=='0';index[name.decode()]={'mode':mode,'sha':sha}
assert set(index)==set(expected)
tree_entries={x['path']:x for x in local['head_snapshot']['tree_entries']}
for name,item in index.items():
    assert item['sha']==tree_entries[name]['sha'] and item['mode']==tree_entries[name]['mode']==actual[name]['mode']
local_heads={}
for line in text('for-each-ref','--format=%(objectname) %(refname)','refs/heads/').splitlines():
    sha,ref=line.split();local_heads[ref]=sha
missing=text('rev-list','--branches','--not',*sorted(set(before.values())))
assert not missing, 'local branch history absent from all actual remote heads'
assert heads()==before
proof={'schema_version':1,'status':'passed','checked_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
       'basis':'New independent bundle-restored GitHub Actions worktree. The earlier unavailable container disk was not re-scanned.',
       'canonical_commit':head,'canonical_tree':tree,'git_parent':parent,'verified_file_count':len(actual),
       'verified_file_bytes':sum(x['bytes'] for x in actual.values()),'untracked_or_ignored_files':[],
       'worktree_clean':True,'index_matches_head':True,'worktree_bytes_match_inventory':True,
       'remote_heads_before':before,'remote_heads_after':before,'local_heads':local_heads,
       'local_branch_commits_missing_from_remote_heads':[],'canonical_and_main_unchanged':True}
(reports/'recovered-worktree-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
manual={'schema_version':1,'status':'passed','checked_at_utc':proof['checked_at_utc'],
        'execution_platform':'GitHub Actions ubuntu-24.04, Python and Git','powershell_executed':False,
        'basis':'Fresh restoration of the same previously uploaded pinned binary bundle; this is a new report, not the inaccessible earlier private report.',
        'canonical_commit':head,'canonical_tree':tree,'git_parent':parent,
        'trusted_inventory_sha256':hashlib.sha256((reports/'local-integrity-cp6.json').read_bytes()).hexdigest(),
        'bundle':json.loads((reports/'package-input-verification.json').read_text()),
        'file_count':len(actual),'file_bytes':proof['verified_file_bytes'],
        'artifact_hashes':local['checkpoint']['artifact_hash_count'],
        'partition_datasets':sum(x['dataset_count'] for x in local['partition_integrity']),
        'partition_parts':sum(x['part_count'] for x in local['partition_integrity']),
        'object_integrity':local['object_integrity'],'new_scientific_work_performed':False}
(reports/'manual-restore-verification.json').write_text(json.dumps(manual,indent=2)+'\n')
print(json.dumps({'recovered_worktree':'passed','files':len(actual),'bytes':proof['verified_file_bytes'],'missing_local_branch_commits':0}))
PYFINAL

# Publication has one permitted target and only the explicitly named proof paths.
git init --bare --quiet "$publish_repo"
git --git-dir="$publish_repo" fetch --quiet --no-tags --depth=1 "$REMOTE" "$GITHUB_SHA"
[[ "$(git --git-dir="$publish_repo" rev-parse FETCH_HEAD)" == "$GITHUB_SHA" ]]
python3 - "$publish_repo" "$GITHUB_SHA" "$reports" "$GITHUB_RUN_ID" <<'PYRECEIPT'
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,sys
repo,source,out,runid=sys.argv[1:]; reports=Path(out)
for name in ['import-actions-run.json','import-actions-jobs.json','import-actions-job.log','runtime-delivery-context.json']:
    data=subprocess.check_output(['git','--git-dir='+repo,'cat-file','blob',source+':temp/sync/CP-0006/'+name])
    (reports/name).write_bytes(data)
local=json.loads((reports/'local-integrity-cp6.json').read_text())
remote=json.loads((reports/'remote-verification-cp6.json').read_text())
worktree=json.loads((reports/'recovered-worktree-verification.json').read_text())
package=json.loads((reports/'package-input-verification.json').read_text())
assert local['status']==remote['status']==worktree['status']==package['status']=='passed'
assert len(local['verified_files'])==1256 and local['head_snapshot']['file_bytes']==881966656
assert local['checkpoint']['artifact_hash_count']==1255
assert local['checkpoint']['checkpoint_file_sha256']=='43c11e7465404e956274fdaadef74f7bd0d27177111de5200f127f36c8c7d47d'
assert sum(x['dataset_count'] for x in local['partition_integrity'])==7
assert sum(x['part_count'] for x in local['partition_integrity'])==120
evidence=[]
for path in sorted(reports.iterdir()):
    assert path.is_file() and path.name!='verification.json'
    data=path.read_bytes();evidence.append({'path':path.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
proof={'schema_version':1,'status':'passed','verified_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
'repository':'ncut-d1z/Insect-Inspired','checkpoint_id':'CP-0006','scope_id':'SCOPE-0001',
'canonical_commit':local['head_commit'],'canonical_tree':local['head_tree'],'git_parent':local['expected_git_parent'],
'parent_checkpoint_id':'CP-0005','checkpoint_sha256':local['checkpoint']['checkpoint_file_sha256'],
'canonical_file_count':1256,'canonical_file_bytes':881966656,'artifact_hash_count':1255,
'partition_dataset_count':7,'partition_part_count':120,'remote_check_count':len(remote['checks']),
'remote_failures':remote['failures'],'remote_clone_arguments':remote['clone_arguments'],
'local_objects_borrowed':remote['local_objects_borrowed'],
'trusted_inventory_sha256':hashlib.sha256((reports/'local-integrity-cp6.json').read_bytes()).hexdigest(),
'trusted_inventory_basis':'Fresh bundle-restored tree pinned by the pre-outage commit/tree, exact bundle and checkpoint hashes; not a recovery of the unavailable private manifest.',
'original_input_commit':'1b46308cab46fe7611c6af465cb338c65549275b',
'verification_workflow_input_commit':source,'verification_run_id':int(runid),
'verification_run_url':'https://github.com/ncut-d1z/Insect-Inspired/actions/runs/'+runid,
'import_run_id':45911635168,'import_run_url':'https://github.com/ncut-d1z/Insect-Inspired/actions/runs/45911635168',
'bundle_bytes':package['bundle_bytes'],'bundle_sha256':package['bundle_sha256'],'bundle_part_count':package['part_count'],
'main_observed':'bb7726c2ef334df0d7069165156b1cbc2c4e2fd8','main_modified':False,
'original_container_currently_accessible':False,'original_container_rescanned':False,
'last_accessible_canonical_worktree':'clean; exact CP6 commit and tree recorded before import',
'recovered_worktree_checked':True,'recovered_worktree_missing_remote_branch_commits':[],
'powershell_executed':False,'scientific_research_added_during_delivery':False,
'phase_status':{'P3':'iterated_partial_checkpointed','P4':'iterated_partial_checkpointed','P5':'iterated_partial_checkpointed','P6':'iterated_partial_checkpointed'},
'research_closure_established':False,'run4_budget_exhausted':True,
'proof_publication_acceptance':'This receipt is finalized before its enclosing Git commit. Accept publication only after this run succeeds and its full remote proof readback passes.',
'evidence_files':evidence}
(reports/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'passed','remote_check_count':proof['remote_check_count'],'evidence_files':len(evidence),
                 'verification_sha256':hashlib.sha256((reports/'verification.json').read_bytes()).hexdigest()}))
PYRECEIPT

export GIT_INDEX_FILE="$import_tmp/proof-index"
git --git-dir="$publish_repo" read-tree "$GITHUB_SHA"
python3 - "$publish_repo" "$reports" <<'PYSTAGE'
from pathlib import Path
import subprocess,sys
repo,out=sys.argv[1:]; paths=sorted(Path(out).iterdir())
allowed={'local-integrity-cp6.json','remote-verification-cp6.json','package-input-verification.json',
'manual-restore-verification.json','recovered-worktree-verification.json','import-actions-run.json',
'import-actions-jobs.json','import-actions-job.log','runtime-delivery-context.json','verification.json'}
assert {p.name for p in paths}==allowed
for path in paths:
    assert path.is_file()
    oid=subprocess.check_output(['git','--git-dir='+repo,'hash-object','-w',str(path)]).decode().strip()
    subprocess.run(['git','--git-dir='+repo,'update-index','--add','--cacheinfo','100644',oid,'temp/sync/CP-0006/'+path.name],check=True)
PYSTAGE
proof_tree="$(git --git-dir="$publish_repo" write-tree)"
export GIT_AUTHOR_NAME='github-actions[bot]' GIT_COMMITTER_NAME='github-actions[bot]'
export GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'
export GIT_COMMITTER_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'
proof_commit="$(printf '%s\n' 'Record complete CP6 restored inventory and independent remote verification' | git --git-dir="$publish_repo" commit-tree "$proof_tree" -p "$GITHUB_SHA")"
[[ "$(git --git-dir="$publish_repo" show -s --format=%P "$proof_commit")" == "$GITHUB_SHA" ]]

guard="$import_tmp/proof-push-guard"
mkdir "$guard"
export CP6_PROOF_COMMIT="$proof_commit" CP6_PROOF_BASE="$GITHUB_SHA" CP6_PROOF_TARGET="$SYNC"
cat > "$guard/pre-push" <<'PROOFGUARD'
#!/usr/bin/env bash
set -euo pipefail
count=0
while read -r local_ref local_sha remote_ref remote_sha; do
  count=$((count+1))
  [[ "$count" == 1 && "$local_sha" == "$CP6_PROOF_COMMIT" ]]
  [[ "$remote_ref" == "$CP6_PROOF_TARGET" && "$remote_sha" == "$CP6_PROOF_BASE" ]]
done
[[ "$count" == 1 ]]
PROOFGUARD
chmod 700 "$guard/pre-push"
[[ "$(git --git-dir="$publish_repo" ls-remote --heads "$REMOTE" "$SYNC")" == "$GITHUB_SHA"$'\t'"$SYNC" ]]
[[ "$(git --git-dir="$publish_repo" ls-remote --heads "$REMOTE" "$TARGET")" == "$CP6"$'\t'"$TARGET" ]]
[[ "$(git --git-dir="$publish_repo" ls-remote --heads "$REMOTE" refs/heads/main)" == "$MAIN"$'\t'refs/heads/main ]]
git --git-dir="$publish_repo" -c core.hooksPath="$guard" push --porcelain "$REMOTE" "$proof_commit:$SYNC"
unset GIT_INDEX_FILE GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL

# Full proof bytes read from a different Git repository after publication.
proof_readback="$import_tmp/proof-readback.git"
git init --bare --quiet "$proof_readback"
git --git-dir="$proof_readback" fetch --quiet --no-tags --depth=1 "$REMOTE" "$SYNC"
[[ "$(git --git-dir="$proof_readback" rev-parse FETCH_HEAD)" == "$proof_commit" ]]
python3 - "$proof_readback" "$proof_commit" "$reports" <<'PYPROOFREAD'
from pathlib import Path
import hashlib,json,subprocess,sys
repo,commit,out=sys.argv[1:]; reports=Path(out)
for path in sorted(reports.iterdir()):
    raw=subprocess.check_output(['git','--git-dir='+repo,'cat-file','blob',commit+':temp/sync/CP-0006/'+path.name])
    assert raw==path.read_bytes(), 'published proof bytes changed'
v=json.loads((reports/'verification.json').read_text())
print(json.dumps({'proof_publication_status':'passed','proof_commit':commit,'files':len(list(reports.iterdir())),
                  'verification_sha256':hashlib.sha256((reports/'verification.json').read_bytes()).hexdigest(),
                  'remote_check_count':v['remote_check_count'],'canonical_commit':v['canonical_commit']},sort_keys=True))
PYPROOFREAD
[[ "$(git --git-dir="$proof_readback" ls-remote --heads "$REMOTE" "$SYNC")" == "$proof_commit"$'\t'"$SYNC" ]]
[[ "$(git --git-dir="$proof_readback" ls-remote --heads "$REMOTE" "$TARGET")" == "$CP6"$'\t'"$TARGET" ]]
[[ "$(git --git-dir="$proof_readback" ls-remote --heads "$REMOTE" refs/heads/main)" == "$MAIN"$'\t'refs/heads/main ]]
printf '%s\n' '## CP6 independent delivery verification passed' \
  "Research commit: $CP6" "Proof commit: $proof_commit" \
  'All 1,256 files, 1,255 artifact hashes and 7 logical datasets verified.' \
  'The inaccessible earlier container was not re-scanned; this used a fresh fixed-bundle restoration and independent HTTPS clone.' \
  'Proof branch only was updated; main and research were unchanged.' >> "$GITHUB_STEP_SUMMARY"
