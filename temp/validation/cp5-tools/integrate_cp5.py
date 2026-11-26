"""One bounded RUN-0003 literature integration, from already synced receipts.

No network requests, no CP4 replay and no scope change. Run once, then export,
audit and synchronize the resulting CP5 before doing more research.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from copy import deepcopy
from collections import Counter
import hashlib, json, sys
from urllib.parse import quote
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path('/workspace/scratch/2e518600ca4c')
REPO = ROOT / 'insect-project'
TEMP = REPO / 'temp'
sys.path.insert(0, str(ROOT / 'cp4_work'))
from storage import read_logical, replace_logical

NOW = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
CP = 'CP-0005'
SCOPE = 'SCOPE-0001'
RUN = 'RUN-0003'
OUT = TEMP / 'reports/RUN-0003-integration.json'
assert not OUT.exists(), 'This one-shot integration has already run.'
TERMINAL = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
names = ['works', 'versions', 'authors', 'tasks', 'queries', 'source-observations',
         'source-list-coverage', 'reference-occurrences', 'citation-edges',
         'discovery-paths', 'manual-reviews', 'assessments']
data = {n: read_logical(n + '.jsonl', TEMP) for n in names}
baseline_counts = {n:len(rows) for n, rows in data.items()}
initial_people = tuple(data['authors'])
original_assessments = deepcopy(data['assessments'])
works = {w['work_id']: w for w in data['works']}
people = {p['person_id']: p for p in data['authors']}
versions = {v['version_id']: v for v in data['versions']}
latest = {}
for t in data['tasks']:
    if t['task_id'] not in latest or t['event_sequence'] > latest[t['task_id']]['event_sequence']:
        latest[t['task_id']] = t
events = []

def h(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

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

def unknown(entity, path, locs, reason, entity_type='work'):
    tid = 'T-Unknown-' + h(entity + '|' + path)
    old = latest.get(tid)
    since = old.get('unknown_since_utc') if old else NOW
    assert since
    task(tid, entity, 'field_review', 'pending', reason, entity_type,
         field_path=path, unknown_since_utc=since, review_task_id=tid,
         deadline_at_utc=(datetime.fromisoformat(since.replace('Z', '+00:00')) + timedelta(hours=24)).isoformat().replace('+00:00', 'Z'))
    return dict(status='unknown', reason=reason, evidence_locator=locs,
                unknown_since_utc=since, review_task_id=tid)

def reported(obj, field, loc, qid):
    old = obj.get('field_states', {}).get(field)
    if old and old.get('review_task_id'):
        tid = old['review_task_id']
        t = latest[tid]
        task(tid, t['entity_id'], t['task_type'], 'verified_complete',
             'This field is now supported by the cited PubMed bibliographic record; broader dimensions remain open.',
             t['entity_type'], query_ids=list(dict.fromkeys(t['query_ids'] + [qid])),
             attempt_count=t['attempt_count'] + 1, error_code=None)
    obj.setdefault('field_states', {})[field] = dict(
        status='reported', reason='Bibliographic field explicitly present in the retained PubMed evidence.',
        evidence_locator=[loc], unknown_since_utc=None, review_task_id=None)

specs = [
    ('28347859', 'W-R525f36f1c11284ce', 'Q-RUN03-WEB-0002',
     dict(volume='46', number='4', pages='552-563', publication_date='2017-04-12')),
    ('27346905', 'W-Re46890f5a27ec270', 'Q-RUN03-WEB-0004',
     dict(volume='47', pages='155-165', publication_date='2016-09', PMCID='PMC4918639')),
    ('26866692', 'W-Rb7fb4e1b3303e196', 'Q-RUN03-WEB-0011',
     dict(volume='12', number='2', eid='e1004683', publication_date='2016-02-11', PMCID='PMC4750948')),
    ('26781051', 'W-R24127d96a1e10330', 'Q-RUN03-WEB-0012',
     dict(volume='105', number='1', pages='41-55', publication_date='2016-01')),
    ('25841648', 'W-R4ee6870ac8ca1a67', 'Q-RUN03-WEB-0015',
     dict(volume='201', number='6', pages='513-515', publication_date='2015-04-05')),
]
review = json.loads((TEMP / 'reports/RUN-0003-identity-review.json').read_text())
assert review['status'] == 'reviewed' and review['work_count'] == 5
successful = {}
for pmid, wid, qid, fields in specs:
    r = json.loads((TEMP / 'query-results' / (qid + '.json')).read_text())
    m = r['metadata']; w = works[wid]; before = deepcopy(w)
    assert m['pmid'] == pmid and m['doi'] and m['authors'] and not w['authors']
    assert not w['doi'] and all(x['work_id'] == wid or x.get('doi') != m['doi'] for x in works.values())
    loc = dict(source_id='institutional_repository', url=r['endpoint_or_url'],
               identifier=qid, accessed_at=r['queried_at_utc'], section='PubMed citation header and author list',
               evidence_note='Exact PMID/DOI and displayed bibliographic fields. Source retrieval cache timing is disclosed in the receipt; no live EPMC core response or fulltext review is asserted.')
    src = dict(source_id='institutional_repository', url=r['endpoint_or_url'], identifier='MED:' + pmid,
               accessed_at=r['queried_at_utc'], verification_status='verified',
               license='Bibliographic facts and source locators only; no restricted abstract or fulltext redistribution.',
               evidence_locator=[loc])
    authors = []
    for pos, a in enumerate(m['authors'], 1):
        name = a['full_name']
        pid = 'P-R' + h(wid + '|' + str(pos) + '|' + name)
        assert pid not in people, 'Unexpected existing scoped authorship identity: ' + pid
        person = dict(person_id=pid, display_name=name, name_variants=[name], orcid=None,
                      external_ids={}, identity_confidence='probable', verification_status='source_supported',
                      affiliation_history=[], sources=[src], field_states={})
        person['field_states']['orcid'] = unknown(pid, 'orcid', [loc],
            'No ORCID-to-this-authorship linkage has been established; a same-name person elsewhere is not a confirmed match.', 'person')
        people[pid] = person; data['authors'].append(person)
        candidates = sorted(p['person_id'] for p in initial_people
                            if p['display_name'].casefold() == name.casefold()
                            or name.casefold() in [n.casefold() for n in p['name_variants']])
        task('T-author_disambiguation-' + pid, pid, 'author_disambiguation', 'pending',
             'Resolve this Work-scoped authorship using identifiers, coauthors and dated affiliations; names alone do not permit merging.',
             'person', source_id='institutional_repository', query_ids=[qid],
             normalized_parameters={'work_id':wid, 'author_position':pos, 'same_name_candidate_ids':candidates})
        ar = dict(person_id=pid, display_name=name, is_corporate=False, organization_ids=[], source=src)
        ar['field_states'] = {'organization_ids':unknown(wid, 'authors.' + str(pos) + '.organization_ids', [loc],
            'Institutional identity and dated affiliation were not adjudicated in this bounded bibliographic review.')}
        authors.append(ar)
    w.update(authors=authors, doi=m['doi'], venue=m['journal'],
             publication_status='published', identity_confidence='confirmed', verification_status='source_supported')
    w['identifiers'].update(DOI=m['doi'], PubMed=pmid)
    fields = dict(fields)
    pmcid = fields.pop('PMCID', None)
    if pmcid: w['identifiers']['PMCID'] = pmcid
    w.update(fields)
    w['title_variants'] = list(dict.fromkeys(w['title_variants'] + [m['title']]))
    w['discovery_sources'].append(src)
    w['dimension_status']['authors'] = 'partial'
    w['u00_reasons'] = [v for v in w['u00_reasons'] if v != 'metadata_unverified']
    w['notes'] += ' RUN-0003: exact PubMed/DOI bibliographic identity completed; first-assigned Work ID/key retained. New author records are Work-scoped provisional identities, not cross-Work merges. Publication-date precision follows the displayed citation; month-only issue dates do not establish an unobserved earlier online date.'
    for field in ['authors', 'doi', 'venue'] + list(fields):
        reported(w, field, loc, qid)
    v = versions['V-' + wid + '-01']
    vb = deepcopy(v)
    v['identifiers'] = deepcopy(w['identifiers']); v['version_date'] = w['publication_date']
    v['source'] = src; v['url'] = r['endpoint_or_url']
    v['notes'] += ' RUN-0003 bibliographic identity enriched from PubMed; no file materialization or original fulltext inspection added.'
    for kind in ['metadata', 'authors']:
        tid = 'T-' + kind + '-' + wid; t = latest[tid]
        task(tid, wid, kind, 'partial',
             'Core PMID/DOI/byline bibliographic fields reviewed; unresolved publisher/language fields, author identities and dated affiliations remain open.',
             query_ids=list(dict.fromkeys(t['query_ids']+[qid])))
    data['manual-reviews'].append(dict(review_id='MR-RUN03-METADATA-' + pmid, run_id=RUN,
        review_type='bibliographic_identity_review', entity_id=wid, reviewer='ChatGPT research team; root checked original source receipts and canonical matches',
        recorded_at_utc=review['reviewed_at_utc'], artifact='temp/reports/RUN-0003-identity-review.json',
        notes='Reviewed existing Work identity, DOI, ordered author names and explicit publication fields; no same-name Person merge or scientific admission.'))
    events.append(dict(kind='bibliographic_identity_enrichment', work_id=wid, query_id=qid,
                       before=before, after=deepcopy(w), version_before=vb, version_after=deepcopy(v)))
    successful[pmid] = qid

# Preserve failed-provider history and distinguish cross-source identity from EPMC service success.
ids = json.loads((TEMP / 'runs/RUN-0003.json').read_text())['first_batch']['pending_identity_ids']
for i, pmid in enumerate(ids, 2):
    tid = 'T-CP4-CiterIdentity-MED-' + pmid; old = latest[tid]
    qid = 'Q-RUN03-WEB-' + str(i).zfill(4)
    resolved = pmid in successful
    reason = ('Exact PMID/DOI identity completed through the retained PubMed record. The original EPMC 503 and new timeout remain historical failures; this is not EPMC core success.' if resolved else
              'EPMC core retry timed out; PubMed retrieval exposed no readable matching citation header. Retain exact MED identity and failed-start cursor for a later bounded retry.')
    task(tid, old['entity_id'], old['task_type'], 'verified_complete' if resolved else 'retryable_error', reason,
         query_ids=list(dict.fromkeys(old['query_ids']+['Q-RUN02-ENT-0104','Q-RUN02-ENT-0198','Q-RUN03-EPMC-0001','Q-RUN03-WEB-0001',qid])),
         attempt_count=old['attempt_count']+3, cursor=None if resolved else {'cursorMark':'*','source':'MED','id':pmid},
         error_code=None if resolved else 'EPMC_TIMEOUT_PUBMED_UNREADABLE',
         normalized_parameters={**old['normalized_parameters'],'epmc_core_success':False,'identity_via_pubmed':resolved})
for row in data['source-list-coverage']:
    if row['coverage_id'] == 'COV-T-CP4-project-3d-citers-epmc':
        row['coverage_note'] = 'One-source citation list remains 42/42. EPMC core metadata remains 28/42 after the failed retry; 5 additional identities are supported by PubMed, giving 33/42 across sources and 9 still pending. Citation contexts remain unreviewed.'
        row['query_ids'] = list(dict.fromkeys(row['query_ids']+['Q-RUN02-ENT-0198','Q-RUN03-EPMC-0001']+list(successful.values())))

# Four author lists already reached their end. Only discrepancy wording and evidence links change.
for pid, profile, listing, total, count in [
    ('P-0014','Q-RUN01-00226','Q-RUN01-00227',59,58),
    ('P-0017','Q-RUN01-00237','Q-RUN01-00239',259,256),
    ('P-0048','Q-RUN01-00500','Q-RUN01-00501',172,171),
    ('P-0056','Q-RUN02-ENT-0202','Q-RUN02-ENT-0203',353,352)]:
    tid='T-author_source_pagination-'+pid; old=latest[tid]
    reason=f'The saved list reached its end with {count} distinct records; the saved profile reports {total}. This is an unresolved provider count discrepancy, not an unconsumed page cursor or a verified set of missing papers.'
    task(tid,pid,'author_source_pagination','partial',reason,'person',
         query_ids=list(dict.fromkeys(old['query_ids']+[profile,listing])),
         cursor={'list_cursor':None,'pagination_complete':True,'visible_total_reconciled':False,'identity_request_required':False})
    for row in data['source-list-coverage']:
        if row.get('entity_id')==pid and row.get('source_id')=='semantic_scholar':
            row['query_ids']=list(dict.fromkeys(row['query_ids']+[profile,listing]))
            row['coverage_note']=reason

# Resolve exactly seven existing references, with separate target-identity and citation-relation evidence.
target='W-Rb7fb4e1b3303e196'; target_key=works[target]['work_key']
target_source=works[target]['discovery_sources'][-1]
edge_pairs={(e['citing_key'],e['cited_key']):e for e in data['citation-edges']}
resolved=[]
for o in data['reference-occurrences']:
    if o.get('cited_work_id') is not None or o.get('candidate_ids')!=['10.1371/journal.pcbi.1004683']:continue
    assert o['occurrence_id'] in review['reference_resolution_ids']
    before=deepcopy(o)
    o.update(cited_work_id=target,identity_confidence='confirmed',verification_status='source_supported',failure_reason=None)
    source=deepcopy(o['source'])
    citing_doi=source['identifier'].split('#')[0]
    relation_loc=dict(source_id='crossref',identifier=source['identifier'],url='https://api.crossref.org/works/'+quote(citing_doi,safe=''),
                      section='Deposited reference '+o['reference_label'],accessed_at=NOW,
                      evidence_note='Existing deposited reference asserts the exact target DOI. Relation is source-supported; original citing-paper context has not been reviewed.')
    source['evidence_locator']=list(source.get('evidence_locator',[]))+[relation_loc]+target_source['evidence_locator']
    o['source']=source
    citing=o['citing_work_id']; pair=(works[citing]['work_key'],target_key)
    assert pair not in edge_pairs, 'Do not create a duplicate citation edge.'
    edge=dict(edge_id='CE-'+h(citing+'|'+target),citing_key=pair[0],cited_key=pair[1],occurrence_ids=[o['occurrence_id']],
              discovery_sources=[source],verification_status='source_supported',citation_roles=['unknown'],context_locators=[],date=NOW[:10])
    data['citation-edges'].append(edge);edge_pairs[pair]=edge
    task('T-RUN03-CitationContext-'+edge['edge_id'],citing,'citation_context','pending',
         'Inspect the original citing text to establish citation role and scientific context; metadata identity and deposited reference alone do not close this task.',
         source_id='crossref',supporting_record_ids=[o['occurrence_id']],query_ids=[o['source']['version'],'Q-RUN03-WEB-0011'],
         normalized_parameters={'edge_id':edge['edge_id'],'cited_work_id':target})
    existing_path=next(d for d in data['discovery-paths'] if d['work_id']==citing)
    step=dict(from_entity_id=citing,to_entity_id=target,discovery_route='backward_citation',source_id='crossref',
              evidence_locator=[relation_loc],verification_status='source_supported',scope_id=SCOPE)
    did='D-RUN03-'+h(citing+'|'+target+'|'+o['occurrence_id'])
    data['discovery-paths'].append(dict(discovery_id=did,scope_id=SCOPE,work_id=target,
        root_seed_id=existing_path['root_seed_id'],depth=existing_path['depth']+1,
        steps=deepcopy(existing_path['steps'])+[step],source_supported_relation=True))
    events.append(dict(kind='reference_identity_resolution',occurrence_id=o['occurrence_id'],before=before,after=deepcopy(o),new_edge=deepcopy(edge),
        note='Exact unique DOI joins the retained PubMed identity. Six references also have agreeing bibliographic text; R-CR-1eb95e311ab92d4b supplies only DOI, so no missing title/author/year cross-check is claimed.'))
    data['manual-reviews'].append(dict(review_id='MR-RUN03-REFERENCE-'+o['occurrence_id'],run_id=RUN,
        review_type='bibliography_target_identity_review',entity_id=citing,
        reviewer='ChatGPT research team; root checked retained reference evidence',recorded_at_utc=review['reviewed_at_utc'],
        artifact='temp/reports/RUN-0003-identity-review.json',
        notes='Reviewed only '+o['occurrence_id']+' against the exact DOI target. This activity does not establish the rest of the bibliography or scientific context.'))
    resolved.append(o['occurrence_id'])
assert sorted(resolved)==sorted(review['reference_resolution_ids']) and len(resolved)==7
for wid in sorted({o['citing_work_id'] for o in data['reference-occurrences'] if o['occurrence_id'] in resolved}):
    tid='T-ReferenceIdentity-'+wid;old=latest[tid]
    remaining=[r['occurrence_id'] for r in data['reference-occurrences'] if r['citing_work_id']==wid and not r['cited_work_id']]
    task(tid,wid,'reference_identity','partial' if remaining else 'verified_complete',
         'One retained DOI target resolved in RUN-0003; all remaining reference identities and original fulltext completeness remain separately open.' if remaining else 'Every currently retained reference target is now identified; original fulltext/reference coverage remains separately open.',
         supporting_record_ids=remaining,cursor=0 if remaining else None,
         query_ids=list(dict.fromkeys(old['query_ids']+['Q-RUN03-WEB-0011'])))

# Register every already synchronized external attempt, including empty pages.
source_specs={s['source_id']:s for s in json.loads((TEMP/'snapshots/scope.json').read_text())['sources']}
by_pmid={str(w.get('identifiers',{}).get('PubMed')):w['work_id'] for w in works.values() if w.get('identifiers',{}).get('PubMed')}
for w in works.values():
    for value in w.get('identifiers',{}).values():
        if str(value).startswith('MED:'):by_pmid.setdefault(str(value)[4:],w['work_id'])
def add_query_receipt(r, path):
    qid=r['query_id'];tid='T-AUDIT-'+qid;sid=r['source_id']
    assert not any(q['query_id']==qid for q in data['queries'])
    count=r.get('returned_count');total=r.get('visible_total')
    status=r.get('status') or ('error' if r.get('error_code') else 'success')
    ok=status in ['success','cache_hit'] and count is not None
    reason=('This identified bibliographic/resource receipt has been checked; no full-corpus or scientific-context coverage is inferred.' if ok else
            'The source response was failed or unreadable. Counts remain unknown; retained parameters and original receipt are the retry evidence.')
    t=task(tid,sid,'query_audit_reconciliation','verified_complete' if ok else ('retryable_error' if status=='error' else 'partial'),reason,'source',
           source_id=sid,query_ids=[qid],attempt_count=1,error_code=r.get('error_code') or (None if ok else 'SOURCE_RECORD_NOT_READABLE'),
           normalized_parameters={'query_id':qid,'endpoint':r['endpoint_or_url']})
    raw={k:v if isinstance(v,(str,int,float,bool)) or v is None or isinstance(v,list) and all(isinstance(x,str) for x in v)
         else json.dumps(v,ensure_ascii=False,separators=(',',':')) for k,v in r.get('raw_parameters',{}).items()}
    norm={k:v if isinstance(v,(str,int,float,bool)) or v is None or isinstance(v,list) and all(isinstance(x,str) for x in v)
          else json.dumps(v,ensure_ascii=False,separators=(',',':')) for k,v in r.get('normalized_parameters',{}).items()}
    pmid=norm.get('pmid')
    q=dict(query_id=qid,task_id=tid,scope_id=SCOPE,checkpoint_id=CP,entity_id=by_pmid.get(str(pmid),'SCOPE-0001'),
           source_id=sid,endpoint_or_url=r['endpoint_or_url'],api_version=source_specs[sid].get('api_version'),
           query_kind='exact_identity_retry' if sid=='europepmc' else 'web_bibliographic_identity' if sid=='institutional_repository' else 'web_source_inspection',
           raw_parameters=raw,normalized_parameters=norm,queried_at_utc=r['queried_at_utc'],
           cursor_in=r.get('cursor_in'),cursor_out=r.get('cursor_out'),page_index=1,page_complete=ok,
           visible_total=total,returned_count=count,count_before_dedup=count,count_after_dedup=count,
           new_work_ids=[],new_work_count=0,result_identifiers=r.get('result_identifiers',[]),
           status=status,verification_status='verified' if ok else 'source_supported',
           error_code=r.get('error_code') or (None if ok else 'SOURCE_RECORD_NOT_READABLE'),
           error_message=r.get('error_message') or (None if ok else reason),retry_count=1 if qid=='Q-RUN03-EPMC-0001' else 0,
           retry_at=None,cache_path=path,cache_hit=False,reused_query_id=None,
           rerun_reason='Recover existing exact MED identities after Q-RUN02-ENT-0198 failed; preserve method/source distinctions.',
           coverage_note=r.get('count_scope','Failed source attempt; no result total established.')+(' '+r.get('retrieval_cache_note','') if r.get('retrieval_cache_note') else ''),
           license_note=r.get('license_note','Sanitized request metadata, response digest and locators; no source body redistribution.'),
           recorded_at_utc=NOW,query_time_status='exact',field_states={})
    missing=[f for f in ['visible_total','returned_count','count_before_dedup','count_after_dedup'] if q[f] is None]
    if missing:
        t.update(field_path='queries.'+qid+'.'+','.join(missing),unknown_since_utc=NOW,
                 deadline_at_utc=(datetime.fromisoformat(NOW.replace('Z','+00:00'))+timedelta(hours=24)).isoformat().replace('+00:00','Z'),review_task_id=tid)
        for field in missing:q['field_states'][field]=dict(status='unknown',reason=reason,evidence_locator=[],unknown_since_utc=NOW,review_task_id=tid)
    data['queries'].append(q)
    data['source-observations'].append(dict(observation_id='OBS-'+qid,query_id=qid,task_id=tid,source_id=sid,
        endpoint_or_url=q['endpoint_or_url'],queried_at_utc=q['queried_at_utc'],query_time_status='exact',status=status,
        http_status=r.get('http_status'),response_kind=r.get('response_kind'),returned_count=count,visible_total=total,
        page_complete=ok,count_scope=q['coverage_note'],receipt_path=path,verification_status=q['verification_status'],
        recorded_at_utc=NOW,external_request_performed=True))
for path in sorted((TEMP/'query-results').glob('Q-RUN03-*.json')):
    r=json.loads(path.read_text())
    if r.get('external_request_performed') is True:add_query_receipt(r,str(path.relative_to(REPO)))
assert sum(q['query_id'].startswith('Q-RUN03-') for q in data['queries'])==16

# The independently reviewed Longden record is integrated only after remote readback.
longden=json.loads((TEMP/'reports/RUN-0003-Longden2010-latency-review.json').read_text())
assert longden['review_status']=='single_claim_review_complete_pending_canonical_ingestion'
a=deepcopy(longden['assessment']);cq=deepcopy(longden['cache_query_record'])
assert a['assessment_id']=='AS-RUN03-Longden2010-L03-onset-latency'
assert not any(x['assessment_id']==a['assessment_id'] for x in data['assessments'])
assert a['evidence_admission_status']=='eligible' and a['handling_level']=='new_evidence_or_hypothesis'
data['assessments'].append(a)
data['manual-reviews'].append(deepcopy(longden['manual_review_record']))
old_l07=next(x for x in data['assessments'] if x['assessment_id']==longden['preservation_guard']['unchanged_assessment_id'])
assert hashlib.sha256((json.dumps(old_l07,ensure_ascii=False,separators=(',',':'))+'\n').encode()).hexdigest()==longden['preservation_guard']['old_assessment_raw_line_sha256']
w=works[a['work_id']]
w['u00_reasons']=[]
w['notes']+=' RUN-0003: one independent L03 response-onset-latency claim admitted after cached primary-page review. The original L07 insufficiency, all other claims and Work-wide assessment coverage remain open.'
assert w['dimension_status']['assessment']=='partial'
tid='T-assessment-'+a['work_id'];old=latest[tid]
task(tid,a['work_id'],'assessment','partial',
     'One L03 onset-latency claim reviewed; original L07 platform-amplitude insufficiency and all other claim/condition coverage remain open.',
     query_ids=list(dict.fromkeys(old['query_ids']+[cq['query_id']])),supporting_record_ids=list(dict.fromkeys(old['supporting_record_ids']+[a['assessment_id']])))
assert latest['T-RUN02-L079-4426c4dc035807f4']['task_state']=='pending'
cache_path='temp/query-results/'+cq['query_id']+'.json'
cq['cache_path']=cache_path
data['queries'].append(cq)
cache_receipt=dict(query_id=cq['query_id'],run_id=RUN,scope_id=SCOPE,source_id=cq['source_id'],
    endpoint_or_url=cq['endpoint_or_url'],queried_at_utc=cq['queried_at_utc'],completed_at_utc=longden['completed_at_utc'],
    query_time_status='exact',cache_hit=True,reused_query_id=cq['reused_query_id'],external_request_performed=False,
    response_kind='cached_primary_pdf_review',returned_count=1,visible_total=1,result_identifiers=cq['result_identifiers'],
    body_sha256=longden['source']['sha256'],body_bytes=longden['source']['bytes'],sanitized=True,payload_retained=False,
    original_retrieved_at_utc=longden['source']['original_retrieved_at_utc'],
    review_report='temp/reports/RUN-0003-Longden2010-latency-review.json',
    timing_note='Timestamp records the completed local cache review; no new origin HTTP request is asserted.')
data['source-observations'].append(dict(observation_id='OBS-'+cq['query_id'],query_id=cq['query_id'],task_id=cq['task_id'],
    source_id=cq['source_id'],endpoint_or_url=cq['endpoint_or_url'],queried_at_utc=cq['queried_at_utc'],query_time_status='exact',
    status='cache_hit',http_status=None,response_kind='cached_primary_pdf_review',returned_count=1,visible_total=1,page_complete=True,
    count_scope=cq['coverage_note'],receipt_path=cache_path,verification_status='verified',recorded_at_utc=NOW,external_request_performed=False))
events.append(dict(kind='new_independent_scientific_claim',assessment_id=a['assessment_id'],work_id=a['work_id'],
    report='temp/reports/RUN-0003-Longden2010-latency-review.json',old_l07_unchanged=True,work_assessment_closed=False))

# Restored unknown clocks are never refreshed. Escalate only actually overdue open fields.
escalated=set()
now_dt=datetime.fromisoformat(NOW.replace('Z','+00:00'))
def walk_unknown(obj):
    if isinstance(obj,list):
        for value in obj:walk_unknown(value)
    elif isinstance(obj,dict):
        if obj.get('status') in {'unknown','unknown_review_required'} and obj.get('unknown_since_utc'):
            since=datetime.fromisoformat(obj['unknown_since_utc'].replace('Z','+00:00'))
            if now_dt>=since+timedelta(hours=24):
                obj['status']='unknown_review_required'
                tid=obj['review_task_id'];t=latest[tid]
                assert t['task_state'] not in TERMINAL
                if tid not in escalated and not(t.get('overdue') and t.get('priority') in ['high','critical']):
                    task(tid,t['entity_id'],t['task_type'],'partial',t['review_condition'],t['entity_type'],overdue=True,priority='high')
                    escalated.add(tid)
        for value in obj.values():walk_unknown(value)
for name in names:
    if name!='tasks':walk_unknown(data[name])
for tid,t in list(latest.items()):
    if t.get('unknown_since_utc') and t['task_state'] not in TERMINAL:
        if now_dt>=datetime.fromisoformat(t['unknown_since_utc'].replace('Z','+00:00'))+timedelta(hours=24):
            if tid not in escalated and not(t.get('overdue') and t.get('priority') in ['high','critical']):
                task(tid,t['entity_id'],t['task_type'],'partial',t['review_condition'],t['entity_type'],overdue=True,priority='high');escalated.add(tid)
assert data['assessments'][:-1]==original_assessments, 'Existing scientific records must remain byte-equivalent.'

schema=json.loads((TEMP/'schema.json').read_text())
checks={'work':[works[x[1]] for x in specs]+[works[a['work_id']]],
        'version':[versions['V-'+x[1]+'-01'] for x in specs],
        'person':data['authors'][baseline_counts['authors']:],
        'task':data['tasks'][baseline_counts['tasks']:],
        'query':data['queries'][baseline_counts['queries']:],
        'reference_occurrence':[x for x in data['reference-occurrences'] if x['occurrence_id'] in resolved],
        'citation_edge':data['citation-edges'][baseline_counts['citation-edges']:],
        'assessment':[a]}
validation=[]
for kind,rows in checks.items():
    validator=Draft202012Validator({'$ref':'#/$defs/'+kind,'$defs':schema['$defs']},format_checker=FormatChecker())
    for row in rows:
        errors=list(validator.iter_errors(row))
        assert not errors, (kind, row.get(kind+'_id'), [(list(e.path),e.message) for e in errors])
    validation.append({'kind':kind,'records':len(rows),'schema_errors':0})
field_completions=[t for t in data['tasks'][baseline_counts['tasks']:] if t['task_type']=='field_review' and t['task_state']=='verified_complete']
assert len(field_completions)==25
assert len(data['authors'])-baseline_counts['authors']==20
assert len(data['queries'])-baseline_counts['queries']==17
assert len(data['manual-reviews'])-baseline_counts['manual-reviews']==13

# All checks above happen before the first canonical write.
for name in names:replace_logical(name+'.jsonl',data[name],TEMP)
dump(REPO/cache_path,cache_receipt)
run=json.loads((TEMP/'runs/RUN-0003.json').read_text())
run.update(external_requests_used=16,external_request_count_status='exact_retained_invocations',
    external_requests_note='One direct EPMC HTTP attempt and 15 recorded web retrieval calls; five PubMed records readable. Git transport is not a research-source query.',
    manual_review_items_used=13,cache_reuse_events=1,status='checkpointing',end_checkpoint_id=CP,
    last_completed_batch='Five existing identities, seven retained reference targets, author-task evidence clarification and one independent L03 cached-fulltext claim.',
    sync_state='All source receipts and manual review decisions were remotely committed and read back before this canonical integration. Canonical/export/checkpoint synchronization pending; no further research may start until exact remote verification passes.')
dump(TEMP/'runs/RUN-0003.json',run)
report=dict(report_id='RUN-0003-integration',scope_id=SCOPE,run_id=RUN,checkpoint_id=CP,
    integrated_at_utc=NOW,baseline_checkpoint='CP-0004',source_receipts_previously_synced=True,
    scientific_records_preserved=len(original_assessments),old_L07_byte_hash_preserved=True,
    changed_logical_datasets=names,counts_before=baseline_counts,counts_after={n:len(v) for n,v in data.items()},
    unknown_field_tasks_closed=len(field_completions),new_work_records=0,new_work_scoped_person_records=20,
    new_reference_resolutions=7,new_source_supported_edges=7,new_assessments=1,new_external_invocations=16,
    cache_reuses=1,manual_review_activities=13,overdue_unknown_tasks_escalated=len(escalated),
    schema_validation=validation,events=events,closure_established=False)
dump(OUT,report)
print(json.dumps({k:v for k,v in report.items() if k not in ['events','schema_validation']},ensure_ascii=False))
