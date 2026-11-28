"""Run the existing full research audit using byte offsets in immutable logical JSONL parts."""
import argparse
from collections import OrderedDict
from collections.abc import MutableMapping
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

import audit_run
from checkpoint_cp10 import require
from history_run10 import blobs
from escalate_unknown_run7 import parts_for
from search_run11_bibliography import ROOT, STATE, TEMP, digest, read
from schema_run11_parts import key as part_key, read_ledger

CANDIDATE=TEMP/"snapshots/checkpoints/CP-0013.json"


class LogicalRows:
    def __init__(self, base, name, parts):
        self.paths=[base/p["path"] for p in parts] if parts else [base/name]
        if parts:
            self.length=sum(p["records"] for p in parts)
        else:
            with self.paths[0].open("rb") as f:self.length=sum(bool(line.strip()) for line in f)
        self.position=None
        self.current=None
        self.files=OrderedDict()

    def __len__(self):
        return self.length

    def __iter__(self):
        for n,path in enumerate(self.paths):
            with path.open("rb") as f:
                pos=0
                for line in f:
                    if line.strip():
                        self.position=(n<<32)|pos
                        self.current=json.loads(line)
                        yield self.current
                    pos+=len(line)

    @lru_cache(maxsize=256)
    def read_at(self, position):
        n=position>>32
        if n not in self.files:
            self.files[n]=self.paths[n].open("rb")
            if len(self.files)>12:
                _,old=self.files.popitem(last=False)
                old.close()
        else:self.files.move_to_end(n)
        f=self.files[n];f.seek(position & 0xffffffff)
        return json.loads(f.readline())

    def close(self):
        for f in self.files.values():f.close()
        self.files.clear()
        self.read_at.cache_clear()


class LocationMap(MutableMapping):
    def __init__(self,rows):
        self.rows=rows
        self.locations={}

    def __getitem__(self,key):
        return self.rows.read_at(self.locations[key])

    def __setitem__(self,key,value):
        if value is not self.rows.current or self.rows.position is None:
            raise ValueError("Index assignments must be bound to the exact current JSONL record")
        self.locations[key]=self.rows.position

    def __delitem__(self,key):
        del self.locations[key]

    def __iter__(self):
        return iter(self.locations)

    def __contains__(self,key):
        return key in self.locations

    def __len__(self):
        return len(self.locations)


class FullAudit(audit_run.Audit):
    schema_ledger=None

    def validate_records(self,kind,records,name):
        if self.schema_ledger is None:
            return super().validate_records(kind,records,name)
        validator=self.validator(kind)
        require(validator is not None,"Missing schema "+kind)
        for path in records.paths:
            raw=path.read_bytes()
            checksum=sha256(raw).hexdigest()
            verified=self.schema_ledger["parts"].get(part_key(kind,checksum))
            if verified:
                count=sum(bool(line.strip()) for line in raw.splitlines())
                require(verified["bytes"]==len(raw) and verified["records"]==count,"Invalid schema validation ledger")
                self.counts["schema_records"]+=count
                self.counts["schema_records_prevalidated_from_identical_git_bytes"]+=count
            else:
                for n,line in enumerate(raw.splitlines(),1):
                    if line.strip():
                        row=json.loads(line)
                        self.validate(kind,row,row.get(audit_run.PRIMARY.get(kind,""),f"{path.name}:{n}"))

    def logical_records(self,name,parts):
        return LogicalRows(self.temp,name,parts)

    def index_storage(self,records):
        return LocationMap(records) if isinstance(records,LogicalRows) else {}

    def load_json(self,path,kind=None):
        data=super().load_json(path,kind)
        if kind=="checkpoint" and data is not None:
            return {k:data[k] for k in ("checkpoint_id","scope_id","status","parent_checkpoint_id","artifact_hashes")}
        return data

    def close(self):
        for rows in self.datasets.values():
            if isinstance(rows,LogicalRows):rows.close()


def run(out,ledger=None):
    cp=read(CANDIDATE);run=read(STATE);baseline=run["checkpoint_commit"]
    bound=digest(CANDIDATE)
    with blobs() as get:
        m=json.loads(get(baseline,"temp/partitions/manifest.json"))
        prior=[json.loads(line) for part in parts_for("assessments",m) for line in get(baseline,"temp/"+part["path"]).splitlines() if line]
    engine=FullAudit(ROOT,out,datetime.fromisoformat(cp["created_at_utc"]))
    if ledger is not None:
        require(ledger.is_file(),"Missing independent schema validation ledger")
        engine.schema_ledger=read_ledger(ledger,(TEMP/"schema.json").read_bytes())
        engine.stats["schema_validation_ledger_sha256"]=digest(ledger)
    engine._manual_assessment_baselines=[(baseline+":temp/assessments.jsonl",prior)]
    engine.stats["candidate_sha256"]=bound
    try:engine.run()
    finally:engine.close()
    result=read(out)
    require(digest(CANDIDATE)==bound and not result["changed_inputs"] and result["status"]=="passed" and result["error_count"]==0,
            "Full research audit failed: "+str(result["findings"]["error"].keys()))
    baseline_warnings=read(TEMP/"validation/cp12-data-audit.json")["findings"]["warning"]
    require(all(k in baseline_warnings and item["count"]<=baseline_warnings[k]["count"] for k,item in result["findings"]["warning"].items()),"New audit warnings require review")
    print("Full audit, errors and warnings",result["error_count"],result["warning_count"],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--schema-ledger",type=Path)
    args=parser.parse_args()
    run(args.output,args.schema_ledger)
