"""Check the cited version in registered bibliographies for pre-VOR indexed citations."""
import argparse
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from search_run9_bibliography import ROOT, stamp

TEMP=ROOT/"temp"
INPUT=TEMP/"query-results/Q-RUN09-BIB-RAY-LIST-METADATA-001.json"
TARGET="W-D343f06a3bc764bf6"
WORK_DATE="2025-07-21"
TASK="T-citations-"+TARGET
VERSION_DOIS={"10.1101/2020.04.04.024703":"V-W-D6538264ebfa49876-01",
              "10.7554/elife.102230.1":"V-CP4-Rayshubskiy-2024-reviewed-preprint",
              "10.7554/elife.102230":"V-W-D343f06a3bc764bf6-01"}
DOI_PATTERN=re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+",re.I)


def logical(name):
    m=json.loads((TEMP/"partitions/manifest.json").read_bytes())
    for p in m["datasets"].get(name+".jsonl",{"parts":[{"path":name+".jsonl"}]})["parts"]:
        with (TEMP/p["path"]).open(encoding="utf-8") as f:
            for line in f: yield json.loads(line)


def known_dois(value):
    candidates=DOI_PATTERN.findall(html.unescape(value).lower())
    return sorted({d for d in VERSION_DOIS if any(token==d or token.rstrip(".,;)")==d for token in candidates)})


def candidates():
    entries=json.loads(INPUT.read_bytes())["records"]
    return sorted((r for r in entries if r["firstPublicationDate"]<WORK_DATE),key=lambda r:(r["firstPublicationDate"],r["doi"]))


def cached():
    known_sources={r["doi"].lower():r["work_id"] for r in logical("works") if r.get("doi")}
    citing={known_sources[r["doi"].lower()] for r in candidates() if r["doi"].lower() in known_sources}
    verified=defaultdict(list)
    for row in logical("reference-occurrences"):
        if row["citing_work_id"] in citing:
            found=known_dois(row["raw_reference"])
            if found:
                verified[row["citing_work_id"]].append(dict(occurrence_id=row["occurrence_id"],version_dois=found))
    return {doi:verified[wid] for doi,wid in known_sources.items() if wid in verified}


def run_batch(number):
    records=candidates()
    origin=cached()
    needed=[r for r in records if r["doi"].lower() not in origin]
    portion=needed[(number-1)*5:number*5]
    if not portion:return
    qid=f"Q-RUN09-BIB-RAY-CROSSREF-DEPOSITS-{number:03}"
    out=TEMP/"query-results"/(qid+".json")
    if out.exists():
        print("retained",qid,flush=True);return
    dois=[r["doi"].lower() for r in portion]
    params={"filter":",".join("doi:"+d for d in dois),"rows":len(dois)}
    url="https://api.crossref.org/works?"+urlencode(params)
    start=stamp()
    rec=dict(query_id=qid,source_id="crossref",entity_id=TARGET,task_id=TASK,run_id="RUN-0009",scope_id="SCOPE-0001",
             checkpoint_id="CP-0011",queried_at_utc=start,endpoint_or_url=url,raw_parameters=params,query_kind="version_in_registered_references",
             page_index=1,cursor_in=None,cursor_out=None,external_request_count=1,cache_hit=False,requested_dois=dois,
             license_note="DOI registration and reference-list metadata only. No article or attachment fetched.",
             status="error",visible_total=None,returned_count=None,page_complete=False,records=[],error_code=None,error_message=None,
             rerun_reason="The projected metadata endpoint returned HTTP 400; retrieve the registry metadata with the DOI filter." if number==1 else None)
    try:
        with urlopen(Request(url,headers={"Accept":"application/json","User-Agent":"Insect-Inspired-bibliography/1.1"}),timeout=50) as res:
            raw=res.read();rec["http_status"]=res.status
        data=json.loads(raw)["message"]
        stripped=[]
        for item in data["items"]:
            refs=item.get("reference",[])
            matched=[]
            for index,ref in enumerate(refs,1):
                found=known_dois(str(ref.get("DOI",""))+" "+str(ref.get("unstructured","")))
                if found:
                    matched.append(dict(position=index,reference_key=ref.get("key"),version_dois=found,
                        version_ids=[VERSION_DOIS[d] for d in found],source_field="DOI" if known_dois(str(ref.get("DOI",""))) else "unstructured"))
            stripped.append(dict(doi=item["DOI"].lower(),title=item.get("title",[]),declared_reference_count=item.get("reference-count"),
                                 deposited_reference_entries=len(refs),matched_references=matched))
        if len({x["doi"] for x in stripped})!=len(stripped) or set(x["doi"] for x in stripped)-set(dois):raise ValueError("Unexpected DOI filter response")
        rec.update(status="success",body_sha256=hashlib.sha256(raw).hexdigest(),body_bytes=len(raw),visible_total=data["total-results"],
                   returned_count=len(stripped),page_complete=data["total-results"]==len(stripped),records=stripped)
    except (OSError,KeyError,ValueError) as exc:
        rec.update(error_code=str(getattr(exc,"code",type(exc).__name__)),error_message=str(exc))
        if isinstance(exc,HTTPError):
            rec["provider_error_detail"]=exc.read(2000).decode("utf-8","replace")
    rec["completed_at_utc"]=stamp()
    out.write_bytes((json.dumps(rec,ensure_ascii=False,indent=2)+"\n").encode())
    print(qid,rec["status"],rec["returned_count"],len(dois),"source version matches",sum(bool(r["matched_references"]) for r in rec["records"]),flush=True)
    if rec["status"]!="success": raise SystemExit(rec["error_message"])


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("batch",type=int,help="1-based input batch; 0 reports the local cache inventory")
    n=p.parse_args().batch
    if n==0:
        old=cached();count=len(candidates());print(json.dumps(dict(candidates=count,cache=old,external_batches=(count-len(old)+4)//5)),flush=True)
    elif n>0:run_batch(n)
    else:p.error("Use a nonnegative batch number")
