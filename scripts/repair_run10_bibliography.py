"""Correct RUN10 display keys and five publication-time affiliation role labels, preserving their evidence."""
import argparse
from collections import Counter
from copy import deepcopy

from integrate_run10_references import Batch, CP, ROOT, RUN, SCOPE, TEMP, apply_batch, file_hash, read, require


def repair(apply):
    name="catalog-corrections"
    report_file=f"temp/reports/RUN-0010-integration-{name}.json"
    if (ROOT/report_file).is_file():return
    batch=Batch();keys=batch.bibliographic_keys()
    review_file=TEMP/"reports/RUN-0010-abstract-affiliation-review.json"
    batch.input_paths.add(review_file);roles=[]
    for item in read(review_file)["items"]:
        wid=item["work_id"];work=batch.works[wid]
        for link in item["publication_affiliation_links"]:
            pid=work["authors"][link["byline_position"]-1]["person_id"];old=batch.people[pid];person=deepcopy(old)
            matched=[a for a in person["affiliation_history"] if a["work_id"]==wid and a["org_id"]==link["org_id"] and a["role"]=="publication_byline"]
            require(len(matched)==1 and any(link["affiliation"] in loc["evidence_note"] for loc in matched[0]["evidence_locator"]),"Unbound byline role correction")
            matched[0]["role"]="byline_affiliation_at_publication"
            batch.modify("authors",old,person);batch.people[pid]=person
            roles.append(dict(work_id=wid,person_id=pid,org_id=link["org_id"],before="publication_byline",after=matched[0]["role"]))
    require(len(roles)==5 and sum(k["reason"]=="retired_key_collision" for k in keys)==2,"Unexpected targeted correction count")
    for key in keys:require(not batch.retired.get(key["corrected_key"]),"Reallocated retired key")
    run=read(TEMP/"runs/RUN-0010.json");old_queue=ROOT/run["next_backward_frontier"];batch.input_paths.add(old_queue)
    frontier=read(old_queue);frontier["worklist"]=[{**r,"work_key":batch.works[r["work_id"]]["work_key"]} for r in frontier["worklist"]]
    frontier["parent_batch"]=report_file;frontier["reconciled_from"]=old_queue.relative_to(ROOT).as_posix()
    new_queue=f"temp/reports/RUN-0010-frontier-after-{name}.json";run["next_backward_frontier"]=new_queue
    adds={k:list(v.values()) for k,v in batch.adds.items() if v}
    report=dict(run_id=RUN,scope_id=SCOPE,target_checkpoint=CP,batch=name,updated_at_utc=batch.now,maintenance_only=True,
                counts={k:len(v) for k,v in adds.items()},coverage=[],new_research_works=0,new_edges=0,new_affiliations=0,
                bibliographic_key_corrections=keys,affiliation_role_corrections=roles,
                input_receipts={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(batch.input_paths)})
    print(dict(keys=dict(Counter(k["reason"] for k in keys)),roles=len(roles),edge_endpoint_updates=len(batch.changes["citation-edges"])),flush=True)
    if apply:apply_batch(dict(batch.changes),adds,report,report_file,{new_queue:frontier,"temp/runs/RUN-0010.json":run})


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--apply",action="store_true");repair(parser.parse_args().apply)
