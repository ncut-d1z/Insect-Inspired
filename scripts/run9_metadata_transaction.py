"""Publish a reviewed RUN9 metadata batch while preserving existing partition boundaries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from advance_review_deadlines import transaction_directory
from escalate_unknown_run7 import CAP, IDS, encoded, git, info, parts_for, publish, require, sha
import gates

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"temp"


def read(name):
    return json.loads((ROOT/name).read_bytes())


def stamp_file(stage, name, obj):
    path=stage/"files"/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode())


def stage_rows(stage, name, changes, additions, old_manifest, new_manifest, guards):
    previous=parts_for(name,old_manifest)
    sequence=[]
    combined=hashlib.sha256()
    count=0
    seen=set()
    added_ids={r[IDS[name]]:r for r in additions}
    require(len(added_ids)==len(additions),"Duplicate added IDs in "+name)
    preexisting={}
    seen_changes=[]
    def output(data):
        nonlocal count
        if not data:return
        digest=sha(data); n=sum(bool(l) for l in data.splitlines())
        dest=name+".jsonl" if not sequence else "partitions/"+name+"/"+digest+".jsonl"
        path=stage/"files/temp"/dest; path.parent.mkdir(parents=True,exist_ok=True)
        if not (BASE/dest).is_file() or sha((BASE/dest).read_bytes())!=digest:
            path.write_bytes(data)
        sequence.append(dict(path=dest,records=n,sha256=digest,bytes=len(data)))
        combined.update(data);count+=n
    for i,p in enumerate(previous):
        relative="temp/"+p["path"]
        raw=(ROOT/relative).read_bytes()
        guards[relative]=info(raw)
        if p.get("sha256"):require(guards[relative]=={"bytes":p["bytes"],"sha256":p["sha256"]},"Corrupt prior partition")
        buf=bytearray()
        def consume(line):
            nonlocal buf
            require(len(line)<=CAP,"One row exceeds the partition limit")
            if buf and len(buf)+len(line)>CAP:
                output(bytes(buf));buf=bytearray()
            buf.extend(line)
        for line in raw.splitlines(keepends=True):
            r=json.loads(line)
            key=r[IDS[name]]
            if key in added_ids:
                require(name=="tasks","ID already exists: "+key)
                preexisting[key]=r
            if key in changes:
                before,after=changes[key]
                require(key not in seen and before==r and after[IDS[name]]==key,"Unbound previous value: "+key)
                revised=encoded(after);seen.add(key)
                seen_changes.append(dict(id=key,before_sha256=sha(line),after_sha256=sha(revised)))
                consume(revised)
            else:consume(line)
        if i==len(previous)-1:
            for r in additions:
                key=r[IDS[name]]
                if name=="tasks":
                    old=preexisting.get(key)
                    require(r["event_sequence"]==(old["event_sequence"]+1 if old else 1),"Task event order "+key)
                    if old and old.get("unknown_since_utc"):
                        require(all(old[k]==r[k] for k in ("unknown_since_utc","deadline_at_utc")),"Reset field clock")
                consume(encoded(r))
        output(bytes(buf))
    require(seen==set(changes),"Missing prior rows in "+name)
    if len(sequence)>1 or name+".jsonl" in old_manifest["datasets"]:
        new_manifest["datasets"][name+".jsonl"]=dict(logical_records=count,logical_sha256=combined.hexdigest(),parts=sequence)
    return dict(logical_records=count,logical_sha256=combined.hexdigest(),replacements=seen_changes,appended_ids=list(added_ids))


def apply_batch(changes,adds,report,report_path,extra_outputs=None):
    from copy import deepcopy
    require(not (ROOT/report_path).exists() and not git(ROOT,"status","--porcelain").strip(),"Commit inputs or locate the existing receipt")
    head=git(ROOT,"rev-parse","HEAD").decode().strip()
    old=read("temp/partitions/manifest.json"); new=deepcopy(old)
    guards={"temp/partitions/manifest.json":info((BASE/"partitions/manifest.json").read_bytes())}
    for p in report.get("input_receipts",{}):
        guards[p]=info((ROOT/p).read_bytes())
        require(guards[p]["sha256"]==report["input_receipts"][p],"Source receipt changed")
    registry=read("temp/schema.json")["x-entity-files"]
    with transaction_directory(ROOT) as stage:
        bindings={}
        for name in sorted(set(changes)|set(adds)):
            update=changes.get(name,{});append=adds.get(name,[])
            schema=registry.get(name+".jsonl") or ("entity_export_relation" if name=="project-relations" else None)
            if schema:
                for r in [*(pair[1] for pair in update.values()),*append]:
                    gates.validate(schema,r)
            bindings[name]=stage_rows(stage,name,update,append,old,new,guards)
        stamp_file(stage,"temp/partitions/manifest.json",new)
        report.update(before_commit=head,datasets=bindings,checkpoint_status="pending_validation")
        stamp_file(stage,report_path,report)
        for p,data in (extra_outputs or {}).items():
            if (ROOT/p).exists():guards[p]=info((ROOT/p).read_bytes())
            stamp_file(stage,p,data)
        before={p["path"] for d in old["datasets"].values() for p in d["parts"]}
        after={p["path"] for d in new["datasets"].values() for p in d["parts"]}
        relative=[p.relative_to(stage/"files").as_posix() for p in (stage/"files").rglob("*") if p.is_file()]
        publish(ROOT,stage,{"temp/"+n for n in before-after if n.startswith("partitions/")},head,guards)
        if os.name=="nt":
            for name in relative:
                p=(ROOT/name).resolve()
                require(p.is_relative_to(BASE) and p.is_file() and not p.is_symlink(),"Unexpected ACL target")
                subprocess.run(["icacls",str(p),"/reset"],check=True,stdout=subprocess.DEVNULL)
    return bindings
