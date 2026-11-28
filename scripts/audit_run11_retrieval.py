"""Audit the two frozen identifier plans and every CP12 retrieval position against immutable Git receipts."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import hashlib
import json

from index_run11_positions import INDEX
from run11_canonical_cursor import committed_paths, query_key
from run11_reference_inventory import OUT, PLAN, ROOT, STATE, SUPPLEMENT, TEMP, WIDTH, digest, preferred, read, stamp, write


def plan_report(name,publish):
    path=PLAN/name
    if not path.exists():return False
    committed=committed_paths(OUT);plan=read(path);results=[];missing=[];totals=defaultdict(Counter)
    for i,g in enumerate(plan["groups"],1):
        key=query_key(g);files=sorted(f for f in committed if f.startswith(key+"-A") and f.endswith(".json"))
        if not files:missing.append(i);continue
        q=read(OUT/files[-1]);source=g["provider"]
        if q["status"]!="success" and q["retryable"] and not q.get("deferred") and q["attempt"]<4:
            missing.append(i);continue
        if q["status"]=="success":
            assert set(g["ids"])==set(q.get("requested_identifiers",[]))
            found=[r["source_identifier"] for r in q["records"]]
            assert len(set(found))==len(found)==q["returned_count"] and set(found)|set(q["missing_identifiers"])==set(g["ids"])
        else:found=[]
        outcomes=totals[source];outcomes["groups"]+=1;outcomes["requested"]+=len(g["ids"]);outcomes["returned"]+=len(found)
        outcomes["not_returned"]+=len(g["ids"])-len(found);outcomes["failed_groups"]+=q["status"]!="success"
        results.append(dict(group=i,query_id=q["query_id"],status=q["status"],requested=len(g["ids"]),returned=len(found),
                            terminal_receipt_sha256=digest(OUT/files[-1]),attempts=files))
    if missing:
        if publish:raise ValueError(f"{len(missing)} identity groups remain unbound")
        return False
    result=PLAN/(path.stem+"-results.json")
    if publish and not result.exists():
        write(result,dict(run_id="RUN-0011",recorded_at_utc=stamp(),input_plan=path.relative_to(ROOT).as_posix(),plan_sha256=digest(path),
                          groups=len(results),by_source={k:dict(v) for k,v in totals.items()},results=results))
    return True


def source_index():
    q=read(STATE);frontier=read(ROOT/q["frontier"])["worklist"];inputs={};parents=[];totals=Counter();channels=Counter();oa=Counter();gaps=[];excluded=[]
    for start in range(0,len(frontier),WIDTH):
        end=min(start+WIDTH,len(frontier));key=f"{start+1:04}-{end:04}";path=preferred(INDEX,key);m=read(path)
        assert ROOT/m["supplement_manifest"]==preferred(SUPPLEMENT,key),"A reviewed index must be materialized before the full-cohort audit"
        assert (m["start_index"],m["next_index"])==(start,end)
        part=ROOT/m["position_file"];assert digest(part)==m["position_file_sha256"]
        assert digest(ROOT/m["primary_manifest"])==m["primary_sha256"] and digest(ROOT/m["supplement_manifest"])==m["supplement_sha256"]
        local=Counter();seen=set();kinds=Counter()
        with part.open(encoding="utf-8") as f:
            for line in f:
                r=json.loads(line);ordinal=r["queue_position"];ref=(ordinal,r["source"],r["position"])
                assert start<ordinal<=end and ref not in seen and len(r["raw_sha256"])==64
                seen.add(ref);local[ordinal]+=1;kinds[r["kind"]]+=1
        assert len(seen)==m["counts"].get("positions",0)
        for a,o in zip(m["parents"],frontier[start:end],strict=True):
            assert a["work_id"]==o["work_id"] and a["work_key"]==o["work_key"] and local[a["queue_position"]]==a["counts"].get("positions",0)
            parents.append(a["work_id"]);channels.update(a["positions_by_channel"]);oa.update(a["openalex_fields"])
            if not local[a["queue_position"]]:gaps.append({k:a[k] for k in ("queue_position","work_id","work_key","task_id")})
            for conflict in a["excluded_parent_identities"]:excluded.append(dict(work_id=a["work_id"],work_key=a["work_key"],**conflict))
        totals.update(m["counts"]);inputs[path.relative_to(ROOT).as_posix()]=digest(path)
    assert len(parents)==len(set(parents))==len(frontier)==2620
    result=TEMP/"reports/RUN-0011-CP12-parent-reconciliation.json"
    lineage={}
    if result.exists() and read(result)["inputs"]!=inputs:
        lineage={"supersedes":result.relative_to(ROOT).as_posix(),"supersedes_sha256":digest(result)}
        result=result.with_stem(result.stem+"-reconciled")
    if result.exists() and read(result)["inputs"]!=inputs:
        raise ValueError("A different published reference reconciliation exists")
    if not result.exists():
        write(result,dict(**lineage,run_id="RUN-0011",scope_id=q["scope_id"],created_at_utc=stamp(),source_frontier=q["frontier"],source_frontier_sha256=q["frontier_sha256"],
                    initial_key=frontier[0]["work_key"],last_key=frontier[-1]["work_key"],visited=len(parents),with_entries=len(parents)-len(gaps),
                    without_entries=len(gaps),positions=dict(totals),positions_by_source_representation=dict(channels),openalex_literal_endpoint_fields=dict(oa),
                    excluded_parent_identities=excluded,alternative_source_queue=gaps,inputs=inputs,original_bibliographies_verified_complete=0,
                    boundary="来源内去重位置；多来源可指同一引文。稳定标识是候选，正式入库与引文边以规范数据事务为准。"))
    print(len(parents),len(gaps),dict(totals),dict(channels),dict(oa),flush=True)


def timing():
    entries=defaultdict(list);unknown=[];errors=Counter();count=0
    for p in sorted(OUT.glob("Q-RUN11-*.json")):
        q=read(p);count+=q["external_request_count"]
        if q["status"]!="success":errors[(q["source_id"],str(q.get("http_status")),q["status"])]+=1
        if q.get("requested_at_utc"):
            a=datetime.fromisoformat(q["requested_at_utc"]);b=datetime.fromisoformat(q["completed_at_utc"]);assert b>=a
            entries[q["source_id"]].append((a,b,q["query_id"],q.get("execution_limits")))
        else:unknown.append(q["query_id"])
    pairs=[];pace=[];counts={}
    for provider,spans in entries.items():
        active=[];last=None;counts[provider]=len(spans)
        for a,b,k,guard in sorted(spans):
            active=[r for r in active if r[1]>a]
            for other in active:
                pairs.append(dict(source_id=provider,first=other[2],second=k,earlier_guarded=bool(other[3]),later_guarded=bool(guard)))
            if provider=="crossref" and last is not None and (a-last[0]).total_seconds()<1:
                pace.append(dict(first=last[2],second=k,seconds=(a-last[0]).total_seconds(),both_guarded=bool(last[3] and guard)))
            active.append((a,b,k,guard));last=(a,b,k,guard)
    p=TEMP/"reports/RUN-0011-provider-timing.json"
    if not p.exists():
        write(p,dict(run_id="RUN-0011",audited_at_utc=stamp(),actual_requests=count,exact_times=counts,unavailable_exact=unknown,
             overlapping_receipt_windows=pairs,crossref_start_intervals_under_one_second=pace,
             source_failures=[dict(source_id=k[0],http_status=k[1],status=k[2],count=v) for k,v in errors.items()],
             interpretation="请求回执区间含本地响应解析。早期并行进程未共用来源锁，历史串行性不能认证。后续共用来源锁、预算登记及 25 秒超时；保留原始回执和失败。"))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("ready","finish","sources","timing"))
    p.add_argument("--plan",default="groups.json",choices=("groups.json","first-1024.json"));args=p.parse_args()
    if args.action in ("ready","finish"):print("ready" if plan_report(args.plan,args.action=="finish") else "waiting")
    elif args.action=="sources":source_index()
    else:timing()
