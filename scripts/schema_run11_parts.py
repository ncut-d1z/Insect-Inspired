"""Validate immutable Git JSONL parts with the audit's schema while bibliographic integration continues."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version, PackageNotFoundError
import inspect
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from audit_run import Audit
from checkpoint_cp10 import require
from escalate_unknown_run7 import git, parts_for
from history_run10 import blobs
from partitioned_research_json import encode, put, sha
from search_run11_bibliography import ROOT, stamp


def environment(schema_bytes):
    versions = {}
    for name in ("jsonschema","jsonschema-specifications","referencing","rpds-py","rfc3339-validator","rfc3987","rfc3987-syntax","uri-template"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return dict(schema_sha256=sha(schema_bytes), validator_packages=versions, available_formats=sorted(FormatChecker().checkers),
                audit_validator_sha256=sha(inspect.getsource(Audit.validator).encode()), validation_implementation_sha256=sha(Path(__file__).read_bytes()))


def read_ledger(path, schema_bytes):
    if not path.exists():
        return {"environment":environment(schema_bytes),"parts":{},"completed_revisions":{}}
    ledger = json.loads(path.read_bytes())
    require(ledger["environment"] == environment(schema_bytes), "Schema or local validator changed. Start a new validation ledger.")
    return ledger


def key(kind, checksum):
    return kind + "/" + checksum


def prevalidate(repo, revision, output):
    require(not output.is_relative_to(ROOT), "Use an independent validation directory")
    commit = git(repo,"rev-parse","--verify",revision+"^{commit}").decode().strip()
    with blobs(repo) as get:
        schema_bytes = get(commit,"temp/schema.json")
        ledger = read_ledger(output,schema_bytes)
        schema = json.loads(schema_bytes)
        Draft202012Validator.check_schema(schema)
        engine = Audit(ROOT,output,datetime.now(timezone.utc))
        engine.schema = schema
        manifest = json.loads(get(commit,"temp/partitions/manifest.json"))
        registry = {**schema["x-entity-files"], **engine.extra_schemas}
        checked, reused, processed = 0, 0, 0
        for filename, kind in sorted(registry.items()):
            validator = engine.validator(kind)
            require(validator is not None, "Missing validator for "+kind)
            for part in parts_for(filename.removesuffix(".jsonl"),manifest):
                path = "temp/"+part["path"]
                h = part.get("sha256")
                if h and key(kind,h) in ledger["parts"]:
                    entry = ledger["parts"][key(kind,h)]
                    require(entry["bytes"]==part["bytes"] and entry["records"]==part["records"], "Cached part count differs")
                    reused += entry["records"]
                    continue
                raw = get(commit,path)
                actual = hashlib.sha256(raw).hexdigest()
                require(h is None or actual==h and len(raw)==part["bytes"], "Git input differs "+path)
                k = key(kind,actual)
                if k in ledger["parts"]:
                    reused += ledger["parts"][k]["records"]
                    continue
                n = 0
                for line in raw.splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    error = next(validator.iter_errors(row),None)
                    if error is not None:
                        raise ValueError(f"Schema error at {commit}:{path}, record {n+1}, {list(error.absolute_path)}: {error.message[:500]}")
                    n += 1
                require(h is None or n==part["records"], "Git input record count differs "+path)
                ledger["parts"][k] = dict(records=n,bytes=len(raw),first_validated_commit=commit,source_path=path)
                checked += n
                processed += 1
                if processed%16==0:
                    put(output,encode(ledger)+b"\n")
                    print(commit[:10],processed,"new parts,",checked,"rows",flush=True)
        ledger["completed_revisions"][commit]=dict(completed_at_utc=stamp(),validated_rows=checked,reused_rows=reused)
        put(output,encode(ledger)+b"\n")
        print("Complete schema prevalidation at",commit,"new",checked,"reused",reused,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--revision",required=True)
    parser.add_argument("--output",type=Path,required=True)
    a=parser.parse_args()
    prevalidate(a.repo.resolve(),a.revision,a.output.resolve())
