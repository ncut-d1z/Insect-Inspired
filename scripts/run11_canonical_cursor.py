"""Resume a canonical slice only after its published source and identifier lookups are available."""
import argparse
import json
import subprocess
from pathlib import Path

from index_run11_positions import INDEX
from run10_reference_records import token
from run11_reference_inventory import OUT, PLAN, ROOT, WIDTH, read

TAG={"crossref":"CR","openalex":"OA","europepmc":"EP"}


def query_key(group):
    return "Q-RUN11-ID-"+TAG[group["provider"]]+"-"+token(*group["ids"])+("-META" if group["provider"]=="crossref" else "")


def committed_paths(folder):
    rel=folder.relative_to(ROOT).as_posix()
    probe=subprocess.run(["git","-C",str(ROOT),"ls-tree","--name-only","HEAD:"+rel],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    return set(probe.stdout.decode().splitlines()) if probe.returncode==0 else set()


def readiness(start,end):
    inputs=[PLAN/"first-1024.json"]
    if end>1024:inputs.append(PLAN/"groups.json")
    committed_plan=committed_paths(PLAN);committed_index=committed_paths(INDEX);committed_raw=committed_paths(OUT)
    if any(p.name not in committed_plan for p in inputs):return False
    wanted=set()
    for base in range(start//WIDTH*WIDTH,end,WIDTH):
        label=f"{base+1:04}-{min(base+WIDTH,2620):04}.jsonl"
        if label not in committed_index:return False
        with (INDEX/label).open(encoding="utf-8") as f:
            for line in f:
                r=json.loads(line)
                if start<r["queue_position"]<=end:wanted.update(r["candidate_identifiers"])
    for p in inputs:
        for g in read(p)["groups"]:
            if wanted.isdisjoint(g["ids"]):continue
            prefix=query_key(g)
            files=[f"{prefix}-A{i}.json" for i in range(1,5) if f"{prefix}-A{i}.json" in committed_raw]
            if not files:return False
            q=read(OUT/files[-1])
            if q["status"]!="success" and q["retryable"] and not q.get("deferred") and q["attempt"]<4:return False
    return True


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("start",type=int);p.add_argument("end",type=int)
    args=p.parse_args();print("ready" if readiness(args.start,args.end) else "waiting")
