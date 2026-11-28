"""Disambiguate two adjacent journal articles using registered DOIs, PMIDs, pages and bylines."""
from copy import deepcopy

from run10_reference_records import cross_metadata, doi, norm
from search_run11_bibliography import CR, OA, OUT, ROOT, TEMP, deposited, digest, read, request, stamp, write

CHAO = "W-R10-39cb4c627b0997084cdb"
REVIEW = TEMP / "reports/RUN-0011-Chao1995-identifier-review.json"


def main():
    base = OUT / "Q-RUN11-B2561-IDX-EPMC-01-A1.json"
    previous = OUT / "Q-RUN10-ID-EP-cd44c96b29b469b812fc-A1.json"
    old = next(r for r in read(previous)["records"] if r.get("epmc") == "MED:7571013")
    matched = next(r for r in read(base)["records"] if r.get("pmid") == "7571013")
    assert norm(old["title"]) == norm(matched["parent_title"]) and old["doi"] != matched["doi"]
    identifiers = {matched["doi"], old["doi"]}
    owner = [{"work_id": CHAO, "task_id": "T-references-" + CHAO}]
    def project_registered(data):
        rows = [cross_metadata(r) for r in data["message"]["items"]]
        if {r["doi"] for r in rows} != identifiers or len(rows) != 2:
            raise ValueError("Incomplete registered DOI pair")
        return dict(records=rows, visible_total=2, returned_count=2, page_complete=True)
    cr = request("PARENT-CHAO-CR", "crossref", CR, {"filter": ",".join("doi:" + d for d in sorted(identifiers)), "rows": 2,
                 "select": "DOI,title,author,container-title,published,volume,issue,page,type,publisher"},
                 owner, "Check the registered titles, bylines and adjacent pages for the two candidate DOIs.", project_registered)
    def project_index(data):
        records = []
        for r in data["results"]:
            records.append(dict(doi=doi(r["doi"]), pmid=r["ids"]["pmid"].rsplit("/", 1)[-1], openalex=r["id"].rsplit("/", 1)[-1],
                                title=r["display_name"], year=r["publication_year"], biblio=r["biblio"],
                                byline=[a["author"]["display_name"] for a in r["authorships"]]))
        if len(records) != 2 or {r["pmid"] for r in records} != {"7571012", "7571013"}:
            raise ValueError("Incomplete PMID pair")
        return dict(records=records, visible_total=2, returned_count=2, page_complete=True)
    oa = request("PARENT-CHAO-OA", "openalex", OA, {"filter": "pmid:7571012|7571013", "per_page": 2,
                 "select": "id,doi,ids,display_name,publication_year,biblio,authorships"},
                 owner, "Check the independent PMID, DOI, author and page mappings for these two papers.", project_index)
    if cr["status"] != "success" or oa["status"] != "success":
        raise ValueError("Insufficient metadata; keep the identity review open")
    items = []
    for r in sorted(oa["records"], key=lambda r:r["pmid"]):
        c = next(x for x in cr["records"] if x["doi"] == r["doi"])
        b = r["biblio"]
        assert norm(r["title"]) == norm(c["title"]) and c["year"] == r["year"] == 1995
        assert c["volume"] == b["volume"] and c["pages"] == b["first_page"] + "-" + b["last_page"]
        authors = [a["lastName"] for a in c["authors"]]
        assert len(authors) == len(r["byline"]) and all(norm(a) in norm(name) for a, name in zip(authors, r["byline"]))
        items.append(dict(pmid=r["pmid"], openalex=r["openalex"], registered_doi=c["doi"], title=c["title"],
                          byline=authors, year=c["year"], pages=c["pages"], volume=c["volume"], venue=c["venue"]))
    assert items[1]["registered_doi"] == matched["doi"] and items[0]["registered_doi"] == old["doi"]
    paths = [base, previous, OUT/(cr["query_id"]+".json"), OUT/(oa["query_id"]+".json")]
    if not REVIEW.exists():
        write(REVIEW, dict(run_id="RUN-0011", reviewed_at_utc=stamp(), work_id=CHAO, items=items,
              affected_field="bibliographic_identifier", original_source_identifier=old["doi"],
              inputs={p.relative_to(TEMP.parent).as_posix():digest(p) for p in paths},
              boundary="书目身份由 DOI、PMID、题名、署名及卷页交叉定位。引用作用与科学主张仍待核实。"))
    print([(r["pmid"],r["registered_doi"],r["pages"]) for r in items],flush=True)


def complete_list():
    from run11_reference_inventory import SUPPLEMENT
    from index_run11_positions import build, queue_inputs
    review = read(REVIEW)
    chao = next(r for r in review["items"] if r["pmid"] == "7571013")
    owner = dict(work_id=CHAO, task_id="T-references-"+CHAO, doi=chao["registered_doi"])
    q = deposited("PARENT-CHAO-DEP", [owner])
    assert q["status"] == "success" and len(q["records"]) == 1
    item = q["records"][0]
    assert doi(item["DOI"]) == owner["doi"] and norm(item["title"][0]) == norm(chao["title"])
    if "reference" not in item:
        print("No deposited list on the corrected DOI", flush=True)
        return
    assert len(item["reference"]) == item["reference-count"]
    orig = SUPPLEMENT / "2561-2620.json"
    dest = SUPPLEMENT / "2561-2620-reconciled.json"
    if not dest.exists():
        sup = deepcopy(read(orig))
        row = next(r for r in sup["parents"] if r["work_id"] == CHAO)
        row["corrected_deposited_query"] = dict(query_id=q["query_id"], doi=owner["doi"], declared=item["reference-count"])
        sup.update(supersedes=orig.relative_to(ROOT).as_posix(), supersedes_sha256=digest(orig), updated_at_utc=stamp())
        qp = OUT/(q["query_id"]+".json")
        sup["receipts"].update({p.relative_to(ROOT).as_posix():digest(p) for p in (qp, REVIEW)})
        write(dest,sup)
    queue, titles = queue_inputs()
    build(2560, queue, titles, reconcile=True)
    print("Registered list on the corrected DOI:",item["reference-count"],flush=True)


if __name__ == "__main__":
    main()
    complete_list()
