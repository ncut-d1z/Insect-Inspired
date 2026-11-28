"""Generate the Q2 entity collections from a pinned Git tree and verify their independent readback."""
import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator, FormatChecker
from escalate_unknown_run7 import parts_for
from export_run import entity_view
from history_run10 import blobs
from partitioned_research_json import ENTITY_KEYS, bound_path, encode, load_view, metadata, put, sha, view_files, write_view

ENTRY = Path("temp/exports/research_entities.json")
RECEIPT = Path("temp/reports/RUN-0011-entity-collections.json")
ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def revision(repo, ref):
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--verify", ref + "^{commit}"], text=True).strip()


def source_rows(get, commit, manifest, name):
    logical = hashlib.sha256()
    total = 0
    for part in parts_for(name, manifest):
        payload = get(commit, "temp/" + part["path"])
        lines = payload.splitlines()
        if "sha256" in part:
            require((len(payload), sha(payload), len(lines)) == (part["bytes"], part["sha256"], part["records"]), "Invalid source part " + part["path"])
        logical.update(payload)
        total += len(lines)
        yield from map(json.loads, lines)
    binding = manifest["datasets"].get(name + ".jsonl")
    if binding:
        require((total, logical.hexdigest()) == (binding["logical_records"], binding["logical_sha256"]), "Invalid source dataset " + name)


def check_ids(view):
    ids = {name: {row[key] for row in view[name]} for name, key in ENTITY_KEYS.items()}
    require(all(len(v) == len(view[k]) for k, v in ids.items()), "Duplicate entity ID")
    keys = [row["work_key"] for row in view["work_refs"]]
    require(len(keys) == len(set(keys)), "Duplicate bibliography key")
    known = set.union(*(ids[k] for k in ("people", "work_refs", "projects", "organizations")))
    for r in view["relations"]:
        require(r["from_id"] in known and r["to_id"] in known, "Unresolved entity relation " + r["relation_id"])
        if "work_id" in r:
            require(r["work_id"] in ids["work_refs"], "Missing Work on relation " + r["relation_id"])
        if r["relation_type"] == "authored_by":
            require(r["from_id"] in ids["work_refs"] and r["to_id"] in ids["people"], "Invalid authorship endpoints")
        if r["relation_type"] == "affiliated_with":
            require(r["from_id"] in ids["people"] and r["to_id"] in ids["organizations"], "Invalid affiliation endpoints")
    return {k: len(v) for k, v in ids.items()}


def build(repo, ref, output):
    commit = revision(repo, ref)
    require(not output.exists(), "Use a new export directory")
    output.mkdir(parents=True)
    with blobs(repo) as get:
        manifest_data = get(commit, "temp/partitions/manifest.json")
        manifest = json.loads(manifest_data)
        registry = json.loads(get(commit, "temp/schema.json"))
        scope = json.loads(get(commit, "temp/snapshots/scope.json"))
        def rows(name):
            return source_rows(get, commit, manifest, name)
        works = {w["work_id"]: {k: w.get(k) for k in ("work_id", "work_key", "authors", "discovery_sources", "publication_date", "verification_status")} for w in rows("works")}
        people = {p["person_id"]: p for p in rows("authors")}
        require(len(works) == manifest["datasets"]["works.jsonl"]["logical_records"] and len(people) == manifest["datasets"]["authors.jsonl"]["logical_records"], "Duplicate canonical ID")
        prefix = {"scope_id": scope["scope_id"], "checkpoint_id": "CP-0013", "schema_version": registry["schema_version"]}
        view = entity_view(prefix, works, people, rows("organizations"), rows("projects"), rows("project-relations"))
    del works, people
    counts = check_ids(view)
    canonical = encode(view) + b"\n"
    digest, size = sha(canonical), len(canonical)
    del canonical
    index = write_view(output / ENTRY, view, ENTITY_KEYS)
    require(index["logical_sha256"] == digest, "Original projection and index differ")
    del view
    gc.collect()
    rebuilt = load_view(output / ENTRY)
    require(check_ids(rebuilt) == counts, "Reconstructed entity IDs differ")
    validator = Draft202012Validator({"$schema": registry["$schema"], "$ref": "#/$defs/research_entities", "$defs": registry["$defs"]}, format_checker=FormatChecker())
    validator.validate(rebuilt)
    entry = output / ENTRY
    manifest_info = json.loads(entry.read_bytes())
    result = dict(source_commit=commit, source_partitions_sha256=sha(manifest_data), status="verified_working_export",
                  checkpoint_acceptance="pending", entry=ENTRY.as_posix(), collections=counts, logical_bytes=size, logical_sha256=digest,
                  relation_types=dict(Counter(r["relation_type"] for r in rebuilt["relations"])), index_sha256=manifest_info["index_sha256"],
                  parts=sum(len(c["parts"]) for c in index["collections"].values()), largest_part_bytes=max(p["bytes"] for c in index["collections"].values() for p in c["parts"]),
                  foreign_keys="passed", schema="research_entities", schema_errors=0,
                  physical_files=[p.relative_to(output).as_posix() for p in view_files(entry)])
    put(output / RECEIPT, encode(result) + b"\n")
    print(json.dumps({k:v for k,v in result.items() if k != "physical_files"}, ensure_ascii=False), flush=True)


def readback(repo, ref, dest):
    commit = revision(repo, ref)
    with blobs(repo) as get, TemporaryDirectory(prefix="entity-collections-") as scratch:
        root = Path(scratch)
        result = json.loads(get(commit, RECEIPT.as_posix()))
        for name in result["physical_files"]:
            require(name == ENTRY.as_posix() or name.startswith("temp/exports/research_entities/"), "Unexpected output path")
            put(bound_path(root, name), get(commit, name))
        entry = root / ENTRY
        index, _ = metadata(entry)
        require({p.relative_to(root).as_posix() for p in view_files(entry)} == set(result["physical_files"]), "Remote inventory differs")
        view = load_view(entry)
        counts = check_ids(view)
        raw = encode(view) + b"\n"
        require((sha(raw), len(raw), counts) == (result["logical_sha256"], result["logical_bytes"], result["collections"]), "Remote reassembly differs")
        require(index["logical_sha256"] == result["logical_sha256"] and json.loads(entry.read_bytes())["index_sha256"] == result["index_sha256"], "Remote index differs")
        record = dict(remote_repository="https://github.com/ncut-d1z/Insect-Inspired.git", method="independent HTTPS fetch; native Git blob readback",
                      export_commit=commit, canonical_source_commit=result["source_commit"], index_sha256=result["index_sha256"], logical_sha256=sha(raw),
                      logical_bytes=len(raw), collections=counts, parts_verified=result["parts"], checkpoint_acceptance="pending")
        put(dest, encode(record) + b"\n")
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("build", "readback"))
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--revision", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.operation == "build":
        build(args.repo, args.revision, args.output.resolve())
    else:
        readback(args.repo, args.revision, args.output.resolve())
