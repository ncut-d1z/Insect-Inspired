"""Bind ordered RUN12 reference lists, look up previously unknown identifiers and commit canonical transactions."""
import argparse
from collections import Counter, defaultdict
from itertools import zip_longest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from integrate_run11_bibliography import Canonical
from run10_reference_records import doi, identifiers, request_identities, token
from run11_reference_inventory import raw_ids, receipt, source_pages
from run12_reference_search import CP, REPORTS, RUN, STATE, deferred, query
from run11_source_limits import private_directory
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

PLANS=TEMP/"reports/RUN-0012-identities"
TRANSACTIONS=TEMP/"reports/RUN-0012-canonical"


class CurrentCanonical(Canonical):
    checkpoint=CP
    id_prefix="R12"
    reuse_citing_positions=True
    prefer_supporting_coverage_query=True
    metadata_prefixes=(*Canonical.metadata_prefixes,"Q-RUN12-ID-")


def label(start,end):
    return f"{start+1:05d}-{end:05d}"


def rows(start,end):
    state=read(STATE)
    frontier=ROOT/state["source_frontier"]
    if digest(frontier)!=state["source_frontier_sha256"]:raise ValueError("Source frontier changed")
    owners=read(frontier)["worklist"][start:end]
    wanted={o["work_id"] for o in owners}
    if len(owners)!=end-start or len(wanted)!=len(owners):raise ValueError("Ambiguous input positions")
    titles={w["work_id"]:[w["canonical_title"],*w["title_variants"]] for w in iter_logical("works.jsonl") if w["work_id"] in wanted}
    attempts=defaultdict(set);paths=set();inputs=set();data=[]
    for path in sorted(REPORTS.glob("*.json")):
        lo,hi=map(int,path.stem.split("-"))
        if lo>end or hi<=start:continue
        report=read(path);inputs.add(path)
        if report["frontier_sha256"]!=state["source_frontier_sha256"]:raise ValueError("Wrong source frontier")
        for name,h in report["input_receipts"].items():
            p=ROOT/name
            if digest(p)!=h:raise ValueError("Source evidence changed: "+name)
            q=receipt(p.stem)
            for o in q["owners"]:
                if o["work_id"] in wanted:
                    attempts[o["work_id"]].add(p.stem);paths.add(p)
        for row in report["worklist"]:
            wid=row["work_id"]
            if wid not in wanted:continue
            owner=owners[row["queue_position"]-start-1]
            if owner["work_id"]!=wid or not attempts[wid]:raise ValueError("Unbound or deferred parent")
            extra={"excluded_parent_identities":[{"query_id":s["query_id"]} for s in row["sources"] if s["parent_title_conflict"]]}
            if row.get("literal"):
                extra.update(openalex_literal_query=row["literal"]["query_id"],openalex_parent=row["literal"]["parent"])
            data.append((owner,row,extra,attempts[wid],list(source_pages(owner,row,titles[wid],extra))))
    if [x[0]["work_id"] for x in data]!=[o["work_id"] for o in owners]:raise ValueError("Gap in ordered input")
    return data,inputs,paths


def plan(start,end):
    PLANS.mkdir(exist_ok=True)
    p=PLANS/(label(start,end)+".json")
    if p.exists():return
    data,inputs,_=rows(start,end)
    existing=set()
    for dataset in ("works","versions","aliases"):
        for r in iter_logical(dataset+".jsonl"):
            if r.get("verification_status") not in ("conflicting","rejected"):existing.update(identifiers(r))
    for prefix in CurrentCanonical.metadata_prefixes:
        for path in OUT.glob(prefix+"*.json"):
            q=read(path)
            if q.get("status")=="success":
                for r in q.get("records",[]):existing.update(x for x in (r.get("doi"),r.get("epmc"),r.get("openalex")) if x)
    existing.discard("10.1523/jneurosci.19-19-08573.1999")
    todo=defaultdict(dict);namespaces=Counter();previous=set()
    for o,_,_,_,pages in data:
        for q,kind,refs,ident,positions in pages:
            for raw in refs:
                ids=raw_ids(raw,q["source_id"])
                if len({k for k in ids if doi(k)})>1:continue
                for k in ids:
                    provider="openalex" if k.startswith("W") else "europepmc" if k.startswith(("MED:","PPR:")) else "crossref"
                    if k in existing:previous.add(k);continue
                    todo[provider].setdefault(k,{"work_id":o["work_id"],"task_id":o["task_id"]})
    groups=[]
    for provider,ids in sorted(todo.items()):
        packet=[];size=0
        for k in ids:
            if packet and (len(packet)>=88 or size+len(k)>3200):
                groups.append((provider,packet));packet=[];size=0
            packet.append(k);size+=len(k)
        if packet:groups.append((provider,packet))
    batches=[]
    for provider,ids in groups:
        owners={todo[provider][k]["work_id"]:todo[provider][k] for k in ids}
        batches.append(dict(provider=provider,ids=ids,owners=list(owners.values())))
        namespaces[provider]+=len(ids)
    per_source=[[g for g in batches if g["provider"]==provider] for provider in sorted(namespaces)]
    batches=[g for wave in zip_longest(*per_source) for g in wave if g is not None]
    write(p,dict(run_id=RUN,checkpoint_id=CP,starting_index=start,next_index=end,created_at_utc=stamp(),cached_or_canonical_identifier_count=len(previous),
             ids_to_lookup=dict(namespaces),input_receipts={x.relative_to(ROOT).as_posix():digest(x) for x in inputs},groups=batches))
    print("Identity plan",p.name,"cached",len(previous),"new identifiers",dict(namespaces),"groups",len(groups),flush=True)


def hydrate(start,end,offset,limit):
    p=PLANS/(label(start,end)+".json")
    groups=read(p)["groups"][offset:offset+limit]
    control=private_directory(RUN)
    def worker(provider):
        results=Counter()
        for g in (g for g in groups if g["provider"]==provider):
            if deferred(provider,control):break
            q=request_identities(g["ids"],provider,g["owners"],query)
            results[q["status"]]+=1
        return provider,dict(results)
    with ThreadPoolExecutor(max_workers=3) as pool:
        print(list(pool.map(worker,sorted({g["provider"] for g in groups}))),flush=True)


def apply(start,end):
    t=monotonic()
    data,inputs,paths=rows(start,end)
    TRANSACTIONS.mkdir(exist_ok=True)
    path=TRANSACTIONS/(label(start,end)+".json")
    if path.exists():raise ValueError("Existing transaction")
    prior=sorted(TRANSACTIONS.glob("*.json"))
    if (read(prior[-1])["next_index"] if prior else 0)!=start:raise ValueError("Canonical cursor gap")
    owners={o["task_id"] for o,*_ in data}
    related=(*OUT.glob("Q-RUN12-ID-*.json"),*OUT.glob("Q-RUN12-AVAIL-CAL-*.json"))
    for p in related:
        q=read(p)
        if any(o["task_id"] in owners for o in q["owners"]):paths.add(p)
    from run12_funding import REPORT as funding_report, register as register_funding
    funding_pending=funding_report.is_file() and not any("funding_review" in read(part) for part in prior)
    if funding_pending:
        paths.add(OUT/(read(funding_report)["query_id"]+".json"))
        paths.update(OUT.glob("Q-RUN12-P5-DEPOSITED-FUNDING-*.json"))
    from run12_legacy_review import REVIEW as legacy_review, register as register_legacy
    legacy_pending=legacy_review.is_file() and not any("cp12_xml_review" in read(part) for part in prior)
    if legacy_pending:
        paths.update(OUT.glob("Q-RUN12-P4-DOC-CP12-*.json"))
    from run12_insect_review import REPORT as insect_report, register as register_insects
    insects_pending=insect_report.is_file() and not any("insect_abstract_review" in read(part) for part in prior)
    if insects_pending:
        paths.update(OUT.glob("Q-RUN12-P6-INSECT-*.json"))
    from run12_cached_revisions import REPORT as extra_report, register as register_extra_versions
    extra_pending = extra_report.is_file() and not any("cached_version_review" in read(p) for p in prior)
    ledger=CurrentCanonical(data,inputs,paths)
    outcomes=ledger.register(data)
    funding=register_funding(ledger) if funding_pending else None
    legacy=register_legacy(ledger) if legacy_pending else None
    insects=register_insects(ledger) if insects_pending else None
    extra_versions = register_extra_versions(ledger) if extra_pending else None
    ledger.account(paths)
    counts={k:len(v) for k,v in ledger.adds.items() if v}
    report=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,starting_index=start,next_index=end,created_at_utc=ledger.now,
        source_frontier=read(STATE)["source_frontier"],coverage=outcomes,discovered_worklist=ledger.new_frontier,
        input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in ledger.input_paths},added_counts=counts)
    if funding is not None:report["funding_review"]=funding
    if legacy is not None:report["cp12_xml_review"]=legacy
    if insects is not None:report["insect_abstract_review"]=insects
    if extra_versions is not None:
        report["cached_version_review"] = extra_versions
    print("Canonical batch",label(start,end),counts,flush=True)
    apply_batch(ledger.changes,{k:list(v.values()) for k,v in ledger.adds.items() if v},report,path.relative_to(ROOT).as_posix())
    print("Committed-file transaction seconds",round(monotonic()-t,2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=("plan","hydrate","apply"))
    p.add_argument("start",type=int);p.add_argument("end",type=int)
    p.add_argument("--offset",type=int,default=0);p.add_argument("--groups",type=int,default=12)
    a=p.parse_args()
    if a.mode=="hydrate":hydrate(a.start,a.end,a.offset,a.groups)
    elif a.mode=="plan":plan(a.start,a.end)
    else:apply(a.start,a.end)
