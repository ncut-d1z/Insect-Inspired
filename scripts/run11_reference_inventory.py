"""Read the CP12 queue in order, reconcile provider projections, and resolve reference identifiers in batches."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import re

from run10_reference_records import doi, fields, identifiers, metadata, request_identities, token
from search_run11_bibliography import (
    BATCHES, OA, OUT, ROOT, STATE, TEMP, WIDTH, compatible_parent, digest, frozen_titles, owners_input, read, request, stamp, write,
)
from storage import iter_logical

SUPPLEMENT = TEMP / "reports/RUN-0011-reference-supplements"
PLAN = TEMP / "reports/RUN-0011-identity-plan"


def preferred(folder,label,extension=".json"):
    corrected=folder/(label+"-reconciled"+extension)
    return corrected if corrected.is_file() else folder/(label+extension)


@lru_cache(maxsize=12)
def receipt(qid):
    return read(OUT / (qid + ".json"))


def queue_inputs():
    run=read(STATE)
    frontier=ROOT/run["frontier"]
    if digest(frontier)!=run["frontier_sha256"]:
        raise ValueError("CP12 frontier checksum changed")
    queue=read(frontier)["worklist"]
    titles=frozen_titles()
    assert len(titles)==len(queue)==run["initial_queue_count"]
    return queue,titles


def manifest(start,end):
    suffix="-reconciled" if start==0 else ""
    path=BATCHES/f"{start+1:04}-{end:04}{suffix}.json"
    obj=read(path)
    assert obj["starting_index"]==start and obj["next_index"]==end
    for rel,h in obj["input_receipts"].items():
        if digest(ROOT/rel)!=h:raise ValueError("Source cache changed: "+rel)
    return path,obj


def primary_lists(owner, row, titles, certified=()):
    if owner["work_id"]!=row["work_id"]:raise ValueError("Parent order changed")
    for obs in row["sources"]:
        q=receipt(obs["query_id"]);provider=q["source_id"]
        if q["status"]!="success":continue
        if provider=="crossref":
            records=[r for r in q["records"] if doi(r.get("DOI"))==doi(owner.get("doi"))]
            if len(records)>1:raise ValueError("Duplicate deposited parent")
            if not records:continue
            paper=records[0];okay=q["query_id"] in certified or any(compatible_parent(t,titles) for t in paper.get("title",[]))
            yield q,"deposited",paper.get("reference",[]),paper.get("reference-count"),okay,paper["DOI"],"reference" in paper
        elif provider=="openalex":
            records=[r for r in q["records"] if r["work_id"]==owner["work_id"]]
            if len(records)>1:raise ValueError("Ambiguous OpenAlex parent")
            if not records:continue
            paper=records[0];okay=q["query_id"] in certified or compatible_parent(paper.get("parent_title"),titles)
            yield q,"index_ids",[{"openalex":v} for v in paper["reference_ids"]],len(paper["reference_ids"]),okay,paper["source_identifier"],True
        else:
            assert provider=="europepmc" and q["owners"]==owners_input([owner])
            yield q,"indexed_bibliography",q["records"],q["visible_total"],True,owner["epmc"],True


def literal_project(data):
    rows=data if isinstance(data,list) else data.get("references")
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError("Unrecognized OpenAlex reference list")
    declared=len(rows) if isinstance(data,list) else int((data.get("meta") or {}).get("count",len(rows)))
    if len(rows)!=declared:raise ValueError("OpenAlex reference list requires further pagination")
    for row in rows:
        wid=row.get("work_id")
        if wid and not re.fullmatch(r"W\d+",wid.rsplit("/",1)[-1]):raise ValueError("Invalid index match")
    return dict(records=rows,visible_total=declared,returned_count=len(rows),page_complete=True)


def supplement(queue,titles,start):
    group=queue[start:start+WIDTH];end=start+len(group);path,batch=manifest(start,end)
    SUPPLEMENT.mkdir(exist_ok=True)
    dest=SUPPLEMENT/f"{start+1:04}-{end:04}.json"
    if dest.exists():
        obj=read(dest);assert obj["base_sha256"]==digest(path) and all(digest(ROOT/f)==h for f,h in obj["receipts"].items())
        return
    reused={}
    for p in [*OUT.glob("Q-RUN11-VER-ORIGINAL-W*.json"),*OUT.glob("Q-RUN11-VER-PRINT-W*.json")]:
        q=receipt(p.stem)
        if q["status"]=="success" and q["endpoint_or_url"].endswith("/references"):reused[q["endpoint_or_url"]]=q
    entries=[];bindings={};summary=Counter()
    for owner,row in zip(group,batch["worklist"]):
        wid=owner["work_id"];seen=[];clashes=[];index=[]
        for q,kind,refs,decl,okay,parent,present in primary_lists(owner,row,titles[wid]):
            if okay and present:seen.append(kind)
            if not okay:
                clashes.append({"source_id":q["source_id"],"query_id":q["query_id"],"identifier":parent,"excluded_positions":len(refs)})
            if okay and kind=="index_ids":index.append((parent,q))
        if len({parent for parent,_ in index})>1:raise ValueError("Conflicting OpenAlex parent identities")
        entry={"work_id":wid,"ordinal":row["queue_position"],"excluded_parent_identities":clashes,"openalex_literal_query":None}
        summary["excluded_parent_identifiers"]+=len(clashes)
        if index:
            parent=index[0][0];endpoint=OA+"/"+parent+"/references"
            q=reused.get(endpoint)
            if not q:
                q=request(f"RAW-{start+1:04}-{parent}","openalex",endpoint,{},owners_input([owner]),
                          "Retrieve the reference-list text, raw DOI and index assignment, including unmatched items.",literal_project)
            entry.update(openalex_literal_query=q["query_id"],openalex_parent=parent)
            p=OUT/(q["query_id"]+".json");bindings[p.relative_to(ROOT).as_posix()]=digest(p)
            summary["literal_requests_bound"]+=1
            summary["literal_positions"]+=len(q.get("records",[]))
        entries.append(entry)
    write(dest,dict(run_id="RUN-0011",base=path.relative_to(ROOT).as_posix(),base_sha256=digest(path),
                    created_at_utc=stamp(),counts=dict(summary),parents=entries,receipts=bindings))
    print(dest.name,dict(summary),flush=True)


def source_pages(owner,row,titles,extra=None):
    """Supplementary literal matches and matched-ID projections can describe the same reference."""
    literal_q=receipt(extra["openalex_literal_query"]) if extra and extra.get("openalex_literal_query") else None
    literal_ids=set()
    if literal_q and literal_q["status"]=="success":
        refs=[]
        for item in literal_q["records"]:
            ident=(item.get("work_id") or "").rsplit("/",1)[-1]
            if ident:literal_ids.add(ident)
            refs.append({**item,"openalex":ident or None})
        yield literal_q,"literal_bibliography",refs,extra["openalex_parent"],list(range(1,len(refs)+1))
    for q,kind,refs,decl,okay,parent,present in primary_lists(owner,row,titles,(extra or {}).get("certified_parent_queries",())):
        if not okay or not present:continue
        start=(q.get("page_index",1)-1)*1000 if kind=="indexed_bibliography" else 0
        rows=[(pos,raw) for pos,raw in enumerate(refs,start+1) if kind!="index_ids" or raw["openalex"] not in literal_ids]
        yield q,kind,[raw for _,raw in rows],parent,[pos for pos,_ in rows]


def raw_ids(raw,provider):
    if provider=="openalex":
        printed,*_=fields({"unstructured":raw.get("raw_reference_string")},"crossref")
        return tuple(dict.fromkeys(k for k in (doi(raw.get("raw_doi")),printed,raw.get("openalex")) if k))
    d,e,*_=fields(raw,provider)
    return tuple(k for k in (d,e) if k)


def plan(queue,titles,end_at=None):
    PLAN.mkdir(exist_ok=True)
    end_at=end_at or len(queue)
    if not 0<end_at<=len(queue) or (end_at%WIDTH and end_at!=len(queue)):
        raise ValueError("The plan must end at a verified cohort boundary")
    destination=PLAN/("groups.json" if end_at==len(queue) else f"first-{end_at:04}.json")
    if destination.is_file():
        saved=read(destination)
        assert saved["queue_end"]==end_at and all(digest(ROOT/k)==v for k,v in saved["source_hashes"].items())
        print("Verified saved plan",destination.name,len(saved["groups"]),flush=True)
        return
    previous=set()
    for name in ("works","versions","aliases"):
        for r in iter_logical(name+".jsonl"):
            if r.get("verification_status") not in ("conflicting","rejected"):previous.update(identifiers(r))
    previous.discard("10.1523/jneurosci.19-19-08573.1999")  # CP12's inherited conflicting DOI
    for r,_ in metadata():previous.update(k for k in (r.get("doi"),r.get("epmc"),r.get("openalex")) if k)
    # The misassigned Europe PMC crosswalk must never vouch for the 1999 record.
    previous.discard("10.1523/jneurosci.19-19-08573.1999")
    for p in OUT.glob("Q-RUN11-ID-*.json"):
        q=receipt(p.stem)
        if q["status"]=="success":
            previous.update(q.get("requested_identifiers",[]))
            for r in q["records"]:previous.update(k for k in (r.get("doi"),r.get("epmc"),r.get("openalex")) if k)
    todo=defaultdict(dict);counts=Counter();source_hashes={};frontier={}
    for start in range(0,end_at,WIDTH):
        group=queue[start:start+WIDTH];end=start+len(group);path,batch=manifest(start,end)
        sp=preferred(SUPPLEMENT,f"{start+1:04}-{end:04}");supp=read(sp);assert supp["base_sha256"]==digest(path)
        source_hashes[sp.relative_to(ROOT).as_posix()]=digest(sp)
        for owner,row,extra in zip(group,batch["worklist"],supp["parents"],strict=True):
            assert owner["work_id"]==extra["work_id"]
            for q,kind,refs,parent,positions in source_pages(owner,row,titles[owner["work_id"]],extra):
                counts[kind]+=len(refs)
                for raw in refs:
                    for k in raw_ids(raw,q["source_id"]):
                        if k in previous:continue
                        provider="openalex" if k.startswith("W") else "europepmc" if k.startswith(("MED:","PPR:")) else "crossref"
                        todo[provider].setdefault(k,owner["work_id"])
            frontier[owner["work_id"]]=owner["task_id"]
    groups=[];limits={"openalex":95,"crossref":115,"europepmc":88}
    # Rotate through providers; a finite source budget must not starve the smaller ID namespaces.
    packed={}
    for provider,ids in todo.items():
        batches=[];items=[];length=0
        for k,wid in ids.items():
            if items and (len(items)>=limits[provider] or length+len(k)>3900):
                batches.append(items);items=[];length=0
            items.append((k,wid));length+=len(k)
        if items:batches.append(items)
        packed[provider]=batches
    for i in range(max(map(len,packed.values()),default=0)):
        for provider in ("crossref","openalex","europepmc"):
            if i>=len(packed.get(provider,[])):continue
            items=packed[provider][i];parents=list(dict.fromkeys(w for _,w in items))
            groups.append(dict(provider=provider,ids=[k for k,_ in items],owners=[dict(work_id=w,task_id=frontier[w]) for w in parents]))
    write(destination,dict(run_id="RUN-0011",queue_end=end_at,source_positions=dict(counts),unique_new_identifier_candidates={k:len(v) for k,v in todo.items()},
                 source_hashes=source_hashes,groups=groups,created_at_utc=stamp()))
    print("distinct unqueried identifiers",dict((k,len(v)) for k,v in todo.items()),"query groups",len(groups),"positions",dict(counts),flush=True)


def lookup_request(key,provider,endpoint,params,owners,why,project):
    if provider=="crossref":
        # A full DOI registration retains language as well as article-number.
        # Crossref explicitly rejects language in its field-selection syntax.
        key+="-META"
    return request(key,provider,endpoint,params,owners,why,project)


def hydrate(start,count,plan_name):
    import subprocess
    common=Path(subprocess.check_output(["git","rev-parse","--path-format=absolute","--git-common-dir"],text=True).strip())
    if (common/"RUN-0011-identity-yield").exists():
        print(f"Yielding before identity group {start+1} in {plan_name}.",flush=True)
        raise SystemExit(75)
    plan=read(PLAN/plan_name)
    for i,group in enumerate(plan["groups"][start:start+count],start):
        q=request_identities(group["ids"],group["provider"],group["owners"],lookup_request)
        print(i+1,q["query_id"],q["status"],q.get("returned_count"),flush=True)
        if q.get("deferred"):raise RuntimeError("Provider requires deferred retry: "+q["query_id"])


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("supplement","plan","hydrate"));p.add_argument("start",type=int,nargs="?",default=0)
    p.add_argument("--count",type=int,default=1);p.add_argument("--end",type=int)
    p.add_argument("--plan",choices=("groups.json","first-1024.json"),default="groups.json");args=p.parse_args()
    if args.action=="hydrate":hydrate(args.start,args.count,args.plan)
    else:
        queue,titles=queue_inputs()
        if args.action=="plan":plan(queue,titles,args.end)
        else:
            for start in range(args.start,min(args.start+args.count*WIDTH,len(queue)),WIDTH):supplement(queue,titles,start)
