#!/usr/bin/env python3
"""Build an invalid CP9 candidate, or finalize it only after exact QA passes.

Preview is read-only. --apply writes the explicit checkpoint/document/QA output
plan. This script performs no research, network access, canonical JSONL edits,
export generation, Git commit, push, or remote-verification claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker
import audit_cp9 as audit
from storage import read_logical

CP, RUN, PARENT = audit.CHECKPOINT, audit.RUN, audit.PARENT
REPORT_PATH = 'temp/reports/P3-P6-CP0009.md'
SYNC_URL = 'https://github.com/ncut-d1z/Insect-Inspired/blob/sync/cp9-checkpoint-import/temp/sync/CP-0009/verification.json'
TERMINAL = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
DIMENSIONS = ('metadata', 'fulltext', 'abstract', 'references', 'citations',
              'authors', 'affiliations_projects', 'assessment')
MUTABLE_IDS = {
    'works': 'work_id', 'versions': 'version_id', 'authors': 'person_id',
    'organizations': 'org_id', 'projects': 'project_id', 'aliases': 'alias_id',
    'reference-occurrences': 'occurrence_id', 'citation-edges': 'edge_id',
    'source-list-coverage': 'coverage_id', 'reference-coverage': 'coverage_id',
    'author-publication-leads': 'lead_id', 'project-relations': 'relation_id',
}
CURSOR_FIELDS = ('event_sequence', 'task_state', 'cursor', 'query_ids', 'attempt_count',
                 'error_code', 'failure_reason', 'retry_at', 'review_condition')
UI_CHECKS = {
    'ten_fixed_tables', 'search_and_theme', 'abstract_expand_collapse',
    'evidence_expand_collapse', 'back_to_top', 'clear', 'counter_evidence_filter',
    'year_sort', 'mobile_no_document_overflow', 'no_javascript_errors',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp(value=None):
    return (value or datetime.now(timezone.utc)).isoformat().replace('+00:00', 'Z')


def utc(value):
    parsed = audit.original.utc(value)
    require(parsed is not None, 'Invalid timezone-aware timestamp: ' + str(value))
    return parsed


def json_bytes(value, compact=False):
    options = {'separators': (',', ':')} if compact else {'indent': 2}
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, **options) + '\n').encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def objects(value):
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(v for v in current.values() if isinstance(v, (dict, list)))
        elif isinstance(current, list):
            stack.extend(v for v in current if isinstance(v, (dict, list)))


def latest_tasks(rows):
    latest = {}
    for row in rows:
        old = latest.get(row['task_id'])
        require(old is None or row['event_sequence'] > old['event_sequence'],
                'Task event order is not strictly increasing: ' + row['task_id'])
        if old and old.get('unknown_since_utc'):
            require(row.get('unknown_since_utc') == old['unknown_since_utc']
                    and row.get('deadline_at_utc') == old.get('deadline_at_utc'),
                    'Original unknown clock/deadline changed: ' + row['task_id'])
        latest[row['task_id']] = row
    return latest


def baseline_rows(repo, filename, manifest):
    entry = manifest['datasets'].get(filename)
    parts = entry['parts'] if entry else [{'path': filename}]
    total, digest = 0, hashlib.sha256()
    for part in parts:
        raw = audit.baseline_bytes(repo, 'temp/' + audit.safe_relative(part['path']))
        lines = [line for line in raw.splitlines(keepends=True) if line.strip()]
        if entry:
            require(len(raw) == part['bytes'] and audit.sha_bytes(raw) == part['sha256']
                    and len(lines) == part['records'], 'Frozen baseline partition differs: ' + filename)
        digest.update(raw)
        total += len(lines)
        for line in lines:
            yield json.loads(line), line
    if entry:
        require(total == entry['logical_records'] and digest.hexdigest() == entry['logical_sha256'],
                'Frozen logical baseline differs: ' + filename)


def preserve_baseline(repo, data, integration, now):
    # The dedicated verifier proves every logical row, raw task prefix, exact
    # archive and JSON-pointer transition against the committed CP8 lineage.
    # This maintenance path grants no generic mutable-record permission.
    maintenance = audit.verify_maintenance(repo, now)
    manifest = json.loads(audit.baseline_bytes(repo, 'temp/partitions/manifest.json'))
    old_names = sorted(name + '.jsonl' for name in maintenance['counts_before'])
    archived_lines = audit.assessment_lines((repo / 'temp/history/CP-0008/assessments.jsonl').read_bytes())
    checks, counts_before, old_latest = [], {}, {}
    old_sets = {name: set() for name in ('work_ids', 'assessment_ids', 'query_ids', 'manual_ids',
                                       'edge_ids', 'person_ids', 'file_hashes', 'reviewed_work_ids')}
    for filename in old_names:
        name = filename.removesuffix('.jsonl')
        require(name in data, 'Old logical dataset missing: ' + name)
        current, count, changed = data[name], 0, 0
        for index, (old, old_line) in enumerate(baseline_rows(repo, filename, manifest)):
            require(index < len(current), 'Old records lost: ' + name)
            new = current[index]
            count += 1
            changed += old != new
            if name == 'works': old_sets['work_ids'].add(old['work_id'])
            elif name == 'authors': old_sets['person_ids'].add(old['person_id'])
            elif name == 'queries': old_sets['query_ids'].add(old['query_id'])
            elif name == 'manual-reviews': old_sets['manual_ids'].add(old['review_id'])
            elif name == 'citation-edges': old_sets['edge_ids'].add(old['edge_id'])
            elif name == 'versions': old_sets['file_hashes'].update(x['sha256'] for x in old.get('file_records', []))
            elif name == 'tasks': old_latest[old['task_id']] = old
            elif name == 'assessments':
                identifier = old['assessment_id']; old_sets['assessment_ids'].add(identifier)
                if old['assessment_status'] == 'active': old_sets['reviewed_work_ids'].add(old['work_id'])
                require(identifier in archived_lines and archived_lines[identifier][1] == old_line,
                        'CP8 original Assessment archived line changed: ' + identifier)
        counts_before[name] = count
        checks.append({'dataset': name, 'old_records': count, 'new_records': len(current),
                       'modified_records': changed, 'appended_records': len(current) - count,
                       'existing_records_lost': 0, 'original_bytes_archived_or_git_bound': True,
                       'only_declared_overdue_status_changes': True})
    require(counts_before == integration['counts_before'], 'Integration baseline count differs')
    require({name: len(rows) for name, rows in data.items()} == integration['counts_after'],
            'Integration current count differs')
    return {**old_sets, 'checks': checks, 'counts_before': counts_before,
            'old_latest': old_latest, 'resolved_reference_ids': [], 'maintenance': maintenance}


def reviewed_new_assessments(repo, records):
    """Require every new scientific row to be an exact saved, committed review object."""
    wanted = {row['assessment_id']: row for row in records}
    found = {}
    for path in sorted((repo / 'temp/reports').glob('RUN-0007*.json')):
        if path.name == 'RUN-0007-integration.json':
            continue
        value = read_json(path)
        matches = {obj['assessment_id']: obj for obj in objects(value)
                   if obj.get('assessment_id') in wanted and obj == wanted[obj['assessment_id']]}
        if not matches:
            continue
        relative = str(path.relative_to(repo))
        published = audit.git_bytes(repo, 'show', 'HEAD:' + relative)
        require(published == path.read_bytes(), 'Scientific review is not the committed exact bytes: ' + relative)
        for identifier in matches:
            found.setdefault(identifier, []).append({'path': relative, 'sha256': audit.sha_bytes(published)})
    require(set(found) == set(wanted), 'A new Assessment lacks an exact committed full review object')
    return found


def collect(repo, now):
    parent = read_json(repo / 'temp/snapshots/checkpoints/CP-0008.json')
    require(parent['status'] == 'valid', 'CP8 must remain a valid parent')
    require(read_json(repo / 'temp/snapshots/checkpoints/CP-0003.json')['status'] == 'invalid', 'CP3 history changed')
    run = read_json(repo / audit.RUN_PATH)
    scope = read_json(repo / 'temp/snapshots/scope.json')
    integration = read_json(repo / audit.INTEGRATION_PATH)
    require(run['run_id'] == RUN and run['scope_id'] == scope['scope_id'] == 'SCOPE-0001'
            and run['start_checkpoint_id'] == PARENT and run['start_commit_sha'] == audit.BASE_COMMIT,
            'RUN7 baseline or scope differs')
    require(integration['run_id'] == RUN and integration['checkpoint_id'] == CP
            and integration['scope_id'] == 'SCOPE-0001', 'Integration identity differs')
    require(run['research_cutoff_at_utc'] == scope['cutoff_at_utc'], 'Research cutoff changed')
    expected_budget = {'wall_clock_hours': scope['budget']['wall_clock_hours_per_run'],
                       'external_requests': scope['budget']['external_requests_per_run'],
                       'manual_review_items': scope['budget']['manual_review_items_per_run'],
                       'paid_spend': scope['budget']['paid_spend_limit']}
    require(run['budget'] == expected_budget and run['paid_spend'] == 0, 'Frozen run budget changed')
    names = sorted(path.name for path in (repo / 'temp').glob('*.jsonl'))
    data = {name.removesuffix('.jsonl'): read_logical(name, repo / 'temp') for name in names}
    base = preserve_baseline(repo, data, integration, now)
    _, certificate = audit.published_cp8_baseline(repo)
    for frozen in certificate['frozen_files']:
        path = repo / frozen['path']
        require(path.stat().st_size == frozen['bytes'] and audit.original.sha(path) == frozen['sha256'],
                'Frozen historical file changed: ' + frozen['path'])
    latest = latest_tasks(data['tasks'])
    works = {row['work_id']: row for row in data['works']}
    require(len(works) == len(data['works']), 'Duplicate Work identity')
    active = [row for row in data['assessments'] if row['assessment_status'] == 'active']
    eligible = [row for row in active if row['evidence_admission_status'] == 'eligible']
    insufficient = [row for row in active if row['evidence_admission_status'] == 'insufficient_evidence']
    new_claims = [row for row in data['assessments'] if row['assessment_id'] not in base['assessment_ids']]
    require(not new_claims, 'CP9 maintenance cannot add scientific claims')
    review_bindings = reviewed_new_assessments(repo, new_claims)
    topics = {f'L{i:02d}': {row['work_id'] for row in eligible if row['limitation_id'] == f'L{i:02d}'} for i in range(1, 10)}
    topic_union = set().union(*topics.values())
    require(topic_union <= set(works), 'Topic Work has no canonical identity')
    queries = [row for row in data['queries'] if row['query_id'] not in base['query_ids']]
    require(all(row['checkpoint_id'] == CP for row in queries), 'New query refers to another checkpoint')
    qids = {row['query_id'] for row in queries}
    observations = [row for row in data['source-observations'] if row.get('query_id') in qids]
    require(Counter(row['query_id'] for row in observations) == Counter({qid: 1 for qid in qids}),
            'Each new query needs one explicit invocation/cache observation')
    require(all(isinstance(row.get('external_request_performed'), bool) for row in observations),
            'Invocation/cache observation lacks an explicit boolean')
    external = sum(audit.external_request_count(row) for row in observations)
    cache = sum(row.get('cache_hit') is True for row in queries)
    cached_ids = {row['query_id'] for row in queries if row.get('cache_hit') is True}
    require(all(not row['external_request_performed'] and row['external_request_count'] == 0
                for row in observations if row['query_id'] in cached_ids),
            'Cache reuse was counted as external access')
    manual = [row for row in data['manual-reviews'] if row['review_id'] not in base['manual_ids']]
    require(all(row['run_id'] == RUN for row in manual), 'New manual review belongs to another run')
    require(run['external_requests_used'] == external and run['manual_review_items_used'] == len(manual)
            and run['cache_reuse_events'] == cache, 'RUN7 accounting differs from actual query/review ledgers')
    require(not queries and not manual and external == cache == 0, 'CP9 is maintenance only: no new queries, reviews or research operations')
    require(external <= run['budget']['external_requests'] and len(manual) <= run['budget']['manual_review_items'],
            'Recorded research exceeds the authorized per-run budget')
    unknown_open = [row for row in latest.values() if row.get('unknown_since_utc') and row['task_state'] not in TERMINAL]
    overdue = [row for row in unknown_open if utc(row['deadline_at_utc']) <= now]
    for row in overdue:
        require(row.get('overdue') is True and row.get('priority') in {'high', 'urgent', 'critical'},
                'Overdue unknown task is not escalated: ' + row['task_id'])
    unknown_states = Counter()
    for rows in data.values():
        for row in rows:
            for obj in objects(row):
                if obj.get('status') in {'unknown', 'unknown_review_required'} and ('unknown_since_utc' in obj or 'review_task_id' in obj):
                    unknown_states[obj['status']] += 1
                    if obj.get('unknown_since_utc') and (now - utc(obj['unknown_since_utc'])).total_seconds() >= 86400:
                        require(obj['status'] == 'unknown_review_required', 'Overdue unknown field has not been escalated')
    closed = [tid for tid, old in base['old_latest'].items() if old['task_type'] == 'field_review'
              and old['task_state'] not in TERMINAL and latest[tid]['task_state'] == 'verified_complete']
    escalated = [tid for tid, row in latest.items() if row.get('overdue') is True
                 and (tid not in base['old_latest'] or base['old_latest'][tid].get('overdue') is not True)]
    seeds = [row for row in data['seed-manifest'] if row['record_type'] == 'seed_mapping']
    seed_work_ids = {row['work_id'] for row in seeds}
    seed_authors = {author['person_id'] for wid in seed_work_ids for author in works[wid]['authors']}
    uploads = {row['upload_id']: row for row in data['uploads']}
    files = {f['sha256'] for row in data['versions'] for f in row.get('file_records', [])}
    reviewed_work_ids = {row['work_id'] for row in active}
    new_edges = [row for row in data['citation-edges'] if row['edge_id'] not in base['edge_ids']]
    coverage_rows = data['source-list-coverage']
    author_coverage = [row for row in coverage_rows if row['entity_id'] in seed_authors and row['source_id'] == 'semantic_scholar']
    absolute = [row for row in active if row['claims_absolute_scale'].get('value') is True]
    counts = {
        'seed_records': len(seeds), 'canonical_works': len(works), 'versions': len(data['versions']),
        'retained_uploads': len(data['uploads']), 'distinct_seed_pdf_sha256': len({uploads[row['upload_id']]['sha256'] for row in seeds}),
        'distinct_files': len(files), 'file_backed_versions': sum(bool(row['file_records']) for row in data['versions']),
        'people_records': len(data['authors']), 'organizations': len(data['organizations']), 'projects': len(data['projects']),
        'reference_occurrences': len(data['reference-occurrences']),
        'resolved_occurrences': sum(row['cited_work_id'] is not None for row in data['reference-occurrences']),
        'unresolved_occurrences': sum(row['cited_work_id'] is None for row in data['reference-occurrences']),
        'citation_edges': len(data['citation-edges']),
        'context_reviewed_edges': sum(bool(row['context_locators']) and any(role != 'unknown' for role in row['citation_roles']) for row in data['citation-edges']),
        'assessments': len(active), 'eligible_claims': len(eligible), 'insufficient_claims': len(insufficient),
        'counter_evidence_claims': sum(row['counter_evidence'] for row in active),
        'fully_resolved_claims': sum(row['handling_level'] == 'fully_resolved' for row in active),
        'topic_work_union': len(topic_union), 'u00_works': len(works) - len(topic_union),
        'task_events': len(data['tasks']), 'unique_tasks': len(latest),
        'unresolved_tasks': sum(row['task_state'] not in TERMINAL for row in latest.values()),
        'queries': len(data['queries']), 'exact_query_timestamps': sum(row.get('query_time_status', 'exact') == 'exact' for row in data['queries']),
        'unavailable_exact_query_timestamps': sum(row.get('query_time_status') == 'unavailable_exact' for row in data['queries']),
        'merged_work_pairs': len(data.get('work-merge-events', [])),
        'seed_reference_occurrences': sum(row['citing_work_id'] in seed_work_ids and not row['occurrence_id'].startswith('R-CR-') for row in data['reference-occurrences']),
        'iteration2_reviewed_reference_occurrences': len(data.get('new-fulltext-reference-audit', [])),
        'scientific_fulltext_works_reviewed': len(reviewed_work_ids), 'manual_review_activities': len(data['manual-reviews']),
        'seed_authors': len(seed_authors), 'seed_author_lists_paginated': sum(row['pagination_complete'] for row in author_coverage),
        'seed_author_lists_reconciled': sum(row['total_reconciled'] for row in author_coverage),
        'seed_s2_lists_reconciled': sum(row['entity_id'] in seed_work_ids and row['source_id'] == 'semantic_scholar' and row['total_reconciled'] for row in coverage_rows),
        'seed_epmc_lists_reconciled': sum(row['entity_id'] in seed_work_ids and row['source_id'] == 'europepmc' and row['total_reconciled'] for row in coverage_rows),
        'unknown_fields': sum(unknown_states.values()), 'open_unknown_review_tasks': len(unknown_open),
        'overdue_open_unknown_review_tasks': len(overdue), 'cascade_events': len(data['cascade-events']),
        'rejected_upload_events': sum(bool(line.strip()) for line in (repo / 'temp/rejected_uploads.log').read_bytes().splitlines()),
        'run7_external_requests': external, 'run7_cache_reuses': cache, 'run7_query_rows': len(queries),
        'run7_manual_review_activities': len(manual), 'run7_new_works': len(set(works) - base['work_ids']),
        'run7_new_people': len({row['person_id'] for row in data['authors']} - base['person_ids']),
        'run7_new_assessments': len(new_claims), 'run7_new_citation_edges': len(new_edges),
        'run7_reference_resolutions': len(base['resolved_reference_ids']),
        'run7_unknown_field_tasks_closed': len(closed), 'run7_overdue_unknown_tasks_escalated': len(escalated),
        'run7_new_scientific_fulltext_works': len(reviewed_work_ids - base['reviewed_work_ids']),
        'run7_new_fulltext_files': len(files - base['file_hashes']),
    }
    counts.update({key + '_works': len(value) for key, value in topics.items()})
    delta = {key: value - parent['counts'][key] for key, value in counts.items() if key in parent['counts']}
    export_hashes = audit.input_snapshot(repo, audit.EXPORTS)
    coverage = {key: {'denominator': len(works), 'states': dict(Counter(row['dimension_status'][key] for row in works.values()))} for key in DIMENSIONS}
    coverage.update({
        'phase_status': dict(parent['coverage']['phase_status']),
        'maintenance': base['maintenance'],
        'closure': {'established': False, 'reason': 'Unresolved references/tasks and incomplete source, fulltext and scientific coverage remain; valid checkpoint does not establish research closure.'},
        'reconciliation': {'K': len(works), 'T_union': len(topic_union), 'U': len(works) - len(topic_union), 'T_i': {key: len(value) for key, value in topics.items()}},
        'scientific_gates': {'eligible': len(eligible), 'insufficient': len(insufficient), 'counter_evidence': counts['counter_evidence_claims'],
                             'fully_resolved': counts['fully_resolved_claims'], 'cp8_assessments_preserved': len(base['assessment_ids']),
                             'absolute_scale_claims': len(absolute), 'absolute_scale_eligible': sum(row['evidence_admission_status'] == 'eligible' for row in absolute),
                             'absolute_scale_insufficient': sum(row['evidence_admission_status'] == 'insufficient_evidence' for row in absolute),
                             'rejection_codes': dict(Counter(code for row in insufficient for code in row['rejection_codes']))},
        'task_states': dict(Counter(row['task_state'] for row in latest.values())),
        'unknown_review': {'field_states': dict(unknown_states), 'open_tasks': len(unknown_open), 'overdue_open_tasks': len(overdue), 'unupgraded_overdue_tasks': 0, 'original_clocks_preserved': True},
        'run7_accounting': {key: value for key, value in counts.items() if key.startswith('run7_')},
        'delta_from_cp8': delta, 'derived_views': {'state': 'generated_pending_validation', 'artifacts': export_hashes},
        'scientific_reviews': {'new_assessment_bindings': review_bindings, 'historical_primary_files_reread': False},
        'synchronization': {'canonical_snapshot_at_checkpoint_write': 'pending_post_commit_remote_verification', 'post_commit_verification_url': SYNC_URL,
                            'research_gate': 'closed_until_final_sync_verified', 'snapshot_time_note': 'This is a historical pre-publication state; do not infer later synchronization failure from it.'},
    })
    preservation = {'status': 'passed', 'checkpoint_id': CP, 'scope_id': 'SCOPE-0001', 'baseline_commit': audit.BASE_COMMIT,
                    'verified_at_utc': stamp(now), 'checks': base['checks'], 'existing_records_lost': 0,
                    'old_scientific_assessments_preserved': len(base['assessment_ids']),
                    'history_archives': base['maintenance']['history_archives'],
                    'maintenance_migration': base['maintenance'],
                    'raw_reference_text_and_fingerprints_preserved': True, 'frozen_files': certificate['frozen_files']}
    return {'repo': repo, 'now': now, 'parent': parent, 'run': run, 'counts': counts, 'coverage': coverage,
            'latest': latest, 'delta': delta, 'new_claims': new_claims, 'preservation': preservation,
            'export_hashes': export_hashes, 'review_bindings': review_bindings,
            'logical_counts': {key + '.jsonl': len(rows) for key, rows in data.items()},
            'maintenance': base['maintenance']}


def validate_checkpoint(repo, candidate):
    schema = read_json(repo / 'temp/schema.json')
    validator = Draft202012Validator({'$ref': '#/$defs/checkpoint', '$defs': schema['$defs']}, format_checker=FormatChecker())
    errors = list(validator.iter_errors(candidate))
    require(not errors, 'Checkpoint schema errors: ' + '; '.join(error.message for error in errors[:5]))


def documents(state, valid=False, qa=None):
    c, parent, coverage = state['counts'], state['parent']['counts'], state['coverage']
    now_text = state['now'].astimezone(ZoneInfo('Asia/Singapore')).strftime('%Y-%m-%d %H:%M:%S UTC+8')
    status = 'valid 数据检查点' if valid else 'invalid 候选；完整 QA 尚未通过'
    rows = [('规范 Work', 'canonical_works'), ('Version', 'versions'), ('署名身份记录', 'people_records'),
            ('参考出现项', 'reference_occurrences'), ('已解析出现项', 'resolved_occurrences'),
            ('未解析出现项', 'unresolved_occurrences'), ('引用边', 'citation_edges'),
            ('已核科学语境的边', 'context_reviewed_edges'), ('活动主张', 'assessments'),
            ('合格主张', 'eligible_claims'), ('不足主张', 'insufficient_claims'), ('反证主张', 'counter_evidence_claims'),
            ('主题 Work 并集', 'topic_work_union'), ('U00 Work', 'u00_works'), ('未结任务', 'unresolved_tasks')]
    table = '\n'.join(f'| {label} | {parent[key]:,} | {c[key]:,} | {c[key]-parent[key]:+,} |' for label, key in rows)
    claims = []
    for row in state['new_claims']:
        bindings = ', '.join('[' + item['path'].split('/')[-1] + '](' + item['path'].split('/')[-1] + ')' for item in state['review_bindings'][row['assessment_id']])
        claims.append(f"- `{row['assessment_id']}`：`{row['work_key']}` / `{row['limitation_id']}` / `{row['evidence_admission_status']}` / `{row['handling_level']}`。{row.get('effect', '')}\n  适用范围与未解决问题：{row.get('remaining_limitations', '')} 来源审阅：{bindings}。")
    claim_text = '\n'.join(claims) if claims else '本轮只恢复已到期 unknown 的真实复核状态，没有新增 Work、科学主张、来源查询或人工科学复核；未结问题继续保留。'
    qualification = (f"完整数据审计 0 错误、{qa['warning_count']} 项已披露警告；七项导出逐字一致；十项 UI 检查通过。" if valid else '候选尚不构成有效验收；必须完成完整数据审计、七项导出确定性、十项 UI 和最终哈希。')
    dimensions = '\n'.join(f'| {key} | {value["denominator"]:,} | `{json.dumps(value["states"], ensure_ascii=False, sort_keys=True)}` |' for key, value in coverage.items() if key in DIMENSIONS)
    hashes = '\n'.join(f'| `{name}` | {value["bytes"]:,} | `{value["sha256"]}` |' for name, value in state['export_hashes'].items())
    report = f'''# CP-0009 恢复维护：unknown 24 小时门禁

## 当前状态

**SCOPE-0001 / RUN-0007 / CP-0009：{status}。** 有效父检查点为 CP-0008。统计时刻：{now_text}；文献截止仍为 {state['run']['research_cutoff_at_utc']}。

本检查点仅为恢复维护：登记到期 unknown→unknown_review_required 和追加超时任务事件，没有新的 P3–P6 科学证据进展。P3–P6 的历史部分完成状态不变，递归闭包未成立，P7 最终研究验收未启动，P8 未触发。{qualification}

本快照生成时，最终提交与独立远端回读属于后置步骤。后置证明见 [verification.json]({SYNC_URL})；没有实际发布的回执时不能仅凭此链接宣称同步成功。后续回执不回写本冻结检查点。

## 相对 CP8 的规范全集对账

| 指标 | CP8 | CP9 | 净变化 |
| --- | ---: | ---: | ---: |
{table}

全部统计来自完整逻辑数据与最新任务事件。历史数据保留检查覆盖 {len(state['preservation']['checks'])} 个逻辑数据集，丢失旧记录 0；{state['preservation']['old_scientific_assessments_preserved']} 条原科学记录保留；Assessment、查询与合并审计原始 JSONL 在 temp/history/CP-0008/ 中逐字归档。当前旧行只允许迁移清单声明的已到期复核 status 变化，科学值、证据、身份、原因和原始时钟均不变。

## 本轮恢复维护

- 新增 Work {c['run7_new_works']}；新增署名身份记录 {c['run7_new_people']}。
- 既有参考出现项新解析 {c['run7_reference_resolutions']}；新增引用边 {c['run7_new_citation_edges']}。
- 新增科学主张 {c['run7_new_assessments']}；新增独立全文审阅 Work {c['run7_new_scientific_fulltext_works']}；新增全文文件哈希 {c['run7_new_fulltext_files']}。
- 关闭 unknown 字段工单 {c['run7_unknown_field_tasks_closed']}；到期升级 {c['run7_overdue_unknown_tasks_escalated']}。到期工单保持开放，升级不等于解决或关闭。
- 严格迁移 {state['maintenance']['batches']} 批，字段 status 变化 {state['maintenance'].get('field_status_transitions', 0):,} 处；原始任务事件逐字前缀保留。
- 外部科研调用 {c['run7_external_requests']}；合法缓存复用 {c['run7_cache_reuses']}；人工复核 {c['run7_manual_review_activities']}；付费 0。Git 同步不计科研查询。

{claim_text}

未重新读取旧环境丢失的历史 PDF/PNG；历史 S19 决定只按已通过 CP8 验收的固定记录及已发布证书继承。新主张没有额外豁免。

## 覆盖与未完成工作

| 维度 | Work 分母 | 当前状态分布 |
| --- | ---: | --- |
{dimensions}

K={c['canonical_works']}，T_union={c['topic_work_union']}，U={c['u00_works']}；T_i=`{json.dumps(coverage['reconciliation']['T_i'], ensure_ascii=False, sort_keys=True)}`。跨主题行数不能相加当独立 Work。

开放 unknown 工单 {c['open_unknown_review_tasks']:,}，其中已到期 {c['overdue_open_unknown_review_tasks']:,}；到期未升级 0。保留原始 unknown 时钟，未因重试刷新 deadline。未结任务 {c['unresolved_tasks']:,}、未解析参考出现项 {c['unresolved_occurrences']:,}；缺全文、索引限制、分页／计数差异及科学证据缺口仍须逐项处理，不能据无新增结果宣称穷尽。

## 交付物与验证

| 产物 | 字节 | SHA-256 |
| --- | ---: | --- |
{hashes}

验证记录：[集成报告](RUN-0007-integration.json)、[数据保留](../validation/cp9-delta-preservation.json)、[完整数据审计](../validation/cp9-data-audit.json)、[确定性](../validation/cp9-determinism.json)、[UI](../validation/cp9-ui-validation.json)、[QA 原始凭据](../validation/cp9-qa/qa-final-receipt.json)、[检查点](../snapshots/checkpoints/CP-0009.json)。候选阶段未产生的文件不得解释为验证已经通过。
'''
    progress = f'''# 当前执行进度：CP-0009

更新时间：{now_text}。**SCOPE-0001 / RUN-0007 / CP-0009：{status}。** 有效父检查点 CP-0008；CP3 invalid 历史保留。

{qualification}

- 规范 Work {c['canonical_works']:,}；活动主张 {c['assessments']}：合格 {c['eligible_claims']}、不足 {c['insufficient_claims']}、反证 {c['counter_evidence_claims']}。
- 本轮新 Work {c['run7_new_works']}，新解析参考出现项 {c['run7_reference_resolutions']}，新边 {c['run7_new_citation_edges']}，新主张 {c['run7_new_assessments']}。
- K={c['canonical_works']}，T_union={c['topic_work_union']}，U={c['u00_works']}。
- 未结任务 {c['unresolved_tasks']:,}；未解析参考出现项 {c['unresolved_occurrences']:,}；开放 unknown 工单 {c['open_unknown_review_tasks']:,}。

本轮只恢复到期复核状态，P3–P6 无新科学证据推进；研究闭包未成立，P7 未启动，P8 未触发。完整同步 CP9 后继续 P3–P6 未结证据任务。详见[阶段报告](reports/P3-P6-CP0009.md)和[CP9](snapshots/checkpoints/CP-0009.json)。最终提交后的[独立同步证明]({SYNC_URL})单独保存；通过前不得开始下一研究批。
'''
    readme = (state['repo'] / 'README.md').read_text(encoding='utf-8')
    begin = readme.index('执行状态统一记录于 ')
    end = readme.index('\n\n', begin)
    readme = readme[:begin] + f'执行状态统一记录于 [进度追踪](temp/progress.md)；P3–P6 当前阶段报告见 [CP-0009 报告]({REPORT_PATH})，[CP-0009]({audit.CP_PATH}) 为{status}，有效父检查点为 [CP-0008](temp/snapshots/checkpoints/CP-0008.json)。CP-0003 保留为 invalid 历史。后置同步证明与研究闭包分别披露。本节定义门禁，不另行维护执行状态。' + readme[end:]
    changelog = (state['repo'] / 'temp/change-log.md').read_text(encoding='utf-8')
    marker = '\n## RUN-0007 / CP-0009\n'
    if marker in changelog:
        changelog = changelog.split(marker, 1)[0].rstrip() + '\n'
    changelog += marker + f'\n{now_text}：{status}。保留 CP8 历史与原科学记录；本轮新增 Work {c["run7_new_works"]}、解析参考 {c["run7_reference_resolutions"]}、引用边 {c["run7_new_citation_edges"]}、主张 {c["run7_new_assessments"]}。来源、预算、失败和队列见[阶段报告](reports/P3-P6-CP0009.md)。研究闭包未成立，最终同步回执单列。\n'
    return {REPORT_PATH: report.encode(), 'temp/progress.md': progress.encode(), 'README.md': readme.encode(), 'temp/change-log.md': changelog.encode()}


def candidate(state):
    repo, now = state['repo'], state['now']
    path = repo / audit.CP_PATH
    created = stamp(now)
    if path.exists():
        old = read_json(path)
        require(old['status'] == 'invalid', 'Never overwrite or downgrade a valid CP9')
        created = old['created_at_utc']
    inputs = audit.input_snapshot(repo, audit.required_input_names(repo))
    projection = audit.run_accounting_projection(state['run'])
    validation = {
        'state': 'data_audit_pending', 'baseline_commit': audit.BASE_COMMIT, 'baseline_tree': audit.BASE_TREE,
        'canonical_input_hashes': inputs, 'canonical_input_digest_sha256': audit.input_digest(inputs),
        'input_frozen_at_utc': stamp(), 'run_record_at_freeze': state['run'],
        'run_accounting_projection': projection, 'run_accounting_projection_sha256': audit.canonical_digest(projection),
        'checkpoint_self_hash_excluded': True, 'git_internal_files_excluded': True,
        'frozen_parent_bytes_unchanged': True, 'frozen_scope_and_seed_unchanged': True,
        'cp8_scientific_content_preserved': state['preservation']['old_scientific_assessments_preserved'],
        'maintenance_only': True, 'history_archives': state['maintenance']['history_archives'],
        'integration_report_sha256': audit.original.sha(repo / audit.INTEGRATION_PATH),
        'scientific_review_bindings': state['review_bindings'],
        'data_audit': 'pending', 'determinism': 'pending', 'ui_validation': 'pending', 'final_artifact_hashes': 'pending',
        'final_remote_verification': 'post_commit_external_receipt_required', 'post_commit_verification_url': SYNC_URL,
        'research_closure_established': False,
    }
    cp = {'checkpoint_id': CP, 'scope_id': 'SCOPE-0001', 'parent_checkpoint_id': PARENT,
          'schema_version': state['parent']['schema_version'], 'created_at_utc': created,
          'task_cursor_state': {tid: {key: row.get(key) for key in CURSOR_FIELDS} for tid, row in sorted(state['latest'].items())},
          'query_log_high_watermark': state['counts']['queries'], 'counts': state['counts'], 'coverage': state['coverage'],
          'unresolved_tasks': sorted(tid for tid, row in state['latest'].items() if row['task_state'] not in TERMINAL),
          'failure_reasons': ['Invalid candidate until full data audit, seven-output determinism, UI and final hashes pass.',
                              'Research closure remains open; pending tasks and source/fulltext/scientific gaps are retained.',
                              'Final publication and independent remote readback are later events recorded separately.'],
          'artifact_hashes': {}, 'validation_results': validation, 'status': 'invalid'}
    validate_checkpoint(repo, cp)
    outputs = documents(state)
    outputs[audit.CP_PATH] = json_bytes(cp, True)
    outputs['temp/validation/cp9-delta-preservation.json'] = json_bytes(state['preservation'])
    return cp, outputs


def load_qa(repo, qa, ui_dir, cp, state):
    data = read_json(qa / 'data-audit-final.json')
    det = read_json(qa / 'cp9-determinism.json')
    ui = read_json(ui_dir / 'ui-audit-final.json')
    exported = read_json(qa / 'export-validation.json')
    expected = cp['validation_results']['canonical_input_hashes']
    digest = audit.input_digest(expected)
    candidate_hash = audit.original.sha(repo / audit.CP_PATH)
    require(audit.input_snapshot(repo, expected) == expected, 'Frozen canonical inputs changed after QA')
    require(audit.run_accounting_projection(state['run']) == cp['validation_results']['run_accounting_projection'], 'Frozen run accounting changed')
    require(data['status'] == 'passed' and data['error_count'] == 0 and data['changed_inputs'] == []
            and data.get('read_only') is True and Path(data['repository']).resolve() == repo, 'Complete data audit did not pass for this repository')
    binding = data['statistics']['cp9_input_binding']
    require(binding['passed'] is True and binding['checkpoint_id'] == CP
            and binding['candidate_sha256'] == binding['candidate_sha256_after'] == candidate_hash
            and binding['before_input_hashes'] == binding['after_input_hashes'] == expected
            and binding['before_digest_sha256'] == binding['after_digest_sha256'] == binding['expected_digest_sha256'] == digest,
            'Data audit is not bound to the exact current candidate/input bytes')
    require(data['statistics']['run_accounting_binding']['passed'] is True
            and data['statistics']['run_accounting_binding']['expected_projection_sha256'] == cp['validation_results']['run_accounting_projection_sha256'],
            'Data audit did not preserve run authorization/accounting')
    require(utc(data['audited_at_utc']) >= utc(cp['validation_results']['input_frozen_at_utc']), 'Audit predates candidate freeze')
    old = json.loads(audit.baseline_bytes(repo, 'temp/validation/cp8-data-audit.json'))
    require(data['findings']['warning'] == old['findings']['warning'] and data['warning_count'] == old['warning_count'],
            'Warning population changed; review explicitly before finalization')
    for key, count in state['logical_counts'].items():
        require(data['statistics'][key] == count, 'Audited logical population differs: ' + key)
    for key, count in {'cp8_assessments_scientific_preserved': 72, 'cp8_assessment_original_rows_archived': 72,
                       'cp8_manual_rejections_preserved': 9,
                       'cp8_manual_counterevidence_preserved': 23, 'cp8_frozen_files_byte_preserved': len(audit.FROZEN_PATHS)}.items():
        require(data['counters'].get(key) == count, 'Historical scientific protection failed: ' + key)
    migration = data['statistics']['cp9_maintenance_migration']
    require(migration['status'] == 'passed' and migration['maintenance_only'] is True
            and all(migration.get(key) == state['maintenance'].get(key) for key in
                    ('batches', 'field_status_transitions', 'appended_task_events', 'history_archives',
                     'counts_before', 'counts_after', 'logical_after')), 'Full maintenance proof differs from current data')
    require(len(data['statistics']['export_metadata']) == 5
            and all(row[1] == 'SCOPE-0001' and row[2] == CP for row in data['statistics']['export_metadata']), 'Audit did not inspect all five CP9 views')
    require(det['status'] == 'passed' and det['checkpoint_id'] == CP and det['changed_inputs'] == []
            and det['candidate_sha256'] == candidate_hash and det['candidate_unchanged'] is True
            and det['canonical_input_digest_sha256'] == digest and det['artifact_count'] == len(det['checks']) == len(audit.EXPORTS)
            and {row['artifact'] for row in det['checks']} == set(audit.EXPORTS), 'Seven-output determinism did not pass')
    for row in det['checks']:
        path = repo / row['artifact']
        require(row['byte_equal'] is True and audit.original.sha(path) == row['canonical_sha256'] == row['independent_export_sha256']
                and path.stat().st_size == row['bytes'], 'Deterministic output changed: ' + row['artifact'])
    require(ui['checkpoint_id'] == CP and ui['passed'] is True and not ui['errors'] and not ui['input_changed']
            and set(ui['checks']) == UI_CHECKS and all(ui['checks'].values()), 'Ten-check UI validation did not pass')
    require(utc(ui['started_at_utc']) >= utc(cp['validation_results']['input_frozen_at_utc']), 'UI check predates freeze')
    require(audit.original.sha(repo / 'ref.html') == ui['html_sha256'] == ui['html_sha256_after']
            and (repo / 'ref.html').stat().st_size == ui['html_bytes'], 'Tested HTML bytes differ')
    require((ui_dir / 'ui-audit-final.json').read_bytes() == (ui_dir / 'html-browser-check.json').read_bytes(), 'UI report aliases differ')
    require(exported['checkpoint_id'] == CP and not exported['schema_errors'], 'Export validation did not pass')
    for name, expected_hash in exported['artifact_hashes'].items():
        require(name in audit.EXPORTS and audit.original.sha(repo / name) == expected_hash, 'Export proof differs: ' + name)
    raw = {'data-audit-final.json': (qa / 'data-audit-final.json').read_bytes(),
           'cp9-determinism.json': (qa / 'cp9-determinism.json').read_bytes(),
           'export-validation.json': (qa / 'export-validation.json').read_bytes(),
           'ui-audit-final.json': (ui_dir / 'ui-audit-final.json').read_bytes(),
           'html-browser-check.json': (ui_dir / 'html-browser-check.json').read_bytes(),
           'audited-candidate.json': (repo / audit.CP_PATH).read_bytes()}
    require(set(ui['screenshots']) == {'html-desktop.png', 'html-topic.png', 'html-mobile.png', 'html-mobile-controls.png'}, 'UI screenshot evidence list differs')
    for name in ui['screenshots']:
        raw[name] = (ui_dir / name).read_bytes()
        require(raw[name].startswith(b'\x89PNG\r\n\x1a\n'), 'UI evidence is not a PNG: ' + name)
    receipt = {'status': 'passed', 'scope_id': 'SCOPE-0001', 'checkpoint_id': CP, 'recorded_at_utc': stamp(),
               'candidate_sha256': candidate_hash, 'canonical_input_digest_sha256': digest,
               'canonical_input_binding': binding, 'run_accounting_binding': data['statistics']['run_accounting_binding'],
               'raw_evidence_files': {name: {'bytes': len(value), 'sha256': audit.sha_bytes(value)} for name, value in raw.items()}}
    return data, det, ui, exported, raw, receipt


def intended_file_set(repo):
    raw = audit.git_bytes(repo, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
    names = {name for name in raw.decode().split('\0') if name and (repo / name).is_file()}
    actual = {str(path.relative_to(repo)) for path in repo.rglob('*')
              if path.is_file() and '.git' not in path.relative_to(repo).parts}
    require(names == actual, 'Unaccounted ignored files exist; inspect before freezing all deliverables')
    require(all(not (repo / name).is_symlink() for name in names), 'Checkpoint inputs cannot be symlinks')
    return names


def finalize(state, qa, ui_dir):
    repo = state['repo']
    cp = read_json(repo / audit.CP_PATH)
    require(cp['checkpoint_id'] == CP and cp['parent_checkpoint_id'] == PARENT
            and cp['status'] == 'invalid' and cp['artifact_hashes'] == {}, 'Expected an invalid unpublished CP9 candidate')
    require(cp['counts'] == state['counts'], 'Current counts differ from frozen candidate')
    cursors = {tid: {key: row.get(key) for key in CURSOR_FIELDS} for tid, row in sorted(state['latest'].items())}
    require(cp['task_cursor_state'] == cursors, 'Latest task cursors differ from candidate')
    require(cp['unresolved_tasks'] == sorted(tid for tid, row in state['latest'].items() if row['task_state'] not in TERMINAL), 'Unresolved queue differs')
    data, det, ui, exported, raw, receipt = load_qa(repo, qa, ui_dir, cp, state)
    outputs = {f'temp/validation/cp9-qa/{name}': value for name, value in raw.items()}
    outputs['temp/validation/cp9-qa/qa-final-receipt.json'] = json_bytes(receipt)
    for name, value in [('cp9-data-audit.json', raw['data-audit-final.json']),
                        ('cp9-determinism.json', raw['cp9-determinism.json']),
                        ('cp9-ui-validation.json', raw['ui-audit-final.json']),
                        ('cp9-export-validation.json', raw['export-validation.json'])]:
        outputs['temp/validation/' + name] = value
    outputs['temp/validation/cp9-delta-preservation.json'] = json_bytes(state['preservation'])
    outputs.update(documents(state, valid=True, qa=data))
    finished = stamp(state['now'])
    hours = (state['now'] - utc(state['run']['started_at_utc'])).total_seconds() / 3600
    run = dict(state['run'])
    run.update(status='checkpointed_open', end_checkpoint_id=CP, checkpoint_status='valid', checkpoint_validation_state='passed',
               checkpoint_completed_at_utc=finished, checkpoint_wall_clock_hours=round(hours, 4),
               budget_exhausted=hours >= run['budget']['wall_clock_hours'] or run['external_requests_used'] >= run['budget']['external_requests']
               or run['manual_review_items_used'] >= run['budget']['manual_review_items'],
               pause_reason='Overdue unknown maintenance is checkpointed; unresolved tasks remain open. Complete independent remote synchronization before continuing P3-P6 evidence work.',
               sync_state='Final canonical publication/readback are later events recorded in a separate receipt.', post_commit_verification_url=SYNC_URL,
               last_completed_batch='RUN7 performed only bound overdue-status maintenance; no new scientific claim, source query, or manual scientific review.', qa_completed_at_utc=finished)
    require(audit.run_accounting_projection(run) == cp['validation_results']['run_accounting_projection'], 'Finalization changes exceed the run whitelist')
    outputs[audit.RUN_PATH] = json_bytes(run)
    cp['status'] = 'valid'
    cp['coverage']['derived_views']['state'] = 'validated_seven_artifacts'
    for key in ('P3', 'P4', 'P5', 'P6'):
        cp['coverage']['phase_status'][key] = 'iterated_partial_checkpointed'
    cp['failure_reasons'] = [reason for reason in cp['failure_reasons'] if not reason.startswith('Invalid candidate')]
    cp['validation_results'].update(state='passed', data_audit='passed', determinism='passed', ui_validation='passed',
        final_artifact_hashes='verified', validation_completed_at_utc=finished, data_audit_errors=0,
        data_audit_warnings=data['warning_count'], seven_exports_byte_identical=True, ten_ui_checks_passed=True,
        existing_records_lost=0, audited_candidate_sha256=receipt['candidate_sha256'],
        finalization_run_whitelist=sorted(audit.RUN_FINALIZATION_FIELDS), qa_receipt_path='temp/validation/cp9-qa/qa-final-receipt.json')
    names = intended_file_set(repo) | set(outputs) | {audit.CP_PATH}
    cp['artifact_hashes'] = {name: audit.sha_bytes(outputs[name]) if name in outputs else audit.original.sha(repo / name)
                             for name in sorted(names - {audit.CP_PATH})}
    validate_checkpoint(repo, cp)
    outputs[audit.CP_PATH] = json_bytes(cp, True)
    return cp, outputs


def write_outputs(repo, outputs):
    fixed = {audit.CP_PATH, audit.RUN_PATH, REPORT_PATH, 'README.md', 'temp/progress.md', 'temp/change-log.md'}
    for name in outputs:
        require(name in fixed or name.startswith('temp/validation/cp9-'), 'Output outside the explicit CP9 finalization namespace: ' + name)
        audit.safe_relative(name)
    for name, raw in outputs.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.cp9-write')
        require(not temporary.exists(), 'Stale partial write exists: ' + str(temporary))
        temporary.write_bytes(raw)
        temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'finalize'])
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--qa-dir', type=Path, help='External QA directory; required for finalize')
    parser.add_argument('--ui-dir', type=Path, help='External UI evidence directory; defaults to QA/ui')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--plan-out', type=Path, help='Optional external JSON receipt; never a canonical output')
    args = parser.parse_args(); repo = args.repo.resolve()
    if args.plan_out and args.plan_out.resolve().is_relative_to(repo):
        parser.error('--plan-out must be outside the repository')
    state = collect(repo, datetime.now(timezone.utc))
    if args.mode == 'prepare':
        cp, outputs = candidate(state)
    else:
        if not args.qa_dir:
            parser.error('--qa-dir is required to finalize')
        qa = args.qa_dir.resolve(); ui = args.ui_dir.resolve() if args.ui_dir else qa / 'ui'
        if qa.is_relative_to(repo) or ui.is_relative_to(repo):
            parser.error('QA and UI evidence must be outside the repository')
        cp, outputs = finalize(state, qa, ui)
    if args.apply:
        write_outputs(repo, outputs)
        if cp['status'] == 'valid':
            require(intended_file_set(repo) == set(cp['artifact_hashes']) | {audit.CP_PATH}, 'Final artifact path set differs after write')
            for name, digest in cp['artifact_hashes'].items():
                require(audit.original.sha(repo / name) == digest, 'Final artifact bytes differ after write: ' + name)
    result = {'status': 'applied' if args.apply else 'preview', 'checkpoint_id': CP, 'checkpoint_status': cp['status'],
              'counts': state['counts'], 'outputs': {name: {'bytes': len(raw), 'sha256': audit.sha_bytes(raw)} for name, raw in outputs.items()},
              'research_closure_established': False, 'remote_verification_performed': False}
    if args.plan_out:
        args.plan_out.parent.mkdir(parents=True, exist_ok=True)
        args.plan_out.write_bytes(json_bytes(result))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
