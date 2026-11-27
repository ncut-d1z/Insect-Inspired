#!/usr/bin/env python3
"""Integrate only the committed RUN5 review candidates into the CP6 datasets.

The default is a read-only preview. --apply performs one bounded canonical
transaction; the caller must finish QA and publish it before further research.
No network request, entity inference, scientific review, or Git mutation occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker
from storage import read_logical, replace_logical
from checkpoint_cp7 import MUTABLE_IDS, latest_tasks, objects

ROOT = Path(__file__).resolve().parents[1]
CP, RUN, SCOPE = 'CP-0007', 'RUN-0005', 'SCOPE-0001'
CANDIDATES = [
    'temp/reports/RUN-0005-seed-reference-candidate.json',
    'temp/reports/RUN-0005-citation-candidate.json',
    'temp/reports/RUN-0005-author-work-candidates.json',
]
IDS = {
    **MUTABLE_IDS, 'assessments': 'assessment_id', 'queries': 'query_id',
    'manual-reviews': 'review_id', 'source-observations': 'observation_id',
    'work-relations': 'relation_id', 'discovery-paths': 'path_id',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def read_committed(repo, name):
    raw = (repo / name).read_bytes()
    saved = subprocess.check_output(['git', '-C', str(repo), 'show', 'HEAD:' + name])
    require(raw == saved, 'Unpublished or modified review input: ' + name)
    return json.loads(raw), {'path': name, 'bytes': len(raw), 'sha256': digest(raw)}


def merge_delta(before, after, current, location):
    """Combine independently reviewed append-only provenance, refusing conflicts."""
    if current == before:
        return deepcopy(after)
    if after == before or current == after:
        return deepcopy(current)
    if all(isinstance(x, dict) for x in (before, after, current)):
        out = deepcopy(current)
        for key in set(before) | set(after):
            if key not in after:
                require(current.get(key) == before.get(key),
                        'Concurrent removal conflict: ' + location + '/' + key)
                out.pop(key, None)
            elif key not in before:
                require(key not in current or current[key] == after[key],
                        'Concurrent added field conflict: ' + location + '/' + key)
                out[key] = deepcopy(after[key])
            else:
                require(key in current, 'Concurrent missing field: ' + location + '/' + key)
                out[key] = merge_delta(before[key], after[key], current[key], location + '/' + key)
        return out
    if all(isinstance(x, list) for x in (before, after, current)):
        require(all(x in after and x in current for x in before),
                'Concurrent non-additive list mutation: ' + location)
        return deepcopy(current) + [deepcopy(x) for x in after if x not in current]
    raise ValueError('Conflicting reviewed field values: ' + location)


def task(tid, entity_id, entity_type, source_id, qids, now, state='verified_complete',
         reason='Bounded recorded source operation; no broader coverage is inferred.'):
    return dict(task_id=tid, entity_type=entity_type, entity_id=entity_id,
                task_type='recorded_source_operation', scope_id=SCOPE, source_id=source_id,
                normalized_parameters={'run_id': RUN}, task_state=state,
                cursor=None, dependency_ids=[], query_ids=qids, attempt_count=1,
                error_code=None, failure_reason=None if state == 'verified_complete' else reason,
                retry_at=None, review_condition=reason, created_at_utc=now,
                updated_at_utc=now, checkpoint_id=CP, event_sequence=1,
                assessment_id=None, field_path=None, unknown_since_utc=None,
                deadline_at_utc=None, review_task_id=None, priority='normal',
                overdue=False, supporting_record_ids=qids)


def identity_index(data):
    index = defaultdict(set)
    for name in ('works', 'versions', 'aliases'):
        for row in data.get(name, []):
            wid = row.get('work_id') or (row.get('target_id') if row.get('entity_type') == 'work' else None)
            if not wid:
                continue
            values = list(row.get('identifiers', {}).values())
            values += [row.get('doi'), row.get('raw_identifier'), row.get('normalized_identifier')]
            for value in values:
                for token in value if isinstance(value, list) else [value]:
                    if token is not None:
                        token = str(token).strip().lower()
                        index[token].add(wid)
                        if token.startswith('https://doi.org/'):
                            index[token[16:]].add(wid)
                        if '/' in token and ('europepmc.org/' in token or 'pubmed.ncbi.nlm.nih.gov/' in token):
                            index[token.rstrip('/').rsplit('/', 1)[-1]].add(wid)
    return index


def source_record_ids(row):
    if row.get('id'):
        return str(row.get('source', 'MED')).upper() + ':' + str(row['id'])
    return row.get('doi') or row.get('url') or row.get('title')


def resolve_record(row, index):
    candidates = set()
    if row.get('id'):
        value = str(row['id']).lower()
        source = str(row.get('source', 'MED')).lower()
        for key in (value, source + ':' + value, source + '/' + value):
            candidates.update(index.get(key, set()))
    if not candidates and row.get('doi'):
        candidates.update(index.get(row['doi'].lower(), set()))
    return next(iter(candidates)) if len(candidates) == 1 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    repo, now = args.repo.resolve(), stamp()
    require(not (repo / 'temp/reports/RUN-0005-integration.json').exists(),
            'RUN5 integration already exists; do not apply it twice.')
    names = sorted(p.stem for p in (repo / 'temp').glob('*.jsonl'))
    data = {name: read_logical(name + '.jsonl', repo / 'temp') for name in names}
    counts_before = {name: len(rows) for name, rows in data.items()}
    baseline_query_ids = {x['query_id'] for x in data['queries']}
    baseline_manual_ids = {x['review_id'] for x in data['manual-reviews']}
    baseline_work_ids = {x['work_id'] for x in data['works']}
    baseline_assessment_raw = (repo / 'temp/assessments.jsonl').read_bytes()
    baseline_latest = latest_tasks(data['tasks'])
    for row in baseline_latest.values():
        if row.get('unknown_since_utc') and not row.get('overdue'):
            require(datetime.fromisoformat(row['deadline_at_utc'].replace('Z', '+00:00'))
                    > datetime.now(timezone.utc), 'Original unknown needs escalation before integration: ' + row['task_id'])
    indices = {name: {row[key]: i for i, row in enumerate(data[name])}
               for name, key in IDS.items() if name in data}
    changes, touched, bindings, inputs, new_by_query = {}, set(), [], [], {}
    queue = list(CANDIDATES)
    while queue:
        name = queue.pop(0)
        require(name not in inputs and name.startswith('temp/reports/RUN-0005'),
                'Duplicate or unexpected review part: ' + name)
        candidate, binding = read_committed(repo, name)
        inputs.append(name); bindings.append(binding)
        for part in candidate.get('candidate_parts', []):
            queue.append(part if isinstance(part, str) else part['path'])
        require(candidate.get('run_id') == RUN and candidate.get('checkpoint_id') == CP,
                'Candidate run/checkpoint mismatch: ' + name)
        for qid, ids in candidate.get('query_new_work_ids', {}).items():
            require(qid not in new_by_query or new_by_query[qid] == ids,
                    'New-Work query attribution conflict: ' + qid)
            new_by_query[qid] = ids
        for change in candidate.get('changed_records', []):
            dataset = change['dataset'].removesuffix('.jsonl')
            require(dataset in MUTABLE_IDS, 'Unapproved mutable dataset: ' + dataset)
            key, identifier = MUTABLE_IDS[dataset], change['id']
            position = indices[dataset][identifier]
            current = data[dataset][position]
            original = changes.get((dataset, identifier), {}).get('before', current)
            require(change['before'] == original, 'Review before-guard differs: ' + dataset + '/' + identifier)
            require(change['before'][key] == change['after'][key] == identifier, 'Identity mutation')
            merged = merge_delta(change['before'], change['after'], current, dataset + '/' + identifier)
            data[dataset][position] = merged
            changes[dataset, identifier] = dict(dataset=dataset, id=identifier,
                before=deepcopy(original), after=merged,
                changed_field_names=sorted(k for k in set(original) | set(merged)
                                          if original.get(k) != merged.get(k) or (k in original) != (k in merged)))
            touched.add(dataset)
        for dataset, rows in candidate.get('additions', {}).items():
            dataset = dataset.removesuffix('.jsonl')
            require(dataset in data, 'New unregistered logical dataset: ' + dataset)
            for row in rows:
                if dataset in IDS:
                    key = IDS[dataset]
                    require(row[key] not in indices[dataset], 'Duplicate addition: ' + dataset + '/' + row[key])
                    indices[dataset][row[key]] = len(data[dataset])
                data[dataset].append(deepcopy(row))
            if rows:
                touched.add(dataset)
    assessment_doc, binding = read_committed(repo, 'temp/reports/RUN-0005-assessment-candidate.json')
    bindings.append(binding)
    data['assessments'].append(assessment_doc['assessment'])
    data['tasks'].extend(assessment_doc['unknown_tasks'])
    touched.update(('assessments', 'tasks'))
    data['manual-reviews'].append(dict(
        review_id='MR-RUN05-Wasserman2015-Hx-odor-01', run_id=RUN,
        review_type='fulltext_claim_review',
        entity_id='AS-RUN05-Wasserman2015-L09-Hx-odor-response',
        reviewer='P6-RUN0005-joint-root-and-evidence-review',
        recorded_at_utc='2026-11-27T02:38:19.093465Z',
        artifact='temp/reports/RUN-0005-assessment-candidate.json',
        notes='One joint review: exact admitted S03 PDF, main methods and Fig3; n=13 and reported p<.05. '
              'Root independently inspected original rendered Fig3. Admitted quantity is the difference '
              'of peaks of group-mean traces, approximately 0.16 deltaF/F with graphical reading range '
              '0.12–0.19, not an individual-peak mean difference, relative percentage, SEM or CI. '
              'Old A-S03-L09-01 and original unknown clocks remain unchanged.'))
    touched.add('manual-reviews')
    index = identity_index(data)
    for path in sorted((repo / 'temp/query-results').glob('Q-RUN05*.json')):
        relative = str(path.relative_to(repo))
        receipt, binding = read_committed(repo, relative)
        bindings.append(binding)
        qid = receipt['query_id']
        require(qid not in indices['queries'], 'Receipt query already added: ' + qid)
        rows = receipt.get('records', [])
        cached_pdf = receipt.get('cache_hit') is True and receipt.get('version_id') == 'V-S03-01'
        failed = receipt['status'] in {'retryable_error', 'error', 'restricted'}
        exact = receipt.get('query_time_status', 'exact') == 'exact'
        tid = receipt.get('task_id') or 'T-RUN05-RECORDED-' + qid
        source = receipt['source_id']
        rawparams = receipt.get('raw_parameters') or (
            {'searches': receipt['queries']} if 'queries' in receipt else
            {'endpoint': receipt['endpoint_or_url'], 'version_id': receipt.get('version_id')})
        identifiers = ([receipt['version_id']] if cached_pdf else
                       list(dict.fromkeys(x for x in map(source_record_ids, rows) if x)))
        resolved = ([receipt['entity_id']] if cached_pdf else [resolve_record(row, index) for row in rows])
        returned = None if failed else (1 if cached_pdf else len(rows))
        dedup_count = None if failed or any(x is None for x in resolved) else len(set(resolved))
        new_ids = sorted(set(new_by_query.get(qid, [])))
        require(all(x not in baseline_work_ids and x in indices['works'] for x in new_ids),
                'Incorrect new-Work attribution: ' + qid)
        q = dict(query_id=qid, task_id=tid, scope_id=SCOPE, checkpoint_id=CP,
            entity_id=receipt['entity_id'], source_id=source,
            endpoint_or_url=receipt.get('endpoint_or_url') or 'web-search://official-bibliographic-records',
            api_version='6.9' if source == 'europepmc' else None,
            query_kind=receipt.get('query_kind') or ('official_bibliographic_identity_review'
                        if source == 'web_search' else 'forward_citation_list'),
            raw_parameters=rawparams,
            normalized_parameters={**rawparams, 'run_id': RUN,
                'count_scope': 'retained bibliographic records; count_after_dedup is unique unambiguous canonical Works'},
            queried_at_utc=receipt.get('queried_at_utc'), cursor_in=receipt.get('cursor_in'),
            cursor_out=receipt.get('cursor_out'), page_index=receipt.get('page_index', 1),
            page_complete=bool(receipt.get('page_complete', False)) and exact and not failed,
            visible_total=receipt.get('visible_total', 1 if cached_pdf else None),
            returned_count=returned, count_before_dedup=returned, count_after_dedup=dedup_count,
            new_work_ids=new_ids, new_work_count=len(new_ids), result_identifiers=identifiers,
            status=('error' if failed else 'partial' if not exact else
                    'cache_hit' if receipt.get('cache_hit') else 'success'),
            verification_status='source_supported' if not cached_pdf else 'verified',
            error_code=receipt.get('error_code'), error_message=receipt.get('error_message'),
            retry_count=0, retry_at=None, cache_path=relative,
            cache_hit=bool(receipt.get('cache_hit')), reused_query_id=receipt.get('reused_query_id'),
            rerun_reason=receipt.get('rerun_reason'), coverage_note=(
                receipt.get('coverage_note', 'The retained source page is separate from Work identity, actual citation context, and fulltext coverage.')
                + ' ' + receipt.get('index_drift_note', '')
                + ' Failed or ambiguous counts remain null; source enumeration never proves research closure.'),
            license_note=receipt['license_note'], recorded_at_utc=receipt.get('recorded_at_utc') or
                receipt.get('completed_at_utc') or receipt.get('queried_at_utc') or now,
            query_time_status='exact' if exact else 'unavailable_exact')
        if not exact:
            q['verification_status'] = 'source_supported'
            q['queried_date'] = q['recorded_at_utc'][:10]
        unknown_fields = [k for k in ('returned_count', 'count_before_dedup', 'count_after_dedup')
                          if q[k] is None]
        if failed:
            unknown_fields.append('visible_total')
        if unknown_fields:
            review_id = 'T-RUN05-QUERY-REVIEW-' + qid
            since = receipt.get('queried_at_utc') or q['recorded_at_utc']
            reason = ('The source operation failed; the unobserved result is not zero.' if failed else
                      'One or more returned identities cannot yet be mapped to a unique canonical Work; source counts remain separately visible.')
            q['field_states'] = {key: dict(status='unknown', reason=reason, evidence_locator=[],
                unknown_since_utc=since, review_task_id=review_id) for key in unknown_fields}
            review = task(review_id, SCOPE, 'scope', source, [qid], now,
                          'retryable_error' if failed else 'needs_disambiguation', reason)
            review.update(task_type='field_review', field_path='queries.' + qid + '.' + ','.join(unknown_fields),
                          unknown_since_utc=since, deadline_at_utc=(
                              datetime.fromisoformat(since.replace('Z', '+00:00')) + timedelta(hours=24)
                          ).isoformat().replace('+00:00', 'Z'),
                          review_task_id=review_id, error_code=q['error_code'])
            data['tasks'].append(review)
        data['queries'].append(q)
        indices['queries'][qid] = len(data['queries']) - 1
        data['source-observations'].append(dict(
            observation_id='OBS-' + qid, query_id=qid, task_id=tid, source_id=source,
            endpoint_or_url=q['endpoint_or_url'], queried_at_utc=q['queried_at_utc'],
            query_time_status=q['query_time_status'], status=q['status'],
            http_status=receipt.get('http_status'), response_kind=q['query_kind'],
            returned_count=returned, visible_total=q['visible_total'], page_complete=q['page_complete'],
            count_scope=q['coverage_note'], receipt_path=relative, receipt_sha256=binding['sha256'],
            verification_status=q['verification_status'], recorded_at_utc=q['recorded_at_utc'],
            external_request_performed=bool(receipt['external_requests_performed']),
            cache_hit=q['cache_hit'], source_search_query_count=receipt.get('search_query_count')))
    touched.update(('queries', 'source-observations', 'tasks'))
    latest = latest_tasks(data['tasks'])
    query_tasks = defaultdict(list)
    for q in data['queries']:
        if q['query_id'] not in baseline_query_ids:
            query_tasks[q['task_id']].append(q)
    for tid, rows in query_tasks.items():
        qids = [q['query_id'] for q in rows]
        if tid not in latest:
            entity = rows[0]['entity_id']
            entity_type = 'work' if entity.startswith('W-') else 'person' if entity.startswith('P-') else 'scope'
            successful = all(q['status'] in {'success', 'cache_hit'} for q in rows)
            event = task(tid, entity, entity_type, rows[0]['source_id'], qids, now,
                         'verified_complete' if successful else 'partial')
            data['tasks'].append(event); latest[tid] = event
        else:
            old = latest[tid]
            missing = [qid for qid in qids if qid not in old['query_ids']]
            if missing:
                event = deepcopy(old)
                event.update(event_sequence=old['event_sequence'] + 1, checkpoint_id=CP,
                             updated_at_utc=now, query_ids=old['query_ids'] + missing)
                data['tasks'].append(event); latest[tid] = event
    latest_tasks(data['tasks'])
    schema = json.loads((repo / 'temp/schema.json').read_text())
    schema_checks = 0
    for name in touched:
        kind = schema['x-entity-files'].get(name + '.jsonl')
        if not kind:
            continue
        validator = Draft202012Validator({'$ref': '#/$defs/' + kind, '$defs': schema['$defs']},
                                        format_checker=FormatChecker())
        rows = data[name][counts_before[name]:]
        rows += [x['after'] for x in changes.values() if x['dataset'] == name]
        for row in rows:
            errors = list(validator.iter_errors(row))
            require(not errors, 'Integration schema error in ' + name + ': ' +
                    '; '.join(e.message for e in errors[:3]))
            schema_checks += 1
    new_queries = [x for x in data['queries'] if x['query_id'] not in baseline_query_ids]
    new_qids = {x['query_id'] for x in new_queries}
    observations = [x for x in data['source-observations'] if x.get('query_id') in new_qids]
    require(Counter(x['query_id'] for x in observations) == Counter({qid: 1 for qid in new_qids}),
            'Each new query must have exactly one invocation/cache observation.')
    run = json.loads((repo / 'temp/runs/RUN-0005.json').read_text())
    run.update(external_requests_used=sum(x['external_request_performed'] for x in observations),
               cache_reuse_events=sum(x['cache_hit'] for x in new_queries),
               manual_review_items_used=sum(x['review_id'] not in baseline_manual_ids for x in data['manual-reviews']),
               last_completed_batch='P3 two reference iterations; P4 nine citation lists and exact identities; P5 five official-author outputs plus correction; P6 distinct Hx odor response',
               next_batch='Complete CP7 QA and full independent remote verification before further research.',
               sync_state='canonical_transaction_pending_publication')
    require(run['manual_review_items_used'] <= run['budget']['manual_review_items'], 'Manual budget exceeded')
    require(run['external_requests_used'] <= run['budget']['external_requests'], 'External budget exceeded')
    report = dict(run_id=RUN, checkpoint_id=CP, scope_id=SCOPE, created_at_utc=now,
        status='integrated_pending_full_qa_and_remote_sync', baseline_checkpoint_id='CP-0006',
        reviewed_input_bindings=bindings, counts_before=counts_before,
        counts_after={name: len(rows) for name, rows in data.items()},
        changed_records=list(changes.values()), query_new_work_ids=new_by_query,
        new_query_rows=len(new_queries), external_requests=run['external_requests_used'],
        cache_reuse_events=run['cache_reuse_events'], manual_review_activities=run['manual_review_items_used'],
        schema_checks=schema_checks, scientific_gate_inherited=False, research_closure=False,
        preservation_note='All old events and assessments retained. Reviewed mutable changes have complete before/after records. Full audit remains required.')
    preview = dict(apply=args.apply, changed_datasets=sorted(touched), changed_records=len(changes),
                   new_works=len(data['works']) - counts_before['works'],
                   new_queries=len(new_queries), manual_reviews=run['manual_review_items_used'],
                   external_requests=run['external_requests_used'], cache_reuses=run['cache_reuse_events'],
                   schema_records_checked=schema_checks)
    if args.apply:
        for name in sorted(touched):
            if name == 'assessments':
                require(name + '.jsonl' not in json.loads((repo / 'temp/partitions/manifest.json').read_text())['datasets'],
                        'Use an explicit append plan for partitioned assessments.')
                raw = baseline_assessment_raw + b''.join(jbytes(x) for x in data[name][counts_before[name]:])
                require(len(raw) <= 4 * 1024 * 1024, 'Assessment dataset needs a new explicit partition.')
                (repo / 'temp/assessments.jsonl').write_bytes(raw)
            else:
                replace_logical(name + '.jsonl', data[name], repo / 'temp')
        (repo / 'temp/runs/RUN-0005.json').write_text(json.dumps(run, ensure_ascii=False, indent=2) + '\n')
        (repo / 'temp/reports/RUN-0005-integration.json').write_bytes(jbytes(report))
    print(json.dumps(preview, ensure_ascii=False))


if __name__ == '__main__':
    main()
