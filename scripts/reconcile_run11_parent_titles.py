"""Reconcile the two truncated/translated parent titles against independent bibliographic identities."""
from copy import deepcopy
from pathlib import Path
from run10_reference_records import doi,norm
from run11_reference_inventory import BATCHES,OA,OUT,ROOT,SUPPLEMENT,TEMP,WIDTH,digest,literal_project,manifest,owners_input,queue_inputs,read,request,stamp,write


def main():
    queue,titles=queue_inputs()
    crp=OUT/"Q-RUN11-PARENT-IDENTITY-CROSSREF-A1.json";epp=OUT/"Q-RUN11-PARENT-IDENTITY-EPMC-A1.json"
    cr={doi(r["DOI"]):r for r in read(crp)["records"]};ep={r["id"]:r for r in read(epp)["records"]}
    reviewed=[]
    for ordinal in (1538,2341):
        owner=queue[ordinal-1];wid=owner["work_id"];start=(ordinal-1)//WIDTH*WIDTH;end=min(start+WIDTH,len(queue));label=f"{start+1:04}-{end:04}"
        mp,m=manifest(start,end);orig=SUPPLEMENT/(label+".json");sup=deepcopy(read(orig));row=m["worklist"][ordinal-start-1]
        ex=sup["parents"][ordinal-start-1];d=owner["doi"];pmid=owner["epmc"].removeprefix("MED:")
        c=cr[d];e=ep[pmid];j=e["journalInfo"];assert doi(e["doi"])==d and c["page"]==e["pageInfo"] and c["volume"]==j["volume"]
        assert c["published"]["date-parts"][0][0]==int(e["pubYear"]) and norm(e["title"])==norm(titles[wid][0])
        names=[p["family"] for p in c["author"]];epnames=[p.get("lastName") for p in e["authorList"]["author"]]
        assert len(names)==len(epnames) and names[0]==epnames[0] and names[-1]==epnames[-1]
        if ordinal==1538:assert e["title"].lower().startswith(c["title"][0].lower()+":")
        else:assert e["language"]=="ger" and e["title"].startswith("[") and c["title"][0].startswith("Vergleichende Skalierung")
        flags=ex["excluded_parent_identities"];assert {r["source_id"] for r in flags}=={"crossref","openalex"}
        oa=next(r for r in flags if r["source_id"]=="openalex")
        oq=read(OUT/(oa["query_id"]+".json"));ident=oa["identifier"];entry=next(r for r in oq["records"] if r["source_identifier"]==ident)
        assert entry["pmid"]==pmid and doi(entry["doi"])==d and norm(entry["parent_title"])==norm(c["title"][0])
        literal=request(f"RAW-{start+1:04}-{ident}","openalex",OA+"/"+ident+"/references",{},owners_input([owner]),
                       "Retrieve the verified parent reference list after resolving a shortened or translated title.",literal_project)
        qids=[r["query_id"] for r in flags];evidence=[crp,epp,OUT/(oa["query_id"]+".json"),OUT/(literal["query_id"]+".json")]
        ex.update(excluded_parent_identities=[],prior_title_flags=flags,certified_parent_queries=qids,openalex_parent=ident,openalex_literal_query=literal["query_id"])
        sup["supersedes"]=orig.relative_to(ROOT).as_posix();sup["supersedes_sha256"]=digest(orig);sup["updated_at_utc"]=stamp()
        sup["receipts"].update({p.relative_to(ROOT).as_posix():digest(p) for p in evidence})
        sup["counts"]["excluded_parent_identifiers"]-=len(flags);sup["counts"]["literal_requests_bound"]=sup["counts"].get("literal_requests_bound",0)+1
        sup["counts"]["literal_positions"]=sup["counts"].get("literal_positions",0)+len(literal.get("records",[]))
        dest=SUPPLEMENT/(label+"-reconciled.json")
        if not dest.exists():write(dest,sup)
        reviewed.append(dict(queue_position=ordinal,work_id=wid,work_key=owner["work_key"],task_id=owner["task_id"],
                   doi=d,pmid=pmid,openalex=ident,registered_title=c["title"][0],indexed_title=e["title"],registered_byline=names,indexed_byline=epnames,
                   page=c["page"],volume=c["volume"],year=e["pubYear"],correction="short_title" if ordinal==1538 else "original_and_translated_titles",
                   inputs={p.relative_to(ROOT).as_posix():digest(p) for p in evidence},reconciled_manifest=dest.relative_to(ROOT).as_posix()))
    path=TEMP/"reports/RUN-0011-parent-identity-review.json"
    if not path.exists():write(path,dict(run_id="RUN-0011",reviewed_at_utc=stamp(),items=reviewed,unrelated_yough_doi_exclusion_preserved=True))
    print([(r["work_key"],r["correction"]) for r in reviewed],flush=True)


if __name__=="__main__":main()
