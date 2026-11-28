"""Build, validate and stage a RUN12 checkpoint using its frozen registry and complete recursive queue."""
import argparse
import gc
from pathlib import Path

from audit_cp10 import input_digest, input_snapshot
from audit_run11_checkpoint import run as data_audit
from checkpoint_cp10 import require, validate_checkpoint
from coverage_run10 import collect
from escalate_unknown_run7 import git
from export_checkpoint_windows import WEB_FILES, generate
from history_run11 import audit as historical_audit
from partitioned_checkpoint import checkpoint_files, load_checkpoint, write_checkpoint
from partitioned_research_json import encode, put, reconstruct
from run12_progress import FRONTIER, SOURCES, TIMING
from run12_reference_search import CP, RUN, STATE
from search_run11_bibliography import ROOT, SCOPE, TEMP, digest, read, stamp
from stage_run11_delivery import groups, install

CANDIDATE=Path("temp/snapshots/checkpoints/CP-0014.json")
INPUTS=Path("temp/validation/cp14-inputs.json")
HISTORY=Path("temp/validation/cp14-history.json")
POST="temp/validation/cp14-post-push.json"


def head():
    return git(ROOT,"rev-parse","HEAD").decode().strip()


def frozen_files():
    tracked=set(git(ROOT,"ls-files","-z").decode().split("\0"))-{""}
    skip={"README.md","temp/progress.md","temp/change-log.md","ref.bib",*WEB_FILES,INPUTS.as_posix(),HISTORY.as_posix(),CANDIDATE.as_posix(),"temp/reports/P3-P6-CP0014.md"}
    return {k for k in tracked-skip if not k.startswith(("temp/exports/","temp/snapshots/checkpoints/CP-0014/","temp/validation/cp14-"))}


def prepare(out):
    require(out.is_absolute() and not out.exists() and not out.is_relative_to(ROOT),"Use a new independent candidate directory")
    require(not git(ROOT,"status","--porcelain").strip(),"Freeze committed inputs")
    run=read(STATE)
    previous=read(TEMP/"snapshots/checkpoints/CP-0012.json")
    recovery=read(TEMP/"snapshots/checkpoints/CP-0013.json")
    require(previous["status"]=="valid" and recovery["status"]=="invalid" and run["start_checkpoint_id"]==previous["checkpoint_id"],"Checkpoint ancestry differs")
    commit=head()
    history=historical_audit(commit,STATE)
    require(history["historical_rows_lost"]==0 and history["parent_checkpoint_sha256"]==run["start_sync_gate"]["checkpoint_sha256"],"Prior state differs")
    when=stamp()
    counts,coverage,cursors,opened=collect(when,RUN)
    frontier=read(FRONTIER);study=read(SOURCES)
    coverage["recursive_cursor"]={k:study[k] for k in ("canonical_parents","remaining_original_parents","next_original_key","without_entries","new_backward_works","new_forward_works")}
    coverage["recursive_cursor"]["continuing_tasks"]=len(frontier["worklist"])
    coverage["original_version_recheck"]=study["scientific_reviews"]["oldest"]
    coverage["previous_invalid_checkpoint"]={"id":recovery["checkpoint_id"],"status":recovery["status"],"remote_receipt":run["start_sync_receipt"]}
    coverage["delta_from_valid_cp12"]={k:v-previous["counts"][k] for k,v in counts.items() if k in previous["counts"]}
    inputs=input_snapshot(ROOT,frozen_files())
    require(head()==commit,"Input revision changed during preparation")
    out.mkdir(parents=True)
    put(out/HISTORY,encode(history)+b"\n");put(out/INPUTS,encode(inputs)+b"\n")
    cp=dict(checkpoint_id=CP,parent_checkpoint_id=previous["checkpoint_id"],scope_id=SCOPE,schema_version=previous["schema_version"],created_at_utc=when,
        task_cursor_state=cursors,query_log_high_watermark=counts["queries"],counts=counts,coverage=coverage,unresolved_tasks=opened,
        failure_reasons=["完整数据、导出及独立回读验收正在进行。","递归、版本、机构归属和主题证据仍有明确缺口。"],
        artifact_hashes={},status="invalid",validation_results=dict(state="pending",input_manifest=INPUTS.as_posix(),input_commit=commit,
        input_digest_sha256=input_digest(inputs),history_file=HISTORY.as_posix(),history_sha256=digest(out/HISTORY),
        source_timing_report=TIMING.relative_to(ROOT).as_posix(),source_timing_sha256=digest(TIMING),research_closure_established=False))
    validate_checkpoint(ROOT,cp);write_checkpoint(out/CANDIDATE,cp)
    del cp,cursors,opened
    gc.collect()
    restored=load_checkpoint(out/CANDIDATE)
    validate_checkpoint(ROOT,restored)
    files=[*checkpoint_files(out/CANDIDATE),out/HISTORY,out/INPUTS]
    put(out/"candidate-files.json",encode({p.relative_to(out).as_posix():dict(bytes=p.stat().st_size,sha256=digest(p)) for p in files})+b"\n")
    print("Candidate",len(files),"files",len(restored["task_cursor_state"]),"task cursors",flush=True)


def exports(out):
    require(not out.exists() and not out.is_relative_to(ROOT),"Use a new independent export directory")
    out.mkdir(parents=True)
    candidate=read(ROOT/CANDIDATE);subject=digest(ROOT/CANDIDATE)
    require(candidate["status"]=="invalid" and candidate["checkpoint_id"]==CP and candidate["validation_results"]["state"]=="pending","Different candidate")
    first=out/"first";second=out/"independent"
    a=generate(first,CP)
    require(all(0<v["bytes"]<100*1024**2 for v in a.values()),"Oversize ordinary Git file")
    put(out/"first-files.json",encode(dict(status="first_generation",checkpoint_id=CP,candidate_sha256=subject,artifacts=a))+b"\n")
    b=generate(second,CP)
    require(a==b,"Independent deterministic exports differ")
    for name in ("research_entities.json","citation_graph.json"):
        path=Path("temp/exports")/name
        require(reconstruct(first/path)==reconstruct(second/path),"Logical JSON differs")
    counts=read(first/"export-validation.json")["counts"];registered=candidate["counts"]
    require(counts["bibtex_entries"]==counts["graph_nodes"]==registered["canonical_works"] and counts["graph_edges"]==registered["citation_edges"]
       and counts["unresolved_pointers"]==registered["unresolved_occurrences"] and counts["active_assessments"]==registered["assessments"]
       and digest(ROOT/CANDIDATE)==subject,"Export registry mismatch")
    proof=dict(status="passed",checkpoint_id=CP,candidate_sha256=subject,checked_at_utc=stamp(),counts=counts,artifact_count=len(a),artifacts=a)
    put(out/"determinism.json",encode(proof)+b"\n")
    print("Independent deterministic export files",len(a),flush=True)


def delivery(action,src,kind,n):
    inventory,blocks=groups(src,kind,CP)
    if action=="plan":
        active=[]
        for number,block in enumerate(blocks):
            if any(not (ROOT/k).is_file() or digest(ROOT/k)!=inventory[k]["sha256"] for k in block):
                active.append(dict(number=number,paths=block))
        print(encode(active).decode())
    else:
        require(n is not None and 0<=n<len(blocks),"Invalid delivery block")
        print("Staged files",install(ROOT,src,inventory,blocks[n]),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("prepare","exports","plan","stage","audit"))
    p.add_argument("--directory",required=True,type=Path)
    p.add_argument("--kind",choices=("candidate","exports","export-parts"))
    p.add_argument("--group",type=int)
    p.add_argument("--ledger",type=Path)
    a=p.parse_args();d=a.directory.resolve()
    if a.action=="prepare":prepare(d)
    elif a.action=="exports":exports(d)
    elif a.action=="audit":data_audit(d/"data-audit.json",a.ledger.resolve(),d/"staged-exports.sha256",candidate=ROOT/CANDIDATE,state_file=STATE)
    else:delivery(a.action,d,a.kind,a.group)
