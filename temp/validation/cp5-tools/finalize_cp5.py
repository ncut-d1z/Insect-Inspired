"""Promote the audited, unpublished CP5 candidate and freeze every artifact hash."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, shutil
from jsonschema import Draft202012Validator, FormatChecker

ROOT=Path('/workspace/scratch/2e518600ca4c');REPO=ROOT/'insect-project';TEMP=REPO/'temp';QA=ROOT/'cp5_qa'
CP=TEMP/'snapshots/checkpoints/CP-0005.json'
NOW=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
audit=json.loads((QA/'data-audit-final.json').read_text())
det=json.loads((QA/'cp5-determinism.json').read_text())
ui=json.loads((QA/'ui-audit-final.json').read_text())
receipt=json.loads((QA/'qa-final-receipt.json').read_text())
assert audit['status']=='passed' and audit['error_count']==0 and audit['warning_count']==16 and not audit['changed_inputs']
for key,value in [('explicit_manual_reassessments',1),('cp4_protected_assessments_compared',30),('cp4_manual_rejections_preserved',9),('cp4_manual_counterevidence_preserved',22)]:
    assert audit['counters'][key]==value,(key,audit['counters'].get(key))
assert det['status']=='passed' and not det['changed_inputs'] and len(det['checks'])==7
for r in det['checks']:assert r['byte_equal'] and sha(REPO/r['artifact'])==r['canonical_sha256'],r['artifact']
assert ui['passed'] and len(ui['checks'])==10 and all(ui['checks'].values()) and not ui['errors'] and not ui['input_changed']
assert sha(REPO/'ref.html')==ui['html_sha256']==ui['html_sha256_after']
assert json.loads((TEMP/'validation/cp5-delta-preservation.json').read_text())['existing_records_lost']==0
for name,info in receipt['raw_evidence_files'].items():
    assert sha(QA/name)==info['sha256'] and (QA/name).stat().st_size==info['bytes'],name
dest=TEMP/'validation/cp5-qa';dest.mkdir(exist_ok=True)
for name in list(receipt['raw_evidence_files'])+['qa-final-receipt.json']:shutil.copyfile(QA/name,dest/name)
for source,target in [('data-audit-final.json','cp5-data-audit.json'),('cp5-determinism.json','cp5-determinism.json'),('ui-audit-final.json','cp5-ui-validation.json')]:
    shutil.copyfile(QA/source,TEMP/'validation'/target)

progress=TEMP/'progress.md';text=progress.read_text()
text=text.replace('# 当前执行进度：CP-0005 候选','# 当前执行进度：CP-0005')
text=text.replace('**SCOPE-0001 / RUN-0003 / CP-0005：invalid 候选，数据已集成，完整审计、七产物确定性、十项 UI 及最终同步待完成。** 最后有效检查点为 CP-0004；CP-0003 invalid 历史保留。',
    '**SCOPE-0001 / RUN-0003 / CP-0005：有效数据检查点。** 完整审计 0 错误、16 项既有辅助 Schema 警告；七产物确定性与十项 UI 全部通过。父检查点为 CP-0004，CP-0003 invalid 历史保留。最终 GitHub 同步以提交后的独立回读凭据为准。')
text=text.replace('[CP5 invalid候选]','[CP5有效检查点]').replace('[最后有效CP4]','[父检查点CP4]')
text=text.replace('不能将候选生成当作有效快照或研究完成。','有效数据检查点不代表研究闭包或所有阶段完成。')
text+='\n验收完成时间（UTC）：'+NOW+'。数据审计、确定性及 UI 原文证据见 [验收凭据](validation/cp5-qa/qa-final-receipt.json)；既有记录保留对账见 [增量保留检查](validation/cp5-delta-preservation.json)。后置同步凭据：[verification.json](https://github.com/ncut-d1z/Insect-Inspired/blob/sync/cp5-checkpoint-import/temp/sync/CP-0005/verification.json)。\n'
progress.write_text(text)
report=TEMP/'reports/P3-P6-CP0005.md';text=report.read_text()
text=text.replace('# P3–P6 阶段进展：CP-0005 候选','# P3–P6 阶段进展：CP-0005')
text=text.replace('**SCOPE-0001 / RUN-0003 / CP-0005：invalid 候选，完整数据审计、确定性、UI 和最终同步待完成。** 最后有效检查点及本候选父检查点为 CP-0004；',
    '**SCOPE-0001 / RUN-0003 / CP-0005：valid 数据检查点；完整数据审计、七产物确定性及十项 UI 全部通过。** 父检查点为 CP-0004；')
text=text.replace('当前 CP-0005 候选','当前 CP-0005').replace('## 5. 导出与待完成验收','## 5. 导出与验收')
text=text.replace('完整交叉对账仍待完整审计。','完整交叉对账已通过审计。')
text=text.replace('完整审计将再次检查24小时升级规则。','完整审计已检查24小时升级规则，未发现逾期未升级的字段。')
text=text.replace('ref.bib、ref.html 与五视图必须七项确定性重生成字节一致；HTML 十项交互必须通过。新增/修改实体 schema 预检查为0错误，不能代替整库审计。候选 artifact_hashes 暂为空；不得在最终报告和验收证据落盘前标记 valid。',
    'ref.bib、ref.html 与五视图共七项独立重生成，全部字节一致，changed_inputs=[]。HTML 十项交互全部通过，JavaScript 错误 0，UI 检查前后输入哈希相同。完整数据审计 3,666,017 条断言、358,579 条 Schema 记录，0 错误、16 条既有 unregistered_auxiliary_schema 警告；辅助数据仍接受通用检查，不能把这些警告表述为零警告。CP4 的 9 条不足结论和 22 条反证保留，S19 历史独立补证例外仍恰为 1；另外按独立 CP4 克隆逐记录比较 19 个逻辑数据集，原始记录丢失数 0。最终 artifact_hashes 在这些报告原字节归档后统一计算，排除检查点自身与 Git 内部文件。')
text=text.replace('[候选检查点]','[有效检查点]').replace('[最后有效 CP-0004]','[父检查点 CP-0004]')
text+='\n验收原文：[完整数据审计](../validation/cp5-data-audit.json)、[七产物确定性](../validation/cp5-determinism.json)、[十项UI](../validation/cp5-ui-validation.json)、[冻结原始QA证据与截图](../validation/cp5-qa/qa-final-receipt.json)、[增量保留检查](../validation/cp5-delta-preservation.json)。验收完成时间（UTC）：'+NOW+'。\n\n提交后的远端同步证明单独保存在 [verification.json](https://github.com/ncut-d1z/Insect-Inspired/blob/sync/cp5-checkpoint-import/temp/sync/CP-0005/verification.json)，用于避免让提交后的证明改变本检查点自身。该证明必须含实际提交、文件数及独立回读结果；上传开始不能替代该证明。\n'
report.write_text(text)
readme=REPO/'README.md';text=readme.read_text()
old='[CP-0005](temp/snapshots/checkpoints/CP-0005.json) 当前为 invalid 候选，待完整验收与最终同步；最后有效快照及 CP-0005 的父检查点为 [CP-0004](temp/snapshots/checkpoints/CP-0004.json)。'
new='[CP-0005](temp/snapshots/checkpoints/CP-0005.json) 已通过完整数据审计、七产物确定性与十项交互验收；提交后的 GitHub 同步见阶段报告所链接的独立回读凭据。CP-0005 的有效父检查点为 [CP-0004](temp/snapshots/checkpoints/CP-0004.json)。'
assert old in text;readme.write_text(text.replace(old,new))
with (TEMP/'change-log.md').open('a') as f:
    f.write('\n## '+NOW+' — CP-0005 验收冻结\n\n完整审计 0 错误、16 项既有辅助 Schema 警告；七产物独立重生成字节一致，十项 UI 通过。既有 68 条科学记录和所有原始引文保留。本步骤仅归档验收证据、更新交付状态及冻结检查点哈希，不增加科研查询或修改规范科学数据。最终同步由提交后的独立远端回读证明，研究闭包仍开放。\n')
run_path=TEMP/'runs/RUN-0003.json';run=json.loads(run_path.read_text())
run.update(status='checkpointed_open',checkpoint_status='valid',checkpoint_validation_state='passed',
    checkpoint_completed_at_utc=NOW,budget_exhausted=False,
    checkpoint_wall_clock_hours=round((datetime.fromisoformat(NOW.replace('Z','+00:00'))-datetime.fromisoformat(run['started_at_utc'].replace('Z','+00:00'))).total_seconds()/3600,4),
    pause_reason='Reviewed batches consolidated into an audited checkpoint. Publication/readback must finish before the next research batch; research closure and budget exhaustion are not asserted.',
    sync_state='Snapshot-creation timestamp: source receipts and review decisions are already remotely verified; final canonical commit/readback is a later event recorded in the external verification receipt. This historical state does not imply a later sync failure.',
    post_commit_verification_url='https://github.com/ncut-d1z/Insect-Inspired/blob/sync/cp5-checkpoint-import/temp/sync/CP-0005/verification.json')
dump(run_path,run)

cp=json.loads(CP.read_text());assert cp['status']=='invalid' and cp['parent_checkpoint_id']=='CP-0004'
for p,digest in cp['validation_results']['frozen_baseline_sha256'].items():assert sha(REPO/p)==digest,p
for phase in ['P3','P4','P5','P6']:cp['coverage']['phase_status'][phase]='iterated_partial_checkpointed'
dump(TEMP/'validation/cp5-coverage.json',cp['coverage'])
validation=cp['validation_results']
validation.update(state='passed',data_audit='passed',determinism='passed',ui_validation='passed',final_artifact_hashes='verified',
    final_remote_verification='post_commit_external_receipt_required',
    post_commit_verification_url=run['post_commit_verification_url'],validation_completed_at_utc=NOW,
    data_audit_errors=0,data_audit_warnings=16,seven_exports_byte_identical=True,ten_ui_checks_passed=True,
    existing_records_lost=0,cp4_scientific_records_unchanged=68,manual_rejections_preserved=9,counter_evidence_baseline_preserved=22)
for name in ['cp5-export-validation.json','cp5-data-audit.json','cp5-determinism.json','cp5-ui-validation.json','cp5-delta-preservation.json']:
    validation[name]=dict(report='temp/validation/'+name,sha256=sha(TEMP/'validation'/name))
cp['failure_reasons']=[r for r in cp['failure_reasons'] if not r.startswith('CP5 candidate is invalid') and not r.startswith('Raw source receipts/review decisions')]
cp['failure_reasons'].append('At snapshot creation source receipts/review decisions were synchronized. Final publication evidence is recorded separately after the commit, so it cannot be included recursively in this snapshot hash set.')
cp['status']='valid'
hashes={str(p.relative_to(REPO)):sha(p) for p in sorted(REPO.rglob('*')) if p.is_file() and p!=CP and '.git' not in p.relative_to(REPO).parts}
cp['artifact_hashes']=hashes
schema=json.loads((TEMP/'schema.json').read_text())
errors=list(Draft202012Validator({'$ref':'#/$defs/checkpoint','$defs':schema['$defs']},format_checker=FormatChecker()).iter_errors(cp))
assert not errors,[(list(e.path),e.message) for e in errors[:10]]
CP.write_text(json.dumps(cp,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
assert all(sha(REPO/p)==digest for p,digest in hashes.items())
result={'status':'valid','checkpoint_id':'CP-0005','artifact_hashes':len(hashes),'file_count':len(hashes)+1,
        'checkpoint_bytes':CP.stat().st_size,'checkpoint_sha256':sha(CP),'validation_completed_at_utc':NOW}
dump(ROOT/'cp5_work/final-checkpoint-result.json',result)
print(json.dumps(result))
