"""Calibrate Europe PMC's bibliographic reference-list flag against the previously observed lists."""
from collections import Counter
from pathlib import Path

from run12_reference_search import RUN, STATE, query
from search_run11_bibliography import EPMC, OUT, ROOT, TEMP, chunks, compatible_parent, digest, owners_input, read, stamp, write

CALIBRATION=TEMP/"reports/RUN-0012-reference-availability-calibration.json"


def lookup(owners,prefix):
    result={}
    for ix,group in enumerate(chunks(owners,"epmc",65,2000),1):
        kinds={}
        desired={o["epmc"]:o for o in group}
        for k in desired:
            src,pid=k.split(":",1);kinds.setdefault(src,[]).append(pid)
        expr=" OR ".join("(SRC:"+src+" AND ("+" OR ".join('EXT_ID:"'+pid+'"' for pid in pids)+"))" for src,pids in kinds.items())
        def project(data):
            papers=data.get("resultList",{}).get("result",[])
            if len(papers)!=int(data["hitCount"]):raise ValueError("Bibliographic availability page incomplete")
            seen=set();rows=[]
            for p in papers:
                key=p["source"]+":"+p["id"]
                if key in seen or key not in desired:raise ValueError("Unexpected availability accession")
                seen.add(key)
                rows.append(dict(source_identifier=key,work_id=desired[key]["work_id"],parent_title=p.get("title"),
                                 has_references=p.get("hasReferences"),bib_date=p.get("firstPublicationDate")))
            return dict(records=rows,returned_count=len(rows),visible_total=len(rows),page_complete=True,missing_identifiers=sorted(desired.keys()-seen))
        q=query(prefix+f"-{ix:02d}","europepmc",EPMC+"search",dict(query=expr,format="json",resultType="lite",pageSize=len(group)),
                owners_input(group),"Check the bibliographic index's reference-list availability flag for identified parents.",project)
        for r in q.get("records",[]):result[r["work_id"]]={**r,"query_id":q["query_id"]}
    return result


def calibrate():
    if CALIBRATION.exists():return
    state=read(STATE);frontier=ROOT/state["source_frontier"]
    if digest(frontier)!=state["source_frontier_sha256"]:raise ValueError("Parent identities changed")
    owners={r["work_id"]:r for r in read(frontier)["worklist"]}
    actual={};sources={}
    for p in sorted(OUT.glob("Q-RUN12-B*-EMPTY-EP-*-P1-A1.json")):
        q=read(p)
        if q["status"]!="success":continue
        o,=q["owners"];wid=o["work_id"];actual[wid]=q["visible_total"]
        sources[p.relative_to(ROOT).as_posix()]=digest(p)
    if not actual:raise ValueError("No real reference-list responses for calibration")
    observed=lookup([owners[w] for w in actual],"AVAIL-CAL")
    cells=Counter();conflicts=[];results=[]
    for wid,n in actual.items():
        card=observed.get(wid,{});flag=card.get("has_references")
        qid=card.get("query_id")
        if qid:
            p=OUT/(qid+".json");sources[p.relative_to(ROOT).as_posix()]=digest(p)
        cells[(flag or "unknown")+("_positive" if n else "_empty")]+=1
        if flag=="N" and n>0:conflicts.append(wid)
        results.append(dict(work_id=wid,epmc=owners[wid]["epmc"],reference_count=n,flag=flag,indicator_query=qid))
    usable=not conflicts and cells["N_empty"]>0 and cells["Y_positive"]>0
    write(CALIBRATION,dict(run_id=RUN,observed_at_utc=stamp(),actual_parents=len(actual),counts=dict(cells),
             false_negative_work_ids=conflicts,negative_indicator_usable_as_index_observation=usable,items=results,input_receipts=sources))
    print("Measured reference availability",dict(cells),"usable for source-reported negatives",usable,flush=True)


if __name__=="__main__":calibrate()
