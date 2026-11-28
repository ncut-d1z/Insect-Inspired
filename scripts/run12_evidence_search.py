"""Collect permitted abstract, byline, grant and forward-index evidence for motion-related Works."""
import argparse
import re

from run10_reference_records import doi, norm
from run11_source_limits import private_directory
from run12_reference_search import RUN, STATE, fetch
from search_run9_bibliography import facts
from search_run11_bibliography import EPMC, ROOT, compatible_parent, digest, read, write
from storage import iter_logical

PMIDS = ("22036184","18161592","9472485","8724666","8723207","11954696","11163855","8917793")


def identities():
    state=read(STATE)
    path=ROOT/state["source_frontier"]
    if digest(path)!=state["source_frontier_sha256"]:raise ValueError("Frontier changed")
    queue={"MED:"+pid for pid in PMIDS}
    owners={r["work_id"]:r for r in read(path)["worklist"] if r["epmc"] in queue}
    works={w["work_id"]:w for w in iter_logical("works.jsonl") if w["work_id"] in owners}
    if len(works)!=len(queue):raise ValueError("Missing or ambiguous PMID")
    return {r["epmc"].split(":")[1]:(r,works[wid]) for wid,r in owners.items()}


def abstracts(papers):
    cache=private_directory(RUN)/"motion-abstracts.json"
    owners=[dict(work_id=papers[pid][0]["work_id"],task_id="T-abstract-"+papers[pid][0]["work_id"]) for pid in PMIDS]
    params={"query":"SRC:MED AND ("+" OR ".join("EXT_ID:"+k for k in PMIDS)+")",
            "resultType":"core","format":"json","pageSize":len(PMIDS)}
    def project(response):
        rows=response["resultList"]["result"]
        if len(rows)!=int(response["hitCount"]) or len({r["id"] for r in rows})!=len(rows):raise ValueError("Unreconciled metadata response")
        result=[]
        texts={}
        for row in rows:
            pid=row["id"];owner,w=papers[pid]
            if row["source"]!="MED" or not compatible_parent(row["title"],[w["canonical_title"],*w["title_variants"]]):
                raise ValueError("PMID and canonical title differ")
            record=facts(row)
            record["work_id"]=owner["work_id"]
            record["identifier_agreement"]=not owner["doi"] or not row.get("doi") or doi(row["doi"])==doi(owner["doi"])
            record["grants"]=[{k:r[k] for k in ("grantId","agency","acronym","orderIn") if k in r} for r in (row.get("grantsList") or {}).get("grant",[])]
            result.append(record)
            if row.get("abstractText"):texts[pid]=row["abstractText"]
        if cache.exists():
            if texts!=read(cache):raise ValueError("Private abstract cache differs")
        else:write(cache,texts)
        return dict(records=result,visible_total=len(result),returned_count=len(result),page_complete=True,missing_identifiers=sorted(set(PMIDS)-{r["id"] for r in rows}))
    q=fetch("P56-MOTION-ABSTRACTS","europepmc",EPMC+"search",params,owners,"Consult bibliographic metadata, abstracts, bylines and registered grant identifiers.",project)
    print(q["query_id"],q["status"],q.get("returned_count"),q.get("error"),flush=True)


def linked(papers,pid,kind,page):
    item,w=papers[pid]
    wid=item["work_id"]
    endpoint=EPMC+"MED/"+pid+"/"+kind
    params={"format":"json","page":page,"pageSize":100}
    def project(response):
        key="citation" if kind=="citations" else "reference"
        rows=response.get(key+"List",{}).get(key,[])
        total=int(response["hitCount"])
        offset=(page-1)*100
        if offset+len(rows)>total or (len(rows)<100 and offset+len(rows)<total):raise ValueError("Incomplete index page")
        return dict(records=rows,visible_total=total,returned_count=len(rows),cursor_in=str(page),
             cursor_out=str(page+1) if offset+len(rows)<total else None,page_complete=offset+len(rows)==total)
    q=fetch(f"P4-{kind.upper()}-{pid}-P{page}","europepmc",endpoint,params,
            [dict(work_id=wid,task_id="T-citations-"+wid)],"Discover forward candidates in a public bibliographic index; preserve page and cutoff uncertainty.",project,page)
    print(q["query_id"],q["status"],q.get("returned_count"),q.get("visible_total"),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("abstracts","citations"))
    parser.add_argument("--pmid",choices=PMIDS)
    parser.add_argument("--page",type=int,default=1)
    args=parser.parse_args()
    papers=identities()
    if args.mode=="abstracts":abstracts(papers)
    else:linked(papers,args.pmid,args.mode,args.page)
