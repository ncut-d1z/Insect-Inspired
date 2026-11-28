"""Freeze the CP12 continuation, retain all recursive cursors and verify split CP13 delivery files."""
import argparse
from collections import Counter
import gc
import json
from pathlib import Path

from audit_cp10 import input_digest, input_snapshot
from checkpoint_cp10 import require, validate_checkpoint
from coverage_run10 import collect
from escalate_unknown_run7 import git, sha
from export_checkpoint_windows import WEB_FILES, generate
from history_run11 import audit
from partitioned_checkpoint import checkpoint_files, load_checkpoint, write_checkpoint
from partitioned_research_json import encode, put, reconstruct
from search_run11_bibliography import CP, ROOT, RUN, SCOPE, STATE, TEMP, digest, read, stamp

CANDIDATE=Path("temp/snapshots/checkpoints/CP-0013.json")
FRONTIER=Path("temp/reports/RUN-0011-frontier-after-CP12.json")
SOURCES=Path("temp/reports/RUN-0011-CP12-parent-reconciliation-reconciled.json")
INPUTS=Path("temp/validation/cp13-inputs.json")
HISTORY=Path("temp/validation/cp13-history.json")
TIMING=Path("temp/reports/RUN-0011-provider-timing.json")


def head():
    return git(ROOT,"rev-parse","HEAD").decode().strip()


def frontier():
    run=read(STATE); original=read(ROOT/run["frontier"])["worklist"]; sources=read(ROOT/SOURCES)
    require(len(original)==sources["visited"]==2620 and digest(ROOT/run["frontier"])==sources["source_frontier_sha256"],"Frozen CP12 frontier differs")
    steps=[];end=0
    for p in sorted((TEMP/"reports/RUN-0011-canonical").glob("*.json")):
        d=read(p)
        require(d["starting_index"]==end and [w["work_id"] for w in original[end:d["next_index"]]]==[w["work_id"] for w in d["coverage"]],"Discontinuous parent processing")
        end=d["next_index"];steps.append((p,d))
    repair=TEMP/"reports/RUN-0011-Chao1995-integration.json"
    if repair.is_file():steps.append((repair,read(repair)))
    children=[w for _,d in sorted(steps,key=lambda p:p[1]["created_at_utc"]) for w in d["discovered_worklist"]]
    # Keep the discovery order among equally deep children.
    children.sort(key=lambda r:r["depth"])
    require(len(children)==len({r["work_id"] for r in children})==len({r["task_id"] for r in children}),"Duplicate or missing discovery task")
    positions=sum(d.get("added_counts",{}).get("reference-occurrences",0) for _,d in steps)
    if end==len(original):require(positions==sources["positions"]["positions"],"Formal occurrences and independently indexed source positions differ")
    result=dict(scope_id=SCOPE,run_id=RUN,checkpoint_id=CP,source_frontier=run["frontier"],source_frontier_sha256=sources["source_frontier_sha256"],
                parent_source_index=SOURCES.as_posix(),parent_source_index_sha256=digest(ROOT/SOURCES),parents_visited=len(original),
                canonical_parents=end,canonical_positions=positions,remaining_original_parents=len(original)-end,
                next_original_parent=original[end] if end<len(original) else None,source_gap_parent_count=sources["without_entries"],
                discovered_work_count=len(children),worklist=children,by_depth=dict(Counter(r["depth"] for r in children)),
                inputs={p.relative_to(ROOT).as_posix():digest(p) for p,_ in steps})
    put(ROOT/FRONTIER,encode(result)+b"\n")
    run.update(next_backward_frontier=FRONTIER.as_posix(),next_backward_count=len(children),canonical_parent_cursor=end)
    put(STATE,encode(run)+b"\n")
    print("Original parents, canonical positions, new recursive queue",end,positions,len(children),flush=True)


def frozen_files():
    tracked=git(ROOT,"ls-files","-z").decode().split("\0")
    ignored={"README.md","temp/progress.md","temp/change-log.md","ref.bib",*WEB_FILES,INPUTS.as_posix(),HISTORY.as_posix(),CANDIDATE.as_posix(),
             "temp/reports/P3-P6-CP0013.md"}
    return {p for p in tracked if p and p not in ignored and not p.startswith(("temp/exports/",CANDIDATE.with_suffix("").as_posix()+"/","temp/validation/cp13-"))}


def prepare(output):
    require(output.is_absolute() and not output.exists() and not output.is_relative_to(ROOT),"Use a new external candidate directory")
    require(not git(ROOT,"status","--porcelain").strip(),"Freeze committed inputs")
    run=read(STATE);require(run["next_backward_frontier"]==FRONTIER.as_posix(),"Publish the recovery frontier before freezing")
    original=read(TEMP/"snapshots/checkpoints/CP-0012.json")
    require(original["status"]=="valid" and run["start_checkpoint_id"]==original["checkpoint_id"] and run["scope_id"]==SCOPE,"Invalid parent")
    commit=head();history=audit(commit)
    require(history["parent_checkpoint_sha256"]==run["start_sync_gate"]["checkpoint_sha256"],"Parent binding differs")
    when=stamp();counts,coverage,cursors,opened=collect(when,RUN)
    inputs=input_snapshot(ROOT,frozen_files());require(head()==commit,"Git inputs changed during checkpoint preparation")
    output.mkdir(parents=True)
    put(output/HISTORY,encode(history)+b"\n");put(output/INPUTS,encode(inputs)+b"\n")
    ws=read(ROOT/FRONTIER);timing=read(ROOT/TIMING)
    coverage["recursive_cursor"]=dict(canonical_parents=ws["canonical_parents"],remaining_original_parents=ws["remaining_original_parents"],
        next_original_parent=ws["next_original_parent"],source_gap_parents=ws["source_gap_parent_count"],new_child_tasks=ws["discovered_work_count"])
    reasons=["完整数据与导出验收尚在进行。","递归扩展、来源覆盖、版本身份和科学证据仍有待核实的项目。"]
    if timing["overlapping_receipt_windows"] or timing["unavailable_exact"]:
        reasons.append("早期请求回执存在时间重叠或缺少精确请求时刻，保留已发生的来源控制偏差。")
    cp=dict(checkpoint_id=CP,parent_checkpoint_id=original["checkpoint_id"],scope_id=SCOPE,schema_version=original["schema_version"],created_at_utc=when,
            task_cursor_state=cursors,query_log_high_watermark=counts["queries"],counts=counts,coverage=coverage,unresolved_tasks=opened,
            failure_reasons=reasons,artifact_hashes={},status="invalid",validation_results=dict(state="pending",input_manifest=INPUTS.as_posix(),
            input_digest_sha256=input_digest(inputs),input_commit=commit,history_file=HISTORY.as_posix(),history_sha256=digest(output/HISTORY),
            source_timing_report=TIMING.as_posix(),source_timing_sha256=digest(ROOT/TIMING),research_closure_established=False))
    validate_checkpoint(ROOT,cp)
    write_checkpoint(output/CANDIDATE,cp)
    del cp,cursors,opened
    gc.collect()
    recovered=load_checkpoint(output/CANDIDATE)
    validate_checkpoint(ROOT,recovered)
    files=[*checkpoint_files(output/CANDIDATE),output/HISTORY,output/INPUTS]
    inventory={p.relative_to(output).as_posix():{"bytes":p.stat().st_size,"sha256":digest(p)} for p in files}
    put(output/"candidate-files.json",encode(inventory)+b"\n")
    print("Checkpoint files, cursors, unresolved tasks:",len(inventory),len(recovered["task_cursor_state"]),len(recovered["unresolved_tasks"]),flush=True)


def exports(output):
    require(not output.exists() and not output.is_relative_to(ROOT),"Use a fresh independent export directory")
    output.mkdir(parents=True)
    candidate=read(ROOT/CANDIDATE)
    require(candidate["status"]=="invalid" and candidate["parent_checkpoint_id"]=="CP-0012","Expected CP13 validation candidate")
    ch=digest(ROOT/CANDIDATE);first=output/"first";second=output/"independent"
    a=generate(first,CP);b=generate(second,CP)
    require(a==b and all(0<v["bytes"]<100*1024**2 for v in a.values()),"Export files differ or exceed GitHub's Git object limit")
    for k in ("research_entities.json","citation_graph.json"):
        f=Path("temp/exports")/k
        require(reconstruct(first/f)==reconstruct(second/f),"Logical exports differ")
    meta=read(first/"export-validation.json");s=candidate["counts"];c=meta["counts"]
    require(c["bibtex_entries"]==c["graph_nodes"]==s["canonical_works"] and c["graph_edges"]==s["citation_edges"] and
            c["unresolved_pointers"]==s["unresolved_occurrences"] and c["active_assessments"]==s["assessments"] and digest(ROOT/CANDIDATE)==ch,"Counts or checkpoint changed")
    stat=dict(status="passed",checkpoint_id=CP,candidate_sha256=ch,checked_at_utc=stamp(),counts=c,artifact_count=len(a),artifacts=a)
    put(output/"determinism.json",encode(stat)+b"\n")
    print("Deterministic exports",len(a),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("frontier","prepare","exports"));p.add_argument("--output",type=Path)
    args=p.parse_args()
    if args.action=="frontier":frontier()
    elif args.output is None:p.error("--output is required for this action")
    elif args.action=="prepare":prepare(args.output.resolve())
    else:exports(args.output.resolve())
