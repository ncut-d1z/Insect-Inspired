"""Resolve the publication institutions and check selected forward candidates against deposited bibliographies."""
import argparse
from collections import defaultdict

from run10_reference_records import doi, request_identities, token
from run12_evidence_search import identities
from run12_reference_search import RUN, query
from search_run11_bibliography import OUT, ROOT, TEMP, compatible_parent, deposited, digest, read, stamp, write

SOURCE=OUT/"Q-RUN12-P56-MOTION-ABSTRACTS-A1.json"
INSTITUTIONS={"22036184":"Australian National University, Canberra, Australia","11954696":"Brown University, Providence, United States",
              "11163855":"York University, Toronto, Canada","9472485":"Boston University, Boston, United States",
              "8917793":"University of Minnesota Twin Cities, Minneapolis, United States","8724666":"Ruhr University Bochum, Germany"}
SELECTION={"22036184":("27053748","24812052","28429124"),"11163855":("14600796","28570860")}
FORWARD=TEMP/"reports/RUN-0012-forward-pairs.json"


def affiliations():
    data=read(SOURCE)
    for row in data["records"]:
        pid=row["id"]
        if pid not in INSTITUTIONS:continue
        if not row["authors"][0].get("affiliations"):raise ValueError("No byline affiliation")
        def project(data):
            rows=[]
            for i in data["items"]:
                org=i["organization"]
                rows.append(dict(source_identifier=org["id"],names=org["names"],status=org["status"],types=org["types"],chosen=i["chosen"]))
            return dict(records=rows,returned_count=len(rows),visible_total=len(rows),page_complete=True)
        wid=row["work_id"];name=INSTITUTIONS[pid]
        q=query("P5-ROR-"+pid,"ror","https://api.ror.org/v2/organizations",{"affiliation":name},
                [dict(work_id=wid,task_id="T-affiliations_projects-"+wid)],"Check an institution explicitly named in a publication byline.",project)
        print(pid,[(r["source_identifier"],next(n["value"] for n in r["names"] if "ror_display" in n["types"])) for r in q.get("records",[]) if r["chosen"]],flush=True)


def pairs():
    if FORWARD.exists():
        snap=read(FORWARD)
        if all(digest(ROOT/k)==v for k,v in snap["input_receipts"].items()):return
        raise ValueError("Previous forward result changed")
    papers=identities();inputs={};owners={};wanted={}
    def bind(path):
        inputs[path.relative_to(ROOT).as_posix()]=digest(path)
        return read(path)
    for seed,ids in SELECTION.items():
        wid=papers[seed][0]["work_id"]
        owners[seed]=dict(work_id=wid,task_id="T-citations-"+wid)
        q=bind(OUT/f"Q-RUN12-P4-CITATIONS-{seed}-P1-A1.json")
        for pid in ids:
            row,=[r for r in q["records"] if r["source"]=="MED" and str(r["id"])==pid]
            wanted[pid]=(seed,row)
    def metaq(key,*args,**kw):return query("P4-"+key,*args,**kw)
    m=request_identities(["MED:"+pid for pid in wanted],"europepmc",list(owners.values()),metaq)
    bind(OUT/(m["query_id"]+".json"))
    if m["status"]!="success":raise ValueError("Citing identity response unavailable")
    items={r["epmc"].split(":")[1]:r for r in m["records"]}
    deposited_cache={}
    needed={doi(r["doi"]) for r in items.values() if r["doi"]}
    for pat in ("Q-RUN10-*DEP*.json","Q-RUN11-*DEP*.json","Q-RUN12-B*-DEP*.json"):
        for p in sorted(OUT.glob(pat)):
            q=read(p)
            if q.get("source_id")!="crossref" or q["status"]!="success":continue
            for r in q["records"]:
                ident=doi(r.get("DOI"))
                if ident in needed and r.get("reference") and len(r["reference"])==r.get("reference-count"):
                    deposited_cache.setdefault(ident,(p,r))
    candidates=[]
    for pid,r in items.items():
        if r.get("doi") and doi(r["doi"]) not in deposited_cache:
            candidates.append({**owners[wanted[pid][0]],"doi":r["doi"]})
    if candidates:
        q=deposited("P4-BACK-DEP-PAIRS",candidates,query);p=OUT/(q["query_id"]+".json");bind(p)
        for r in q.get("records",[]):deposited_cache[doi(r["DOI"])]=(p,r)
    checks=[]
    for pid,(seed,fw) in wanted.items():
        root,paper=papers[seed];mrow=items.get(pid)
        row=dict(target_pmid=seed,citing_pmid=pid,cited_work_id=paper["work_id"],forward_query=f"Q-RUN12-P4-CITATIONS-{seed}-P1-A1",
                 citing_metadata_query=m["query_id"],citing_metadata_identifier="MED:"+pid,matches=[],citation_role="unknown")
        d=doi(mrow.get("doi")) if mrow else None
        if d and d in deposited_cache and compatible_parent(mrow["title"],[fw["title"]]) and mrow["date"] and mrow["date"]<"2026-11-26":
            p,record=deposited_cache[d];bind(p);row.update(deposited_query=p.stem,citing_doi=d,source_declared=record.get("reference-count"))
            if any(compatible_parent(t,[mrow["title"]]) for t in record.get("title",[])):
                for idx,ref in enumerate(record.get("reference",[]),1):
                    if doi(ref.get("DOI"))!=doi(paper["doi"]) or not paper.get("doi"):continue
                    if ref.get("article-title") and not compatible_parent(ref["article-title"],[paper["canonical_title"],*paper["title_variants"]]):continue
                    row["matches"].append(dict(position=idx,reference=ref))
        row["status"]="forward_and_deposited_doi_match" if row["matches"] else "reference_list_verification_open"
        checks.append(row)
    write(FORWARD,dict(run_id=RUN,created_at_utc=stamp(),selection="Three PMID-bound registered candidates and two topic-related forward candidates, with retained complete source pages for the remaining candidates.",items=checks,input_receipts=inputs))
    print([(r["citing_pmid"],r["target_pmid"],r["status"],[x["position"] for x in r["matches"]]) for r in checks],flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("affiliations","pairs"));a=p.parse_args()
    if a.action=="pairs":pairs()
    else:affiliations()
