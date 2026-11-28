"""Resume a Git-bound breadth-first frontier in small, independently publishable batches."""
import argparse
import hashlib
from pathlib import Path
import re
import time

from run10_reference_records import token
from search_run10_references import ROOT, RUN, SCOPE, crossref, europe, fetch, read, write


def prepare(source, dest, count):
    if count < 1 or dest.exists():
        raise ValueError("Expected a new batch and a positive number of parents")
    rows = read(source)["worklist"]
    if not rows or len({row["work_id"] for row in rows}) != len(rows):
        raise ValueError("Expected a nonempty frontier of distinct works")
    parents = rows[:count]
    write(dest, dict(run_id=RUN, scope_id=SCOPE, queue_source=source.relative_to(ROOT).as_posix(),
                     queue_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), queue_total=len(rows),
                     start_index=0, next_index=len(parents), remaining_before_new_discoveries=len(rows)-len(parents),
                     worklist=parents))


def openalex(owner):
    identifier = owner["openalex"]
    if not re.fullmatch(r"W[0-9]+", identifier):
        raise ValueError(identifier)
    def project(data):
        if data["id"].rsplit("/",1)[-1] != identifier:
            raise ValueError("OpenAlex parent changed identity")
        ids = data["referenced_works"]
        records = [{"openalex": ident.rsplit("/",1)[-1]} for ident in ids]
        if any(not re.fullmatch(r"W[0-9]+", r["openalex"]) for r in records):
            raise ValueError("Invalid OpenAlex reference ID")
        return dict(records=records, source_bibliography={k:data.get(k) for k in ("id","doi","display_name","ids","publication_year")},
                    visible_total=len(ids), returned_count=len(records), page_complete=True)
    fetch("ROA-"+identifier, "openalex", "https://api.openalex.org/works/"+identifier,
          {"select":"id,doi,ids,display_name,publication_year,referenced_works"}, [owner],
          "Follow a recursively discovered bibliographic work by its registered OpenAlex ID.", project)


def retrieve(batch):
    group = read(batch)["worklist"]
    with_doi = [r for r in group if r.get("doi")]
    for i in range(0, len(with_doi), 8):
        owners = with_doi[i:i+8]
        crossref("RCR-"+token(*(r["work_id"] for r in owners)), owners,
                 "Retrieve publisher-deposited lists for the next registered backward-citation frontier.")
        time.sleep(1)
    for owner in group:
        if owner.get("epmc"):
            europe(owner, "REP")
        elif not owner.get("doi") and owner.get("openalex"):
            openalex(owner)
        elif not owner.get("doi"):
            raise ValueError("No registered retrieval identifier for "+owner["work_id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("source", type=Path)
    prep.add_argument("dest", type=Path)
    prep.add_argument("--parents", required=True, type=int)
    get = commands.add_parser("fetch")
    get.add_argument("batch", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.source.resolve(), args.dest.resolve(), args.parents)
    else:
        retrieve(args.batch)
