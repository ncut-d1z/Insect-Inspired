"""One RUN-0004 integration from already published, independently reviewed receipts.

No network calls. Existing CP5 records are retained; additions and every changed
record are explicitly reconciled. Run exactly once, then export/audit/publish CP6.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from copy import deepcopy
from collections import Counter
from urllib.parse import quote
import hashlib
import json
import re
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path('/workspace/scratch/2e518600ca4c')
REPO = ROOT / 'insect-project'
TEMP = REPO / 'temp'
sys.path.insert(0, str(ROOT / 'cp4_work'))
from storage import read_logical, replace_logical

CP, RUN, SCOPE = 'CP-0006', 'RUN-0004', 'SCOPE-0001'
BASE = '82f759ce71e7b532f03cd4ba54a1fcc77c4f4006'
ACTUAL_NOW = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
recovery_path = TEMP / 'reports/RUN-0004-runtime-recovery.json'
recovery = json.loads(recovery_path.read_text()) if recovery_path.exists() else None
if recovery:
    assert recovery['run_id'] == RUN and recovery['checkpoint_id'] == CP
    assert recovery['recovery_kind'] == 'replay_already_reviewed_events_after_runtime_loss'
    assert recovery['published_source_commit'] == 'e82f0c3d31777edffb767218745035433e8a5238'
    # This was the observed time of the original successful integration. Reuse
    # it only for those already-reviewed events and their unknown-field clocks.
    NOW = recovery['original_integration_at_utc']
    assert NOW == '2026-11-26T16:58:00.155120Z'
    assert datetime.fromisoformat(NOW.replace('Z', '+00:00')) <= datetime.fromisoformat(ACTUAL_NOW.replace('Z', '+00:00'))
else:
    NOW = ACTUAL_NOW
OUT = TEMP / 'reports/RUN-0004-integration.json'
assert not OUT.exists(), 'One-shot RUN-0004 integration has already run'
assert not subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain=v1', '--untracked-files=all']).strip(), 'Start from published clean receipts'
head = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
remote = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'origin/research/p3-p6-cp6'], text=True).strip()
assert head == remote, 'Published source receipts are a prerequisite'
TERMINAL = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
NAMES = ['works', 'versions', 'authors', 'tasks', 'queries', 'source-observations',
         'source-list-coverage', 'reference-occurrences', 'citation-edges',
         'discovery-paths', 'manual-reviews', 'assessments']
ID_FIELDS = {'works': 'work_id', 'versions': 'version_id', 'authors': 'person_id',
             'source-observations': 'observation_id', 'source-list-coverage': 'coverage_id',
             'reference-occurrences': 'occurrence_id', 'citation-edges': 'edge_id',
             'discovery-paths': 'discovery_id', 'manual-reviews': 'review_id',
             'assessments': 'assessment_id', 'queries': 'query_id'}
data = {n: read_logical(n + '.jsonl', TEMP) for n in NAMES}
before_counts = {n: len(v) for n, v in data.items()}
old_assessments = deepcopy(data['assessments'])
assert len(old_assessments) == 69
works = {w['work_id']: w for w in data['works']}
versions = {v['version_id']: v for v in data['versions']}
people = {p['person_id']: p for p in data['authors']}
old_people = tuple(data['authors'])
latest = {}
for t in data['tasks']:
    if t['task_id'] not in latest or t['event_sequence'] > latest[t['task_id']]['event_sequence']:
        latest[t['task_id']] = t
changed_records, events, conflicts = [], [], []


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def change(name, before, after):
    if before != after:
        changed_records.append(dict(dataset=name, id=before[ID_FIELDS[name]], before=before,
                                    after=deepcopy(after), changed_field_names=sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))))


def task(tid, entity, kind, state, reason, entity_type='work', **changes):
    old = latest.get(tid)
    if old:
        t = deepcopy(old)
        t['event_sequence'] += 1
    else:
        t = dict(task_id=tid, entity_type=entity_type, entity_id=entity, task_type=kind,
                 scope_id=SCOPE, source_id=None, normalized_parameters={}, task_state=state,
                 cursor=None, dependency_ids=[], query_ids=[], attempt_count=0,
                 error_code=None, failure_reason=None, retry_at=None, review_condition='',
                 created_at_utc=NOW, updated_at_utc=NOW, checkpoint_id=CP, event_sequence=1,
                 assessment_id=None, field_path=None, unknown_since_utc=None,
                 deadline_at_utc=None, review_task_id=None, priority='normal', overdue=False,
                 supporting_record_ids=[])
    t.update(task_state=state, review_condition=reason,
             failure_reason=None if state in TERMINAL else reason,
             updated_at_utc=NOW, checkpoint_id=CP)
    t.update(changes)
    data['tasks'].append(t)
    latest[tid] = t
    return t


def unknown(entity, field, locs, reason, entity_type='work'):
    tid = 'T-Unknown-' + h(entity + '|' + field)
    old = latest.get(tid)
    since = old['unknown_since_utc'] if old else NOW
    assert since and (not old or old['task_state'] not in TERMINAL)
    task(tid, entity, 'field_review', 'pending', reason, entity_type, field_path=field,
         unknown_since_utc=since, review_task_id=tid,
         deadline_at_utc=(datetime.fromisoformat(since.replace('Z', '+00:00')) + timedelta(hours=24)).isoformat().replace('+00:00', 'Z'))
    return dict(status='unknown', reason=reason, evidence_locator=locs,
                unknown_since_utc=since, review_task_id=tid)


def reported(obj, field, loc, qid):
    old = obj.get('field_states', {}).get(field)
    if old and old.get('review_task_id'):
        t = latest[old['review_task_id']]
        assert t['task_state'] not in TERMINAL
        task(t['task_id'], t['entity_id'], t['task_type'], 'verified_complete',
             'This exact bibliographic field is now supported by the retained official record; broader Work/Person coverage remains open.',
             t['entity_type'], query_ids=list(dict.fromkeys(t['query_ids'] + [qid])),
             attempt_count=t['attempt_count'] + 1, error_code=None)
    locs = list(old.get('evidence_locator', [])) if old and old.get('status') == 'reported' else []
    if loc not in locs:
        locs.append(loc)
    obj.setdefault('field_states', {})[field] = dict(status='reported', reason='Explicit official bibliographic field; retrieval method is disclosed in its receipt.', evidence_locator=locs, unknown_since_utc=None, review_task_id=None)


def norm_name(name):
    return re.sub(r'[^\w]+', '', name.casefold())


receipts = {}
for path in sorted((TEMP / 'query-results').glob('Q-RUN04-*.json')):
    r = json.loads(path.read_text())
    if r.get('external_requests_performed', 0) or r.get('external_request_performed'):
        assert r.get('sanitized') and not r.get('payload_retained')
        receipts[r['query_id']] = r
review_path = TEMP / 'reports/RUN-0004-identity-review.json'
review = json.loads(review_path.read_text())
assert review['status'] == 'reviewed'
snapshot = review['input_snapshot']
assert hashlib.sha256((TEMP / 'partitions/manifest.json').read_bytes()).hexdigest() == snapshot['partition_manifest_sha256'], 'Reviewed logical snapshot changed'
subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', snapshot['git_head'], head], check=True)
for name, count in snapshot['logical_counts_scanned'].items():
    assert len(data[name.removesuffix('.jsonl')]) == count, ('Reviewed input count changed', name)
assert {x['query_id'] for x in snapshot['source_receipt_hashes']} == set(receipts)
for spec in snapshot['source_receipt_hashes']:
    raw = (TEMP / 'query-results' / (spec['query_id'] + '.json')).read_bytes()
    assert len(raw) == spec['bytes'] and hashlib.sha256(raw).hexdigest() == spec['sha256'], ('Reviewed receipt changed', spec['query_id'])
reference_reviews = {x['occurrence_id']: x for x in review['reference_reviews']}
assert len(reference_reviews) == len(review['reference_resolution_ids'])
assert set(reference_reviews) == set(review['reference_resolution_ids'])
original_occurrences = {x['occurrence_id']: x for x in data['reference-occurrences']}
reference_source_times = {}
for oid, rr in reference_reviews.items():
    original = original_occurrences[oid]
    for field in ['citing_work_id', 'candidate_ids', 'reference_label', 'raw_reference', 'raw_fingerprint']:
        assert original[field] == rr[field], ('Reviewed reference changed', oid, field)
    assert original['version_id'] == rr['citing_version_id']
    assert versions[original['version_id']]['work_id'] == original['citing_work_id']
    assert original['cited_work_id'] is None
    assert all(original['source'].get(k) == v for k, v in rr['source'].items())
    source_raw = (TEMP / 'query-results' / (rr['source_query_id'] + '.json')).read_bytes()
    assert hashlib.sha256(source_raw).hexdigest() == rr['source_query_receipt_sha256']
    source_receipt = json.loads(source_raw)
    assert source_receipt['body_sha256'] == rr['source_response_body_sha256']
    reference_source_times[oid] = source_receipt['queried_at_utc']
approved = {str(r['pmid']): r for r in review['records']}
run = json.loads((TEMP / 'runs/RUN-0004.json').read_text())
pending_ids = run['first_batch']['pending_identity_ids']
assert set(approved) == set(pending_ids), 'Review must account for every selected pending identity'
successful = {}
new_person_ids, enriched_work_ids = [], []
for pmid, decision in approved.items():
    qids = decision.get('successful_query_ids', [])
    if not qids:
        continue
    candidates = [receipts[q] for q in qids]
    assert all(r['status'] == 'success' and r.get('metadata', {}).get('pmid') == pmid for r in candidates)
    r = candidates[0]
    m = decision['preferred_metadata']
    assert set(decision['field_query_ids']) == set(m)
    for field, qid in decision['field_query_ids'].items():
        assert qid in qids and receipts[qid]['metadata'][field] == m[field], ('Field evidence differs from reviewed receipt', pmid, field)
    assert m['pmid'] == pmid and m['doi']
    wid = decision['work_id']
    assert wid in works and decision['work_key'] == works[wid]['work_key']
    assert all(x['entity_id'] == wid for x in candidates)
    assert all(x.get('doi', '').lower() != m['doi'].lower() or x['work_id'] == wid for x in works.values() if x.get('doi'))
    w, before = works[wid], deepcopy(works[wid])
    assert w.get('doi') in (None, '', m['doi'])
    assert norm_name(m['title']) in {norm_name(t) for t in [w['canonical_title']] + w['title_variants']}, 'Identity title differs; adjudicate before integration'
    sid = r.get('underlying_source_id') or r['source_id']
    assert sid == 'institutional_repository', 'This batch admits official PubMed bibliographic evidence only'
    indexed = r['source_id'] == 'web_search'
    loc = dict(source_id=sid, url=r['endpoint_or_url'], identifier=r['query_id'],
               accessed_at=r['queried_at_utc'], section='Official PubMed indexed bibliographic header' if indexed else 'Official PubMed bibliographic header and byline',
               evidence_note='Exact PMID/DOI/title/byline reviewed. ' + ('Indexed official metadata; no new origin article-body fetch is asserted. Per-field provenance and any official publisher/PMC corroboration are retained in this receipt metadata_field_evidence/source_locators and the identity review field_source_refs.' if indexed else 'Readable bibliographic record; not a scientific fulltext review.'))
    src = dict(source_id=sid, url=r['endpoint_or_url'], identifier='MED:' + pmid,
               accessed_at=r['queried_at_utc'], verification_status='source_supported',
               license='Bibliographic facts and original review only; no original abstract/fulltext redistribution.', evidence_locator=[loc])
    names = m.get('authors', [])
    assert names, 'No author list may be inferred from absent evidence'
    if w['authors']:
        assert len(w['authors']) == len(names)
        assert all(norm_name(a['display_name']) == norm_name(b.get('display_name', b.get('full_name', ''))) for a, b in zip(w['authors'], names)), 'Do not replace an unresolved byline'
        preserved_authors = deepcopy(w['authors'])
    else:
        for pos, item in enumerate(names, 1):
            name = item.get('display_name', item.get('full_name'))
            pid = 'P-R' + h(wid + '|' + str(pos) + '|' + name)
            assert pid not in people
            person = dict(person_id=pid, display_name=name, name_variants=[name], orcid=None,
                          external_ids={}, identity_confidence='probable', verification_status='source_supported',
                          affiliation_history=[], sources=[src], field_states={})
            person['field_states']['orcid'] = unknown(pid, 'orcid', [loc], 'No ORCID-to-this-authorship linkage established; same-name records are only candidates.', 'person')
            people[pid] = person
            data['authors'].append(person)
            new_person_ids.append(pid)
            same_name = sorted(p['person_id'] for p in old_people if norm_name(p['display_name']) == norm_name(name) or norm_name(name) in [norm_name(n) for n in p['name_variants']])
            task('T-author_disambiguation-' + pid, pid, 'author_disambiguation', 'pending',
                 'Resolve this Work-scoped authorship with identifiers, coauthors and dated affiliation evidence. Names alone do not establish global identity.', 'person', source_id=sid, query_ids=qids,
                 normalized_parameters={'work_id': wid, 'author_position': pos, 'same_name_candidate_ids': same_name})
            ar = dict(person_id=pid, display_name=name, is_corporate=False, organization_ids=[], source=src)
            ar['field_states'] = {'organization_ids': unknown(wid, 'authors.' + str(pos) + '.organization_ids', [loc], 'Raw publication affiliation facts are retained in the source receipt; canonical organization IDs and dated Person links have not yet been adjudicated.')}
            w['authors'].append(ar)
        preserved_authors = None
    w['doi'] = m['doi'].lower()
    for key, value in [('DOI', w['doi']), ('PubMed', pmid), ('PMCID', m.get('pmcid'))]:
        if value:
            assert w['identifiers'].get(key) in (None, value)
            w['identifiers'][key] = value
    fields = {'venue': m.get('venue') or m.get('journal') or m.get('venue_abbreviation'), 'volume': m.get('volume'),
              'number': m.get('issue'), 'pages': m.get('pages'), 'eid': m.get('article_number'),
              'publisher': m.get('publisher'), 'language': m.get('language')}
    field_updates = []
    for field, value in fields.items():
        if value is None:
            continue
        value = str(value)
        current = w.get(field)
        if current in (None, '', 'und'):
            w[field] = value
            reported(w, field, loc, r['query_id'])
            field_updates.append(field)
        elif current == value:
            if field in w.get('field_states', {}) and w['field_states'][field]['status'] in {'unknown', 'unknown_review_required'}:
                reported(w, field, loc, r['query_id'])
                field_updates.append(field)
        elif field != 'venue':
            conflicts.append(dict(work_id=wid, field=field, retained_value=current, source_value=value, query_id=r['query_id'], handling='Retain existing value and disclose difference; no silent overwrite'))
    # Existing citation year remains the issue year; a separately evidenced online
    # date may precede it. Preserve both meanings explicitly in notes/receipt.
    pd = m.get('publication_date')
    if pd and (len(w.get('publication_date') or '') < len(pd) or m.get('publication_date_kind') == 'electronic_publication_date'):
        w['publication_date'] = pd
        reported(w, 'publication_date', loc, r['query_id'])
        field_updates.append('publication_date')
    assert w['year'] == before['year']
    w.update(publication_status='published', identity_confidence='confirmed', verification_status='source_supported')
    w['title_variants'] = list(dict.fromkeys(w['title_variants'] + [m['title']]))
    w['discovery_sources'].append(src)
    for field in ['authors', 'doi']:
        reported(w, field, loc, r['query_id'])
    w['dimension_status']['authors'] = 'partial'
    w['u00_reasons'] = [x for x in w['u00_reasons'] if x != 'metadata_unverified']
    note = ' RUN-0004: exact official PubMed identity and byline reviewed; retrieval_method=' + ('indexed_official_record' if indexed else 'direct_readable_metadata') + '. Work ID/key and citation year retained. No global Person merge or whole-Work/fulltext completion.'
    if m.get('electronic_publication_date'):
        note += ' Explicit electronic publication date=' + m['electronic_publication_date'] + '; issue date=' + str(m.get('issue_date', 'not established')) + '. These date meanings are separate.'
    w['notes'] = (w.get('notes') or '') + note
    if preserved_authors is not None:
        assert w['authors'] == preserved_authors
    vs = [v for v in data['versions'] if v['work_id'] == wid]
    assert len(vs) == 1, 'Select bibliographic Version explicitly if multiple versions exist'
    v, vb = vs[0], deepcopy(vs[0])
    v['identifiers'].update(w['identifiers'])
    v['version_date'] = w['publication_date']
    v['source'], v['url'] = src, r['endpoint_or_url']
    v['notes'] = (v.get('notes') or '') + ' RUN-0004: exact bibliographic identity enriched; Version ID/type/files remain unchanged. ' + note
    for kind in ['metadata', 'authors']:
        tid = 'T-' + kind + '-' + wid
        t = latest[tid]
        task(tid, wid, kind, 'partial', 'Core identity/byline evidence reviewed; other bibliographic fields, cross-Work Person disambiguation, dated affiliation, fulltext and citation context are separately open.', query_ids=list(dict.fromkeys(t['query_ids'] + qids)))
    data['manual-reviews'].append(dict(review_id='MR-RUN04-METADATA-' + pmid, run_id=RUN,
        review_type='bibliographic_identity_review', entity_id=wid, reviewer='Joint source/citation agent and root review',
        recorded_at_utc=review['reviewed_at_utc'], artifact='temp/reports/RUN-0004-identity-review.json',
        notes='One existing Work identity/byline review; author/organization global identity and scientific evidence admission are not inferred.'))
    change('works', before, w)
    change('versions', vb, v)
    successful[pmid] = dict(work_id=wid, query_ids=qids, preferred_query_id=r['query_id'], indexed=indexed, source=src)
    enriched_work_ids.append(wid)
    events.append(dict(kind='bibliographic_identity_enrichment', work_id=wid, pmid=pmid, query_ids=qids, new_scoped_people=len(names) if preserved_authors is None else 0, existing_byline_preserved=preserved_authors is not None, field_updates=field_updates))

# Append recovery events to the original nine tasks. Failed service calls remain
# in history even when a different method establishes the exact identity.
for pmid in pending_ids:
    tid = 'T-CP4-CiterIdentity-MED-' + pmid
    old = latest[tid]
    attempts = []
    for qid, r in receipts.items():
        params = r.get('normalized_parameters', {})
        wanted = r.get('requested_pmids') or params.get('id') or []
        if params.get('pmid') == pmid or pmid in wanted or pmid in r.get('raw_parameters', {}).get('query', ''):
            attempts.append(qid)
    ok = pmid in successful
    method = ('indexed_official_record' if successful[pmid]['indexed'] else 'direct_readable_metadata') if ok else None
    reason = ('Exact PMID/DOI identity is now established by retained official PubMed bibliographic evidence (' + method + '). Original EPMC and failed page operations remain failures; EPMC core success is not asserted.' if ok else 'Exact identity remains unresolved after the logged bounded attempts; retain original failed-start cursor and retry evidence.')
    task(tid, old['entity_id'], old['task_type'], 'verified_complete' if ok else 'retryable_error', reason,
         query_ids=list(dict.fromkeys(old['query_ids'] + attempts)), attempt_count=old['attempt_count'] + len(attempts),
         cursor=None if ok else old['cursor'], error_code=None if ok else 'OFFICIAL_METADATA_RETRY_INCOMPLETE',
         normalized_parameters={**old['normalized_parameters'], 'epmc_core_success': False, 'identity_via_pubmed': ok, 'identity_access_method': method})
all_initial_ids = json.loads((TEMP / 'runs/RUN-0003.json').read_text())['first_batch']['pending_identity_ids']
assert len(set(all_initial_ids)) == len(all_initial_ids)
assert {'T-CP4-CiterIdentity-MED-' + p for p in all_initial_ids} == {tid for tid in latest if tid.startswith('T-CP4-CiterIdentity-')}
recovered = sum(latest['T-CP4-CiterIdentity-MED-' + p]['task_state'] == 'verified_complete' for p in all_initial_ids)
for row in data['source-list-coverage']:
    if row['coverage_id'] == 'COV-T-CP4-project-3d-citers-epmc':
        before = deepcopy(row)
        original_list_query = next(q for q in data['queries'] if q['query_id'] == 'Q-RUN02-ENT-0104')
        total = row['visible_total']
        assert total == row['returned_count'] == row['distinct_count'] == len(set(original_list_query['result_identifiers']))
        assert {'MED:' + p for p in all_initial_ids} <= set(original_list_query['result_identifiers'])
        core_count = total - len(all_initial_ids)
        assert all(latest['T-CP4-CiterIdentity-MED-' + p]['normalized_parameters']['epmc_core_success'] is False for p in all_initial_ids)
        row['coverage_note'] = f'One-source citation list remains {total}/{total}. EPMC core remains {core_count}/{total}; {recovered} further exact identities are supported by official PubMed evidence, giving {core_count + recovered}/{total} across sources and {len(all_initial_ids) - recovered} unresolved. Direct records and indexed official metadata are distinguished in receipts. No source-wide or scientific citation-context completion is inferred.'
        row['query_ids'] = list(dict.fromkeys(row['query_ids'] + list(receipts)))
        change('source-list-coverage', before, row)

# Exact DOI reference joins require the separate manual relation review. Keep
# original raw references/fingerprints and preserve multiple occurrences per edge.
approved_refs = set(review['reference_resolution_ids'])
doi_target = {works[v['work_id']]['doi'].lower(): v['work_id'] for v in successful.values()}
edge_pairs = {(e['citing_key'], e['cited_key']): e for e in data['citation-edges']}
resolved = []
new_edges, augmented_edges = [], []
work_qids = {x['work_id']: x['query_ids'] for x in successful.values()}
for o in data['reference-occurrences']:
    if o['occurrence_id'] not in approved_refs:
        continue
    assert o.get('cited_work_id') is None
    matches = [str(x).lower() for x in o['candidate_ids'] if str(x).lower() in doi_target]
    assert len(matches) == 1
    target, before = doi_target[matches[0]], deepcopy(o)
    rr = reference_reviews[o['occurrence_id']]
    assert target == rr['cited_work_id'] and matches[0] == rr['target_doi']
    citing = o['citing_work_id']
    assert citing != target and citing in works
    o.update(cited_work_id=target, identity_confidence='confirmed', verification_status='source_supported', failure_reason=None)
    source = deepcopy(o['source'])
    cited_source = next(v['source'] for v in successful.values() if v['work_id'] == target)
    citing_doi = source['identifier'].split('#')[0]
    loc = dict(source_id=source['source_id'], identifier=source['identifier'], url=source.get('url') or 'https://api.crossref.org/works/' + quote(citing_doi, safe=''),
               section='Retained deposited reference ' + str(o['reference_label']), accessed_at=reference_source_times[o['occurrence_id']],
               evidence_note=rr['qualification'] + ' Local review at ' + review['reviewed_at_utc'] + '; no new source retrieval. Citing fulltext context and citation role are not reviewed.')
    source['evidence_locator'] = list(source.get('evidence_locator', [])) + [loc] + cited_source['evidence_locator']
    o['source'] = source
    pair = (works[citing]['work_key'], works[target]['work_key'])
    if pair in edge_pairs:
        edge = edge_pairs[pair]
        eb = deepcopy(edge)
        edge['occurrence_ids'] = list(dict.fromkeys(edge['occurrence_ids'] + [o['occurrence_id']]))
        edge['discovery_sources'].append(source)
        change('citation-edges', eb, edge)
        augmented_edges.append(edge['edge_id'])
    else:
        edge = dict(edge_id='CE-' + h(citing + '|' + target), citing_key=pair[0], cited_key=pair[1], occurrence_ids=[o['occurrence_id']],
                    discovery_sources=[source], verification_status='source_supported', citation_roles=['unknown'], context_locators=[], date=NOW[:10])
        data['citation-edges'].append(edge)
        edge_pairs[pair] = edge
        new_edges.append(edge['edge_id'])
    if not edge.get('context_locators'):
        task('T-RUN04-CitationContext-' + edge['edge_id'], citing, 'citation_context', 'pending',
             'Original citing text is needed to establish scientific citation roles. Target identity and deposited reference do not close context review.',
             source_id=source['source_id'], supporting_record_ids=[o['occurrence_id']], query_ids=list(dict.fromkeys([source.get('version')] + work_qids[target])),
             normalized_parameters={'edge_id': edge['edge_id'], 'cited_work_id': target})
    existing_path = next(d for d in data['discovery-paths'] if d['work_id'] == citing)
    step = dict(from_entity_id=citing, to_entity_id=target, discovery_route='backward_citation', source_id=source['source_id'], evidence_locator=[loc], verification_status='source_supported', scope_id=SCOPE)
    data['discovery-paths'].append(dict(discovery_id='D-RUN04-' + h(citing + '|' + target + '|' + o['occurrence_id']), scope_id=SCOPE, work_id=target, root_seed_id=existing_path['root_seed_id'], depth=existing_path['depth'] + 1, steps=deepcopy(existing_path['steps']) + [step], source_supported_relation=True))
    data['manual-reviews'].append(dict(review_id='MR-RUN04-REFERENCE-' + o['occurrence_id'], run_id=RUN, review_type='bibliography_target_identity_review', entity_id=citing,
        reviewer='Joint source/citation agent and root review', recorded_at_utc=review['reviewed_at_utc'], artifact='temp/reports/RUN-0004-identity-review.json',
        notes=rr['qualification'] + ' Original raw reference preserved; scientific citation context remains open.'))
    change('reference-occurrences', before, o)
    resolved.append(o['occurrence_id'])
    events.append(dict(kind='reference_identity_resolution', occurrence_id=o['occurrence_id'], citing_work_id=citing, cited_work_id=target, edge_id=edge['edge_id']))
assert set(resolved) == approved_refs
assert not augmented_edges, 'This reviewed batch permits only new pairs; historic citation edges must remain byte-preserved'
for wid in sorted({o['citing_work_id'] for o in data['reference-occurrences'] if o['occurrence_id'] in approved_refs}):
    tid = 'T-ReferenceIdentity-' + wid
    old = latest[tid]
    remaining = [r['occurrence_id'] for r in data['reference-occurrences'] if r['citing_work_id'] == wid and not r['cited_work_id']]
    task(tid, wid, 'reference_identity', 'partial' if remaining else 'verified_complete',
         'Reviewed exact DOI targets resolved in RUN-0004. Remaining target identities and original fulltext/reference completeness remain separately open.' if remaining else 'All currently retained targets are identified; fulltext bibliography completeness remains a separate task.',
         supporting_record_ids=remaining, cursor=0 if remaining else None, query_ids=list(dict.fromkeys(old['query_ids'] + [q for v in successful.values() for q in v['query_ids']])))

# Every real external operation, including failed and partial retrievals, is
# registered. Search-hit counts and target identity counts are not conflated.
source_specs = {s['source_id']: s for s in json.loads((TEMP / 'snapshots/scope.json').read_text())['sources']}
def parameters(value):
    return {k: v if isinstance(v, (str, int, float, bool)) or v is None or isinstance(v, list) and all(isinstance(x, str) for x in v) else json.dumps(v, ensure_ascii=False, separators=(',', ':')) for k, v in value.items()}


for qid, r in receipts.items():
    assert not any(q['query_id'] == qid for q in data['queries'])
    sid, status = r['source_id'], r['status']
    count, total = r.get('returned_count'), r.get('visible_total')
    before_count = r.get('count_before_dedup', count)
    after_count = r.get('count_after_dedup', count)
    page_complete = r.get('page_complete', status == 'success' and count is not None and total is not None)
    fields = {'visible_total': total, 'returned_count': count, 'count_before_dedup': before_count, 'count_after_dedup': after_count}
    missing = [k for k, v in fields.items() if v is None]
    error = r.get('error_code') or r.get('error', {}).get('code')
    reason = ('Exact retrieved metadata is available; query-source coverage is limited to the disclosed receipt.' if status == 'success' else 'Failed or unreadable source operation; no absent metadata or zero-result inference is permitted.')
    if missing:
        reason += ' Unobserved result totals remain unknown with a review clock.'
    tid = 'T-AUDIT-' + qid
    t = task(tid, sid, 'query_audit_reconciliation', 'verified_complete' if not missing and status == 'success' and page_complete else 'retryable_error' if status == 'error' else 'partial', reason, 'source',
             source_id=sid, query_ids=[qid], attempt_count=1, error_code=error, normalized_parameters={'query_id': qid, 'endpoint': r['endpoint_or_url']})
    q = dict(query_id=qid, task_id=tid, scope_id=SCOPE, checkpoint_id=CP, entity_id=r.get('entity_id') or SCOPE,
             source_id=sid, endpoint_or_url=r['endpoint_or_url'], api_version=source_specs[sid].get('api_version'),
             query_kind='official_indexed_identity' if sid == 'web_search' else 'exact_identity_retry',
             raw_parameters=parameters(r.get('raw_parameters', {})), normalized_parameters=parameters(r.get('normalized_parameters', {})),
             queried_at_utc=r['queried_at_utc'], cursor_in=r.get('cursor_in'), cursor_out=r.get('cursor_out'), page_index=1,
             page_complete=bool(page_complete), **fields, new_work_ids=[], new_work_count=0, result_identifiers=r.get('result_identifiers', []),
             status=status, verification_status=r.get('verification_status', 'source_supported'), error_code=error,
             error_message=r.get('error_message') or r.get('error', {}).get('message'), retry_count=0, retry_at=None,
             cache_path='temp/query-results/' + qid + '.json', cache_hit=False, reused_query_id=None,
             rerun_reason=r.get('rerun_reason', 'Recover an existing exact identity after recorded failed or unreadable operations; do not repeat successful list retrieval.'),
             coverage_note=r.get('count_scope', '') + ' ' + r.get('retrieval_cache_note', ''), license_note=r.get('license_note', 'Sanitized bibliographic facts and provenance only.'),
             recorded_at_utc=NOW, query_time_status='exact', field_states={})
    if missing:
        since = r['queried_at_utc']
        t.update(field_path='queries.' + qid + '.' + ','.join(missing), unknown_since_utc=since, deadline_at_utc=(datetime.fromisoformat(since.replace('Z', '+00:00')) + timedelta(hours=24)).isoformat().replace('+00:00', 'Z'), review_task_id=tid)
        for field in missing:
            q['field_states'][field] = dict(status='unknown', reason=reason, evidence_locator=[], unknown_since_utc=since, review_task_id=tid)
    data['queries'].append(q)
    data['source-observations'].append(dict(observation_id='OBS-' + qid, query_id=qid, task_id=tid, source_id=sid, endpoint_or_url=q['endpoint_or_url'], queried_at_utc=q['queried_at_utc'], query_time_status='exact', status=status, http_status=r.get('http_status'), response_kind=r.get('response_kind'), returned_count=count, visible_total=total, page_complete=q['page_complete'], count_scope=q['coverage_note'], receipt_path=q['cache_path'], verification_status=q['verification_status'], recorded_at_utc=NOW, external_request_performed=True))

# Append the independently reviewed Jung claim; no existing Assessment changes.
jung = json.loads((TEMP / 'reports/RUN-0004-Jung2011-adaptation-review.json').read_text())
a, cq = deepcopy(jung['assessment']), deepcopy(jung['cache_query_record'])
assert a['assessment_id'] == 'AS-RUN04-Jung2011-L03-impulse-decay-adaptation'
assert a['evidence_admission_status'] == 'eligible' and a['handling_level'] == 'new_evidence_or_hypothesis'
assert not any(x['assessment_id'] == a['assessment_id'] for x in data['assessments'])
data['assessments'].append(a)
data['manual-reviews'].append(deepcopy(jung['manual_review_record']))
w, wb = works[a['work_id']], deepcopy(works[a['work_id']])
w['u00_reasons'] = []
w['notes'] = (w.get('notes') or '') + ' RUN-0004: one independent L03 Fig6b impulse-response-decay claim admitted from cached original pages. Original L07 insufficiency and all other claims remain unchanged; not a measured biological high-pass component or platform-amplitude recovery claim.'
assert w['dimension_status']['assessment'] == 'partial'
change('works', wb, w)
old = latest[cq['task_id']]
task(old['task_id'], a['work_id'], 'assessment', 'partial', 'One L03 adaptation/impulse-decay claim reviewed. Existing Jung/Longden L07 insufficiency and other Work-wide claims remain open.', query_ids=list(dict.fromkeys(old['query_ids'] + [cq['query_id']])), supporting_record_ids=list(dict.fromkeys(old['supporting_record_ids'] + [a['assessment_id']])))
cache_path = 'temp/query-results/' + cq['query_id'] + '.json'
cq['cache_path'] = cache_path
data['queries'].append(cq)
cache_receipt = dict(query_id=cq['query_id'], run_id=RUN, scope_id=SCOPE, checkpoint_id=CP, source_id=cq['source_id'], endpoint_or_url=cq['endpoint_or_url'], queried_at_utc=cq['queried_at_utc'], query_time_status='exact', cache_hit=True, reused_query_id=cq['reused_query_id'], external_request_performed=False, status='cache_hit', response_kind='cached_primary_pdf_review', returned_count=1, visible_total=1, result_identifiers=cq['result_identifiers'], body_sha256=jung['source']['sha256'], body_bytes=jung['source']['bytes'], sanitized=True, payload_retained=False, original_retrieved_at_utc=jung['source']['original_retrieved_at_utc'], review_report='temp/reports/RUN-0004-Jung2011-adaptation-review.json', timing_note='Joint cached single-claim review timestamp; no new HTTP retrieval or new fulltext Work.')
data['source-observations'].append(dict(observation_id='OBS-' + cq['query_id'], query_id=cq['query_id'], task_id=cq['task_id'], source_id=cq['source_id'], endpoint_or_url=cq['endpoint_or_url'], queried_at_utc=cq['queried_at_utc'], query_time_status='exact', status='cache_hit', http_status=None, response_kind='cached_primary_pdf_review', returned_count=1, visible_total=1, page_complete=True, count_scope=cq['coverage_note'], receipt_path=cache_path, verification_status='verified', recorded_at_utc=NOW, external_request_performed=False))
events.append(dict(kind='new_independent_scientific_claim', assessment_id=a['assessment_id'], work_id=a['work_id'], report='temp/reports/RUN-0004-Jung2011-adaptation-review.json', all_old_assessments_unchanged=True, whole_work_closed=False))

# The fixed 24-hour rule applies without resetting prior clocks.
escalated = set()
now_dt = datetime.fromisoformat(ACTUAL_NOW.replace('Z', '+00:00'))
def walk_unknown(obj):
    if isinstance(obj, list):
        for x in obj:
            walk_unknown(x)
    elif isinstance(obj, dict):
        if obj.get('status') in {'unknown', 'unknown_review_required'} and obj.get('unknown_since_utc'):
            since = datetime.fromisoformat(obj['unknown_since_utc'].replace('Z', '+00:00'))
            if now_dt >= since + timedelta(hours=24):
                obj['status'] = 'unknown_review_required'
                t = latest[obj['review_task_id']]
                assert t['task_state'] not in TERMINAL
                if t['task_id'] not in escalated and not (t.get('overdue') and t.get('priority') in {'high', 'critical'}):
                    task(t['task_id'], t['entity_id'], t['task_type'], 'partial', t['review_condition'], t['entity_type'], overdue=True, priority='high')
                    escalated.add(t['task_id'])
        for x in obj.values():
            walk_unknown(x)
for name in NAMES:
    if name != 'tasks':
        walk_unknown(data[name])
for tid, t in list(latest.items()):
    if t.get('unknown_since_utc') and t['task_state'] not in TERMINAL and now_dt >= datetime.fromisoformat(t['unknown_since_utc'].replace('Z', '+00:00')) + timedelta(hours=24):
        if tid not in escalated and not (t.get('overdue') and t.get('priority') in {'high', 'critical'}):
            task(tid, t['entity_id'], t['task_type'], 'partial', t['review_condition'], t['entity_type'], overdue=True, priority='high')
            escalated.add(tid)
assert not escalated, 'Any newly due historic field requires an explicit separate delta review before this batch is applied'
assert data['assessments'][:-1] == old_assessments

schema = json.loads((TEMP / 'schema.json').read_text())
checks = {'work': [works[x] for x in set(enriched_work_ids + [a['work_id']])],
          'version': [r['after'] for r in changed_records if r['dataset'] == 'versions'],
          'person': data['authors'][before_counts['authors']:], 'task': data['tasks'][before_counts['tasks']:],
          'query': data['queries'][before_counts['queries']:], 'reference_occurrence': [r['after'] for r in changed_records if r['dataset'] == 'reference-occurrences'],
          'citation_edge': data['citation-edges'][before_counts['citation-edges']:] + [r['after'] for r in changed_records if r['dataset'] == 'citation-edges'], 'assessment': [a]}
validation = []
for kind, rows in checks.items():
    validator = Draft202012Validator({'$ref': '#/$defs/' + kind, '$defs': schema['$defs']}, format_checker=FormatChecker())
    for row in rows:
        errors = list(validator.iter_errors(row))
        assert not errors, (kind, [(list(e.path), e.message) for e in errors])
    validation.append(dict(kind=kind, records=len(rows), schema_errors=0))
new_tasks = data['tasks'][before_counts['tasks']:]
field_completions = [t for t in new_tasks if t['task_type'] == 'field_review' and t['task_state'] == 'verified_complete']
external = sum(int(r.get('external_requests_performed', 1)) for r in receipts.values())
manual = [m for m in data['manual-reviews'] if m.get('run_id') == RUN]
assert len(manual) == len(successful) + len(resolved) + 1
assert len(data['queries']) - before_counts['queries'] == len(receipts) + 1

# No canonical writes occur before all evidence, identity and schema checks above.
for name in NAMES:
    replace_logical(name + '.jsonl', data[name], TEMP)
dump(REPO / cache_path, cache_receipt)
run.update(external_requests_used=external, external_request_count_status='exact_retained_invocations',
           external_requests_note='One receipt per actual tool/direct-source operation; upstream web cache behavior is disclosed. Git transport is not a research query.',
           manual_review_items_used=len(manual), cache_reuse_events=1, status='checkpointing', end_checkpoint_id=CP,
           last_completed_batch=f'{len(successful)} exact existing identities, {len(resolved)} retained reference targets and one distinct Jung2011 L03 cached-fulltext claim.',
           sync_state='All research-source receipts and manual decisions were published and byte-verified before this canonical integration. Derived snapshot/exports require final validation and independent remote readback before any new research.')
dump(TEMP / 'runs/RUN-0004.json', run)
report = dict(report_id='RUN-0004-integration', scope_id=SCOPE, run_id=RUN, checkpoint_id=CP, integrated_at_utc=NOW,
              baseline_checkpoint='CP-0005', baseline_commit=BASE, pre_integration_published_commit=head, source_receipts_previously_synced=True,
              scientific_records_preserved=len(old_assessments), old_L07_byte_hash_preserved=True, changed_logical_datasets=NAMES,
              counts_before=before_counts, counts_after={n: len(v) for n, v in data.items()},
              unknown_field_tasks_closed=len(field_completions), new_work_records=0, new_work_scoped_person_records=len(new_person_ids),
              new_reference_resolutions=len(resolved), new_source_supported_edges=len(new_edges), augmented_existing_edges=len(set(augmented_edges)),
              new_assessments=1, new_external_invocations=external, cache_reuses=1, manual_review_activities=len(manual),
              overdue_unknown_tasks_escalated=len(escalated), successful_identity_pmids=sorted(successful),
              identity_access_methods={p: 'indexed_official_record' if v['indexed'] else 'direct_readable_metadata' for p, v in successful.items()},
              new_person_ids=new_person_ids, reference_resolution_ids=resolved, closed_field_task_ids=[t['task_id'] for t in field_completions],
              retained_bibliographic_differences=conflicts, schema_validation=validation, changed_records=changed_records,
              events=events, closure_established=False)
if recovery:
    report['runtime_recovery'] = dict(recovered_at_utc=ACTUAL_NOW,
        recovery_receipt='temp/reports/RUN-0004-runtime-recovery.json',
        original_event_time_preserved=NOW, original_unknown_clocks_preserved=True,
        fresh_current_clock_used_for_overdue_checks=True,
        new_research_requests=0, new_manual_research_reviews=0,
        lost_prior_local_commit=recovery['lost_prior_local_commit'],
        original_commit_or_tree_identity_claimed=False)
    run['runtime_recovery'] = report['runtime_recovery']
    dump(TEMP / 'runs/RUN-0004.json', run)
dump(OUT, report)
print(json.dumps({k: v for k, v in report.items() if k not in {'changed_records', 'events', 'schema_validation'}}, ensure_ascii=False))
