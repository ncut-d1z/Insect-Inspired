"""Fetch one metadata-and-abstract page for previously unsummarized insect odometry Works."""
from run10_reference_records import doi
from run11_source_limits import private_directory
from run12_reference_search import RUN, query
from search_run9_bibliography import facts
from search_run11_bibliography import EPMC, compatible_parent, read, write
from storage import iter_logical

DOIS = ("10.1242/jeb.200.19.2513", "10.1007/bf00243395", "10.1242/jeb.203.7.1113",
        "10.1007/bf00192324", "10.1242/jeb.070540", "10.1007/s00359-003-0448-5",
        "10.1242/jeb.102897", "10.1016/j.beproc.2012.09.013")


def main():
    matches=[w for w in iter_logical("works.jsonl") if doi(w.get("doi")) in DOIS]
    works={doi(w["doi"]):w for w in matches}
    if len(works)!=len(matches) or set(works)!=set(DOIS):
        raise ValueError("Target DOI set and canonical insect studies disagree")
    if any(w["abstract_items"] for w in matches):
        raise ValueError("An original-language or summarized abstract already exists")
    owners=[dict(work_id=w["work_id"],task_id="T-abstract-"+w["work_id"]) for w in matches]
    params={"query":"SRC:MED AND ("+" OR ".join('DOI:"'+d+'"' for d in DOIS)+")",
            "resultType":"core","format":"json","pageSize":len(DOIS)}
    cache=private_directory(RUN)/"insect-odometry-abstracts.json"
    def project(reply):
        raw=reply["resultList"]["result"];records=[];texts={};seen=set()
        if len(raw)!=int(reply["hitCount"]):
            raise ValueError("Metadata page incomplete")
        for r in raw:
            d=doi(r.get("doi"))
            if d not in works or d in seen or r.get("source")!="MED":
                raise ValueError("Unbound or duplicate source DOI")
            w=works[d]
            if not compatible_parent(r["title"],[w["canonical_title"],*w["title_variants"]]):
                raise ValueError("DOI and canonical title disagree")
            seen.add(d);record=facts(r)
            record.update(work_id=w["work_id"],work_key=w["work_key"],parent_title_checked=True)
            if r.get("abstractText"):texts[r["id"]]=r["abstractText"]
            records.append(record)
        if cache.exists():
            if read(cache)!=texts:raise ValueError("Abstract specifically bound to earlier receipt changed")
        else:write(cache,texts)
        return dict(records=records,visible_total=len(raw),returned_count=len(records),page_complete=True,missing_identifiers=sorted(set(DOIS)-seen))
    receipt=query("P6-INSECT-ODOMETRY","europepmc",EPMC+"search",params,owners,
                  "Consult bibliographic metadata and published abstracts of honeybee, stingless bee and desert ant odometry and bumblebee learning flight.",project)
    if receipt["status"]!="success":raise ValueError("Insect abstract source unavailable")
    print([(r["id"],r["work_key"],bool(r.get("abstract_sha256"))) for r in receipt["records"]],receipt["missing_identifiers"],flush=True)


if __name__=="__main__":
    main()
