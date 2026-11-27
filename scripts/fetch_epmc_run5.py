#!/usr/bin/env python3
"""One bounded RUN-0005 Europe PMC operation; retain bibliographic facts only.

The root orchestrator publishes each receipt before invoking this again. This
helper does not change canonical records or infer identities/citation contexts.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--query-id', required=True)
    p.add_argument('--task-id', required=True)
    p.add_argument('--entity-id', required=True)
    p.add_argument('--kind', choices=['identity', 'citations'], required=True)
    p.add_argument('--query')
    p.add_argument('--pmid')
    p.add_argument('--page', type=int, default=1)
    p.add_argument('--reason', required=True)
    a = p.parse_args()
    assert a.query_id.startswith('Q-RUN05-') and '/' not in a.query_id
    out = ROOT / 'temp/query-results' / (a.query_id + '.json')
    assert not out.exists(), 'Do not overwrite a retained operation'
    if a.kind == 'identity':
        assert a.query and not a.pmid
        params = dict(query=a.query, resultType='core', format='json', pageSize=100)
        url = API + 'search?' + urllib.parse.urlencode(params)
    else:
        assert a.pmid and a.pmid.isdigit() and not a.query and a.page > 0
        params = dict(format='json', page=a.page, pageSize=1000)
        url = API + 'MED/' + a.pmid + '/citations?' + urllib.parse.urlencode(params)
    r = dict(query_id=a.query_id, run_id='RUN-0005', scope_id='SCOPE-0001',
             checkpoint_id='CP-0007', task_id=a.task_id, entity_id=a.entity_id,
             source_id='europepmc', endpoint_or_url=url, raw_parameters=params,
             query_kind=a.kind, queried_at_utc=stamp(), query_time_status='exact',
             external_requests_performed=1, cache_hit=False, rerun_reason=a.reason,
             sanitized=True, payload_retained=False,
             license_note='Public bibliographic facts; abstract/full text and personal contact details omitted.',
             cutoff_at_utc='2026-11-26T05:24:08Z',
             index_drift_note='Live source observed now, not a historical snapshot. Publication cutoff is checked separately.')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Insect-Inspired literature research'})
        with urllib.request.urlopen(req, timeout=25) as h:
            raw = h.read()
            r.update(http_status=h.status, content_type=h.headers.get('Content-Type'))
        d = json.loads(raw)
        rows = d.get('resultList', {}).get('result', []) if a.kind == 'identity' else d.get('citationList', {}).get('citation', [])
        allowed = {'id', 'source', 'pmid', 'pmcid', 'doi', 'title', 'authorString',
                   'journalAbbreviation', 'pubYear', 'firstPublicationDate',
                   'isOpenAccess', 'inEPMC', 'inPMC', 'pubTypeList', 'pageInfo'}
        records = []
        for row in rows:
            v = {k: x for k, x in row.items() if k in allowed}
            if 'authorList' in row:
                v['authors'] = [{k: x for k, x in z.items() if k in
                    {'fullName', 'firstName', 'lastName', 'initials', 'collectiveName'}}
                    for z in row['authorList'].get('author', [])]
            if 'journalInfo' in row:
                ji = row['journalInfo']
                v['journal'] = {k: x for k, x in ji.get('journal', {}).items()
                                if k in {'title', 'medlineAbbreviation', 'issn', 'essn'}}
                v['journal_issue'] = {k: x for k, x in ji.items() if k in {'issue', 'volume', 'yearOfPublication', 'dateOfPublication'}}
            records.append(v)
        total = d.get('hitCount')
        if a.kind == 'identity':
            cursor_in = '*'
            complete = isinstance(total, int) and total == len(records)
            cursor_out = None if complete else d.get('nextCursorMark')
        else:
            cursor_in = str(a.page)
            complete = isinstance(total, int) and (a.page - 1) * 1000 + len(records) == total
            cursor_out = None if complete else str(a.page + 1)
        r.update(status='success', body_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest(),
                 records=records, returned_count=len(records), visible_total=total,
                 cursor_in=cursor_in, cursor_out=cursor_out, page_index=a.page,
                 page_complete=complete, provider_response_keys=sorted(d),
                 error_code=None, error_message=None)
    except Exception as e:
        r.update(status='retryable_error', http_status=getattr(e, 'code', None),
                 error_code=type(e).__name__, error_message=str(e), records=[],
                 returned_count=0, visible_total=None, page_complete=False,
                 cursor_in='*' if a.kind == 'identity' else str(a.page),
                 cursor_out='*' if a.kind == 'identity' else str(a.page), page_index=a.page)
    r['completed_at_utc'] = stamp()
    out.write_text(json.dumps(r, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: r.get(k) for k in ['query_id', 'status', 'returned_count', 'visible_total', 'page_complete', 'error_message']}))


if __name__ == '__main__':
    main()
