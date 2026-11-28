"""Recover abstracts of the two older insect odometry studies missed by a DOI search."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

from run10_reference_records import doi,norm
from run11_source_limits import private_directory
from run12_reference_search import RUN,query
from search_run11_bibliography import CR,EPMC,OA,OUT,ROOT,TEMP,compatible_parent,digest,read,stamp,write
from storage import iter_logical

REPORT=TEMP/"reports/RUN-0012-insect-abstract-coverage.json"


def main():
    if REPORT.is_file():return
    initial=next(read(p) for p in sorted(OUT.glob("Q-RUN12-P6-INSECT-ODOMETRY-*.json")) if read(p)["status"]=="success")
    missing=set(initial["missing_identifiers"])
    works={doi(w["doi"]):w for w in iter_logical("works.jsonl") if doi(w.get("doi")) in missing}
    if not missing or set(works)!=missing:raise ValueError("Unexpected missing DOI inventory")
    every=[dict(work_id=w["work_id"],task_id="T-abstract-"+w["work_id"]) for w in works.values()]
    def get(provider):
        if provider=="crossref":
            url=CR
            params={"filter":",".join("doi:"+d for d in sorted(missing)),"rows":len(missing),"select":"DOI,title,author,abstract,published"}
        elif provider=="europepmc":
            url=EPMC+"search"
            params={"query":"SRC:MED AND ("+" OR ".join('TITLE:"'+w["canonical_title"]+'"' for w in works.values())+")",
                    "resultType":"core","format":"json","pageSize":30}
        else:
            url=OA
            params={"filter":"doi:"+"|".join(sorted(missing)),"per_page":len(missing),"select":"id,doi,display_name,publication_year,abstract_inverted_index"}
        cache=private_directory(RUN)/("insect-odometry-alt-"+provider+".json")
        def project(reply):
            if provider=="crossref":
                items=reply["message"]["items"];total=reply["message"]["total-results"]
            elif provider=="europepmc":
                items=reply["resultList"]["result"];total=reply["hitCount"]
            else:
                items=reply["results"];total=reply["meta"]["count"]
            if len(items)!=int(total):raise ValueError("Alternate bibliography page incomplete")
            obj=[];texts={}
            for row in items:
                if provider=="crossref":
                    key=doi(row["DOI"]);title=(row.get("title") or [""])[0];year=(row.get("published",{}).get("date-parts") or [[None]])[0][0]
                    authors=[a.get("family","") for a in row.get("author",[])];sid=key;body=row.get("abstract")
                elif provider=="europepmc":
                    key=doi(row.get("doi"));title=row["title"];year=row.get("pubYear");sid="MED:"+row["id"]
                    authors=[a.get("lastName","") for a in (row.get("authorList",{}).get("author") or [])];body=row.get("abstractText")
                else:
                    key=doi(row.get("doi"));title=row.get("display_name") or "";year=row.get("publication_year");sid=row["id"].rsplit("/",1)[-1];authors=[]
                    tokens=sorted((n,word) for word,positions in (row.get("abstract_inverted_index") or {}).items() for n in positions)
                    if [n for n,_ in tokens]!=list(range(len(tokens))):raise ValueError("Non-contiguous abstract positions")
                    body=" ".join(word for _,word in tokens)
                if key:
                    candidates=[key] if key in works and compatible_parent(title,[works[key]["canonical_title"]]) else []
                    matched="registered_doi_and_title"
                else:
                    candidates=[d for d,w in works.items() if norm(title)==norm(w["canonical_title"]) and str(w["year"])==str(year)
                                and authors and w["authors"] and norm(authors[0])==norm(w["authors"][0].get("family_name") or "")]
                    matched="complete_title_year_first_author"
                if len(candidates)!=1:continue
                d=candidates[0];w=works[d];record=dict(work_id=w["work_id"],work_key=w["work_key"],canonical_doi=d,source_identifier=sid,
                            source_doi=key or None,title=title,year=year,identity_basis=matched,abstract_sha256=sha256(body.encode()).hexdigest() if body else None)
                obj.append(record)
                if body:texts[d]=body
            if cache.exists():
                if read(cache)!=texts:raise ValueError("Private abstract cache changed")
            else:write(cache,texts)
            return dict(records=obj,visible_total=int(total),returned_count=len(obj),page_complete=True,unmatched_search_hits=int(total)-len(obj))
        return query("P6-INSECT-ALT-"+provider.upper(),provider,url,params,every,"Check old insect odometry abstracts via registered publisher metadata or precisely matched bibliographic titles.",project)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(get,("crossref","europepmc")))
    def found():return {r["canonical_doi"] for q in results for r in q.get("records",[]) if r.get("abstract_sha256")}
    if missing-found():results.append(get("openalex"))
    chosen={}
    for q in results:
        for r in q.get("records",[]):
            if r.get("abstract_sha256"):
                chosen.setdefault(r["canonical_doi"],dict(query_id=q["query_id"],source_id=q["source_id"],**r))
    raw=[OUT/(q["query_id"]+".json") for q in (initial,*results)]
    counts=dict(attempted_works=len(missing),recovered_abstracts=len(chosen),still_without_abstract=sorted(missing-set(chosen)))
    write(REPORT,dict(run_id=RUN,checked_at_utc=stamp(),counts=counts,selected=chosen,
                       reference_search=initial["query_id"],input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in raw}))
    print(counts,[(k,r["source_id"]) for k,r in chosen.items()],flush=True)


if __name__=="__main__":main()
