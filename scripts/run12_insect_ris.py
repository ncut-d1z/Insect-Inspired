"""Check the publisher's downloadable bibliographic citations of the two older odometry studies."""
import re
from hashlib import sha256
from urllib.parse import quote

from run10_reference_records import doi
from run11_source_limits import private_directory
from run12_insect_recovery import REPORT as PREVIOUS
from run12_reference_search import RUN,query
from search_run11_bibliography import OUT,ROOT,TEMP,compatible_parent,digest,read,stamp,write
from storage import iter_logical

REPORT=TEMP/"reports/RUN-0012-insect-publisher-coverage.json"


def ris_fields(body):
    text=body.decode("utf-8-sig")
    if not re.search(r"(?m)^TY  -",text) or not re.search(r"(?m)^ER  -",text):
        raise ValueError("Publisher endpoint did not deliver a bibliographic RIS record")
    fields={};key=None
    for line in text.splitlines():
        match=re.match(r"^([A-Z0-9]{2})  -\s?(.*)$",line)
        if match:
            key=match[1]
            fields.setdefault(key,[]).append(match[2])
        elif key and line.strip():
            fields[key][-1]+=" "+line.strip()
    return fields


def main():
    if REPORT.is_file():return
    previous=read(PREVIOUS);missing=set(previous["counts"]["still_without_abstract"])
    works={doi(w["doi"]):w for w in iter_logical("works.jsonl") if doi(w.get("doi")) in missing}
    if set(works)!=missing:raise ValueError("Bibliographic lookup subjects changed")
    subjects=[];receipts={PREVIOUS.relative_to(ROOT).as_posix():digest(PREVIOUS)}
    for key,w in sorted(works.items()):
        suffix=key.rsplit("/",1)[-1].upper()
        def project(fields):
            identifiers={doi(v) for v in fields.get("DO",[]) if v}
            titles=fields.get("TI") or fields.get("T1") or []
            if identifiers!={key} or not any(compatible_parent(t,[w["canonical_title"]]) for t in titles):
                raise ValueError("Publisher citation DOI or title differs")
            abstracts=fields.get("AB") or fields.get("N2") or []
            if len(abstracts)>1:raise ValueError("Multiple abstracts need disambiguation")
            body=abstracts[0].strip() if abstracts else ""
            cache=private_directory(RUN)/("insect-publisher-"+suffix+".json")
            if cache.is_file():
                if read(cache)!=body:raise ValueError("Publisher abstract changed")
            else:write(cache,body)
            return dict(records=[dict(work_id=w["work_id"],work_key=w["work_key"],source_identifier=key,title=titles[0],
                            publication_year=fields.get("PY") or fields.get("Y1"),authors=fields.get("AU",[]),
                            abstract_sha256=sha256(body.encode()).hexdigest() if body else None)],visible_total=1,returned_count=1,page_complete=True)
        q=query("P6-INSECT-RIS-"+suffix,"publisher","https://citation-needed.springer.com/v2/references/"+quote(key,safe="/"),
                {"format":"refman","flavour":"citation"},[dict(work_id=w["work_id"],task_id="T-abstract-"+w["work_id"])],
                "Check only the publisher's downloadable bibliographic RIS record and its abstract field.",project,decode=ris_fields,
                accept="application/x-research-info-systems, text/plain;q=0.9")
        p=OUT/(q["query_id"]+".json");receipts[p.relative_to(ROOT).as_posix()]=digest(p)
        subjects.append(dict(canonical_doi=key,work_id=w["work_id"],work_key=w["work_key"],source_id=q["source_id"],
                             query_id=q["query_id"],source_status=q["status"],records=q.get("records",[])))
    recovered=sum(any(x["abstract_sha256"] for x in r["records"]) for r in subjects)
    write(REPORT,dict(run_id=RUN,checked_at_utc=stamp(),items=subjects,counts=dict(checked=len(subjects),published_abstracts=recovered),
          input_receipts=receipts))
    print([(r["work_key"],r["source_status"],bool(r["records"] and r["records"][0]["abstract_sha256"])) for r in subjects],flush=True)


if __name__=="__main__":main()
