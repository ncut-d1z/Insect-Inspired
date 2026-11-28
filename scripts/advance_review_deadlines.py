"""Apply the README's 24-hour rule to the current run, preserving the exact task clocks."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

from checkpoint_cp10 import latest_tasks, TERMINAL
from escalate_unknown_run7 import (
    encoded, git, info, logical_lines, logical_names, next_event, objects_with_paths,
    publish, replace_status_tokens, require, row_id, sha, stage_dataset, utc, write_parts,
)
from storage import read_logical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    run_path = repo / "temp/runs" / (args.run + ".json")
    run = json.loads(run_path.read_bytes())
    require(run["run_id"] == args.run and run["scope_id"] == "SCOPE-0001", "Incorrect run")
    require(args.checkpoint == f"CP-{int(run['start_checkpoint_id'][3:])+1:04d}", "Incorrect target checkpoint")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "merge-base", "--is-ancestor", run["start_commit_sha"], head)
    manifest_path = repo / "temp/partitions/manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    guards = {"temp/partitions/manifest.json": info(manifest_path.read_bytes()),
              run_path.relative_to(repo).as_posix(): info(run_path.read_bytes())}
    latest = latest_tasks(read_logical("tasks.jsonl", repo / "temp"))
    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    open_fields = {tid: t for tid, t in latest.items() if t.get("unknown_since_utc") and t["task_state"] not in TERMINAL}
    due, events, future = set(), {}, []
    for tid, task in open_fields.items():
        since, deadline = utc(task["unknown_since_utc"]), utc(task["deadline_at_utc"])
        require(since <= deadline <= since + timedelta(hours=24), f"Invalid deadline {tid}")
        if now < deadline:
            future.append(deadline)
            continue
        due.add(tid)
        if task.get("overdue") is not True or task["priority"] not in {"high", "critical"}:
            event = next_event(task, stamp)
            event["checkpoint_id"] = args.checkpoint
            events[tid] = event
    changes, event_locations = {}, {}
    for name in logical_names(repo, manifest):
        rows = {}
        for ordinal, raw in enumerate(logical_lines(repo, name, manifest, guards)):
            if name == "tasks":
                task = json.loads(raw)
                if task["task_id"] in events:
                    event_locations[task["task_id"]] = (ordinal, sha(raw))
                continue
            if b'"unknown"' not in raw or b'"review_task_id"' not in raw:
                continue
            row = json.loads(raw)
            leaves = []
            for pointer, state in objects_with_paths(row):
                if state.get("status") != "unknown" or not state.get("review_task_id"):
                    continue
                tid = state["review_task_id"]
                if tid not in due:
                    continue
                task = open_fields[tid]
                require(task["unknown_since_utc"] == state["unknown_since_utc"], f"Clock mismatch {tid}")
                leaves.append(dict(pointer=pointer + "/status", review_task_id=tid,
                                   unknown_since_utc=task["unknown_since_utc"], deadline_at_utc=task["deadline_at_utc"]))
            if leaves:
                revised = replace_status_tokens(raw, [i["pointer"] for i in leaves])
                rows[ordinal] = dict(dataset=name, id=row_id(name, row, ordinal), line_index=ordinal,
                                     before_line_sha256=sha(raw), after_line_sha256=sha(revised), changes=leaves)
        if rows:
            changes[name] = rows
    require(set(event_locations) == set(events), "Original event missing")
    n_fields = sum(len(record["changes"]) for rows in changes.values() for record in rows.values())
    summary = dict(run_id=args.run, scope_id=run["scope_id"], target_checkpoint=args.checkpoint,
                   parent_checkpoint=run["start_checkpoint_id"], before_commit=head, evaluated_at_utc=stamp,
                   open_unknowns=len(open_fields), due=len(due), task_events=len(events), field_transitions=n_fields,
                   next_deadline_at_utc=min(future).isoformat().replace("+00:00","Z") if future else None,
                   changed_records_by_dataset={k:len(v) for k,v in changes.items()}, maintenance_only=True,
                   external_requests=0, manual_reviews=0, new_assessments=0, new_works=0)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not args.apply or not (events or changes):
        return
    require(not git(repo, "status", "--porcelain").strip(), "Concurrent worktree changes")
    new_manifest = deepcopy(manifest)
    prefix = f"temp/reports/{args.run}-deadlines-{now:%Y%m%dT%H%M%S%fZ}"
    # Stage on the same volume as the data for rollback-safe file replacement.
    with tempfile.TemporaryDirectory(prefix="insect-deadlines-", dir=repo / ".git") as directory:
        stage = Path(directory)
        for name in sorted(set(changes) | ({"tasks"} if events else set())):
            def revised_lines():
                for ordinal, raw in enumerate(logical_lines(repo, name, manifest)):
                    delta = changes.get(name, {}).get(ordinal)
                    if delta:
                        require(sha(raw) == delta["before_line_sha256"], "Input changed")
                        raw = replace_status_tokens(raw, [i["pointer"] for i in delta["changes"]])
                        require(sha(raw) == delta["after_line_sha256"], "Replacement differs")
                    yield raw
                if name == "tasks":
                    for tid in sorted(events):
                        yield encoded(events[tid])
            stage_dataset(stage, name, revised_lines(), manifest, new_manifest)
        target = stage / "files/temp/partitions/manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((json.dumps(new_manifest, ensure_ascii=False, indent=2) + "\n").encode())
        summary["field_change_parts"] = write_parts(stage, prefix, "fields", (
            rec for rows in changes.values() for rec in rows.values()))
        summary["task_event_parts"] = write_parts(stage, prefix, "events", (
            dict(task_id=tid, before_line=event_locations[tid][0], before_sha256=event_locations[tid][1],
                 after_sha256=sha(encoded(events[tid])), event_sequence=events[tid]["event_sequence"],
                 unknown_since_utc=events[tid]["unknown_since_utc"], deadline_at_utc=events[tid]["deadline_at_utc"])
            for tid in sorted(events)))
        (stage / "files" / (prefix + ".json")).write_bytes(encoded(summary))
        old = {p["path"] for ds in manifest["datasets"].values() for p in ds["parts"]}
        new = {p["path"] for ds in new_manifest["datasets"].values() for p in ds["parts"]}
        publish(repo, stage, {"temp/" + p for p in old-new if p.startswith("partitions/")}, head, guards)
        print(prefix + ".json", flush=True)


if __name__ == "__main__":
    main()
