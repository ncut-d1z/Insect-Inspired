"""Replay every published RUN10 canonical transaction against its immediate Git parent."""
from collections import Counter
from contextlib import contextmanager
import itertools
import json
from pathlib import Path
import subprocess

from escalate_unknown_run7 import IDS, git, info, parts_for, replace_status_tokens, require, sha
from history_run9 import ledger
from search_run10_references import ROOT, TEMP, read


@contextmanager
def blobs():
    proc=subprocess.Popen(["git","--no-replace-objects","-C",str(ROOT),"cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    def get(rev,path):
        require(not Path(path).is_absolute() and ".." not in Path(path).parts and "\n" not in path,"Invalid Git path")
        proc.stdin.write(f"{rev}:{path}\n".encode());proc.stdin.flush()
        header=proc.stdout.readline().split()
        require(len(header)==3 and header[1]==b"blob","Missing historical blob "+path)
        size=int(header[2]);data=proc.stdout.read(size)
        require(len(data)==size and proc.stdout.read(1)==b"\n","Incomplete Git object")
        return data
    try: yield get
    finally:
        proc.stdin.close();proc.stdout.close();require(proc.wait()==0,"Git object reader failed")


def verify(base):
    git(ROOT,"merge-base","--is-ancestor",base,"HEAD")
    published={}
    for pattern in ("RUN-0010-integration-*.json","RUN-0010-deadlines-*.json"):
        for path in sorted((TEMP/"reports").glob(pattern)):
            rel=path.relative_to(ROOT).as_posix()
            additions=git(ROOT,"log","--diff-filter=A","--format=%H",base+"..HEAD","--",rel).decode().splitlines()
            require(len(additions)==1,"Missing or repeated transaction "+rel)
            require(additions[0] not in published,"Multiple canonical transactions in one commit")
            published[additions[0]]=(rel,read(path))
    changed=git(ROOT,"log","--reverse","--format=%H",base+"..HEAD","--",":(top,glob)temp/*.jsonl","temp/partitions").decode().splitlines()
    require(set(changed)==set(published),"Unrecorded change to canonical datasets")
    frozen=["temp/snapshots/checkpoints","temp/snapshots/scope.json","temp/snapshots/scopes","temp/seed-manifest.jsonl","temp/schema.json","temp/query-results","temp/history"]
    require(not git(ROOT,"diff","--name-only","--no-renames","--diff-filter=DM",base,"HEAD","--",*frozen),"Historical inventory changed")
    totals=Counter();replays=[]
    with blobs() as get:
        for commit in changed:
            rel,report=published[commit];before=report["before_commit"]
            require(git(ROOT,"rev-parse",commit+"^").decode().strip()==before,"Unexpected transaction parent")
            require(get(commit,rel)==(ROOT/rel).read_bytes(),"Published receipt differs")
            old=json.loads(get(before,"temp/partitions/manifest.json"));new=json.loads(get(commit,"temp/partitions/manifest.json"))
            deadline=Path(rel).name.startswith("RUN-0010-deadlines-");datasets=report.get("datasets",{})
            require(bool(datasets)!=deadline and (not deadline or report.get("maintenance_only") is True),"Transaction receipt format differs")
            fields={};events={}
            if deadline:
                for r in ledger(report["field_change_parts"]):fields[r["dataset"],r["line_index"]]=r
                events={r["task_id"]:r for r in ledger(report["task_event_parts"])}
                names=set(report["changed_records_by_dataset"]) | ({"tasks"} if events else set())
            else: names=set(datasets)
            for n in set(old["datasets"])|set(new["datasets"]):
                if old["datasets"].get(n)!=new["datasets"].get(n):require(n[:-6] in names,"Undeclared changed dataset "+n)
            def lines(rev,m,n):
                for p in parts_for(n,m):
                    raw=get(rev,"temp/"+p["path"])
                    if "sha256" in p:require(info(raw)=={k:p[k] for k in ("bytes","sha256")},"Changed Git partition")
                    yield from raw.splitlines(keepends=True)
            tally=Counter()
            for name in sorted(names):
                delta=datasets.get(name,{})
                replacements={r["id"]:r for r in delta.get("replacements",[])}
                extra=iter(sorted(events) if deadline and name=="tasks" else delta.get("appended_ids",[]))
                for i,(a,b) in enumerate(itertools.zip_longest(lines(before,old,name),lines(commit,new,name))):
                    require(b is not None,"Lost prior record")
                    if a is None:
                        row=json.loads(b);key=row[IDS[name]]
                        require(next(extra,None)==key,"Undeclared appended row "+key)
                        if deadline:
                            e=events.pop(key)
                            require(sha(b)==e["after_sha256"] and row["unknown_since_utc"]==e["unknown_since_utc"] and
                                    row["deadline_at_utc"]==e["deadline_at_utc"] and row["overdue"],"Deadline clock changed")
                        tally["appended_rows"]+=1
                    elif a!=b:
                        if deadline:
                            entry=fields.pop((name,i))
                            require(sha(a)==entry["before_line_sha256"] and sha(b)==entry["after_line_sha256"] and
                                    b==replace_status_tokens(a,[v["pointer"] for v in entry["changes"]]),"Undeclared field mutation")
                        else:
                            key=json.loads(a)[IDS[name]];entry=replacements.pop(key)
                            require(json.loads(b)[IDS[name]]==key and sha(a)==entry["before_sha256"] and sha(b)==entry["after_sha256"],"Undeclared research mutation")
                        tally["changed_rows"]+=1
                    else: tally["byte_identical_row_comparisons"]+=1
                require(next(extra,None) is None and not replacements,"Unapplied records "+name)
            require(not fields and not events,"Incomplete deadline replay")
            replays.append(dict(receipt=rel,commit=commit,before=before,maintenance=bool(report.get("maintenance_only")),
                                transaction_format="deadline_fields_and_events" if deadline else "dataset_row_hashes",counts=dict(tally)))
            totals.update(tally)
        cp="temp/snapshots/checkpoints/CP-0011.json"
        require(get(base,cp)==(ROOT/cp).read_bytes() and read(ROOT/cp)["status"]=="valid","Invalid parent checkpoint")
    return dict(status="passed",parent_commit=base,parent_checkpoint_sha256=sha((ROOT/cp).read_bytes()),canonical_transactions=replays,
                totals=dict(totals),old_records_lost=0,clock_history_preserved=True)
