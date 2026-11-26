#!/usr/bin/env python3
"""Generate CP5 metrics, progress and an INVALID candidate from integrated data.

No research, imports, exports or valid-checkpoint promotion. The six canonical
write targets below are the complete authorized output surface of this script.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta
import csv
import hashlib
import io
import json
import re
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path('/workspace/scratch/2e518600ca4c')
REPO = ROOT / 'insect-project'
TEMP = REPO / 'temp'
PRIVATE = Path(__file__).resolve().parent
sys.path.insert(0, '/workspace/scratch/9d487ee78414/p3p6_work')
from storage import read_logical

CP = 'CP-0005'
RUN = 'RUN-0003'
PARENT = 'CP-0004'
BASE_COMMIT = 'bb7726c2ef334df0d7069165156b1cbc2c4e2fd8'
DEST = TEMP / 'snapshots/checkpoints/CP-0005.json'
TERMINAL = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
DIMENSIONS = ['metadata', 'fulltext', 'abstract', 'references', 'citations',
              'authors', 'affiliations_projects', 'assessment']
ALLOWED = {DEST, TEMP / 'progress.md', TEMP / 'reports/P3-P6-CP0005.md',
           TEMP / 'change-log.md', REPO / 'README.md', TEMP / 'runs/RUN-0003.json'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def git_bytes(path):
    return subprocess.check_output(['git', '-C', str(REPO), 'show', BASE_COMMIT + ':' + path])


def baseline_logical(name, manifest):
    entry = manifest.get('datasets', {}).get(name)
    parts = entry['parts'] if entry else [{'path': name}]
    chunks = []
    for part in parts:
        raw = git_bytes('temp/' + part['path'])
        if entry:
            assert hashlib.sha256(raw).hexdigest() == part['sha256']
        chunks.append(raw)
    raw = b''.join(chunks)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if entry:
        assert hashlib.sha256(raw).hexdigest() == entry['logical_sha256']
        assert len(rows) == entry['logical_records']
    return rows


def write_canonical(path, text):
    assert path in ALLOWED, path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def json_text(value, compact=False):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      **({'separators': (',', ':')} if compact else {'indent': 2})) + '\n'


def objects(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        elif isinstance(item, list):
            stack.extend(v for v in item if isinstance(v, (dict, list)))


def main():
    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace('+00:00', 'Z')
    if DEST.exists():
        assert json.loads(DEST.read_text())['status'] == 'invalid', 'Never downgrade a valid checkpoint'
        created = json.loads(DEST.read_text())['created_at_utc']
    else:
        created = stamp
    frozen = ['temp/snapshots/checkpoints/CP-0003.json',
              'temp/snapshots/checkpoints/CP-0004.json',
              'temp/snapshots/scope.json', 'temp/seed-manifest.jsonl']
    frozen_hashes = {}
    for name in frozen:
        digest = hashlib.sha256(git_bytes(name)).hexdigest()
        assert sha(REPO / name) == digest, 'Frozen CP4 baseline changed: ' + name
        frozen_hashes[name] = digest
    parent = json.loads((TEMP / 'snapshots/checkpoints/CP-0004.json').read_text())
    assert parent['status'] == 'valid'
    assert json.loads((TEMP / 'snapshots/checkpoints/CP-0003.json').read_text())['status'] == 'invalid'
    scope = json.loads((TEMP / 'snapshots/scope.json').read_text())
    run = json.loads((TEMP / 'runs/RUN-0003.json').read_text())
    integration = json.loads((TEMP / 'reports/RUN-0003-integration.json').read_text())
    longden = json.loads((TEMP / 'reports/RUN-0003-Longden2010-latency-review.json').read_text())
    assert run['start_checkpoint_id'] == PARENT and run['scope_id'] == scope['scope_id'] == 'SCOPE-0001'
    manifest = json.loads((TEMP / 'partitions/manifest.json').read_text())
    inputs = {TEMP / 'partitions/manifest.json'}
    for p in TEMP.glob('*.jsonl'):
        inputs.add(p)
        for part in manifest['datasets'].get(p.name, {}).get('parts', []):
            inputs.add(TEMP / part['path'])
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in inputs}
    names = ['works', 'versions', 'uploads', 'authors', 'organizations', 'projects',
             'reference-occurrences', 'citation-edges', 'assessments', 'tasks', 'queries',
             'manual-reviews', 'source-list-coverage', 'source-observations', 'work-merge-events',
             'seed-manifest', 'fulltext-file-audit', 'new-fulltext-reference-audit', 'cascade-events']
    data = {name: read_logical(name + '.jsonl', base=TEMP) for name in names}
    works = data['works']
    work_by_id = {w['work_id']: w for w in works}
    latest = {}
    for t in data['tasks']:
        if t['task_id'] not in latest or t['event_sequence'] > latest[t['task_id']]['event_sequence']:
            latest[t['task_id']] = t
    active = [a for a in data['assessments'] if a['assessment_status'] == 'active']
    eligible = [a for a in active if a['evidence_admission_status'] == 'eligible']
    insufficient = [a for a in active if a['evidence_admission_status'] == 'insufficient_evidence']
    topics = {f'L{i:02}': {a['work_id'] for a in eligible if a['limitation_id'] == f'L{i:02}'} for i in range(1, 10)}
    union = set().union(*topics.values())
    seeds = [s for s in data['seed-manifest'] if s['record_type'] == 'seed_mapping']
    seed_work_ids = {s['work_id'] for s in seeds}
    seed_author_ids = {a['person_id'] for wid in seed_work_ids for a in work_by_id[wid]['authors']}
    uploads = {u['upload_id']: u for u in data['uploads']}
    files = {f['sha256'] for v in data['versions'] for f in v['file_records']}
    baseline_manifest = json.loads(git_bytes('temp/partitions/manifest.json'))
    baseline_versions = baseline_logical('versions.jsonl', baseline_manifest)
    baseline_files = {f['sha256'] for v in baseline_versions for f in v['file_records']}
    baseline_assessments = baseline_logical('assessments.jsonl', baseline_manifest)
    before_assessments = {a['assessment_id']: a for a in baseline_assessments}
    current_assessments = {a['assessment_id']: a for a in data['assessments']}
    assert all(current_assessments.get(k) == a for k, a in before_assessments.items())
    reviewed_works = {a['work_id'] for a in active}
    baseline_reviewed_works = {a['work_id'] for a in baseline_assessments if a['assessment_status'] == 'active'}
    assert reviewed_works == baseline_reviewed_works
    assert len(reviewed_works) == parent['counts']['scientific_fulltext_works_reviewed'] == 37
    assert files == baseline_files, 'This batch must not add or replace fulltext files'
    cov = data['source-list-coverage']
    author_cov = [c for c in cov if c['entity_id'] in seed_author_ids and c['source_id'] == 'semantic_scholar']
    project_cov = next(c for c in cov if c['coverage_id'] == 'COV-T-CP4-project-3d-citers-epmc')
    initial_ids = run['first_batch']['pending_identity_ids']
    identity_tasks = [latest['T-CP4-CiterIdentity-MED-' + pmid] for pmid in initial_ids]
    pubmed_resolved = sum(t['task_state'] == 'verified_complete' and t['normalized_parameters'].get('identity_via_pubmed') is True for t in identity_tasks)
    epmc_core = project_cov['distinct_count'] - len(initial_ids)
    epmc_core += sum(t['normalized_parameters'].get('epmc_core_success') is True for t in identity_tasks)
    identity_pending = sum(t['task_state'] not in TERMINAL for t in identity_tasks)
    manual = [m for m in data['manual-reviews'] if m['run_id'] == RUN]
    queries = [q for q in data['queries'] if q['checkpoint_id'] == CP]
    query_ids = {q['query_id'] for q in queries}
    observations = [o for o in data['source-observations'] if o.get('query_id') in query_ids]
    assert len(observations) == len(query_ids)
    external = sum(o.get('external_request_performed') is True for o in observations)
    cache_reuses = sum(q.get('cache_hit') is True for q in queries)
    assert external == run['external_requests_used'] == integration['new_external_invocations']
    assert len(manual) == run['manual_review_items_used'] == integration['manual_review_activities']
    assert cache_reuses == run['cache_reuse_events'] == integration['cache_reuses']
    field_closed = {t['task_id'] for t in data['tasks'] if t['checkpoint_id'] == CP
                    and t['task_type'] == 'field_review' and t['task_state'] == 'verified_complete'}
    assert len(field_closed) == integration['unknown_field_tasks_closed']
    enriched = [e for e in integration['events'] if e['kind'] == 'bibliographic_identity_enrichment']
    resolved_events = [e for e in integration['events'] if e['kind'] == 'reference_identity_resolution']
    occurrence_by_id = {o['occurrence_id']: o for o in data['reference-occurrences']}
    edge_by_id = {e['edge_id']: e for e in data['citation-edges']}
    assert all(occurrence_by_id[e['occurrence_id']] == e['after']
               and edge_by_id[e['new_edge']['edge_id']] == e['new_edge'] for e in resolved_events)
    new_claims = [a for a in active if a['assessment_id'] not in before_assessments]
    assert len(new_claims) == 1 and new_claims[0] == longden['assessment']
    unknown_open = [t for t in latest.values() if t.get('unknown_since_utc') and t['task_state'] not in TERMINAL]
    overdue = [t for t in unknown_open if now >= datetime.fromisoformat(t['deadline_at_utc'].replace('Z', '+00:00'))]
    unknown_states = Counter()
    for path in sorted(TEMP.glob('*.jsonl')):
        rows = data.get(path.stem)
        if rows is None:
            rows = read_logical(path.name, base=TEMP)
        for row in rows:
            for obj in objects(row):
                if obj.get('status') in {'unknown', 'unknown_review_required'} and ('unknown_since_utc' in obj or 'review_task_id' in obj):
                    unknown_states[obj['status']] += 1
    def condition_value(value):
        return value.get('value') if isinstance(value, dict) else value
    absolute = [a for a in active if condition_value(a['claims_absolute_scale']) is True]
    counts = dict(seed_records=len(seeds), canonical_works=len(works), versions=len(data['versions']),
        retained_uploads=len(data['uploads']), distinct_seed_pdf_sha256=len({uploads[s['upload_id']]['sha256'] for s in seeds}),
        distinct_files=len(files), file_backed_versions=sum(bool(v['file_records']) for v in data['versions']),
        people_records=len(data['authors']), organizations=len(data['organizations']), projects=len(data['projects']),
        reference_occurrences=len(data['reference-occurrences']),
        resolved_occurrences=sum(bool(o['cited_work_id']) for o in data['reference-occurrences']),
        unresolved_occurrences=sum(not o['cited_work_id'] for o in data['reference-occurrences']),
        citation_edges=len(data['citation-edges']),
        context_reviewed_edges=sum(bool(e['context_locators']) and any(r != 'unknown' for r in e['citation_roles']) for e in data['citation-edges']),
        assessments=len(active), eligible_claims=len(eligible), insufficient_claims=len(insufficient),
        counter_evidence_claims=sum(a['counter_evidence'] for a in active),
        topic_work_union=len(union), u00_works=len(works) - len(union),
        task_events=len(data['tasks']), unique_tasks=len(latest),
        unresolved_tasks=sum(t['task_state'] not in TERMINAL for t in latest.values()),
        queries=len(data['queries']), exact_query_timestamps=sum(q.get('query_time_status', 'exact') == 'exact' for q in data['queries']),
        unavailable_exact_query_timestamps=sum(q.get('query_time_status') == 'unavailable_exact' for q in data['queries']),
        merged_work_pairs=len(data['work-merge-events']),
        seed_reference_occurrences=sum(o['citing_work_id'] in seed_work_ids and not o['occurrence_id'].startswith('R-CR-') for o in data['reference-occurrences']),
        iteration2_reviewed_reference_occurrences=len(data['new-fulltext-reference-audit']),
        scientific_fulltext_works_reviewed=len(reviewed_works), run3_new_scientific_fulltext_works=len(reviewed_works-baseline_reviewed_works),
        run3_new_fulltext_files=len(files-baseline_files),
        seed_s2_lists_reconciled=sum(c['entity_id'] in seed_work_ids and c['source_id'] == 'semantic_scholar' and c['total_reconciled'] for c in cov),
        seed_epmc_lists_reconciled=sum(c['entity_id'] in seed_work_ids and c['source_id'] == 'europepmc' and c['total_reconciled'] for c in cov),
        seed_authors=len(seed_author_ids), seed_author_lists_paginated=sum(c['pagination_complete'] for c in author_cov),
        seed_author_lists_reconciled=sum(c['total_reconciled'] for c in author_cov),
        manual_review_activities=len(data['manual-reviews']), run3_manual_review_activities=len(manual),
        fully_resolved_claims=sum(a['handling_level'] == 'fully_resolved' for a in active),
        run3_existing_works_enriched=len(enriched), run3_unknown_field_tasks_closed=len(field_closed),
        run3_external_requests=external, run3_cache_reuses=cache_reuses,
        run3_query_rows=len(queries), run3_reference_resolutions=len(resolved_events),
        unknown_fields=sum(unknown_states.values()), open_unknown_review_tasks=len(unknown_open),
        overdue_open_unknown_review_tasks=len(overdue), cascade_events=len(data['cascade-events']),
        rejected_upload_events=sum(r.get('record_type') == 'rejected_upload' for r in data['seed-manifest']))
    counts.update({key + '_works': len(value) for key, value in topics.items()})
    delta = {key: value-parent['counts'][key] for key, value in counts.items() if key in parent['counts']}
    assert counts['canonical_works'] == 5085 and delta['people_records'] == 20
    assert delta['resolved_occurrences'] == 7 and delta['citation_edges'] == 7
    assert delta['assessments'] == delta['eligible_claims'] == delta['counter_evidence_claims'] == 1
    assert delta['queries'] == 17 and delta['manual_review_activities'] == 13
    assert len(field_closed) == 25 and epmc_core == 28 and epmc_core+pubmed_resolved == 33 and identity_pending == 9
    coverage = {dim: {'denominator': len(works), 'states': dict(Counter(w['dimension_status'][dim] for w in works))} for dim in DIMENSIONS}
    coverage.update(
        phase_status={**{f'P{i}': 'completed' for i in range(3)}, **{f'P{i}': 'iterated_partial_candidate_pending_validation' for i in range(3, 7)}, 'P7': 'not_started_final_research_acceptance', 'P8': 'not_triggered'},
        closure={'established': False, 'reason': 'Unresolved references, original fulltext/supplements, identity, pagination count discrepancies, scientific conditions and citation contexts remain open.'},
        fulltext_meaning={'scientific_fulltext_works_reviewed': len(reviewed_works), 'run3_new_works': len(reviewed_works-baseline_reviewed_works), 'run3_new_files': len(files-baseline_files), 'scope': 'The established CP4 set of 37 claim-reviewed Works is unchanged; the cached Longden single-claim review does not increase it. S01 remains partial. This is not complete claim/supplement coverage.'},
        scientific_gates={'eligible': len(eligible), 'insufficient': len(insufficient), 'counter_evidence': counts['counter_evidence_claims'], 'fully_resolved': counts['fully_resolved_claims'], 'cp4_assessments_preserved': len(before_assessments), 'old_L07_unchanged': True, 'absolute_scale_claims': len(absolute), 'absolute_scale_eligible': sum(a['evidence_admission_status'] == 'eligible' for a in absolute), 'absolute_scale_insufficient': sum(a['evidence_admission_status'] == 'insufficient_evidence' for a in absolute), 'rejection_codes': dict(Counter(code for a in insufficient for code in a['rejection_codes']))},
        sources={'project_citation_list_returned': project_cov['distinct_count'], 'project_citation_list_total': project_cov['visible_total'], 'project_epmc_core_metadata': epmc_core, 'project_identity_cross_source': epmc_core+pubmed_resolved, 'project_identity_pending': identity_pending, 'seed_author_total': len(seed_author_ids), 'seed_author_lists_paginated': counts['seed_author_lists_paginated'], 'seed_author_lists_reconciled': counts['seed_author_lists_reconciled'], 'index_snapshot_historical': False},
        reconciliation={'K': len(works), 'T_union': len(union), 'U': len(works)-len(union), 'T_i': {k: len(v) for k, v in topics.items()}, 'multi_label_sum_is_not_independent_work_count': True},
        task_states=dict(Counter(t['task_state'] for t in latest.values())),
        queries=dict(Counter(q.get('query_time_status', 'exact') for q in data['queries'])),
        run3_accounting={'external_invocations': external, 'cache_reuses': cache_reuses, 'manual_reviews': len(manual), 'query_rows': len(queries), 'new_fulltext_works': 0, 'new_fulltext_files': 0},
        unknown_review={'field_states': dict(unknown_states), 'open_tasks': len(unknown_open), 'overdue_open_tasks': len(overdue), 'closed_field_tasks_this_run': len(field_closed), 'original_clocks_preserved': True},
        delta_from_cp4=delta,
        synchronization={'recorded_at_utc': stamp, 'source_receipts_previously_synced': integration['source_receipts_previously_synced'], 'canonical_snapshot_at_checkpoint_write': 'pending_final_export_audit_and_exact_remote_verification', 'research_gate': 'closed_until_final_sync_verified', 'subsequent_proof_location': 'Fixed synchronization workflow logs and a verification receipt on the separate transport branch; this historical pending observation does not imply a later sync failure.'})
    export_rows = []
    for name, key in [('citation_graph.json', 'nodes'), ('research_entities.json', 'relations'), ('research_paths.json', 'paths')]:
        path = TEMP / 'exports' / name
        value = json.loads(path.read_text())
        assert value['checkpoint_id'] == CP
        export_rows.append((name, sha(path), len(value[key]), key))
    for name in ['evidence_matrix.csv', 'research_implications.csv']:
        path = TEMP / 'exports' / name
        with path.open(newline='') as f:
            rows = list(csv.DictReader(f))
        assert all(r['checkpoint_id'] == CP for r in rows)
        export_rows.append((name, sha(path), len(rows), 'rows'))
    coverage['derived_views'] = {'state': 'generated_pending_complete_audit', 'views': [dict(path='temp/exports/'+n, sha256=h, records=nrows, record_basis=kind) for n,h,nrows,kind in export_rows]}
    failures = [
        'CP5 candidate is invalid until complete data audit, seven-artifact determinism, ten-check UI validation and final artifact hashes pass.',
        'Research closure is not established; all unresolved queues and original clocks remain retained.',
        f'Project citation list is {project_cov["distinct_count"]}/{project_cov["visible_total"]}; EPMC core identity remains {epmc_core}/{project_cov["visible_total"]}, cross-source identity {epmc_core+pubmed_resolved}/{project_cov["visible_total"]}, and {identity_pending} identities remain pending.',
        'Four seed-author lists reached their end but retain provider count discrepancies; no missing publication identities were invented.',
        'Seven new edges are deposited-reference source support only; their scientific citation contexts remain unknown.',
        'The new Longden L03 claim is confined to the reported H2/CDM onset-latency conditions and retains the peak-latency negative result; the original L07 insufficiency remains unchanged.',
        'Raw source receipts/review decisions were synchronized before integration; current canonical data/exports/checkpoint synchronization is still pending and further research is blocked.'
    ]
    validation = {'state': 'data_audit_pending', 'checkpoint_self_hash_excluded': True,
        'git_internal_files_excluded': True, 'frozen_parent_bytes_unchanged': True,
        'frozen_scope_and_seed_unchanged': True, 'frozen_baseline_sha256': frozen_hashes,
        'new_or_modified_record_schema_precheck': {'errors': sum(row['schema_errors'] for row in integration['schema_validation']), 'report': 'temp/reports/RUN-0003-integration.json'},
        'data_audit': 'pending', 'determinism': 'pending', 'ui_validation': 'pending',
        'final_artifact_hashes': 'pending', 'final_remote_verification': 'pending',
        'research_closure_established': False, 'cp4_scientific_records_unchanged': len(before_assessments)}
    cp = dict(checkpoint_id=CP, scope_id=scope['scope_id'], parent_checkpoint_id=PARENT,
        schema_version=parent['schema_version'], created_at_utc=created,
        task_cursor_state={tid: {f: t.get(f) for f in ['event_sequence', 'task_state', 'cursor', 'query_ids', 'attempt_count', 'error_code', 'failure_reason', 'retry_at', 'review_condition']} for tid,t in sorted(latest.items())},
        query_log_high_watermark=len(data['queries']), counts=counts, coverage=coverage,
        unresolved_tasks=sorted(tid for tid,t in latest.items() if t['task_state'] not in TERMINAL),
        failure_reasons=failures, artifact_hashes={}, validation_results=validation, status='invalid')
    registry = json.loads((TEMP / 'schema.json').read_text())
    validator = Draft202012Validator({'$ref': '#/$defs/checkpoint', '$defs': registry['$defs']}, format_checker=FormatChecker())
    errors = list(validator.iter_errors(cp))
    assert not errors, [(list(e.path), e.message) for e in errors[:10]]
    table_fields = [('canonical_works','规范 Work'),('versions','Version'),('people_records','署名身份记录'),('reference_occurrences','参考出现项'),('resolved_occurrences','已解析出现项'),('unresolved_occurrences','未解析出现项'),('citation_edges','唯一引用边'),('context_reviewed_edges','已核科学引用语境的边'),('assessments','活动主张'),('eligible_claims','合格主张'),('insufficient_claims','不足主张'),('counter_evidence_claims','含反证主张'),('topic_work_union','主题 Work 并集'),('u00_works','U00 Work'),('task_events','任务事件'),('unique_tasks','最新任务'),('unresolved_tasks','开放任务'),('queries','查询记录'),('manual_review_activities','人工复核活动')]
    table = '\n'.join(f'| {label} | {parent["counts"][key]:,} | {counts[key]:,} | {delta[key]:+,} |' for key,label in table_fields)
    dimtable = '\n'.join('| '+dim+' | '+str(len(works))+' | '+' | '.join(str(coverage[dim]['states'].get(s,0)) for s in ['verified_complete','partial','pending','restricted','not_applicable'])+' |' for dim in DIMENSIONS)
    topicline = '；'.join(f'{k}={len(v)}' for k,v in topics.items())
    viewtable = '\n'.join(f'| [{n}](../exports/{n}) | {nrows:,} {kind} | `{h}` |' for n,h,nrows,kind in export_rows)
    claim = new_claims[0]
    report = f'''# P3–P6 阶段进展：CP-0005 候选

## 1. 状态与范围

**SCOPE-0001 / RUN-0003 / CP-0005：invalid 候选，完整数据审计、确定性、UI 和最终同步待完成。** 最后有效检查点及本候选父检查点为 CP-0004；CP-0003 保持 invalid 历史，二者原字节未改。P3–P6 继续部分推进，研究闭包未成立，P7 最终研究验收尚未启动，P8 未触发。

统计时刻：{stamp}。文献截止仍为 {scope['cutoff_at_utc']}；种子、范围、来源政策和 unknown 原始时钟不变。原始回执和人工决定已在集成前同步并回读；本检查点写入时，最终 canonical 推送和回读尚未发生。后续同步证明保存在固定同步 workflow 日志和独立传输分支的 verification receipt；此处是历史时点记录，不能据此推断之后同步失败。冻结后的检查点不因后置同步凭据改写。最终验证完成前暂停新研究。

## 2. 相对有效 CP-0004 的数量对账

| 指标 | CP-0004 | 当前 CP-0005 候选 | 净变化 |
| --- | ---: | ---: | ---: |
{table}

保留 Upload {counts['retained_uploads']}、不同文件 {counts['distinct_files']}、正式项目 {counts['projects']}、机构记录 {counts['organizations']}。Person 为署名身份记录，新增 {delta['people_records']} 条限定于本次 Work 的暂定身份，没有按同名跨 Work 合并。

已有逐主张科学全文审阅 Work 集合仍为 {len(reviewed_works)}；新增全文 Work {counts['run3_new_scientific_fulltext_works']}、新增文件 {counts['run3_new_fulltext_files']}。本批在既有 Longden 缓存上检查一个新主张，不计为再新增一篇全文。S01及其他未完成全文/补充材料范围继续开放。

## 3. 本批具体推进

- **P3：**补全 {len(enriched)} 个既有 Work 的精确 PubMed/DOI、署名和明确书目信息，规范 Work 数不增加。解析 {len(resolved_events)} 个已登记的 Ardin 目标 DOI 引用，新增同数 source_supported 边；原始引文保留。六项另有一致书目信息，一项只有精确 DOI，不补造标题/作者/年份复核。原 EPMC 五条关系保持。
- **P4：**原项目成果施引列表仍为单来源 {project_cov['distinct_count']}/{project_cov['visible_total']}；EPMC core 详情仍 {epmc_core}/{project_cov['visible_total']}，通过 PubMed 补全 {pubmed_resolved} 个身份，跨来源合计 {epmc_core+pubmed_resolved}/{project_cov['visible_total']}，剩余 {identity_pending} 个。未把超时、空白或缓存响应写成来源成功，也未把书目边计作正文语境核验。
- **P5：**种子作者列表分页 {counts['seed_author_lists_paginated']}/{len(seed_author_ids)}，总量对账 {counts['seed_author_lists_reconciled']}/{len(seed_author_ids)}。四项差异只补齐已有回执和“列表已结束、计数未一致”的准确说明，不声称还有未消费分页；作者消歧和历史机构/项目归属继续开放。
- **P6：**新增 Longden2010 的独立 L03 起始潜伏期主张；既有 {len(before_assessments)} 条 Assessment 逐记录保持不变，原 L07 不足、全部拒收及反证保留。新增主张包含 negative_result；fully_resolved 仍为 {counts['fully_resolved_claims']}。

### Longden2010 单主张结论

原始证据 DOI：[10.3389/fnsys.2010.00153](https://doi.org/10.3389/fnsys.2010.00153)，已保存 PDF 的 Methods/Statistics/Response latency 页定位及 SHA 见 [本轮人工复核](RUN-0003-Longden2010-latency-review.json)。在固定制备、CDM 受控干预和 0.85–8 Hz 汇总条件下，H2 起始潜伏期由 44.8±1.3 ms 变为 40.9±1.5 ms（均值±SE，N=7，配对 t 检验 P=.04）；作者报告约 9% 缩短。峰值潜伏期未显著改变，作为 negative_result 保留。

{claim['remaining_limitations']} 生物机制含义：{claim['biological_implications']} 工程含义：{claim['engineering_implications']} 处理程度为 `{claim['handling_level']}`；不能据此宣称局限性已解决。

## 4. 覆盖、任务与预算

| 维度 | 分母 | verified_complete | partial | pending | restricted | not_applicable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{dimtable}

主题集合：{topicline}。K={len(works)}，主题并集={len(union)}，U={len(works)-len(union)}；跨主题行数不能相加当独立 Work。

本轮关闭 {len(field_closed)} 个字段 unknown 复核任务；新增署名消歧、字段、引用语境和查询审计任务使总开放任务净变化为 {delta['unresolved_tasks']:+,}，不把“关闭25项”描述为净减少25项。当前开放 unknown 工单 {len(unknown_open):,}，逾期 {len(overdue)}；完整逻辑数据包含 unknown 状态对象 {sum(unknown_states.values()):,}，该数包含字段及共享投影，不能当独立工单数。原始时钟保留，完整审计将再次检查24小时升级规则。

本轮查询 {len(queries)} 条：{external} 次外部科研调用（1次直接 EPMC 尝试、15次已留回执网页调用）与 {cache_reuses} 次本地缓存复核；缓存不计 HTTP。人工复核 {len(manual)}/{run['budget']['manual_review_items']}，外部调用 {external}/{run['budget']['external_requests']}，付费支出 {run['paid_spend']}。运行墙钟预算 {run['budget']['wall_clock_hours']} 小时；本次为同步和验收暂停，没有声称预算耗尽。累计精确查询时刻 {counts['exact_query_timestamps']}，历史不可恢复精确时刻 {counts['unavailable_exact_query_timestamps']}。

证据不足 {len(insufficient)} 条，拒收代码分布（非互斥）：`{json.dumps(coverage['scientific_gates']['rejection_codes'],ensure_ascii=False,sort_keys=True)}`。绝对尺度明确主张 {len(absolute)} 条，其中合格 {coverage['scientific_gates']['absolute_scale_eligible']}、不足 {coverage['scientific_gates']['absolute_scale_insufficient']}；本批没有新增绝对尺度结论。拒绝 Upload 事件 {counts['rejected_upload_events']}，级联事件 {counts['cascade_events']}。

## 5. 导出与待完成验收

以下五视图已从本批规范数据生成；表内 SHA 为当前文件实测值，完整交叉对账仍待完整审计。

| 视图 | 记录数口径 | SHA-256 |
| --- | ---: | --- |
{viewtable}

ref.bib、ref.html 与五视图必须七项确定性重生成字节一致；HTML 十项交互必须通过。新增/修改实体 schema 预检查为0错误，不能代替整库审计。候选 artifact_hashes 暂为空；不得在最终报告和验收证据落盘前标记 valid。

复查入口：[本轮集成](RUN-0003-integration.json)、[身份人工复核](RUN-0003-identity-review.json)、[Longden 单主张](RUN-0003-Longden2010-latency-review.json)、[候选检查点](../snapshots/checkpoints/CP-0005.json)、[最后有效 CP-0004](../snapshots/checkpoints/CP-0004.json)。剩余任务按已保存游标继续；九个详情身份、四个计数差、原全文/补充书目、跨来源覆盖及科学引用语境都不宣称完成。
'''
    progress = f'''# 当前执行进度：CP-0005 候选

更新时间：{stamp}。

**SCOPE-0001 / RUN-0003 / CP-0005：invalid 候选，数据已集成，完整审计、七产物确定性、十项 UI 及最终同步待完成。** 最后有效检查点为 CP-0004；CP-0003 invalid 历史保留。P3–P6 部分推进，研究闭包未成立，P7 最终研究验收尚未启动，P8 未触发。

| 阶段 | 本批推进 | 仍开放 |
| --- | --- | --- |
| P3 | {len(enriched)}个既有身份补全；{len(resolved_events)}个参考解析和同数来源支持边；Work总量{len(works):,} | {counts['unresolved_occurrences']:,}个未解析出现项；完整正文/补充书目及递归 |
| P4 | 项目施引列表{project_cov['distinct_count']}/{project_cov['visible_total']}；跨来源详情{epmc_core+pubmed_resolved}/{project_cov['visible_total']} | EPMC详情仍{epmc_core}/{project_cov['visible_total']}；{identity_pending}个身份、来源覆盖和引用语境 |
| P5 | 作者列表分页{counts['seed_author_lists_paginated']}/{len(seed_author_ids)}、总量对账{counts['seed_author_lists_reconciled']}/{len(seed_author_ids)}；四项任务证据澄清 | 四个来源计数差；新增署名尚待跨Work消歧；历史机构/项目 |
| P6 | {len(active)}条主张：{len(eligible)}合格、{len(insufficient)}不足、{counts['counter_evidence_claims']}含反证；新增Longden L03单主张 | 原L07不足不变；fully_resolved={counts['fully_resolved_claims']}；其他条件及主张仍开放 |

主题Work并集{len(union)}、U00={len(works)-len(union)}。既有科学全文审阅Work {len(reviewed_works)}，本轮新增全文Work/文件0/0；缓存复核不重复计数。引用边{counts['citation_edges']:,}，已核科学语境仍{counts['context_reviewed_edges']}。

开放任务{counts['unresolved_tasks']:,}（相对CP4 {delta['unresolved_tasks']:+,}）；本轮25个字段工单关闭不等于开放任务净减25。开放unknown工单{len(unknown_open):,}、逾期{len(overdue)}。本轮外部科研调用{external}/2000，缓存复用{cache_reuses}次另计，人工{len(manual)}/200，付费0。

原始回执/人工决定已先行同步；本检查点写入时，最终推送和精确回读尚未发生，验证前不开始下一研究批。后置同步证明保存在固定同步workflow日志及独立传输分支的verification receipt，此历史时点说明不代表之后同步失败；冻结内容不因后置凭据改写。不能将候选生成当作有效快照或研究完成。

- [CP5阶段报告与全部计数](reports/P3-P6-CP0005.md)
- [CP5 invalid候选](snapshots/checkpoints/CP-0005.json)
- [最后有效CP4](snapshots/checkpoints/CP-0004.json)
- [本轮集成及原始回执关联](reports/RUN-0003-integration.json)
'''
    readme = (REPO / 'README.md').read_text()
    pattern = r'^执行状态统一记录于 \[进度追踪\].*$'
    pointer = '执行状态统一记录于 [进度追踪](temp/progress.md)；阶段验收见 [P1/P2 报告](temp/reports/P1-P2.md)。P3–P6 当前阶段报告见 [CP-0005 报告](temp/reports/P3-P6-CP0005.md)，[CP-0005](temp/snapshots/checkpoints/CP-0005.json) 当前为 invalid 候选，待完整验收与最终同步；最后有效快照及 CP-0005 的父检查点为 [CP-0004](temp/snapshots/checkpoints/CP-0004.json)。[CP-0003](temp/snapshots/checkpoints/CP-0003.json) 保留为 invalid 恢复历史。本节定义阶段门禁，不另行维护执行状态。'
    readme, replacements = re.subn(pattern, pointer, readme, flags=re.MULTILINE)
    assert replacements == 1
    change_log = (TEMP / 'change-log.md').read_text()
    marker_start, marker_end = '<!-- CP5-CANDIDATE-START -->', '<!-- CP5-CANDIDATE-END -->'
    section = f'''{marker_start}
## CP-0005 / RUN-0003 / {now.date()} · invalid候选

相对有效CP4补全{len(enriched)}个既有Work、增加{delta['people_records']}个Work限定署名身份、关闭{len(field_closed)}个字段unknown工单；解析{len(resolved_events)}个既有引用并增加同数source_supported边。新增Longden2010 L03独立主张，原68条Assessment及L07不足不变。共{external}次科研外部调用、{cache_reuses}次缓存复核、{len(manual)}次人工复核；新增全文Work/文件0/0。

CP5是invalid候选，完整数据审计/七产物确定性/十项UI及最终同步待完成。原始回执已先行同步，不能据此宣称当前canonical已同步。研究闭包未成立，开放任务{counts['unresolved_tasks']:,}；见[阶段报告](reports/P3-P6-CP0005.md)。CP3 invalid与CP4 valid原字节保留。
{marker_end}'''
    if marker_start in change_log:
        change_log, n = re.subn(re.escape(marker_start)+r'.*?'+re.escape(marker_end), lambda _: section, change_log, flags=re.DOTALL)
        assert n == 1
    else:
        change_log = change_log.rstrip() + '\n\n' + section + '\n'
    run.update(status='checkpointing', end_checkpoint_id=CP, checkpoint_status='invalid',
               checkpoint_validation_state='data_audit_pending', checkpoint_candidate_created_at_utc=created)
    assert before == {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in inputs}, 'Logical inputs changed during metrics generation'
    for name,digest in frozen_hashes.items():
        assert sha(REPO / name) == digest
    outputs = {DEST: json_text(cp, True), TEMP / 'progress.md': progress,
               TEMP / 'reports/P3-P6-CP0005.md': report, TEMP / 'change-log.md': change_log,
               REPO / 'README.md': readme, TEMP / 'runs/RUN-0003.json': json_text(run)}
    for path,text in outputs.items():
        write_canonical(path,text)
    for name,digest in frozen_hashes.items():
        assert sha(REPO / name) == digest
    (PRIVATE / 'final-counts.json').write_text(json_text(counts))
    (PRIVATE / 'final-coverage.json').write_text(json_text(coverage))
    receipt = {'status': 'invalid_candidate_generated', 'checkpoint_id': CP,
               'generated_at_utc': stamp, 'schema_errors': 0, 'artifact_hashes_count': 0,
               'counts': counts, 'delta_from_cp4': delta, 'frozen_hashes_unchanged': frozen_hashes,
               'canonical_outputs': {str(p.relative_to(REPO)): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in outputs},
               'research_requests': 0, 'remote_write_performed': False,
               'logical_datasets_written': False, 'exports_written': False}
    (PRIVATE / 'checkpoint-generation.json').write_text(json_text(receipt))
    print(json.dumps({'status': receipt['status'], 'works': len(works), 'assessments': len(active),
          'eligible': len(eligible), 'counter': counts['counter_evidence_claims'],
          'open_tasks': counts['unresolved_tasks'], 'open_task_delta': delta['unresolved_tasks'],
          'queries': counts['queries'], 'manual_run3': len(manual), 'unknown_open': len(unknown_open),
          'candidate_bytes': DEST.stat().st_size, 'receipt': str(PRIVATE / 'checkpoint-generation.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
