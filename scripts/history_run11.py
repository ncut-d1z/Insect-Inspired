"""Verify RUN11's declared canonical mutations against the exact parent and child Git blobs."""
import argparse
from collections import Counter
import json
from pathlib import Path

from escalate_unknown_run7 import IDS, git, parts_for, require, sha
from history_run10 import blobs
from search_run11_bibliography import ROOT, STATE, read

CANONICAL = [":(top,glob)temp/*.jsonl", "temp/partitions"]


def tree(revision):
    rows = git(ROOT, "ls-tree", "-r", "-z", revision, "--", "temp")
    result = {}
    for line in rows.split(b"\0"):
        if line:
            tag, path = line.split(b"\t", 1)
            if path.startswith(b"temp/partitions/") or (path.count(b"/")==1 and path.endswith(b".jsonl")):
                result[path.decode()] = tag.split()[2].decode()
    return result


def part_sequence(get, revision, names, descriptors, seen):
    for part in descriptors:
        path = "temp/" + part["path"]
        oid = names[path]
        if oid not in seen:
            raw = get(revision, path)
            count = raw.count(b"\n")
            require(not raw or raw.endswith(b"\n"), "Missing final newline in " + path)
            seen[oid] = (sha(raw), len(raw), count)
        checksum, length, count = seen[oid]
        if "sha256" in part:
            require((checksum,length,count)==(part["sha256"],part["bytes"],part["records"]), "Physical Git part differs " + path)
        if count:
            yield oid, path, count


def compare(get, before, commit, left, right):
    # Equal complete Git blobs skip decoding. Changed blocks compare every complete JSONL row in order.
    a = b = None
    la = lb = None
    while True:
        if a is None:
            a = next(left, None)
            i = 0
            la = None
        if b is None:
            b = next(right, None)
            j = 0
            lb = None
        if a is None and b is None:
            return
        require(b is not None, "Lost historical canonical rows")
        if a and i == j == 0 and a[0] == b[0]:
            yield a[2], None, None
            a = b = None
            continue
        if lb is None:
            lb = get(commit,b[1]).splitlines(keepends=True)
        if a and la is None:
            la = get(before,a[1]).splitlines(keepends=True)
        n = min(a[2]-i, b[2]-j) if a else b[2]-j
        for k in range(n):
            yield 0, la[i+k] if a else None, lb[j+k]
        i += n
        j += n
        if a and i == a[2]:
            a = None
        if j == b[2]:
            b = None


def audit(end="HEAD"):
    run=read(STATE)
    base=run["start_commit_sha"]
    end=git(ROOT,"rev-parse",end+"^{commit}").decode().strip()
    git(ROOT,"merge-base","--is-ancestor",base,end)
    changed=git(ROOT,"log","--reverse","--format=%H",base+".."+end,"--",*CANONICAL).decode().splitlines()
    frozen=["temp/snapshots/checkpoints","temp/snapshots/scope.json","temp/snapshots/scopes","temp/seed-manifest.jsonl","temp/schema.json","temp/query-results","temp/history"]
    require(not git(ROOT,"diff","--name-only","--no-renames","--diff-filter=DM",base,end,"--",*frozen), "Historical scope, receipt or checkpoint changed")
    seen={}; receipt_list=[]; total=Counter()
    with blobs() as get:
        parent=get(base,"temp/snapshots/checkpoints/CP-0012.json")
        require(sha(parent)==run["start_sync_gate"]["checkpoint_sha256"] and json.loads(parent)["status"]=="valid","CP12 differs")
        for commit in changed:
            before=git(ROOT,"rev-parse",commit+"^").decode().strip()
            paths=git(ROOT,"diff","--name-only","--no-renames","--diff-filter=A",before,commit,"--","temp/reports").decode().splitlines()
            reports=[]
            for p in paths:
                if p.endswith(".json"):
                    obj=json.loads(get(commit,p))
                    if isinstance(obj,dict) and obj.get("before_commit")==before and "datasets" in obj:reports.append((p,obj))
            require(len(reports)==1,"Missing or ambiguous canonical transaction receipt "+commit)
            name,rep=reports[0]; require(get(end,name)==get(commit,name),"Canonical transaction receipt was superseded")
            old=json.loads(get(before,"temp/partitions/manifest.json"));new=json.loads(get(commit,"temp/partitions/manifest.json"))
            lt,rt=tree(before),tree(commit);tally=Counter();permitted={"temp/partitions/manifest.json"}
            for dataset,delta in rep["datasets"].items():
                l=parts_for(dataset,old);r=parts_for(dataset,new)
                permitted.update("temp/"+p["path"] for p in [*l,*r])
                repl={v["id"]:v for v in delta["replacements"]}; extras=iter(delta["appended_ids"]); count=0
                lseq=part_sequence(get,before,lt,l,seen);rseq=part_sequence(get,commit,rt,r,seen)
                for same,a,b in compare(get,before,commit,lseq,rseq):
                    if same:
                        tally["byte_identical_row_comparisons"]+=same;count+=same;continue
                    count+=1
                    if a is None:
                        key=json.loads(b)[IDS[dataset]]
                        require(next(extras,None)==key,"Undeclared appended "+dataset+" ID "+key)
                        tally["appended_rows"]+=1
                    elif a==b:tally["byte_identical_row_comparisons"]+=1
                    else:
                        key=json.loads(a)[IDS[dataset]]; x=repl.pop(key)
                        require(json.loads(b)[IDS[dataset]]==key and (sha(a),sha(b))==(x["before_sha256"],x["after_sha256"]), "Undeclared row mutation "+key)
                        tally["changed_rows"]+=1
                if repl:
                    expected={v["before_sha256"]:k for k,v in repl.items() if v["before_sha256"]==v["after_sha256"]}
                    require(len(expected)==len(repl),"Unapplied non-identical replacement "+dataset)
                    for rev,parts in ((before,l),(commit,r)):
                        missing=dict(expected)
                        for part in parts:
                            for line in get(rev,"temp/"+part["path"]).splitlines(keepends=True):
                                digest=sha(line)
                                if digest in missing:
                                    require(json.loads(line)[IDS[dataset]]==missing.pop(digest),"No-op receipt identity mismatch "+dataset)
                            if not missing:break
                        require(not missing,"No-op receipt hash absent from Git "+dataset)
                    tally["verified_byte_identical_replacements"]+=len(repl)
                require(count==delta["logical_records"] and next(extras,None) is None,"Logical count or transaction receipt differs "+dataset)
                entry=new["datasets"].get(dataset+".jsonl")
                resulting_digest=entry["logical_sha256"] if entry else seen[rt["temp/"+dataset+".jsonl"]][0]
                require(resulting_digest==delta["logical_sha256"],"Recorded transaction and dataset digest differ "+dataset)
            for filename in old["datasets"].keys()|new["datasets"].keys():
                if old["datasets"].get(filename)!=new["datasets"].get(filename):
                    require(filename[:-6] in rep["datasets"],"Unreported manifest change "+filename)
            changed_paths=set(git(ROOT,"diff","--name-only","--no-renames",before,commit,"--",*CANONICAL).decode().splitlines())
            require(changed_paths<=permitted, "Unexpected canonical file "+str(changed_paths-permitted))
            total.update(tally)
            receipt_list.append(dict(commit=commit,before=before,receipt=name,receipt_sha256=sha(get(commit,name)),counts=dict(tally)))
            print(commit[:10],len(receipt_list),"/",len(changed),dict(tally),flush=True)
    return dict(run_id="RUN-0011",parent_checkpoint="CP-0012",parent_commit=base,parent_checkpoint_sha256=sha(parent),bound_commit=end,
                status="passed",historical_rows_lost=0,ordered_transactions=receipt_list,totals=dict(total),unique_verified_partition_blobs=len(seen))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--end",default="HEAD");p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    result=audit(args.end)
    with args.output.open("xb") as f:f.write((json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n").encode())
