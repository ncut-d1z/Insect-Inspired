"""Fetch only bibliographic records, abstracts or reference/citing lists for the current run."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"KRESS":"10.1242/jeb.097436", "RAY":"10.7554/elife.102230", "SUNKARA":"10.7554/elife.04693"}
IDS = {"KRESS":"W-D3726e94bf3bda20c","RAY":"W-D343f06a3bc764bf6","SUNKARA":"W-R24649f4879cc831d"}
CONTACT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")


def facts(row):
    fields = ("id","source","pmid","pmcid","doi","title","authorString","authorName","authorList",
              "journalAbbreviation","journalTitle","issn","volume","issue","pageInfo","pubYear","pubType",
              "pubTypeList","firstPublicationDate","firstPage","lastPage","citationType")
    record = {k:row[k] for k in fields if k in row and k != "authorList"}
    if "authorList" in row:
        record["authors"] = []
        for author in row["authorList"].get("author",[]):
            a = {k:author[k] for k in ("fullName","firstName","lastName","initials","collectiveName","authorId") if k in author}
            affiliations = author.get("authorAffiliationDetailsList",{}).get("authorAffiliation",[])
            if affiliations:
                a["affiliations"] = [CONTACT.sub("", v["affiliation"]).strip(" .;,") for v in affiliations if v.get("affiliation")]
            record["authors"].append(a)
    if "journalInfo" in row:
        ji = row["journalInfo"]
        record["journal"] = {k:v for k,v in ji.get("journal",{}).items() if k in ("title","issn","essn","medlineAbbreviation")}
        record["issue_details"] = {k:ji[k] for k in ("volume","issue","dateOfPublication") if k in ji}
    # Keep the availability and fingerprint; abstract text is not republished.
    if row.get("abstractText"):
        record["abstract_available"] = True
        record["abstract_sha256"] = hashlib.sha256(row["abstractText"].encode()).hexdigest()
    return record


def search(target, kind, page=1):
    operation = f"Q-RUN09-BIB-{target}-{kind.upper()}-{page:03}"
    out = ROOT / "temp/query-results" / (operation+".json")
    if out.exists():
        return json.loads(out.read_bytes())
    doi, work = SOURCES[target], IDS[target]
    if kind == "identity":
        params = dict(query=f'DOI:"{doi}"',resultType="core",format="json",pageSize=100)
        path = "search"
        field, sub = "resultList","result"
    else:
        identity = search(target,"identity")
        matches = [row for row in identity["records"] if row.get("doi","").lower() == doi and row.get("source")=="MED"]
        if len(matches)!=1: raise ValueError("A unique PubMed bibliographic identifier is required")
        pmid = str(matches[0]["id"])
        if not pmid.isdigit(): raise ValueError("Invalid PubMed identifier")
        params=dict(format="json",page=page,pageSize=1000)
        path = "MED/"+pmid+"/"+kind
        field, sub = ("citationList","citation") if kind=="citations" else ("referenceList","reference")
    url=BASE+path+"?"+urlencode(params)
    started=stamp()
    receipt=dict(query_id=operation, run_id="RUN-0009", scope_id="SCOPE-0001", checkpoint_id="CP-0011",
                 entity_id=work,task_id="T-"+("metadata" if kind=="identity" else kind)+"-"+work, source_id="europepmc",
                 query_kind="bibliographic_"+kind,endpoint_or_url=url,raw_parameters=params,queried_at_utc=started,
                 page_index=page,external_request_count=1,cache_hit=False,license_note="Public bibliographic facts and author identifiers. Abstract text is represented only by availability and a digest.",
                 cutoff_at_utc="2026-11-26T05:24:08Z",records=[],visible_total=None,returned_count=None,page_complete=False,
                 cursor_in="*" if kind=="identity" else str(page),cursor_out=None,error_code=None,error_message=None)
    try:
        with urlopen(Request(url,headers={"Accept":"application/json","User-Agent":"Insect-Inspired-bibliography/1.1"}),timeout=45) as response:
            raw=response.read()
            receipt["http_status"]=response.status
        data=json.loads(raw)
        entries=data[field].get(sub,[])
        total=data["hitCount"]
        result=[facts(r) for r in entries]
        complete = total == len(entries) if kind=="identity" else (page-1)*1000+len(entries)==total
        if not complete and not entries: raise ValueError("Empty page before visible total")
        receipt.update(status="success",body_bytes=len(raw),body_sha256=hashlib.sha256(raw).hexdigest(),records=result,
                       visible_total=total,returned_count=len(entries),page_complete=complete,
                       cursor_out=None if complete else (str(page+1) if kind!="identity" else data.get("nextCursorMark")))
    except (OSError, ValueError, KeyError) as exc:
        receipt.update(status="error",error_code=str(exc.code) if isinstance(exc,HTTPError) else type(exc).__name__,error_message=str(exc))
    receipt["completed_at_utc"]=stamp()
    with out.open("xb") as sink:
        sink.write((json.dumps(receipt,indent=2,ensure_ascii=False)+"\n").encode())
    print(operation,receipt["status"],receipt["returned_count"],receipt["visible_total"],flush=True)
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target",choices=SOURCES)
    parser.add_argument("kind",choices=["identity","citations","references"])
    args=parser.parse_args()
    page=1
    while True:
        result=search(args.target,args.kind,page)
        if result["status"]!="success": raise SystemExit(result["error_message"])
        if result["page_complete"]: break
        if args.kind=="identity": raise SystemExit("Ambiguous DOI page; preserve cursor for identity review")
        page+=1
