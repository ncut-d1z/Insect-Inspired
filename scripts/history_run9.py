"""Bind CP11 records to the published CP10 Git tree and recorded incremental transactions."""
from collections import Counter, defaultdict
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess

from audit_cp10 import original
from escalate_unknown_run7 import IDS, git, info, logical_lines, logical_names, parts_for, replace_status_tokens, require, sha

ROOT=Path(__file__).resolve().parents[1]
BASE="5f2181b0e5a91bcafde2a3f19eb526668934a80e"
TREE="53463d7daa180a82199ab56281afe411f8e61e7b"
CP,RUN="CP-0011","RUN-0009"
INTEGRATION="temp/reports/RUN-0009-S06-integration.json"
MAINTENANCE="temp/reports/RUN-0009-deadlines-20261128T032738482072Z.json"
BIB="temp/reports/RUN-0009-bibliographic-integration.json"
CUT="temp/reports/RUN-0009-bibliography-cutover.json"


def read(name):
    return json.loads((ROOT/name).read_bytes())


@contextmanager
def baseline_reader():
    proc=subprocess.Popen(["git","-C",str(ROOT),"cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    def get(path):
        value=Path(path)
        require(not value.is_absolute() and ".." not in value.parts and "\n" not in path,"Unsafe history path")
        proc.stdin.write((BASE+":"+value.as_posix()+"\n").encode());proc.stdin.flush()
        header=proc.stdout.readline().split()
        require(len(header)==3 and header[1]==b"blob","Unavailable historical blob "+path)
        size=int(header[2]);raw=proc.stdout.read(size)
        require(len(raw)==size and proc.stdout.read(1)==b"\n","Truncated Git blob")
        return raw
    try:yield get
    finally:
        proc.stdin.close();proc.stdout.close();require(proc.wait()==0,"Git object read failed")


def ledger(parts):
    for part in parts:
        raw=(ROOT/part["path"]).read_bytes()
        require(info(raw)=={k:part[k] for k in ("bytes","sha256")} and len(raw.splitlines())==part["records"],"Incomplete deadline ledger")
        yield from map(json.loads,raw.splitlines())


def verify_history():
    git(ROOT,"merge-base","--is-ancestor",BASE,"HEAD")
    require(git(ROOT,"rev-parse",BASE+"^{tree}").decode().strip()==TREE,"CP10 tree mismatch")
    m=read(MAINTENANCE);early=read(INTEGRATION)["datasets"];cut=read(CUT);bib=read(BIB)["datasets"]
    due=defaultdict(dict)
    for row in ledger(m["field_change_parts"]):due[row["dataset"]][row["line_index"]]=row
    events={r["task_id"]:r for r in ledger(m["task_event_parts"])}
    this_manifest=read("temp/partitions/manifest.json")
    changes=defaultdict(lambda:defaultdict(list)); additions=defaultdict(list)
    for n,b in early.items():
        for x in b["changed"]:changes[n][x["id"]].append(x)
        additions[n].extend(b["appended_ids"])
    for n,rows in cut["changed_rows"].items():
        for x in rows:changes[n][x["id"]].append(x)
    additions["tasks"].extend(cut["new_tasks"])
    additions["privacy-redactions"].append("REDACT-RUN09-KRESS-AFFILIATION")
    for n,b in bib.items():
        for x in b["replacements"]:changes[n][x["id"]].append(x)
        additions[n].extend(b["appended_ids"])
    summaries={};total=Counter()
    with baseline_reader() as get:
        manifest=json.loads(get("temp/partitions/manifest.json"))
        source_names={Path(n).stem for n in git(ROOT,"ls-tree","--name-only",BASE+":temp").decode().splitlines() if n.endswith(".jsonl")}
        require(set(logical_names(ROOT,this_manifest))==source_names,"Different set of canonical JSONL datasets")
        for n in sorted(source_names):
            current=iter(logical_lines(ROOT,n,this_manifest)); old_count=0;changed=0;timed=0; matched=set()
            for part in parts_for(n,manifest):
                raw=get("temp/"+part["path"])
                if "sha256" in part:require(info(raw)=={k:part[k] for k in ("bytes","sha256")},"Broken parent shard")
                for old in raw.splitlines(keepends=True):
                    current_line=next(current);expected=old
                    if old_count in due[n]:
                        change=due[n][old_count]
                        expected=replace_status_tokens(old,[x["pointer"] for x in change["changes"]])
                        require(sha(old)==change["before_line_sha256"] and sha(expected)==change["after_line_sha256"],"Undeclared maintenance mutation")
                        timed+=1
                    if current_line!=expected:
                        key=json.loads(old)[IDS[n]]
                        binding=sha(expected)
                        for change in changes[n].get(key,[]):
                            require(change["before_sha256"]==binding,"Broken research edit chain: "+key)
                            binding=change["after_sha256"]
                        require(sha(current_line)==binding,"Historical row changed without a research receipt: "+key)
                        if n=="reference-occurrences":
                            before,after=json.loads(old),json.loads(current_line)
                            require(all(before.get(k)==after.get(k) for k in ("raw_reference","raw_fingerprint","reference_label","version_id")),"Historical printed reference altered")
                        changed+=1;matched.add(key)
                    old_count+=1
            require(timed==len(due[n]),"Missing maintenance transitions")
            observed=[]; observed_events=set()
            for line in current:
                key=json.loads(line)[IDS[n]]
                if n=="tasks" and key in events and sha(line)==events[key]["after_sha256"]:
                    require(key not in observed_events,"Duplicate maintenance event");observed_events.add(key)
                else:
                    observed.append(key)
                    if key in changes[n]:
                        require(sha(line)==changes[n][key][-1]["after_sha256"],"Changed appended row differs: "+key)
                        matched.add(key)
            require(observed==additions[n],"New or lost rows outside ledgers: "+n)
            if n=="tasks":require(set(events)==observed_events,"Missing historical deadline events")
            # A later decision can restore an original row byte-for-byte; verify that chain too.
            for k,chain in changes[n].items():
                if k not in matched:
                    require(chain[0]["before_sha256"]==chain[-1]["after_sha256"] and all(a["after_sha256"]==b["before_sha256"] for a,b in zip(chain,chain[1:])),
                            "Unused declared row change: "+k)
            summaries[n]=dict(old_rows=old_count,research_modified=changed,maintenance_only_transitions=timed,
                              added_records=len(observed),added_deadline_events=len(observed_events))
            total.update(summaries[n])
        parent=json.loads(get("temp/snapshots/checkpoints/CP-0010.json"))
        require(parent["status"]=="valid","Parent checkpoint invalid")
        frozen={p:h for p,h in parent["artifact_hashes"].items() if p.startswith(("scripts/","temp/history/","temp/query-results/","temp/reports/","temp/runs/","temp/validation/","temp/snapshots/")) or p in {"temp/schema.json","temp/seed-manifest.jsonl","temp/rejected_uploads.log"}}
        for name,expected in frozen.items():require(original.sha(ROOT/name)==expected,"Frozen legacy artifact changed: "+name)
        require(sha(get("temp/snapshots/checkpoints/CP-0010.json"))==original.sha(ROOT/"temp/snapshots/checkpoints/CP-0010.json"),"Parent snapshot bytes changed")
    return dict(status="passed",baseline_commit=BASE,baseline_tree=TREE,old_records_lost=0,historical_files_verified=len(frozen)+1,
                logical_datasets=summaries,totals=dict(total),scientific_baseline_rows=summaries["assessments"]["old_rows"],
                old_reference_strings_preserved=True)
