"""Reconcile ordered RUN12 source, canonical and Git measurements without advancing any research task."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from run12_canonical import PLANS, TRANSACTIONS
from run12_evidence_integration import LEGACY, PAIRS, TRANSACTION
from run12_reference_search import CP, REPORTS, RUN, STATE
from run12_reviews import ABSTRACTS, VERSIONS
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write

SOURCES=TEMP/"reports/RUN-0012-reference-accounting.json"
FRONTIER=TEMP/"reports/RUN-0012-next-frontier.json"
TIMING=TEMP/"reports/RUN-0012-provider-timing.json"
PILOT_GIT={128:(9.8505676,106.09,72.1756817),256:(10.6345635,108.16,79.9145681),
           384:(14.4193175,112.63,95.9278039),512:(12.1057506,118.41,93.5609104)}


def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT,text=True,encoding="utf-8").strip()


def account():
    run=read(STATE)
    initial=ROOT/run["source_frontier"]
    if digest(initial)!=run["source_frontier_sha256"]:raise ValueError("Initial frontier changed")
    original=read(initial)["worklist"]
    raw_end=0
    canonical_end=0
    source_positions=Counter()
    materialized=Counter()
    absent=[]
    new=[]
    added=Counter()
    version_ids=set()
    unresolved=0
    funding={}
    cp12_xml={}
    insects={}
    inputs={}
    measurements=[]
    bound={}

    def recorded(p):
        inputs[p.relative_to(ROOT).as_posix()]=digest(p)
        return read(p)

    for path in sorted(REPORTS.glob("*.json")):
        d=recorded(path)
        if d["starting_index"]!=raw_end:raise ValueError("Source cursor gap")
        if d["frontier_sha256"]!=run["source_frontier_sha256"]:raise ValueError("Changed saved source frontier")
        if [r["work_id"] for r in d["worklist"]]!=[r["work_id"] for r in original[raw_end:d["next_index"]]]:raise ValueError("Source order changed")
        for k,h in d["input_receipts"].items():
            if digest(ROOT/k)!=h:raise ValueError("Changed source receipt "+k)
        source_positions.update(d["source_positions"])
        for row in d["worklist"]:
            wid=row["work_id"]
            n=sum(s["rows"] for s in row["sources"])+(row.get("literal") or {}).get("rows",0)
            bound[wid]=n
            if n==0:absent.append(dict(work_id=wid,work_key=row["work_key"],task_id=row["task_id"],position=row["queue_position"],
                                     source_batch=path.relative_to(ROOT).as_posix(),next_action="alternative_bibliographic_source"))
        raw_end=d["next_index"]
        row=dict(start=d["starting_index"],end=raw_end,source_wall_seconds=d["elapsed_seconds"],retrieved_parents=d["parents_with_rows"])
        if raw_end in PILOT_GIT:
            row["publish_seconds"],row["canonical_transaction_seconds"],row["canonical_publish_seconds"]=PILOT_GIT[raw_end]
            row["timing_basis"]="PowerShell stopwatch and Python transaction elapsed times from the four pilot batch invocations."
        measurements.append(row)
    for path in sorted(TRANSACTIONS.glob("*.json")):
        d=recorded(path)
        if d["starting_index"]!=canonical_end or d["next_index"]>raw_end:raise ValueError("Canonical cursor gap")
        if [r["work_id"] for r in d["coverage"]]!=[r["work_id"] for r in original[canonical_end:d["next_index"]]]:raise ValueError("Canonical order changed")
        for r in d["coverage"]:
            if sum(r["positions"].values())!=bound[r["work_id"]]:raise ValueError("Returned and registered position totals differ "+r["work_id"])
            materialized.update(r["positions"]);unresolved+=sum(r["unresolved"].values())
        if "funding_review" in d:funding=d["funding_review"]
        if "cp12_xml_review" in d:cp12_xml=d["cp12_xml_review"]
        if "insect_abstract_review" in d:insects=d["insect_abstract_review"]
        new.extend(d["discovered_worklist"])
        added.update(d["added_counts"])
        version_ids.update(t for t in d["datasets"]["tasks"]["appended_ids"] if t.startswith("T-R12-CITED-"))
        canonical_end=d["next_index"]
    science=recorded(TRANSACTION)
    new.extend(science["discovered_worklist"])
    reviews=recorded(VERSIONS);original_review=recorded(LEGACY)
    abstracts=recorded(ABSTRACTS);forward=recorded(PAIRS)
    frontier=[*original[canonical_end:],*new]
    frontier.sort(key=lambda r:r["depth"])
    if len(frontier)!=len({r["work_id"] for r in frontier}) or len(frontier)!=len({r["task_id"] for r in frontier}):
        raise ValueError("Duplicate or dropped continuing task")
    plans=[recorded(p) for p in sorted(PLANS.glob("*.json"))]
    stats=dict(visited=raw_end,with_entries=raw_end-len(absent),without_entries=len(absent),positions={"positions":sum(source_positions.values()),**source_positions},
        canonical_parents=canonical_end,canonical_positions=sum(materialized.values()),resolved_positions=sum(materialized.values())-unresolved,unresolved_positions=unresolved,
        canonical_source_positions=dict(materialized),new_backward_works=added["works"],new_backward_edges=added["citation-edges"],new_crossdate_tasks=len(version_ids),
        initial_frontier=len(original),remaining_original_parents=len(original)-canonical_end,pending_materialization=raw_end-canonical_end,
        next_original_key=original[canonical_end]["work_key"] if canonical_end<len(original) else None,
        new_forward_works=sum(r["new_work"] for r in science["forward"]),new_forward_edges=sum(r["new_edge"] for r in science["forward"]),
        next_frontier_count=len(frontier),original_bibliographies_verified_complete=0,source_frontier_sha256=run["source_frontier_sha256"])
    resource=dict(plan_identifier_cache_memberships=sum(p["cached_or_canonical_identifier_count"] for p in plans),
                  identifier_request_groups=sum(len(p["groups"]) for p in plans),identifier_candidates=sum(sum(p["ids_to_lookup"].values()) for p in plans))
    return run,stats,absent,frontier,new,inputs,dict(versions=reviews["counts"],oldest=original_review["counts"],abstracts=abstracts["counts"],forward=forward["counts"],publication_funding=funding,cp12_xml=cp12_xml,insect_abstracts=insects),measurements,resource


def times():
    providers=defaultdict(list);status=Counter();requests=0
    for p in sorted(OUT.glob("Q-RUN12-*.json")):
        q=read(p)
        if q["run_id"]!=RUN or q["external_request_count"]!=1:raise ValueError("Unbound source request")
        start=datetime.fromisoformat(q["requested_at_utc"]);end=datetime.fromisoformat(q["completed_at_utc"])
        if end<start:raise ValueError("Invalid source clock")
        providers[q["source_id"]].append((start,end,q["query_id"]))
        status[q["status"]]+=1;requests+=1
    overlap=[];rate=[];minimum={}
    for sid,rs in providers.items():
        ordered=sorted(rs);smallest=None
        for (a,b,x),(c,d,y) in zip(ordered,ordered[1:]):
            if c<b:overlap.append([sid,x,y])
            seconds=(c-a).total_seconds()
            if sid=="crossref" and seconds<1:rate.append([x,y,seconds])
            smallest=seconds if smallest is None else min(smallest,seconds)
        minimum[sid]=smallest
    priv=Path(git("rev-parse","--absolute-git-dir"))
    logs=priv/"RUN-0012-publish-timings.jsonl"
    import json
    git_timings=[json.loads(line) for line in logs.read_text("utf-8").splitlines()] if logs.exists() else []
    if (priv/"RUN-0012-sync-halt").exists():raise ValueError("Git synchronization requires recovery")
    return dict(run_id=RUN,observed_at_utc=stamp(),requests=requests,by_source={s:len(v) for s,v in providers.items()},by_status=dict(status),
          overlapping_source_windows=overlap,crossref_short_intervals=rate,minimum_start_interval_seconds=minimum,publish_timings=git_timings)


def save(path,value):
    if path.exists():raise ValueError("An immutable report already exists: "+path.name)
    write(path,value)


def main(freeze):
    run,s,absent,frontier,new,inputs,science,measurements,resources=account()
    timing=times()
    if timing["overlapping_source_windows"] or timing["crossref_short_intervals"]:raise ValueError("Source timing requires reconciliation")
    reviewed=read(TRANSACTION)["added_counts"]["manual-reviews"]+science["cp12_xml"].get("reviewed_items",0)+science["insect_abstracts"].get("reviewed_abstracts",0)
    when=stamp()
    report=dict(run_id=RUN,scope_id=SCOPE,checkpoint_target=CP,observed_at_utc=when,checkpoint_validated=False,canonical_head=git("rev-parse","HEAD"),
            study=s,scientific_reviews=science,source_timing={k:v for k,v in timing.items() if k!="publish_timings"},measurements=measurements,
            identifier_lookup=resources,manual_review_items=reviewed,canonical_input_hashes=inputs)
    if not freeze:
        path=TEMP/"reports"/f"RUN-0012-progress-{s['canonical_parents']:05d}.json"
        if not path.exists():save(path,report)
        print(s,flush=True)
        return
    if s["pending_materialization"] or git("status","--porcelain"):raise ValueError("Publish complete source and canonical cohorts before freezing")
    if timing["requests"]>run["budget"]["external_requests"] or reviewed>run["budget"]["manual_review_items"]:raise ValueError("Budget exceeded")
    save(TIMING,timing)
    save(SOURCES,{**report,**s,"no_visible_positions":absent,"unresolved_source_actions":"Retain all source-specific tasks and cursor history; an empty index does not certify an empty bibliography."})
    save(FRONTIER,dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,source_frontier=run["source_frontier"],source_frontier_sha256=run["source_frontier_sha256"],
         canonical_parents=s["canonical_parents"],canonical_positions=s["canonical_positions"],remaining_original_parents=s["remaining_original_parents"],
         next_original_parent=s["next_original_key"],source_gap_parent_count=len(absent),gap_ledger=SOURCES.relative_to(ROOT).as_posix(),
         discovered_work_count=len(new),continuing_task_count=len(frontier),by_depth=dict(Counter(r["depth"] for r in frontier)),worklist=frontier))
    baseline=read(ROOT/run["start_sync_receipt"])
    run.update(status="checkpoint_preparation",canonical_watermark_at_utc=when,authorized_stages=["P3","P4","P5","P6"],branch="main",
        checkpoint_commit=run["start_commit_sha"],start_sync_gate={"checkpoint_sha256":baseline["parent_checkpoint_sha256"],"recovered_data_commit":baseline["commit"]},
        external_requests_used=timing["requests"],manual_review_items_used=reviewed,paid_spend=0,
        cache_reuse_events={"metadata_identifier_memberships":resources["plan_identifier_cache_memberships"],"definition":"Distinct known identifiers per lookup plan, not an external-request count."},
        next_backward_frontier=FRONTIER.relative_to(ROOT).as_posix(),source_accounting=SOURCES.relative_to(ROOT).as_posix(),
        version_review_file=VERSIONS.relative_to(ROOT).as_posix(),abstract_review_file=ABSTRACTS.relative_to(ROOT).as_posix())
    temp=STATE.with_suffix(".new")
    write(temp,run);temp.replace(STATE)
    print(s,timing["requests"],reviewed,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--freeze",action="store_true");main(p.parse_args().freeze)
