"""Read the funding fields deposited with topical Works, separately from claims about project membership."""
from copy import deepcopy

from integrate_run10_references import source
from run10_reference_records import doi
from run12_reference_search import CP, RUN, query
from run12_reviews import ABSTRACTS
from search_run11_bibliography import CR, OUT, ROOT, SCOPE, TEMP, compatible_parent, digest, read, stamp, write
from storage import iter_logical

SCIENCE=TEMP/"reports/RUN-0012-scientific-integration.json"
REPORT=TEMP/"reports/RUN-0012-publication-funding.json"
KEY="P5-DEPOSITED-FUNDING"


def fetch():
    if REPORT.is_file():return
    wanted={r["work_id"] for r in read(ABSTRACTS)["items"]}|{r["citing_work_id"] for r in read(SCIENCE)["forward"]}
    works={doi(w["doi"]):w for w in iter_logical("works.jsonl") if w["work_id"] in wanted}
    if not all(works) or len(works)!=len(wanted):raise ValueError("Missing or ambiguous publication DOI")
    owners=[dict(work_id=w["work_id"],task_id="T-affiliations_projects-"+w["work_id"]) for d,w in sorted(works.items())]
    def project(data):
        msg=data["message"];items=msg["items"]
        if len(items)!=msg["total-results"] or len({doi(r["DOI"]) for r in items})!=len(items):raise ValueError("Incomplete grant metadata query")
        output=[]
        for x in items:
            ident=doi(x["DOI"]);w=works[ident]
            if not any(compatible_parent(t,[w["canonical_title"],*w["title_variants"]]) for t in x.get("title",[])):raise ValueError("Funding parent title disagrees")
            funders=[{k:f[k] for k in ("name","DOI","award","award-info","id","doi-asserted-by") if k in f} for f in x.get("funder",[])]
            output.append(dict(source_identifier=ident,work_id=w["work_id"],title=x["title"],funders=funders))
        return dict(records=output,visible_total=len(items),returned_count=len(items),page_complete=True,missing_identifiers=sorted(set(works)-{r["source_identifier"] for r in output}))
    q=query(KEY,"crossref",CR,{"filter":",".join("doi:"+d for d in sorted(works)),"rows":len(works),"select":"DOI,title,funder"},owners,
            "Check only publication metadata for depositing-member funder names and award identifiers.",project)
    if q["status"]!="success":raise ValueError("Funding deposit metadata not retrieved")
    items=[];awards=set();named=set()
    for r in q["records"]:
        fs=[]
        for f in r["funders"]:
            agency=f.get("name") or None
            ids=list(dict.fromkeys(str(v) for v in f.get("award",[]) if v))
            if agency:named.add(agency)
            for i in ids:awards.add((agency,i))
            fs.append(dict(deposited_funder=agency,deposited_funder_doi=doi(f.get("DOI")) or None,award_identifiers=ids,
                           award_info=f.get("award-info",[])))
        items.append(dict(work_id=r["work_id"],work_key=works[r["source_identifier"]]["work_key"],doi=r["source_identifier"],
                    deposited_funding=fs,status="publication_funding_metadata" if fs else "no_funder_list_in_this_deposit"))
    source_file=OUT/(q["query_id"]+".json")
    counts=dict(works_checked=len(items),works_with_funder_metadata=sum(bool(r["deposited_funding"]) for r in items),
                distinct_deposited_funder_names=len(named),distinct_funder_award_pairs=len(awards),new_confirmed_projects=0)
    write(REPORT,dict(run_id=RUN,scope_id=SCOPE,observed_at_utc=q["completed_at_utc"],query_id=q["query_id"],source_sha256=digest(source_file),
         counts=counts,items=items,boundary="资助方和编号仅按本篇文献登记元数据记录。项目正式名称、执行人员与成果归属需有各自来源。"))
    print(counts,[(r["work_key"],r["deposited_funding"]) for r in items if r["deposited_funding"]],flush=True)


def register(ledger):
    study=read(REPORT);p=OUT/(study["query_id"]+".json");q=read(p)
    if digest(p)!=study["source_sha256"]:raise ValueError("Funding assertion source changed")
    rows={r["work_id"]:r for r in study["items"] if r["deposited_funding"]}
    for w in iter_logical("works.jsonl"):
        wid=w["work_id"]
        if wid not in rows:continue
        r=rows[wid]
        if doi(w["doi"])!=r["doi"]:raise ValueError("Wrong funding DOI")
        old=ledger.changes["works"].get(wid,(w,w))[1]
        work=deepcopy(old);evidence=source(q,r["doi"],"Publisher-deposited funder and award metadata",study["boundary"])
        dim="affiliations_projects";tid="T-"+dim+"-"+wid
        state=work["dimension_status"][dim]
        if state=="pending":state="partial"
        work["dimension_status"][dim]=state
        ledger.modify("works",w,work);ledger.works[wid]=work
        event=ledger.task(tid,wid,dim,study["boundary"],state,[q["query_id"]],source_id="crossref")
        event["normalized_parameters"].update(funding_source_doi=r["doi"],funding_query=q["query_id"],
                funding_source_url=evidence["evidence_locator"][0]["url"],funding_report=REPORT.relative_to(ROOT).as_posix(),
                deposited_funder_names=[f["deposited_funder"] for f in r["deposited_funding"] if f["deposited_funder"]],
                deposited_award_identifiers=sorted({item for f in r["deposited_funding"] for item in f["award_identifiers"]}))
        event["supporting_record_ids"]=list(dict.fromkeys([*event["supporting_record_ids"],q["query_id"]]))
    ledger.input_paths.update((REPORT,p))
    return study["counts"]


if __name__=="__main__":fetch()
