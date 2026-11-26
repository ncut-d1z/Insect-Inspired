#!/usr/bin/env python3
"""Build a CP6 INVALID candidate from complete logical canonical datasets.

Default: private preview only. --apply writes exactly the six documented paths.
No imports, research, exports, remote writes or valid-checkpoint promotion.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(__file__).resolve().parent
sys.path.insert(0, '/workspace/scratch/9d487ee78414/p3p6_work')
from storage import read_logical

CP, RUN, PARENT = 'CP-0006', 'RUN-0004', 'CP-0005'
BASE_COMMIT = '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
BASE_TREE = '27b8ac91e5e86fca891dc24e0f08134aaab96ebd'
SYNC_URL = 'https://github.com/ncut-d1z/Insect-Inspired/blob/sync/cp6-checkpoint-import/temp/sync/CP-0006/verification.json'
CP_PATH = 'temp/snapshots/checkpoints/CP-0006.json'
REPORT_PATH = 'temp/reports/P3-P6-CP0006.md'
INTEGRATION_PATH = 'temp/reports/RUN-0004-integration.json'
SCIENCE_PATH = 'temp/reports/RUN-0004-Jung2011-adaptation-review.json'
ALLOWED = {CP_PATH, REPORT_PATH, 'temp/progress.md', 'temp/change-log.md',
           'README.md', 'temp/runs/RUN-0004.json'}
FROZEN = [f'temp/snapshots/checkpoints/CP-{i:04d}.json' for i in range(1, 6)] + [
    'temp/snapshots/scope.json', 'temp/snapshots/scopes/SCOPE-0001.json', 'temp/seed-manifest.jsonl']
NAMES = ['works', 'versions', 'authors', 'reference-occurrences', 'tasks', 'queries',
         'citation-edges', 'discovery-paths', 'assessments', 'manual-reviews',
         'source-observations', 'organizations', 'projects', 'aliases', 'work-relations',
         'uploads', 'seed-manifest', 'reference-coverage', 'source-list-coverage']
MUTABLE = {'works': 'work_id', 'versions': 'version_id', 'authors': 'person_id',
           'reference-occurrences': 'occurrence_id', 'source-list-coverage': 'coverage_id'}
TERMINAL = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
DIMENSIONS = ['metadata', 'fulltext', 'abstract', 'references', 'citations',
              'authors', 'affiliations_projects', 'assessment']
EXPORTS = ['ref.bib', 'ref.html', 'temp/exports/citation_graph.json',
           'temp/exports/evidence_matrix.csv', 'temp/exports/research_entities.json',
           'temp/exports/research_implications.csv', 'temp/exports/research_paths.json']


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def input_digest(snapshot):
    return sha_bytes(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False).encode('utf-8'))


def json_text(value, compact=False):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      **({'separators': (',', ':')} if compact else {'indent': 2})) + '\n'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'Timestamp must include a timezone')
    return result.astimezone(timezone.utc)


def git_bytes(repo, relative):
    path = PurePosixPath(relative)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe Git blob path')
    return subprocess.run(['git', '-C', str(repo), 'show', BASE_COMMIT + ':' + str(path)],
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def baseline_rows(repo, name, manifest):
    entry = manifest['datasets'].get(name + '.jsonl')
    parts = entry['parts'] if entry else [{'path': name + '.jsonl'}]
    total, logical_hash = 0, hashlib.sha256()
    for part in parts:
        raw = git_bytes(repo, 'temp/' + part['path'])
        lines = [line for line in raw.splitlines(keepends=True) if line.strip()]
        if entry:
            require(sha_bytes(raw) == part['sha256'] and len(raw) == part['bytes']
                    and len(lines) == part['records'], 'Frozen partition differs: ' + name)
        logical_hash.update(raw)
        total += len(lines)
        for line in lines:
            yield json.loads(line), line
    if entry:
        require(total == entry['logical_records'] and logical_hash.hexdigest() == entry['logical_sha256'],
                'Frozen logical manifest differs: ' + name)


def frozen_hashes(repo):
    tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', BASE_COMMIT + '^{tree}'], text=True).strip()
    require(tree == BASE_TREE, 'CP5 Git tree differs')
    hashes = {}
    for name in FROZEN:
        digest = sha_bytes(git_bytes(repo, name))
        require(sha(repo / name) == digest, 'Frozen historical file changed: ' + name)
        hashes[name] = digest
    return hashes


def file_snapshot(repo, names):
    return {name: {'bytes': (repo / name).stat().st_size, 'sha256': sha(repo / name)}
            for name in sorted(names)}


def verify_snapshot(repo, snapshot):
    for name, expected in snapshot.items():
        path = repo / name
        require(path.is_file() and path.stat().st_size == expected['bytes']
                and sha(path) == expected['sha256'], 'Input changed: ' + name)


def latest_tasks(rows):
    result = {}
    for row in rows:
        previous = result.get(row['task_id'])
        require(previous is None or row['event_sequence'] != previous['event_sequence'],
                'Duplicate latest task sequence: ' + row['task_id'])
        if previous is None or row['event_sequence'] > previous['event_sequence']:
            result[row['task_id']] = row
    return result


def objects(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        elif isinstance(item, list):
            stack.extend(v for v in item if isinstance(v, (dict, list)))


def preserve_baseline(repo, data, integration, manifest):
    changes = integration.get('changed_records')
    require(isinstance(changes, list), 'Integration must contain complete changed_records')
    declared = {}
    for event in changes:
        name, key = event['dataset'], event['id']
        require(name in MUTABLE, 'Unexpected mutable dataset: ' + name)
        require((name, key) not in declared, 'Duplicate declared change: ' + str((name, key)))
        before, after = event['before'], event['after']
        field = MUTABLE[name]
        require(before[field] == after[field] == key, 'Changed record identity differs')
        fields = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)
                        or (k in before) != (k in after))
        require(fields == sorted(event['changed_field_names']), 'changed_field_names differs: ' + key)
        require(fields, 'Empty declared mutation: ' + key)
        declared[name, key] = event
    seen, checks, counts_before, old_latest = set(), [], {}, {}
    old_files, old_reviewed, old_assessment_ids = set(), set(), set()
    old_person_ids, old_work_ids, resolved_ids = set(), set(), []
    old_query_ids, old_manual_ids, old_edge_ids = set(), set(), set()
    current_assessment_lines = {}
    current_manifest = read_json(repo / 'temp/partitions/manifest.json')
    entry = current_manifest['datasets'].get('assessments.jsonl')
    for part in entry['parts'] if entry else [{'path': 'assessments.jsonl'}]:
        for line in (repo / 'temp' / part['path']).read_bytes().splitlines(keepends=True):
            if line.strip():
                aid = json.loads(line)['assessment_id']
                require(aid not in current_assessment_lines, 'Duplicate Assessment ID')
                current_assessment_lines[aid] = line
    for name in NAMES:
        rows, changed, count = data[name], [], 0
        for index, (old, old_line) in enumerate(baseline_rows(repo, name, manifest)):
            require(index < len(rows), 'Old records lost from ' + name)
            new = rows[index]
            count += 1
            if name in MUTABLE:
                key_field = MUTABLE[name]
                key = old[key_field]
                require(new.get(key_field) == key, 'Old record order/identity differs: ' + name)
                if old != new:
                    event = declared.get((name, key))
                    require(event is not None and event['before'] == old and event['after'] == new,
                            'Actual old-record change lacks exact before/after: ' + str((name, key)))
                    seen.add((name, key)); changed.append(key)
                if name == 'reference-occurrences':
                    require(all(old[k] == new[k] for k in ['raw_reference', 'raw_fingerprint']),
                            'Original reference text/fingerprint changed: ' + key)
                    if not old.get('cited_work_id') and new.get('cited_work_id'):
                        resolved_ids.append(key)
            else:
                require(old == new, 'Old record/event prefix changed: ' + name + ':' + str(index))
            if name == 'assessments':
                require(current_assessment_lines.get(old['assessment_id']) == old_line,
                        'Old Assessment line bytes changed: ' + old['assessment_id'])
                old_assessment_ids.add(old['assessment_id'])
                if old['assessment_status'] == 'active': old_reviewed.add(old['work_id'])
            elif name == 'versions': old_files.update(f['sha256'] for f in old.get('file_records', []))
            elif name == 'works': old_work_ids.add(old['work_id'])
            elif name == 'authors': old_person_ids.add(old['person_id'])
            elif name == 'queries': old_query_ids.add(old['query_id'])
            elif name == 'manual-reviews': old_manual_ids.add(old['review_id'])
            elif name == 'citation-edges': old_edge_ids.add(old['edge_id'])
            elif name == 'tasks':
                tid = old['task_id']
                if tid not in old_latest or old['event_sequence'] > old_latest[tid]['event_sequence']:
                    old_latest[tid] = {k: old.get(k) for k in ['event_sequence', 'task_state', 'task_type',
                        'unknown_since_utc', 'deadline_at_utc', 'overdue', 'normalized_parameters', 'entity_id']}
        counts_before[name] = count
        checks.append({'dataset': name, 'old_records': count, 'new_records': len(rows),
                       'missing_records': 0, 'added_records': len(rows) - count,
                       'changed_existing_ids': changed, 'expected_changes_only': True,
                       'old_order_preserved': True})
    require(seen == set(declared), 'Declared changes do not equal actual canonical differences')
    return dict(checks=checks, counts_before=counts_before, old_latest=old_latest,
                old_files=old_files, old_reviewed=old_reviewed, old_assessment_ids=old_assessment_ids,
                old_person_ids=old_person_ids, old_work_ids=old_work_ids, resolved_ids=resolved_ids,
                old_query_ids=old_query_ids, old_manual_ids=old_manual_ids, old_edge_ids=old_edge_ids)


def export_inventory(repo):
    result = []
    for name in EXPORTS:
        path = repo / name
        require(path.is_file(), 'Required CP6 export missing: ' + name)
        item = {'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)}
        if name.endswith('.json'):
            value = read_json(path)
            require(value['checkpoint_id'] == CP, 'Export checkpoint differs: ' + name)
            key = {'citation_graph.json': 'nodes', 'research_entities.json': 'relations',
                   'research_paths.json': 'paths'}[path.name]
            item.update(records=len(value[key]), record_basis=key)
        elif name.endswith('.csv'):
            with path.open(encoding='utf-8', newline='') as handle: rows = list(csv.DictReader(handle))
            require(all(row['checkpoint_id'] == CP for row in rows), 'CSV checkpoint differs: ' + name)
            item.update(records=len(rows), record_basis='rows')
        result.append(item)
    return result


def collect(repo, now):
    temp = repo / 'temp'
    frozen = frozen_hashes(repo)
    parent = read_json(temp / 'snapshots/checkpoints/CP-0005.json')
    require(parent['status'] == 'valid', 'CP5 must remain valid')
    require(read_json(temp / 'snapshots/checkpoints/CP-0003.json')['status'] == 'invalid', 'CP3 history changed')
    scope, run = read_json(temp / 'snapshots/scope.json'), read_json(temp / 'runs/RUN-0004.json')
    integration, science = read_json(repo / INTEGRATION_PATH), read_json(repo / SCIENCE_PATH)
    require(run['run_id'] == RUN and run['start_checkpoint_id'] == PARENT
            and run['start_commit_sha'] == BASE_COMMIT and run['scope_id'] == scope['scope_id'] == 'SCOPE-0001', 'Run baseline differs')
    require(integration['run_id'] == RUN and integration['checkpoint_id'] == CP
            and integration['scope_id'] == scope['scope_id'], 'Integration identity differs')
    require(science['run_id'] == RUN and science['intended_checkpoint_id'] == CP, 'Scientific report identity differs')
    manifest = read_json(temp / 'partitions/manifest.json')
    input_names = {'temp/partitions/manifest.json', 'temp/schema.json', INTEGRATION_PATH, SCIENCE_PATH, *FROZEN}
    logical_names = sorted(p.name for p in temp.glob('*.jsonl'))
    for name in logical_names:
        input_names.add('temp/' + name)
        for part in manifest['datasets'].get(name, {}).get('parts', []):
            path = (temp / part['path']).resolve()
            require(path.is_relative_to(temp.resolve()), 'Partition path escapes temp')
            input_names.add(str(path.relative_to(repo)))
    inputs = file_snapshot(repo, input_names)
    data = {Path(name).stem: read_logical(name, base=temp) for name in logical_names}
    for name, entry in manifest['datasets'].items():
        h, total = hashlib.sha256(), 0
        for part in entry['parts']:
            raw = (temp / part['path']).read_bytes()
            require(sha_bytes(raw) == part['sha256'] and len(raw) == part['bytes'], 'Current partition mismatch: ' + name)
            count = sum(bool(line.strip()) for line in raw.splitlines())
            require(count == part['records'], 'Current partition count mismatch: ' + name)
            h.update(raw); total += count
        require(total == entry['logical_records'] == len(data[Path(name).stem])
                and h.hexdigest() == entry['logical_sha256'], 'Current logical manifest mismatch: ' + name)
    base = preserve_baseline(repo, data, integration, json.loads(git_bytes(repo, 'temp/partitions/manifest.json')))
    for key, count in integration['counts_before'].items():
        require(key in base['counts_before'] and count == base['counts_before'][key], 'Integration counts_before differs: ' + key)
    for key, count in integration['counts_after'].items():
        require(key in data and count == len(data[key]), 'Integration counts_after differs: ' + key)
    latest = latest_tasks(data['tasks'])
    works = data['works']; work_by_id = {w['work_id']: w for w in works}
    require(len(work_by_id) == len(works), 'Duplicate Work ID')
    active = [a for a in data['assessments'] if a['assessment_status'] == 'active']
    eligible = [a for a in active if a['evidence_admission_status'] == 'eligible']
    insufficient = [a for a in active if a['evidence_admission_status'] == 'insufficient_evidence']
    new_claims = [a for a in data['assessments'] if a['assessment_id'] not in base['old_assessment_ids']]
    require({a['assessment_id'] for a in new_claims} == {science['assessment']['assessment_id']}
            and new_claims[0] == science['assessment'], 'Only the exact reviewed Jung independent claim may be added')
    require(new_claims[0]['limitation_id'] == 'L03' and new_claims[0]['handling_level'] != 'fully_resolved', 'Jung claim scope/handling differs')
    topics = {f'L{i:02}': {a['work_id'] for a in eligible if a['limitation_id'] == f'L{i:02}'} for i in range(1, 10)}
    union = set().union(*topics.values())
    require(union <= set(work_by_id), 'Topic contains an unknown Work')
    seeds = [s for s in data['seed-manifest'] if s['record_type'] == 'seed_mapping']
    seed_work_ids = {s['work_id'] for s in seeds}
    seed_authors = {a['person_id'] for wid in seed_work_ids for a in work_by_id[wid]['authors']}
    files = {f['sha256'] for v in data['versions'] for f in v.get('file_records', [])}
    reviewed = {a['work_id'] for a in active}
    queries = [q for q in data['queries'] if q['query_id'].startswith('Q-RUN04-')]
    require({q['query_id'] for q in queries} == {q['query_id'] for q in data['queries']} - base['old_query_ids'], 'New query prefix does not reconcile')
    require(all(q['checkpoint_id'] == CP for q in queries), 'RUN4 query checkpoint differs')
    qids = {q['query_id'] for q in queries}
    observations = [o for o in data['source-observations'] if o.get('query_id') in qids]
    require(Counter(o['query_id'] for o in observations) == Counter({q: 1 for q in qids}), 'New queries require one explicit invocation/cache observation each')
    require(all(isinstance(o.get('external_request_performed'), bool) for o in observations), 'New observation lacks explicit external-request flag')
    external = sum(o['external_request_performed'] for o in observations)
    cache = sum(q.get('cache_hit') is True for q in queries)
    cache_ids = {q['query_id'] for q in queries if q.get('cache_hit') is True}
    require(all(not o['external_request_performed'] for o in observations if o['query_id'] in cache_ids), 'Cache incorrectly counted as HTTP')
    manual = [m for m in data['manual-reviews'] if m['run_id'] == RUN]
    require({m['review_id'] for m in manual} == {m['review_id'] for m in data['manual-reviews']} - base['old_manual_ids'], 'New manual ledger does not reconcile')
    old_latest = base['old_latest']
    closed = [tid for tid, old in old_latest.items() if old['task_type'] == 'field_review'
              and old['task_state'] not in TERMINAL and latest[tid]['task_state'] == 'verified_complete']
    escalated = [tid for tid, t in latest.items() if t.get('unknown_since_utc') and t.get('overdue') is True
                 and (tid not in old_latest or old_latest[tid].get('overdue') is not True)]
    unknown_open = [t for t in latest.values() if t.get('unknown_since_utc') and t['task_state'] not in TERMINAL]
    overdue = [t for t in unknown_open if t.get('deadline_at_utc') and utc(t['deadline_at_utc']) <= now]
    for tid, old in old_latest.items():
        new = latest[tid]
        if old.get('unknown_since_utc') and new['task_state'] not in TERMINAL:
            require(new.get('unknown_since_utc') == old['unknown_since_utc']
                    and new.get('deadline_at_utc') == old['deadline_at_utc'], 'Unknown clock reset: ' + tid)
    unknown_states = Counter(obj['status'] for rows in data.values() for row in rows for obj in objects(row)
        if obj.get('status') in {'unknown', 'unknown_review_required'}
        and ('unknown_since_utc' in obj or 'review_task_id' in obj))
    new_people = {a['person_id'] for a in data['authors']} - base['old_person_ids']
    person_works = {pid: set() for pid in new_people}
    for w in works:
        for author in w['authors']:
            if author['person_id'] in person_works: person_works[author['person_id']].add(w['work_id'])
    require(all(len(ids) == 1 for ids in person_works.values()), 'New Work-scoped Person reused across Works or orphaned')
    new_edges = [e for e in data['citation-edges'] if e['edge_id'] not in base['old_edge_ids']]
    metadata_fields = {'canonical_title', 'title_variants', 'authors', 'document_type',
        'publication_status', 'year', 'publication_date', 'venue', 'volume', 'number',
        'pages', 'eid', 'publisher', 'identifiers', 'doi', 'url', 'language',
        'discovery_sources', 'identity_confidence', 'verification_status'}
    enriched_work_ids = {event['id'] for event in integration['changed_records']
        if event['dataset'] == 'works' and metadata_fields.intersection(event['changed_field_names'])}
    derived = dict(new_work_records=len(set(work_by_id) - base['old_work_ids']),
                   new_work_scoped_person_records=len(new_people), new_reference_resolutions=len(base['resolved_ids']),
                   new_source_supported_edges=sum(e.get('verification_status') == 'source_supported' for e in new_edges),
                   new_assessments=len(new_claims), new_external_invocations=external,
                   cache_reuses=cache, manual_review_activities=len(manual),
                   unknown_field_tasks_closed=len(closed), overdue_unknown_tasks_escalated=len(escalated))
    for key, count in derived.items(): require(integration[key] == count, 'Integration claimed delta differs: ' + key)
    for field, count in [('external_requests_used', external), ('cache_reuse_events', cache), ('manual_review_items_used', len(manual))]:
        require(run[field] == count, 'Run accounting differs: ' + field)
    require(run['paid_spend'] == 0, 'Paid spend is outside the authorized budget')
    require(external <= run['budget']['external_requests'] and len(manual) <= run['budget']['manual_review_items'],
            'Recorded activity exceeds the authorized RUN4 request/manual budget')
    coverage_rows = data['source-list-coverage']
    author_cov = [c for c in coverage_rows if c['entity_id'] in seed_authors and c['source_id'] == 'semantic_scholar']
    origin = run['first_batch']['origin_work_id']
    project_rows = [c for c in coverage_rows if c['entity_id'] == origin and c['source_id'] == 'europepmc']
    require(len(project_rows) == 1, 'Ambiguous project citing-list coverage')
    project = project_rows[0]
    identity_tasks = [t for tid, t in latest.items() if tid.startswith('T-CP4-CiterIdentity-MED-')]
    old_identity = [t for tid, t in old_latest.items() if tid.startswith('T-CP4-CiterIdentity-MED-')]
    other_core = project['distinct_count'] - len(identity_tasks)
    require(other_core >= 0 and len(old_identity) == len(identity_tasks), 'Project identity task universe changed')
    epmc = other_core + sum(t['normalized_parameters'].get('epmc_core_success') is True for t in identity_tasks)
    cross = other_core + sum(t['task_state'] == 'verified_complete' and
        (t['normalized_parameters'].get('epmc_core_success') is True or t['normalized_parameters'].get('identity_via_pubmed') is True)
        for t in identity_tasks)
    old_core = other_core + sum(t['normalized_parameters'].get('epmc_core_success') is True for t in old_identity)
    old_cross = other_core + sum(t['task_state'] == 'verified_complete' and
        (t['normalized_parameters'].get('epmc_core_success') is True or t['normalized_parameters'].get('identity_via_pubmed') is True)
        for t in old_identity)
    require(old_core == parent['coverage']['sources']['project_epmc_core_metadata']
            and old_cross == parent['coverage']['sources']['project_identity_cross_source'], 'Project baseline denominator does not reconcile')
    pending_identity = sum(t['task_state'] not in TERMINAL for t in identity_tasks)
    initial = [latest['T-CP4-CiterIdentity-MED-' + str(p)] for p in run['first_batch']['pending_identity_ids']]
    resolved_this_run = sum(t['task_state'] == 'verified_complete' for t in initial)
    uploads = {u['upload_id']: u for u in data['uploads']}
    absolute = [a for a in active if (a['claims_absolute_scale'].get('value') if isinstance(a['claims_absolute_scale'], dict) else a['claims_absolute_scale']) is True]
    counts = dict(seed_records=len(seeds), canonical_works=len(works), versions=len(data['versions']),
        retained_uploads=len(data['uploads']), distinct_seed_pdf_sha256=len({uploads[s['upload_id']]['sha256'] for s in seeds}),
        distinct_files=len(files), file_backed_versions=sum(bool(v['file_records']) for v in data['versions']),
        people_records=len(data['authors']), organizations=len(data['organizations']), projects=len(data['projects']),
        reference_occurrences=len(data['reference-occurrences']), resolved_occurrences=sum(bool(o['cited_work_id']) for o in data['reference-occurrences']),
        unresolved_occurrences=sum(not o['cited_work_id'] for o in data['reference-occurrences']), citation_edges=len(data['citation-edges']),
        context_reviewed_edges=sum(bool(e['context_locators']) and any(r != 'unknown' for r in e['citation_roles']) for e in data['citation-edges']),
        assessments=len(active), eligible_claims=len(eligible), insufficient_claims=len(insufficient), counter_evidence_claims=sum(a['counter_evidence'] for a in active),
        fully_resolved_claims=sum(a['handling_level'] == 'fully_resolved' for a in active), topic_work_union=len(union), u00_works=len(works) - len(union),
        task_events=len(data['tasks']), unique_tasks=len(latest), unresolved_tasks=sum(t['task_state'] not in TERMINAL for t in latest.values()),
        queries=len(data['queries']), exact_query_timestamps=sum(q.get('query_time_status', 'exact') == 'exact' for q in data['queries']),
        unavailable_exact_query_timestamps=sum(q.get('query_time_status') == 'unavailable_exact' for q in data['queries']),
        merged_work_pairs=len(data.get('work-merge-events', [])), seed_reference_occurrences=sum(o['citing_work_id'] in seed_work_ids and not o['occurrence_id'].startswith('R-CR-') for o in data['reference-occurrences']),
        iteration2_reviewed_reference_occurrences=len(data.get('new-fulltext-reference-audit', [])), scientific_fulltext_works_reviewed=len(reviewed),
        run4_new_scientific_fulltext_works=len(reviewed - base['old_reviewed']), run4_new_fulltext_files=len(files - base['old_files']),
        seed_s2_lists_reconciled=sum(c['entity_id'] in seed_work_ids and c['source_id'] == 'semantic_scholar' and c['total_reconciled'] for c in coverage_rows),
        seed_epmc_lists_reconciled=sum(c['entity_id'] in seed_work_ids and c['source_id'] == 'europepmc' and c['total_reconciled'] for c in coverage_rows),
        seed_authors=len(seed_authors), seed_author_lists_paginated=sum(c['pagination_complete'] for c in author_cov), seed_author_lists_reconciled=sum(c['total_reconciled'] for c in author_cov),
        manual_review_activities=len(data['manual-reviews']), run4_manual_review_activities=len(manual), run4_external_requests=external, run4_cache_reuses=cache,
        run4_query_rows=len(queries), run4_reference_resolutions=len(base['resolved_ids']), run4_unknown_field_tasks_closed=len(closed),
        run4_overdue_unknown_tasks_escalated=len(escalated), run4_existing_works_enriched=len(enriched_work_ids),
        unknown_fields=sum(unknown_states.values()), open_unknown_review_tasks=len(unknown_open), overdue_open_unknown_review_tasks=len(overdue),
        cascade_events=len(data.get('cascade-events', [])), rejected_upload_events=sum(s.get('record_type') == 'rejected_upload' for s in data['seed-manifest']))
    counts.update({key + '_works': len(value) for key, value in topics.items()})
    delta = {key: count - parent['counts'][key] for key, count in counts.items() if key in parent['counts']}
    coverage = {dim: {'denominator': len(works), 'states': dict(Counter(w['dimension_status'][dim] for w in works))} for dim in DIMENSIONS}
    coverage.update(phase_status={**{f'P{i}': 'completed' for i in range(3)}, **{f'P{i}': 'iterated_partial_candidate_pending_validation' for i in range(3, 7)}, 'P7': 'not_started_final_research_acceptance', 'P8': 'not_triggered'},
        closure={'established': False, 'reason': 'Unresolved tasks, source identity/access/count gaps and evidence limits remain; checkpoint validation is not research closure.'},
        fulltext_meaning={'scientific_fulltext_works_reviewed': len(reviewed), 'run4_new_works': len(reviewed - base['old_reviewed']), 'run4_new_files': len(files - base['old_files']), 'scope': 'Distinct Works with active claim reviews; a cached additional claim does not imply complete Work/supplement coverage.'},
        scientific_gates={'eligible': len(eligible), 'insufficient': len(insufficient), 'counter_evidence': counts['counter_evidence_claims'], 'fully_resolved': counts['fully_resolved_claims'], 'cp5_assessments_preserved': len(base['old_assessment_ids']), 'absolute_scale_claims': len(absolute), 'absolute_scale_eligible': sum(a['evidence_admission_status'] == 'eligible' for a in absolute), 'absolute_scale_insufficient': sum(a['evidence_admission_status'] == 'insufficient_evidence' for a in absolute), 'rejection_codes': dict(Counter(code for a in insufficient for code in a['rejection_codes']))},
        sources={'project_citation_list_returned': project['distinct_count'], 'project_citation_list_total': project['visible_total'], 'project_epmc_core_metadata': epmc, 'project_identity_cross_source': cross, 'project_identity_pending': pending_identity, 'run4_identity_target_count': len(initial), 'run4_identity_resolved': resolved_this_run, 'seed_author_total': len(seed_authors), 'seed_author_lists_paginated': counts['seed_author_lists_paginated'], 'seed_author_lists_reconciled': counts['seed_author_lists_reconciled'], 'index_snapshot_historical': False},
        reconciliation={'K': len(works), 'T_union': len(union), 'U': len(works) - len(union), 'T_i': {k: len(v) for k, v in topics.items()}, 'multi_label_sum_is_not_independent_work_count': True},
        task_states=dict(Counter(t['task_state'] for t in latest.values())), queries=dict(Counter(q.get('query_time_status', 'exact') for q in data['queries'])),
        run4_accounting={**derived, 'query_rows': len(queries), 'new_fulltext_works': len(reviewed - base['old_reviewed']), 'new_fulltext_files': len(files - base['old_files'])},
        unknown_review={'field_states': dict(unknown_states), 'open_tasks': len(unknown_open), 'overdue_open_tasks': len(overdue), 'closed_field_tasks_this_run': len(closed), 'overdue_escalations_this_run': len(escalated), 'original_clocks_preserved': True}, delta_from_cp5=delta,
        synchronization={'recorded_at_utc': now.isoformat().replace('+00:00', 'Z'), 'canonical_snapshot_at_checkpoint_write': 'pending_final_validation_and_post_commit_remote_verification', 'research_gate': 'closed_until_final_sync_verified', 'post_commit_verification_url': SYNC_URL, 'historical_state_note': 'This snapshot-time pending observation does not imply a later sync failure; later verification is recorded separately without rewriting the frozen checkpoint.'})
    exports = export_inventory(repo)
    coverage['derived_views'] = {'state': 'generated_pending_complete_audit', 'artifacts': exports}
    verify_snapshot(repo, inputs)
    return dict(repo=repo, now=now, parent=parent, scope=scope, run=run, integration=integration,
                science=science, counts=counts, coverage=coverage, latest=latest, delta=delta, inputs=inputs,
                frozen=frozen, exports=exports, derived=derived,
                preservation={'status': 'passed', 'checkpoint_id': CP, 'baseline_commit': BASE_COMMIT,
                    'verified_at_utc': now.isoformat().replace('+00:00', 'Z'), 'method': 'All 19 complete logical datasets compared with exact CP5 Git blobs in manifest order; mutable changes equal complete declared before/after records.',
                    'checks': base['checks'], 'raw_reference_text_and_fingerprints_preserved': True,
                    'old_scientific_assessments_preserved': len(base['old_assessment_ids']), 'existing_records_lost': 0})


def documents(state, valid=False, qa=None):
    c, cov, d = state['counts'], state['coverage'], state['derived']
    now, science, claim = state['now'], state['science'], state['science']['assessment']
    local_now = now.astimezone(ZoneInfo('Asia/Singapore'))
    stamp = local_now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC+8 (Asia/Singapore)'
    source = cov['sources']
    state_word = 'valid 数据检查点' if valid else 'invalid 候选，完整验收待完成'
    acceptance = ('完整数据审计 0 错误、' + str(qa['warning_count']) + ' 项已报告警告；七产物字节一致，十项 UI 通过。'
                  if valid else '完整数据审计、七产物确定性、十项 UI 和最终 artifact hashes 尚待验收。')
    table_fields = [('canonical_works','规范 Work'),('versions','Version'),('people_records','署名身份记录'),
        ('reference_occurrences','参考出现项'),('resolved_occurrences','已解析出现项'),('unresolved_occurrences','未解析出现项'),
        ('citation_edges','引用边'),('context_reviewed_edges','已核科学语境的边'),('assessments','活动主张'),
        ('eligible_claims','合格主张'),('insufficient_claims','不足主张'),('counter_evidence_claims','含反证主张'),
        ('topic_work_union','主题 Work 并集'),('u00_works','U00 Work'),('task_events','任务事件'),
        ('unique_tasks','最新任务'),('unresolved_tasks','未结任务'),('queries','查询记录'),('manual_review_activities','人工复核')]
    table = '\n'.join(f'| {label} | {state["parent"]["counts"][key]:,} | {c[key]:,} | {state["delta"][key]:+,} |' for key,label in table_fields)
    dimensions = '\n'.join('| '+dim+' | '+str(cov[dim]['denominator'])+' | '+json.dumps(cov[dim]['states'], ensure_ascii=False, sort_keys=True)+' |' for dim in DIMENSIONS)
    metrics = '\n'.join('| '+str(m['metric_id'])+' | '+str(m.get('value'))+' | '+str(m.get('unit'))+' | '+str(m.get('sample_count'))+' |' for m in claim['metric_records'])
    methods, finding = science['verified_methods'], science['verified_finding']
    views = '\n'.join(f'| `{e["path"]}` | {e["bytes"]:,} | `{e["sha256"]}` |' for e in state['exports'])
    sync = f'本检查点写入时，最终 canonical 提交、推送及独立远端回读尚未发生；后置证明固定保存在 [verification.json]({SYNC_URL})。这是快照创建时的历史说明，不能据此推断之后同步失败；冻结检查点不因后置同步回执改写。最终远端验证通过前停止下一研究批。'
    report = f'''# P3–P6 阶段进展：{CP}

## 1. 当前状态和范围

**SCOPE-0001 / {RUN} / {CP}：{state_word}。** 有效父检查点为 {PARENT}；CP1–CP5、scope 和种子清单八文件原字节保留，其中 CP3 保持 invalid 历史。P3–P6 为 iterated partial；研究闭包未成立，P7 最终研究验收未启动，P8 未触发。

统计时刻 {stamp}；文献截止仍为 {state['scope']['cutoff_at_utc']}。{acceptance}

{sync}

## 2. 相对 CP5 的规范全集对账

| 指标 | CP5 | CP6 | 净变化 |
| --- | ---: | ---: | ---: |
{table}

数量均取完整逻辑数据与最新任务，不以 integration 报告声明代替实测。19 个逻辑数据集逐记录比较，旧记录丢失为 0；实际可变记录修改均与完整 before/after 一致，旧事件前缀保留。原 {cov['scientific_gates']['cp5_assessments_preserved']} 条 Assessment 连同各条 JSONL 原始行完全不变。

## 3. 本轮推进及保留边界

P3：现有 Work 书目身份修改 {c['run4_existing_works_enriched']} 条；新 Work {d['new_work_records']}；既有参考出现项解析 {d['new_reference_resolutions']}；新 source_supported 边 {d['new_source_supported_edges']}。引用身份和登记边不代表正文科学引用语境完成。

P4：本批精确 PMID 目标 {source['run4_identity_target_count']} 项，已关闭身份 {source['run4_identity_resolved']} 项。项目施引列表仍为 {source['project_citation_list_returned']}/{source['project_citation_list_total']}；EPMC core {source['project_epmc_core_metadata']}/{source['project_citation_list_total']}，跨来源身份 {source['project_identity_cross_source']}/{source['project_citation_list_total']}，仍待身份 {source['project_identity_pending']}。来源失败、游标和原始失败回执继续保留。

P5：新增 {d['new_work_scoped_person_records']} 条 Work 限定署名身份；不按姓名自动跨 Work 合并。种子作者列表分页 {c['seed_author_lists_paginated']}/{c['seed_authors']}、总量对账 {c['seed_author_lists_reconciled']}/{c['seed_authors']}；消歧、历史机构及项目归属仍以各任务真实状态为准。

P6：唯一新科学记录来自 [Jung2011 单主张人工复核](RUN-0004-Jung2011-adaptation-review.json)，主张 `{claim['claim_id']}`，局限性 `{claim['limitation_id']}`，处理程度 `{claim['handling_level']}`。既有科学记录不被替换或升级；fully_resolved 当前 {c['fully_resolved_claims']}。

### Jung2011 Fig. 6b 的条件与数值

原始 DOI {science['source']['doi']}；缓存版本 `{science['source']['version_id']}`；PDF SHA `{science['source']['sha256']}`。对象为 {methods['scientific_name']}、{methods['sex']}、{methods['cell']}；固定制备中的非飞行/系留飞行状态。适应运动 {methods['adaptation_duration_s']} s、{methods['adaptation_temporal_frequency_hz']} Hz，适应结束 {methods['post_adapter_test_delay_s']} s 后测试。

| 原记录指标 ID | 平均响应衰减常数 | 单位 | 该图组样本数（不可逐行相加） |
| --- | ---: | --- | ---: |
{metrics}

图组总样本为 {finding['n']} {finding['n_unit']}；不确定性：{finding['uncertainty']}。检验方法：{finding['test']}，精确 P 值状态 `{finding['exact_p_value_status']}`。解释限于所测脉冲响应衰减估计及其模型映射，不等于直接测得生物高通器件。{claim['remaining_limitations']}

生物含义：{claim['biological_implications']} 工程含义：{claim['engineering_implications']}

既有逐主张全文审阅 Work {c['scientific_fulltext_works_reviewed']}，本轮新增审阅 Work {c['run4_new_scientific_fulltext_works']}、新增文件 {c['run4_new_fulltext_files']}；缓存上增加一个主张不会重复计全文 Work，也不意味着整篇全部主张或补充材料已完成。

## 4. 覆盖、未知项、任务和预算

| 维度 | Work 分母 | 全部状态分布 |
| --- | ---: | --- |
{dimensions}

K={c['canonical_works']}，T_union={c['topic_work_union']}，U={c['u00_works']}；T_i=`{json.dumps(cov['reconciliation']['T_i'], ensure_ascii=False, sort_keys=True)}`。跨主题行数不能相加当独立 Work。

关闭字段 unknown 工单 {d['unknown_field_tasks_closed']}，本轮逾期升级 {d['overdue_unknown_tasks_escalated']}；未结任务净变化 {state['delta']['unresolved_tasks']:+,}，不能把关闭工单数当净减少数。开放 unknown 工单 {c['open_unknown_review_tasks']:,}，到期仍开放 {c['overdue_open_unknown_review_tasks']:,}；字段/共享投影状态对象共 {c['unknown_fields']:,}，该数不是独立工单数。原始时钟保留，完整审计检查24小时升级规则。

本轮查询 {c['run4_query_rows']}：外部科研调用 {d['new_external_invocations']}/{state['run']['budget']['external_requests']}；缓存 {d['cache_reuses']} 次另计；手工活动 {d['manual_review_activities']}/{state['run']['budget']['manual_review_items']}；付费 {state['run']['paid_spend']}；墙钟预算 {state['run']['budget']['wall_clock_hours']} 小时。本次验收暂停不意味着预算耗尽。

不足主张 {c['insufficient_claims']}，拒收代码分布 `{json.dumps(cov['scientific_gates']['rejection_codes'], ensure_ascii=False, sort_keys=True)}`。绝对尺度主张 {cov['scientific_gates']['absolute_scale_claims']}，合格 {cov['scientific_gates']['absolute_scale_eligible']}、不足 {cov['scientific_gates']['absolute_scale_insufficient']}；本批 Jung 条目不提供绝对尺度或平台速度恢复结论。

## 5. 导出、验收和继续条件

| 产物 | 字节 | SHA-256 |
| --- | ---: | --- |
{views}

{acceptance} 全部原科学门禁保留，S19 仍仅原来的一个历史例外；新增条目不能遮盖旧不足或反证。预检查不能代替完整数据审计。任务闭包还要求固定点、分页及计数核对、全部适用任务终结或有证据的不适用；来源失败和缺失全文不能据无增长判为完成。

验收依据：[集成报告](RUN-0004-integration.json)、[增量保留](../validation/cp6-delta-preservation.json)、[完整审计](../validation/cp6-data-audit.json)、[七产物确定性](../validation/cp6-determinism.json)、[十项 UI](../validation/cp6-ui-validation.json)、[原始 QA 凭据](../validation/cp6-qa/qa-final-receipt.json)、[CP6](../snapshots/checkpoints/CP-0006.json)。候选阶段尚未生成的验收链接须待实际报告归档，不能视为已通过。
'''
    progress = f'''# 当前执行进度：{CP}

更新时间：{stamp}。**SCOPE-0001 / {RUN} / {CP}：{state_word}。** 父检查点 {PARENT}；CP3 invalid 历史保留。{acceptance}

P3–P6 继续部分推进，研究闭包未成立，P7 未启动，P8 未触发。

- 规范 Work {c['canonical_works']:,}；活动 Assessment {c['assessments']}：合格 {c['eligible_claims']}、不足 {c['insufficient_claims']}、反证 {c['counter_evidence_claims']}；新增 Jung L03 单主张，全部既有科学记录保持不变。
- 本批 PMID 身份 {source['run4_identity_resolved']}/{source['run4_identity_target_count']}；项目跨来源 {source['project_identity_cross_source']}/{source['project_citation_list_total']}，仍待 {source['project_identity_pending']}。EPMC core 单列 {source['project_epmc_core_metadata']}/{source['project_citation_list_total']}。
- 新 Work 限定署名 {d['new_work_scoped_person_records']}；种子作者分页 {c['seed_author_lists_paginated']}/{c['seed_authors']}、计数对账 {c['seed_author_lists_reconciled']}/{c['seed_authors']}。
- 参考解析 {d['new_reference_resolutions']}，新来源支持边 {d['new_source_supported_edges']}；引用语境完成量 {c['context_reviewed_edges']}，不与书目边混计。
- K={c['canonical_works']}，T_union={c['topic_work_union']}，U={c['u00_works']}；全文审阅 Work {c['scientific_fulltext_works_reviewed']}，本批新增 Work/文件 {c['run4_new_scientific_fulltext_works']}/{c['run4_new_fulltext_files']}。
- 未结任务 {c['unresolved_tasks']:,}（相对 CP5 {state['delta']['unresolved_tasks']:+,}）；关闭 unknown 工单 {d['unknown_field_tasks_closed']}，逾期升级 {d['overdue_unknown_tasks_escalated']}，开放 unknown {c['open_unknown_review_tasks']:,}。
- 外部科研调用 {d['new_external_invocations']}、缓存复用 {d['cache_reuses']}、手工 {d['manual_review_activities']}；均据真实账本，缓存不计 HTTP。

{sync}

详见 [本轮阶段报告](reports/P3-P6-CP0006.md)、[CP6](snapshots/checkpoints/CP-0006.json)、[父 CP5](snapshots/checkpoints/CP-0005.json)及[集成证据](reports/RUN-0004-integration.json)。有效数据检查点也不等于研究闭包。
'''
    pointer = f'执行状态统一记录于 [进度追踪](temp/progress.md)；阶段验收见 [P1/P2 报告](temp/reports/P1-P2.md)。P3–P6 当前阶段报告见 [CP-0006 报告](temp/reports/P3-P6-CP0006.md)，[CP-0006](temp/snapshots/checkpoints/CP-0006.json) 为{state_word}；有效父检查点为 [CP-0005](temp/snapshots/checkpoints/CP-0005.json)。CP-0003 保留为 invalid 历史。后置同步证明见阶段报告所链接的独立 verification receipt。本节定义阶段门禁，不另行维护执行状态。'
    readme, n = re.subn(r'^执行状态统一记录于 \[进度追踪\].*$', lambda _: pointer, (state['repo'] / 'README.md').read_text(encoding='utf-8'), flags=re.MULTILINE)
    require(n == 1, 'README status pointer not unique')
    start, end = '<!-- CP6-CHECKPOINT-START -->', '<!-- CP6-CHECKPOINT-END -->'
    section = f'{start}\n## {CP} / {RUN} / {local_now.date()} UTC+8 · {state_word}\n\nPMID 身份本批完成 {source["run4_identity_resolved"]}/{source["run4_identity_target_count"]}；新 Work {d["new_work_records"]}、署名身份 {d["new_work_scoped_person_records"]}、参考解析 {d["new_reference_resolutions"]}、source_supported 边 {d["new_source_supported_edges"]}。Jung 独立 L03 单主张新增，原科学记录完整保留。unknown 关闭 {d["unknown_field_tasks_closed"]}、逾期升级 {d["overdue_unknown_tasks_escalated"]}。外部 {d["new_external_invocations"]}、缓存 {d["cache_reuses"]}、人工 {d["manual_review_activities"]}。{acceptance} 研究闭包未成立；最终同步由提交后的外部回读证明。\n{end}'
    change = (state['repo'] / 'temp/change-log.md').read_text(encoding='utf-8')
    if start in change:
        change, n = re.subn(re.escape(start) + r'.*?' + re.escape(end), lambda _: section, change, flags=re.DOTALL)
        require(n == 1, 'CP6 change-log section not unique')
    else: change = change.rstrip() + '\n\n' + section + '\n'
    return {REPORT_PATH: report, 'temp/progress.md': progress, 'README.md': readme, 'temp/change-log.md': change}


def validate_checkpoint(repo, cp):
    schema = read_json(repo / 'temp/schema.json')
    errors = list(Draft202012Validator({'$ref': '#/$defs/checkpoint', '$defs': schema['$defs']}, format_checker=FormatChecker()).iter_errors(cp))
    require(not errors, 'Checkpoint schema errors: ' + str([(list(e.path), e.message) for e in errors[:8]]))


def write_outputs(repo, outputs):
    require(set(outputs) == ALLOWED, 'Canonical output whitelist differs')
    for name in sorted(outputs, key=lambda name: name == CP_PATH):
        path = repo / name
        require(path.resolve().is_relative_to(repo.resolve()), 'Output escapes canonical repo')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[name], encoding='utf-8')


def candidate(state):
    repo, stamp = state['repo'], state['now'].isoformat().replace('+00:00', 'Z')
    path = repo / CP_PATH
    created = stamp
    if path.exists():
        old = read_json(path)
        require(old['status'] == 'invalid', 'Never replace or downgrade a valid CP6')
        created = old['created_at_utc']
    c, cov = state['counts'], state['coverage']
    failures = ['Candidate invalid until complete data audit, seven-export determinism, ten-check UI and final artifact hashes pass.',
        'Research closure remains open; unresolved tasks, missing original text and source/identity/count gaps retain their true cursors.',
        'Jung Fig6b admission is confined to reported response-decay estimates, conditions and uncertainty; no universal mechanism or fully-resolved claim is inferred.',
        'At snapshot creation final canonical publication/readback has not occurred; post-commit verification is recorded separately.']
    # created_at is historical identity; every refresh gets a distinct freeze.
    frozen_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    validation = {'state': 'data_audit_pending', 'checkpoint_self_hash_excluded': True, 'git_internal_files_excluded': True,
        'frozen_parent_bytes_unchanged': True, 'frozen_scope_and_seed_unchanged': True, 'frozen_baseline_sha256': state['frozen'],
        'canonical_input_hashes': state['inputs'], 'baseline_commit': BASE_COMMIT, 'baseline_tree': BASE_TREE,
        'input_frozen_at_utc': frozen_at, 'canonical_input_digest_sha256': input_digest(state['inputs']),
        'integration_report_sha256': sha(repo / INTEGRATION_PATH), 'scientific_review_sha256': sha(repo / SCIENCE_PATH),
        'data_audit': 'pending', 'determinism': 'pending', 'ui_validation': 'pending', 'final_artifact_hashes': 'pending',
        'final_remote_verification': 'post_commit_external_receipt_required', 'post_commit_verification_url': SYNC_URL,
        'research_closure_established': False, 'cp5_scientific_records_unchanged': cov['scientific_gates']['cp5_assessments_preserved']}
    cp = dict(checkpoint_id=CP, scope_id='SCOPE-0001', parent_checkpoint_id=PARENT,
        schema_version=state['parent']['schema_version'], created_at_utc=created,
        task_cursor_state={tid: {f: t.get(f) for f in ['event_sequence', 'task_state', 'cursor', 'query_ids', 'attempt_count', 'error_code', 'failure_reason', 'retry_at', 'review_condition']} for tid,t in sorted(state['latest'].items())},
        query_log_high_watermark=c['queries'], counts=c, coverage=cov,
        unresolved_tasks=sorted(tid for tid,t in state['latest'].items() if t['task_state'] not in TERMINAL),
        failure_reasons=failures, artifact_hashes={}, validation_results=validation, status='invalid')
    validate_checkpoint(repo, cp)
    run = dict(state['run'])
    run.update(status='checkpointing', end_checkpoint_id=CP, checkpoint_status='invalid', checkpoint_validation_state='data_audit_pending',
               checkpoint_candidate_created_at_utc=created, post_commit_verification_url=SYNC_URL)
    outputs = documents(state)
    outputs[CP_PATH] = json_text(cp, True); outputs['temp/runs/RUN-0004.json'] = json_text(run)
    return cp, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT / 'insect-project')
    parser.add_argument('--apply', action='store_true', help='Write exactly the six authorized canonical paths')
    args = parser.parse_args(); repo = args.repo.resolve()
    state = collect(repo, datetime.now(timezone.utc)); cp, outputs = candidate(state)
    verify_snapshot(repo, state['inputs'])
    if args.apply: write_outputs(repo, outputs)
    for name, expected in state['frozen'].items(): require(sha(repo / name) == expected, 'Historical bytes changed')
    for name, value in [('final-counts.json', state['counts']), ('final-coverage.json', state['coverage']),
                        ('cp6-delta-preservation.json', state['preservation'])]:
        (PRIVATE / name).write_text(json_text(value), encoding='utf-8')
    receipt = {'status': 'invalid_candidate_generated' if args.apply else 'private_candidate_preview_passed',
        'checkpoint_id': CP, 'counts': state['counts'], 'delta_from_cp5': state['delta'], 'schema_errors': 0,
        'artifact_hashes_count': 0, 'canonical_written': args.apply, 'canonical_write_whitelist': sorted(ALLOWED),
        'prepared_outputs': {name: {'bytes': len(text.encode()), 'sha256': sha_bytes(text.encode())} for name,text in outputs.items()},
        'logical_datasets_written': False, 'exports_written': False, 'research_requests': 0, 'remote_write_performed': False}
    (PRIVATE / 'checkpoint-generation.json').write_text(json_text(receipt), encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'counts': state['counts'], 'receipt': str(PRIVATE / 'checkpoint-generation.json')}, ensure_ascii=False))


if __name__ == '__main__': main()
