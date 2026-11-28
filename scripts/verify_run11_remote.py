"""Verify every bound CP13 artifact and reconstruct its large logical JSON from an independent Git checkout."""
import argparse
import gc
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from checkpoint_cp10 import require
from escalate_unknown_run7 import git
from history_run10 import blobs
from partitioned_checkpoint import checkpoint_files, load_checkpoint
from partitioned_research_json import bound_path, encode, metadata, put, reconstruct, sha, view_files
from search_run11_bibliography import stamp

CHECKPOINT = "temp/snapshots/checkpoints/CP-0013.json"
PARENT = "temp/snapshots/checkpoints/CP-0012.json"
RUN_FILE = "temp/runs/RUN-0011.json"
VIEWS = ("temp/exports/research_entities.json", "temp/exports/citation_graph.json")


def readback(repo, ref, scratch, output):
    require(git(repo, "rev-parse", "--is-bare-repository").strip() == b"true" and
            not (repo / "objects/info/alternates").exists(), "Use an independent bare object store")
    commit = git(repo, "rev-parse", "--verify", ref+"^{commit}").decode().strip()
    tree = git(repo, "rev-parse", commit+"^{tree}").decode().strip()
    paths = set(git(repo, "ls-tree", "--name-only", "-r", "-z", commit).decode().split("\0")) - {""}
    with blobs(repo) as get, TemporaryDirectory(prefix="cp13-independent-", dir=scratch) as tmp:
        temp = Path(tmp)
        def copy(name):
            require(name in paths, "Missing remote artifact " + name)
            target = bound_path(temp, name)
            put(target, get(commit, name))
            return target
        public = json.loads(get(commit, CHECKPOINT))
        run = json.loads(get(commit, RUN_FILE))
        require(public["parent_checkpoint_id"] == "CP-0012" and public["scope_id"] == run["scope_id"], "Remote checkpoint ancestry differs")
        baseline = run["checkpoint_commit"]
        git(repo, "merge-base", "--is-ancestor", baseline, commit)
        previous = {p for p in git(repo, "ls-tree", "--name-only", "-r", baseline, "--", "temp/snapshots/checkpoints").decode().splitlines() if p.endswith(".json")}
        require(PARENT in previous and all(get(commit, p) == get(baseline, p) for p in previous), "Historical checkpoint changed")
        older = ["temp/reports", "temp/query-results", "temp/runs", "temp/validation", "temp/snapshots/scope.json"]
        require(not git(repo, "diff", "--name-only", "--no-renames", "--diff-filter=DM", baseline, commit, "--", *older),
                "Historical research receipt changed")
        parent_sha = sha(get(commit, PARENT))
        require(parent_sha == run["start_sync_gate"]["checkpoint_sha256"], "CP12 differs from its original binding")
        artifacts = public["artifact_hashes"]
        if public["status"] == "valid":
            require(set(artifacts) == paths - {CHECKPOINT, "temp/validation/cp13-post-push.json"}, "Checkpoint inventory differs from the remote tree")
        total = 0
        for name, expected in artifacts.items():
            data = get(commit, name)
            require(sha(data) == expected, "Remote data digest differs: " + name)
            total += len(data)
        def copy_view(name):
            path = copy(name)
            pointer = json.loads(path.read_bytes())
            unique = bound_path(path.parent, pointer["index"])
            copy(unique.relative_to(temp).as_posix())
            index, folder = metadata(path)
            require(folder is not None, "Expected a partitioned export: " + name)
            copy((folder / "index.json").relative_to(temp).as_posix())
            for collection in index["collections"].values():
                for part in collection["parts"]:
                    copy(bound_path(folder, part["path"]).relative_to(temp).as_posix())
            return index, path
        logical = {}
        for view in VIEWS:
            index, entry = copy_view(view)
            logical[view] = dict(logical_sha256=reconstruct(entry), physical_files=len(view_files(entry)),
                                 collection_counts={k:c["records"] for k,c in index["collections"].items()})
        cp_path = copy(CHECKPOINT)
        immutable = bound_path(cp_path.parent, public["task_collections"])
        copy(immutable.relative_to(temp).as_posix())
        copy_view(immutable.with_name("queues.json").relative_to(temp).as_posix())
        recovered = load_checkpoint(cp_path)
        queue_stats = dict(task_cursors=len(recovered["task_cursor_state"]), unresolved_tasks=len(recovered["unresolved_tasks"]),
                           logical_sha256=public["logical_sha256"], physical_files=len(checkpoint_files(cp_path, public)))
        require(queue_stats["task_cursors"] == public["counts"]["unique_tasks"] and queue_stats["unresolved_tasks"] == public["counts"]["unresolved_tasks"], "Remote queue counts differ")
        del recovered
        gc.collect()
        frontier = json.loads(get(commit, run["next_backward_frontier"]))
        require(frontier["canonical_positions"] == public["coverage"]["parent_reference_search"]["positions"]["positions"] and
                frontier["discovered_work_count"] == len(frontier["worklist"]) == public["coverage"]["backward_queue"]["work_count"], "Remote recursive cursor differs")
        result = dict(status="passed", verified_at_utc=stamp(), verified_remote="https://github.com/ncut-d1z/Insect-Inspired.git",
                      branch="main", method="Native Git fetch into an independent bare object store, followed by full blob SHA-256 and logical JSON reconstruction.",
                      commit=commit, tree=tree, checkpoint_status=public["status"], checkpoint_sha256=sha(get(commit, CHECKPOINT)),
                      previous_checkpoint_files_unchanged=len(previous), parent_checkpoint_sha256=parent_sha, old_reports_queries_runs_and_validation_files_changed=0,
                      checked_artifact_hashes=len(artifacts), checked_artifact_bytes=total, reconstructed_json=logical, recovered_queue=queue_stats,
                      original_parents=frontier["canonical_parents"], new_recursive_tasks=frontier["discovered_work_count"])
        put(output, encode(result) + b"\n")
        print("Remote commit, tree, verified artifacts, bytes and recovered queue:", commit, tree, len(artifacts), total, queue_stats, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    readback(args.repo.resolve(), args.ref, args.scratch.resolve(), args.output.resolve())
