"""Persist the queue position and evidence locator for every distinct source position, including unidentified items."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from run11_reference_inventory import ROOT, TEMP, SUPPLEMENT, WIDTH, digest, manifest, queue_inputs, raw_ids, read, source_pages, stamp, write

INDEX=TEMP/"reports/RUN-0011-reference-index"


def build(start,queue,titles):
    group=queue[start:start+WIDTH];end=start+len(group);path,base=manifest(start,end);label=f"{start+1:04}-{end:04}"
    supplement=SUPPLEMENT/(label+".json");ext=read(supplement);assert digest(path)==ext["base_sha256"]
    for f,h in ext["receipts"].items():assert digest(ROOT/f)==h
    INDEX.mkdir(exist_ok=True)
    rows_path=INDEX/(label+".jsonl");summary_path=INDEX/(label+".json")
    if summary_path.exists():
        s=read(summary_path);assert digest(rows_path)==s["position_file_sha256"] and digest(supplement)==s["supplement_sha256"];return
    lines=[];parents=[];tot=Counter();scope={}
    for o,b,x in zip(group,base["worklist"],ext["parents"],strict=True):
        assert o["work_id"]==b["work_id"]==x["work_id"]
        counts=Counter();channels=Counter();index_evidence=Counter()
        for q,kind,refs,parent,positions in source_pages(o,b,titles[o["work_id"]],x):
            source=q["source_id"];qid=q["query_id"];scope[qid]=q["endpoint_or_url"]
            for pos,r in zip(positions,refs,strict=True):
                ids=raw_ids(r,source)
                channels[kind]+=1;counts["positions"]+=1
                counts["with_candidate_identifier" if ids else "without_candidate_identifier"]+=1
                support=kind
                if kind=="literal_bibliography":
                    support="original_text" if r.get("raw_reference_string") else "raw_doi_only" if r.get("raw_doi") else "index_match_only" if r.get("openalex") else "empty_source_position"
                    index_evidence[support]+=1
                    if not r.get("openalex"):counts["openalex_unmatched_positions"]+=1
                raw={k:v for k,v in r.items() if k!="openalex"} if kind=="literal_bibliography" else r
                encoded=json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
                entry=dict(queue_position=b["queue_position"],source=qid,source_parent=parent,position=pos,kind=support,
                           raw_sha256=hashlib.sha256(encoded).hexdigest(),candidate_identifiers=ids)
                lines.append((json.dumps(entry,ensure_ascii=False,separators=(",",":"))+"\n").encode())
        parents.append(dict(queue_position=b["queue_position"],work_id=o["work_id"],work_key=o["work_key"],task_id=o["task_id"],
                            counts=dict(counts),positions_by_channel=dict(channels),openalex_fields=dict(index_evidence),
                            excluded_parent_identities=x["excluded_parent_identities"]))
        tot.update(counts)
    data=b"".join(lines)
    if rows_path.exists():
        if rows_path.read_bytes()!=data:raise ValueError("Previously staged source positions changed")
    else:
        part=rows_path.with_suffix(".part")
        with part.open("xb") as f:f.write(data)
        part.rename(rows_path)
    write(summary_path,dict(run_id="RUN-0011",start_index=start,next_index=end,created_at_utc=stamp(),parent_count=len(parents),
                  counts=dict(tot),parents_with_positions=sum(r["counts"].get("positions",0)>0 for r in parents),
                  primary_manifest=path.relative_to(ROOT).as_posix(),primary_sha256=digest(path),
                  supplement_manifest=supplement.relative_to(ROOT).as_posix(),supplement_sha256=digest(supplement),
                  position_file=rows_path.relative_to(ROOT).as_posix(),position_file_sha256=digest(rows_path),sources=scope,parents=parents))
    print(label,len(group),dict(tot),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("start",type=int);a=p.parse_args()
    q,t=queue_inputs();build(a.start,q,t)
