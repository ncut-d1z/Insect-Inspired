"""Fetch the CP12 queue in its saved order, retaining source-specific reference lists."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from run10_reference_records import clean, doi
from search_run10_references import CR, EPMC, OUT, ROOT, TEMP, read, stamp, write

RUN = "RUN-0011"
CP = "CP-0013"
SCOPE = "SCOPE-0001"
STATE = TEMP / "runs" / (RUN + ".json")
BATCHES = TEMP / "reports" / "RUN-0011-batches"
OA = "https://api.openalex.org/works"
WIDTH = 64


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owners_input(rows):
    return [{k:row[k] for k in ("work_id","task_id")} for row in rows]


def request(key, source, endpoint, parameters, owners, why, project, page=1):
    url = endpoint + ("?" + urlencode(parameters) if parameters else "")
    for attempt in range(1, 4):
        file = OUT / f"Q-RUN11-{key}-A{attempt}.json"
        if file.exists():
            saved = read(file)
            if saved["endpoint_or_url"] != url or saved["owners"] != owners:
                raise ValueError("Mismatching recorded query " + key)
            if saved["status"] == "success" or not saved.get("retryable") or saved.get("deferred") or attempt == 3:
                return saved
            continue
        run = read(STATE)
        if (datetime.now(timezone.utc)-datetime.fromisoformat(run["started_at_utc"])).total_seconds() >= run["budget"]["wall_clock_hours"]*3600:
            raise RuntimeError("Run clock budget reached")
        if sum(1 for _ in OUT.glob("Q-RUN11-*.json")) >= run["budget"]["external_requests"]:
            raise RuntimeError("Run source request budget reached")
        entry = dict(query_id=file.stem,run_id=RUN,scope_id=SCOPE,target_checkpoint=CP,source_id=source,
                     requested_at_utc=stamp(),endpoint_or_url=url,parameters=parameters,page_index=page,owners=owners,
                     reason=why,external_request_count=1,attempt=attempt,status="error",http_status=None,retryable=False)
        delay = 2**attempt
        headers = {"Accept":"application/json","User-Agent":"Insect-Inspired-Bibliography/1.3"}
        try:
            with urlopen(Request(url,headers=headers), timeout=32) as response:
                entry["http_status"] = response.status
                raw = response.read()
            entry.update(response_sha256=hashlib.sha256(raw).hexdigest(),response_bytes=len(raw))
            entry.update(project(json.loads(raw)))
            entry["status"] = "success"
        except HTTPError as exc:
            entry.update(http_status=exc.code,error=str(exc),retryable=exc.code in (408,429,500,502,503,504))
            header = exc.headers.get("Retry-After")
            if header:
                entry["retry_after"] = header
                try:
                    delay = max(delay, int(header) if header.isdigit() else (parsedate_to_datetime(header)-datetime.now(timezone.utc)).total_seconds())
                except (TypeError,ValueError,OverflowError): pass
        except (OSError,KeyError,ValueError,TypeError,AssertionError) as exc:
            entry.update(error=type(exc).__name__+": "+str(exc),retryable=isinstance(exc,OSError))
        if delay > 60: entry["deferred"] = True
        entry["completed_at_utc"] = stamp()
        write(file,entry)
        if entry["status"] == "success" or not entry["retryable"] or entry.get("deferred") or attempt == 3:
            return entry
        time.sleep(delay)


def chunks(rows, id_field, maximum, characters=1800):
    packet = []
    length = 0
    for row in rows:
        value = row[id_field]
        if packet and (len(packet) == maximum or length + len(value) > characters):
            yield packet
            packet = []
            length = 0
        packet.append(row)
        length += len(value)
    if packet:
        yield packet


def deposited(key, group):
    wanted = {doi(row["doi"]): row for row in group}
    params = {"filter":",".join("doi:"+k for k in wanted),"rows":len(wanted)}
    def project(data):
        msg = data["message"]; papers = msg["items"]
        got = [doi(p["DOI"]) for p in papers]
        if len(set(got)) != len(papers) or set(got)-set(wanted) or len(papers) != msg["total-results"]:
            raise ValueError("Crossref DOI-set response differs")
        papers=[{k:r[k] for k in ("DOI","title","reference","reference-count","published") if k in r} for r in papers]
        return dict(records=papers,visible_total=len(papers),returned_count=len(papers),page_complete=True,
                    missing_identifiers=sorted(set(wanted)-set(got)))
    return request(key,"crossref",CR,params,owners_input(group),"Publisher-deposited reference lists for the saved CP12 parents.",project)


def indexed(key, group, field):
    wanted = {row[field]:row for row in group}
    api = {"doi":"doi","openalex":"openalex_id","epmc":"pmid"}[field]
    ids = [k.split(":")[-1] if field=="epmc" else k for k in wanted]
    params = {"filter":api+":"+"|".join(ids),"per_page":len(ids),"select":"id,doi,ids,display_name,publication_year,referenced_works"}
    def project(data):
        records=[];seen=set();hits=Counter()
        for paper in data["results"]:
            oid=paper["id"].rsplit("/",1)[-1];pmid=(paper.get("ids",{}).get("pmid") or "").rsplit("/",1)[-1]
            got={"doi":doi(paper.get("doi")),"openalex":oid,"epmc":"MED:"+pmid}[field]
            if oid in seen or not re.fullmatch(r"W\d+",oid):raise ValueError("Duplicate or malformed OpenAlex Work ID")
            seen.add(oid);hits[got]+=1
            ids=[v.rsplit("/",1)[-1] for v in paper["referenced_works"]]
            if not all(re.fullmatch(r"W\d+",v) for v in ids):raise ValueError("Malformed referenced Work ID")
            records.append(dict(source_identifier=oid,requested_identity=got,work_id=None,parent_title=paper.get("display_name"),
                           doi=doi(paper.get("doi")),pmid=pmid or None,reference_ids=ids))
        if len(records)!=data["meta"]["count"]:raise ValueError("OpenAlex list pagination differs")
        for r in records:
            value=r["requested_identity"]
            if value in wanted and hits[value]==1:r["work_id"]=wanted[value]["work_id"]
        matched={r["requested_identity"] for r in records if r["work_id"]}
        return dict(records=records,visible_total=len(records),returned_count=len(records),page_complete=True,
                    missing_or_ambiguous_identifiers=sorted(set(wanted)-matched))
    return request(key,"openalex",OA,params,owners_input(group),"Indexed reference identifiers for a missing or incomplete deposited bibliography.",project)


def european(prefix, owner):
    kind,ident=owner["epmc"].split(":",1);total=None;page=1
    if kind not in ("PPR","MED") or not ident.isalnum():raise ValueError("Bad Europe PMC ID")
    while True:
        def project(data):
            n=int(data["hitCount"]);rows=data.get("referenceList",{}).get("reference",[])
            if (total is not None and total!=n) or (page-1)*1000+len(rows)>n or (not rows and (page-1)*1000<n):
                raise ValueError("Europe PMC count drift")
            return dict(records=rows,visible_total=n,returned_count=len(rows),page_complete=(page-1)*1000+len(rows)==n,
                        cursor_in=str(page),cursor_out=None if (page-1)*1000+len(rows)==n else str(page+1))
        q=request(prefix+"-EP-"+ident+"-P"+str(page),"europepmc",EPMC+kind+"/"+quote(ident)+"/references",
                  {"format":"json","page":page,"pageSize":1000},owners_input([owner]),"Complement missing parent bibliographies with an independent reference-list index.",project,page)
        yield q
        if q["status"]!="success" or q["page_complete"]: break
        total=q["visible_total"];page+=1


def fetch_batch(start, reconcile=False):
    run=read(STATE);frontier=ROOT/run["frontier"]
    if digest(frontier)!=run["frontier_sha256"]:raise ValueError("CP12 queue has changed")
    queue=read(frontier)["worklist"]
    if not 0<=start<len(queue) or start%WIDTH:raise ValueError("Use a saved batch boundary")
    parents=queue[start:start+WIDTH];end=start+len(parents)
    BATCHES.mkdir(exist_ok=True)
    if start and not (BATCHES/f"{start-WIDTH+1:04}-{start:04}.json").exists():raise ValueError("Missing earlier batch")
    report=BATCHES/f"{start+1:04}-{end:04}.json"
    prior=None
    if reconcile:
        if start!=0 or not report.exists():raise ValueError("Expected the original first batch")
        prior=read(report);report=report.with_stem(report.stem+"-reconciled")
    if report.exists():
        obj=read(report)
        assert obj["frontier_sha256"]==run["frontier_sha256"] and all(digest(ROOT/p)==h for p,h in obj["input_receipts"].items())
        return
    prefix=f"B{start+1:04}";coverage={r["work_id"]:[] for r in parents}
    def add(owner,q,n,declared,present,complete):
        if any(s["query_id"]==q["query_id"] for s in coverage[owner["work_id"]]):return
        coverage[owner["work_id"]].append(dict(source_id=q["source_id"],query_id=q["query_id"],rows=n,source_declared=declared,
                                  available=present,source_reconciled=complete,status=q["status"]))
    if prior:
        for row in prior["worklist"]:coverage[row["work_id"]].extend(row["sources"])
    for ix,group in enumerate(chunks([p for p in parents if p["doi"]],"doi",18)):
        q=deposited(prefix+f"-DEP-{ix+1:02}",group)
        recs={doi(r["DOI"]):r for r in q.get("records",[])}
        for owner in group:
            item=recs.get(doi(owner["doi"]),{});n=len(item.get("reference",[]));decl=item.get("reference-count")
            add(owner,q,n,decl,"reference" in item,"reference" in item and n==decl)
    def usable(owner):
        return any(r["rows"]>0 and r["source_reconciled"] for r in coverage[owner["work_id"]])
    needs=[p for p in parents if not usable(p)]
    for field in ("openalex","doi","epmc"):
        subset=[p for p in needs if p.get(field)]
        for ix,group in enumerate(chunks(subset,field,35)):
            q=indexed(prefix+f"-IDX-{field.upper()}-{ix+1:02}",group,field)
            recs={r["work_id"]:r for r in q.get("records",[])}
            for p in group:
                item=recs.get(p["work_id"]);n=len(item["reference_ids"]) if item else 0
                add(p,q,n,n if item else None,bool(item),bool(item))
        needs=[p for p in needs if not p.get(field)]
    for p in parents:
        if p.get("epmc") and not usable(p):
            for q in european(prefix,p):
                add(p,q,len(q.get("records",[])),q.get("visible_total"),q["status"]=="success",q.get("page_complete",False))
    receipts=sorted(OUT.glob("Q-RUN11-"+prefix+"-*.json"))
    tables=[dict(queue_position=i,work_id=p["work_id"],work_key=p["work_key"],task_id=p["task_id"],sources=coverage[p["work_id"]]) for i,p in enumerate(parents,start+1)]
    if not all(r["sources"] for r in tables):raise ValueError("No source attempt for parent")
    counts=Counter()
    for row in tables:
        for s in row["sources"]:counts[s["source_id"]]+=s["rows"]
    obj=dict(run_id=RUN,scope_id=SCOPE,frontier_sha256=run["frontier_sha256"],starting_index=start,next_index=end,
             first_key=parents[0]["work_key"],parent_count=len(parents),parents_with_rows=sum(any(s["rows"] for s in r["sources"]) for r in tables),
             source_positions=dict(counts),sources_requested=len(receipts),created_at_utc=stamp(),worklist=tables,
             input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in receipts})
    if prior:obj["supersedes_batch_sha256"]=digest(BATCHES/f"{start+1:04}-{end:04}.json")
    write(report,obj);print(report.name,obj["parents_with_rows"],sum(counts.values()),dict(counts),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start",type=int,help="Zero-based saved index in the CP12 frontier")
    parser.add_argument("--reconcile",action="store_true")
    args=parser.parse_args()
    fetch_batch(args.start,args.reconcile)
