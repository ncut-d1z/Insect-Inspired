"""Resume a Git-bound breadth-first frontier in small, independently publishable batches."""
import argparse
import hashlib
from pathlib import Path
import re
import time
from urllib.parse import quote

from run10_reference_records import doi, source_lists, token
from search_run10_references import ROOT, RUN, SCOPE, crossref, europe, fetch, read, write
from storage import iter_logical


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
    identifier=owner.get("openalex");registered=doi(owner.get("doi"));pmid=(owner.get("epmc") or "").removeprefix("MED:")
    if identifier and re.fullmatch(r"W[0-9]+",identifier):lookup=identifier
    elif registered:lookup="https://doi.org/"+quote(registered,safe="/")
    elif pmid.isdigit():lookup="pmid:"+pmid
    else:raise ValueError("No stable OpenAlex lookup for "+owner["work_id"])
    def project(data):
        observed=data["id"].rsplit("/",1)[-1]
        if not re.fullmatch(r"W[0-9]+",observed) or (identifier and observed!=identifier) or (registered and doi(data.get("doi"))!=registered):
            raise ValueError("OpenAlex parent changed identity")
        if not identifier and not registered and (data.get("ids",{}).get("pmid") or "").rsplit("/",1)[-1]!=pmid:
            raise ValueError("OpenAlex PMID does not match the submitted parent")
        ids = data["referenced_works"]
        records = [{"openalex": ident.rsplit("/",1)[-1]} for ident in ids]
        if any(not re.fullmatch(r"W[0-9]+", r["openalex"]) for r in records):
            raise ValueError("Invalid OpenAlex reference ID")
        return dict(records=records, source_bibliography={k:data.get(k) for k in ("id","doi","display_name","ids","publication_year")},
                    visible_total=len(ids), returned_count=len(records), page_complete=True)
    fetch("ROA-"+(identifier or "X"+token(owner["work_id"])), "openalex", "https://api.openalex.org/works/"+lookup,
          {"select":"id,doi,ids,display_name,publication_year,referenced_works"}, [owner],
          "Follow a recursively discovered bibliographic work by its registered OpenAlex ID.", project)


def retrieve(batch, start, count):
    all_parents = read(batch)["worklist"]
    if start < 0 or start >= len(all_parents) or (count is not None and count < 1):
        raise ValueError("Invalid position in the published batch")
    group = all_parents[start:start+count] if count is not None else all_parents[start:]
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


def editions():
    owners=[]
    for version in iter_logical("versions.jsonl"):
        wid=version["work_id"]
        if wid.startswith("W-R10-") and version["source"]["source_id"]=="openalex":
            owners.append(dict(work_id=wid,version_id=version["version_id"],openalex=version["identifiers"]["openalex"],task_id="T-metadata-"+wid))
    owners.sort(key=lambda x:x["openalex"])
    for start in range(0,len(owners),35):
        group=owners[start:start+35];wanted={o["openalex"] for o in group}
        def project(data):
            records=[]
            for item in data["results"]:
                loc=item.get("primary_location") or {}
                records.append(dict(source_identifier=item["id"].rsplit("/",1)[-1],doi=item.get("doi"),location_version=loc.get("version"),
                                    is_published=loc.get("is_published"),location_source=(loc.get("source") or {}).get("display_name")))
            actual={r["source_identifier"] for r in records}
            if len(records)!=data["meta"]["count"] or len(actual)!=len(records) or actual-wanted:raise ValueError("OpenAlex edition identity mismatch")
            return dict(records=records,visible_total=len(records),returned_count=len(records),page_complete=True,missing_identifiers=sorted(wanted-actual))
        fetch("ED-"+token(*sorted(wanted)),"openalex","https://api.openalex.org/works",
              {"filter":"openalex_id:"+"|".join(sorted(wanted)),"per_page":len(group),"select":"id,doi,primary_location"},group,
              "Check explicitly indexed publication versions for bibliographic manifestations recovered via OpenAlex.",project)
        time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("source", type=Path)
    prep.add_argument("dest", type=Path)
    prep.add_argument("--parents", required=True, type=int)
    get = commands.add_parser("fetch")
    get.add_argument("batch", type=Path)
    get.add_argument("--start", type=int, default=0)
    get.add_argument("--count", type=int)
    commands.add_parser("editions")
    fallback=commands.add_parser("supplement")
    fallback.add_argument("batch",type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.source.resolve(), args.dest.resolve(), args.parents)
    elif args.mode == "fetch":
        retrieve(args.batch, args.start, args.count)
    elif args.mode == "supplement":
        parents=read(args.batch)["worklist"];acquired=set();indexed=set()
        for owner,q,entries,_,_ in source_lists(parents):
            if entries:acquired.add(owner["work_id"])
            if q["source_id"]=="openalex":indexed.add(owner["work_id"])
        for parent in parents:
            if parent["work_id"] not in acquired|indexed:
                openalex(parent);time.sleep(1)
    else:
        editions()
