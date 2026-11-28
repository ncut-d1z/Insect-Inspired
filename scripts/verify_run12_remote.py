"""Independently read every sealed CP14 artifact, task cursor and partitioned research view from a native Git object store."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from checkpoint_cp10 import require
from checkpoint_run12 import CANDIDATE, POST
from escalate_unknown_run7 import git, sha
from history_run10 import blobs
from partitioned_checkpoint import checkpoint_files, load_checkpoint
from partitioned_research_json import bound_path, encode, metadata, put, reconstruction_info, view_files
from run12_reference_search import CP, RUN
from search_run11_bibliography import stamp


def verify(repo,ref,scratch,out,determinism):
    require(git(repo,"rev-parse","--is-bare-repository").strip()==b"true" and not (repo/"objects/info/alternates").exists(),"Independent object store required")
    requested=git(repo,"rev-parse","--verify",ref+"^{commit}").decode().strip()
    snapshot=CANDIDATE.as_posix()
    with blobs(repo) as get:
        commit=requested
        if git(repo,"ls-tree","--name-only",commit,"--",POST).strip():
            post=json.loads(get(commit,POST))
            commit=post["commit"]
            git(repo,"merge-base","--is-ancestor",commit,requested)
            changed=set(git(repo,"diff","--name-only","--no-renames",commit,requested).decode().splitlines())
            require(post["status"]=="passed" and post["checkpoint_sha256"]==sha(get(commit,snapshot)) and changed=={POST},"Post-push receipt mismatch")
        tree=git(repo,"rev-parse",commit+"^{tree}").decode().strip()
        if requested!=commit:require(tree==post["tree"],"Sealed tree differs")
        paths=set(git(repo,"ls-tree","--name-only","-r","-z",commit).decode().split("\0"))-{""}
        run=json.loads(get(commit,"temp/runs/"+RUN+".json"))
        checkpoint=json.loads(get(commit,snapshot))
        baseline=run["start_commit_sha"]
        git(repo,"merge-base","--is-ancestor",baseline,commit)
        required=sorted(p for p in git(repo,"ls-tree","--name-only","-r",baseline,"--","temp/snapshots/checkpoints").decode().splitlines() if p.endswith(".json"))
        require(all(get(baseline,p)==get(commit,p) for p in required),"Historical checkpoint file changed")
        parent="temp/snapshots/checkpoints/"+run["start_checkpoint_id"]+".json"
        require(parent in required and checkpoint["parent_checkpoint_id"]==run["start_checkpoint_id"] and run["scope_id"]==checkpoint["scope_id"] and
                sha(get(commit,parent))==run["start_sync_gate"]["checkpoint_sha256"] and json.loads(get(commit,parent))["status"]=="valid","Invalid parent checkpoint")
        earlier=("temp/reports","temp/runs","temp/query-results","temp/validation","temp/snapshots/scope.json","temp/seed-manifest.jsonl")
        require(not git(repo,"diff","--name-only","--no-renames","--diff-filter=DM",baseline,commit,"--",*earlier),"Prior evidence changed")
        binding=checkpoint["artifact_hashes"];total=0
        if binding or checkpoint["status"]=="valid":
            require(set(binding)==paths-{snapshot,POST},"Sealed file set differs")
            for filename,h in binding.items():
                data=get(commit,filename)
                require(sha(data)==h,"Remote artifact hash differs: "+filename)
                total+=len(data)
        proof=json.loads(determinism.read_bytes())
        require(proof["status"]=="passed" and proof["checkpoint_id"]==CP,"Unexpected export QA")
        if binding:
            state=checkpoint["validation_results"]
            checked=state["audited_candidate_commit"]
            git(repo,"merge-base","--is-ancestor",checked,commit)
            previous=get(checked,snapshot);candidate=json.loads(previous)
            require(state["audited_candidate_sha256"]==sha(previous)==proof["candidate_sha256"] and candidate["validation_results"]["state"]=="pending"
              and candidate["task_collections_sha256"]==checkpoint["task_collections_sha256"] and candidate["counts"]==checkpoint["counts"]
              and sha(determinism.read_bytes())==binding["temp/validation/cp14-determinism.json"],"Validated candidate differs from sealed data")
        else:require(sha(get(commit,snapshot))==proof["candidate_sha256"] and checkpoint["validation_results"]["state"]=="pending","Unexpected candidate")
        for filename,info in proof["artifacts"].items():
            data=get(commit,filename)
            require(info==dict(bytes=len(data),sha256=sha(data)),"Remote export differs: "+filename)
        with TemporaryDirectory(prefix="cp14-readback-",dir=scratch) as folder:
            root=Path(folder)
            def copy(name):
                require(name in paths,"Missing remote object: "+name)
                local=bound_path(root,name);put(local,get(commit,name));return local
            def view(name):
                entry=copy(name);idx=bound_path(entry.parent,json.loads(entry.read_bytes())["index"])
                copy(idx.relative_to(root).as_posix())
                manifest,partdir=metadata(entry)
                copy((partdir/"index.json").relative_to(root).as_posix())
                for component in manifest["collections"].values():
                    for part in component["parts"]:copy(bound_path(partdir,part["path"]).relative_to(root).as_posix())
                return entry,manifest
            logical={}
            for name in ("temp/exports/research_entities.json","temp/exports/citation_graph.json"):
                entry,idx=view(name)
                logical[name]={**reconstruction_info(entry),"physical_files":len(view_files(entry)),
                    "collection_counts":{k:c["records"] for k,c in idx["collections"].items()}}
            entry=copy(snapshot);immutable=bound_path(entry.parent,checkpoint["task_collections"])
            copy(immutable.relative_to(root).as_posix())
            view(immutable.with_name("queues.json").relative_to(root).as_posix())
            restored=load_checkpoint(entry)
            queue=dict(task_cursors=len(restored["task_cursor_state"]),unresolved_tasks=len(restored["unresolved_tasks"]),physical_files=len(checkpoint_files(entry)))
            require(queue["task_cursors"]==checkpoint["counts"]["unique_tasks"] and queue["unresolved_tasks"]==checkpoint["counts"]["unresolved_tasks"],"Cursor set differs")
        frontier=json.loads(get(commit,run["next_backward_frontier"]))
        require(frontier["continuing_task_count"]==len(frontier["worklist"])==checkpoint["coverage"]["backward_queue"]["work_count"]
                and frontier["canonical_parents"]==checkpoint["coverage"]["recursive_cursor"]["canonical_parents"],"Recursive queue differs")
        result=dict(status="passed",verified_at_utc=stamp(),verified_remote="https://github.com/ncut-d1z/Insect-Inspired.git",branch="main",
            method="Independent native Git fetch, SHA-256 for each sealed artifact, all task cursors and two logical JSON reconstructions.",
            commit=commit,tree=tree,checked_requested_commit=requested,checkpoint_sha256=sha(get(commit,snapshot)),checkpoint_status=checkpoint["status"],
            checked_artifact_hashes=len(binding),checked_artifact_bytes=total,physical_exports_compared_with_double_generation=len(proof["artifacts"]),
            historical_checkpoint_headers=sum(Path(k).parent.as_posix()=="temp/snapshots/checkpoints" for k in required),
            previous_checkpoint_files_unchanged=len(required),parent_checkpoint_sha256=sha(get(commit,parent)),old_reports_queries_runs_and_validation_files_changed=0,
            recovered_queue=queue,reconstructed_json=logical,canonical_parents=frontier["canonical_parents"],continuing_recursive_tasks=len(frontier["worklist"]))
        put(out,encode(result)+b"\n")
        print(checkpoint["status"],commit,len(binding),queue,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",type=Path,required=True);p.add_argument("--ref",required=True);p.add_argument("--scratch",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--determinism",type=Path,required=True)
    a=p.parse_args();verify(a.repo.resolve(),a.ref,a.scratch.resolve(),a.output.resolve(),a.determinism.resolve())
