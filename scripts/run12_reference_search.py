"""Retrieve an ordered slice of the saved CP13 frontier with per-provider limits."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from time import monotonic

from run10_reference_records import doi
from run11_source_limits import private_directory
from search_run11_bibliography import (
    OA, OUT, ROOT, SCOPE, TEMP, chunks, compatible_parent, deposited, digest, european, indexed, owners_input,
    read, request, stamp, write,
)
from run11_reference_inventory import literal_project, receipt
from storage import iter_logical

RUN = "RUN-0012"
CP = "CP-0014"
STATE = TEMP / "runs" / (RUN + ".json")
REPORTS = TEMP / "reports" / (RUN + "-batches")
fetch = partial(request, run_id=RUN, checkpoint=CP)


def query(key, provider, endpoint, params, owners, reason, project, *args, **kwargs):
    if provider == "crossref" and "-DEP-" in key:
        key += "-REGISTRY"
        reason = "Retrieve publisher-deposited bibliographies for the saved CP13 frontier."
    return fetch(key, provider, endpoint, params, owners, reason, project, *args, **kwargs)


def deferred(provider, control):
    quota = control / (provider + ".quota")
    if quota.is_file():
        return "daily quota at " + quota.read_text()
    delay = control / (provider + ".next")
    if delay.exists() and float(delay.read_text()) - datetime.now().timestamp() > 60:
        return "provider Retry-After until Unix time " + delay.read_text()
    return None


def family(prefix, owners, provider, field, control):
    observations = defaultdict(list)
    for index, group in enumerate(chunks(owners, field, 40 if provider == "crossref" else 90, 1600)):
        reason = deferred(provider, control)
        if reason:
            for owner in group:
                observations[owner["work_id"]].append((provider, None, None, reason))
            continue
        if provider == "crossref":
            q = deposited(f"{prefix}-DEP-{index+1:02d}", group, query)
            records = {doi(r["DOI"]):r for r in q.get("records", [])}
            for owner in group:
                observations[owner["work_id"]].append((provider,q,records.get(doi(owner[field])),None))
        else:
            q = indexed(f"{prefix}-IDX-{field.upper()}-{index+1:02d}", group, field, query)
            records = {r["work_id"]:r for r in q.get("records", []) if r.get("work_id")}
            for owner in group:
                observations[owner["work_id"]].append((provider,q,records.get(owner["work_id"]),None))
    return observations


def register(observations, titles, coverage, deferred_sources):
    for wid, items in observations.items():
        for provider,q,item,defer in items:
            if defer:
                deferred_sources[wid][provider]=defer
                continue
            item = item or {}
            if provider=="crossref":
                available="reference" in item
                count=len(item.get("reference", []))
                declared=item.get("reference-count")
                match=any(compatible_parent(t,titles[wid]) for t in item.get("title",[]))
            else:
                available="reference_ids" in item
                count=len(item.get("reference_ids", []))
                declared=count if available else None
                match=compatible_parent(item.get("parent_title"),titles[wid])
            coverage[wid].append(dict(query_id=q["query_id"],source_id=provider,status=q["status"],
                rows=count if match else 0,source_declared=declared,available=available and match,
                source_reconciled=available and match and count==declared,parent_title_conflict=bool(item) and not match))


def recover_empty(owners, coverage, control, prefix, postponed, titles):
    from run12_index_availability import CALIBRATION, lookup
    literal={}
    empty=[o for o in owners if o.get("epmc") and not any(s["rows"] for s in coverage[o["work_id"]])]
    calibrated=CALIBRATION.is_file() and read(CALIBRATION)["negative_indicator_usable_as_index_observation"]
    flags=lookup(empty,prefix+"-EP-AVAIL") if calibrated and empty and not deferred("europepmc",control) else {}
    for owner in owners:
        wid=owner["work_id"]
        if any(s["rows"] for s in coverage[wid]):continue
        flag=flags.get(wid,{})
        source_negative=flag.get("has_references")=="N" and compatible_parent(flag.get("parent_title"),titles[wid])
        if owner.get("epmc") and not source_negative:
            wait=deferred("europepmc",control)
            if wait:postponed[wid]["europepmc"]=wait
            else:
                for q in european(prefix+"-EMPTY",owner,query):
                    n=len(q.get("records",[]));ok=q["status"]=="success"
                    coverage[wid].append(dict(source_id="europepmc",query_id=q["query_id"],rows=n,source_declared=q.get("visible_total"),
                             available=ok,source_reconciled=ok and q.get("page_complete",False),status=q["status"],parent_title_conflict=False))
        if any(s["rows"] for s in coverage[wid]):continue
        matched=set()
        for s in coverage[wid]:
            if s["source_id"]=="openalex" and s["available"] and not s["parent_title_conflict"]:
                for row in receipt(s["query_id"])["records"]:
                    if row.get("work_id")==wid:matched.add(row["source_identifier"])
        if len(matched)!=1:continue
        if calibrated and not any((s.get("source_declared") or 0)>0 or s.get("parent_title_conflict") for s in coverage[wid]):
            postponed[wid]["openalex_literal"]="保留逐篇参考条目接口复查。上批 63 个零索引母文献的该接口均返回零条；本轮先处理有来源差额的名单。"
            continue
        ident,=matched
        wait=deferred("openalex",control)
        if wait:
            postponed[wid]["openalex_literal"]=wait
            continue
        q=query(prefix+"-LITERAL-"+ident,"openalex",OA+"/"+ident+"/references",{},owners_input([owner]),
            "Inspect the reference-list representation of an identified parent whose deposited and matched-index views returned no positions.",literal_project)
        literal[wid]=dict(query_id=q["query_id"],parent=ident,rows=len(q.get("records",[])),status=q["status"])
    return literal,flags


def run(start, count):
    timer = monotonic()
    state=read(STATE)
    frontier=ROOT/state["source_frontier"]
    if digest(frontier)!=state["source_frontier_sha256"]:
        raise ValueError("The saved frontier changed")
    queue=read(frontier)["worklist"]
    end=min(start+count,len(queue))
    if not 0<=start<end:raise ValueError("Invalid queue slice")
    REPORTS.mkdir(exist_ok=True)
    report=REPORTS/f"{start+1:05d}-{end:05d}.json"
    if report.exists():
        old=read(report)
        if not all(digest(ROOT/p)==h for p,h in old["input_receipts"].items()):
            raise ValueError("Stored receipt changed")
        return
    if start and not any(p.stem.endswith(f"-{start:05d}") for p in REPORTS.glob("*.json")):
        raise ValueError("Earlier ordered receipt slice is missing")
    owners=queue[start:end]
    wanted={r["work_id"] for r in owners}
    titles={w["work_id"]:[w["canonical_title"],*w["title_variants"]] for w in iter_logical("works.jsonl") if w["work_id"] in wanted}
    if titles.keys()!=wanted:raise ValueError("Missing canonical parent title")
    control=private_directory(RUN)
    prefix=f"B{start+1:05d}"
    coverage=defaultdict(list)
    deferred_sources=defaultdict(dict)
    def fetch_family(*args):return family(prefix,*args,control)
    # OpenAlex-only parents are independent of the deposited DOI requests.
    with ThreadPoolExecutor(max_workers=2) as pool:
        cr=pool.submit(fetch_family,[o for o in owners if o["doi"]],"crossref","doi")
        oa=pool.submit(fetch_family,[o for o in owners if not o["doi"] and o.get("openalex")],"openalex","openalex")
        for job in (cr,oa):register(job.result(),titles,coverage,deferred_sources)
    needs=[o for o in owners if not any(s["source_reconciled"] and s["rows"] for s in coverage[o["work_id"]])
           and (o["doi"] or not o.get("openalex"))]
    for field in ("openalex","epmc","doi"):
        group=[o for o in needs if o.get(field)]
        if group:register(family(prefix+"-FALLBACK",group,"openalex",field,control),titles,coverage,deferred_sources)
        needs=[o for o in needs if not o.get(field)]
    literal,flags=recover_empty(owners,coverage,control,prefix,deferred_sources,titles)
    tables=[dict(queue_position=i,work_id=o["work_id"],work_key=o["work_key"],task_id=o["task_id"],literal=literal.get(o["work_id"]),reference_index_indicator=flags.get(o["work_id"]),
                 sources=coverage[o["work_id"]],deferred_sources=deferred_sources[o["work_id"]])
            for i,o in enumerate(owners,start+1)]
    if any(not r["sources"] and not r["deferred_sources"] for r in tables):raise ValueError("Missing source accounting")
    receipts=sorted(OUT.glob(f"Q-RUN12-{prefix}-*.json"))
    counts=Counter()
    for entry in tables:
        for source in entry["sources"]:counts[source["source_id"]]+=source["rows"]
        if entry.get("literal"):counts["openalex"]+=entry["literal"]["rows"]
    summary=dict(starting_index=start,next_index=end,parent_count=len(owners),parents_with_rows=sum(bool(any(s["rows"] for s in r["sources"]) or (r.get("literal") or {}).get("rows")) for r in tables),
                 source_positions=dict(counts),sources_requested=len(receipts),elapsed_seconds=round(monotonic()-timer,3))
    write(report,dict(run_id=RUN,scope_id=SCOPE,target_checkpoint=CP,frontier_sha256=state["source_frontier_sha256"],
          first_key=owners[0]["work_key"],next_key=queue[end]["work_key"] if end<len(queue) else None,created_at_utc=stamp(),**summary,
          input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in receipts},worklist=tables))
    print(summary,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start",type=int)
    parser.add_argument("count",type=int)
    args=parser.parse_args()
    run(args.start,args.count)
