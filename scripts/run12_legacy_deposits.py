"""Locate the outstanding CP12 version cases in the depositing member's bibliographic XML."""
from collections import defaultdict
from urllib.parse import quote, unquote

from run10_reference_records import doi
from run12_old_versions import parse, tag
from run12_reference_search import CP, RUN, query
from run12_version_screen import EXACT, OLD
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write

REPORT = TEMP / "reports/RUN-0012-CP12-deposit-positions.json"


def reference_list(root, parent):
    articles = [n for n in root.iter() if tag(n) in ("journal_article", "posted_content", "conference_paper")
                and any(tag(d) == "doi" and doi(d.text) == parent for group in n if tag(group) == "doi_data" for d in group)]
    if len(articles) != 1:
        raise ValueError("Depositing member XML has no unique matching parent DOI")
    entries = []
    for listing in articles[0]:
        if tag(listing) != "citation_list":
            continue
        for entry in listing:
            if tag(entry) != "citation":
                continue
            fields = [dict(field=tag(e), value=" ".join("".join(e.itertext()).split()), attributes=dict(e.attrib)) for e in entry]
            links = [v for e in entry.iter() for k,v in e.attrib.items() if k.rsplit("}",1)[-1] in ("href","uri")]
            entries.append(dict(source_identifier=entry.get("key") or str(len(entries)+1), position=len(entries)+1, fields=fields, links=links))
    return dict(records=entries, visible_total=len(entries), returned_count=len(entries), page_complete=True, parent_doi=parent,
                response_media_type="Crossref deposit XML (UNIXREF)")


def main():
    if REPORT.is_file():
        return
    cases = [c for c in read(OLD)["items"] if c["cohort"] == "CP12-crossdate" and c["status"] != "original_version_supported"]
    if len(cases) != 28:
        raise ValueError("The CP12 version queue changed")
    grouped = defaultdict(list)
    for case in cases:
        grouped[case["citing_doi"]].append(case)
    prior = {}
    for p in sorted(OUT.glob("Q-RUN12-P4-LEGACY-XML-*.json")):
        q = read(p)
        if q["status"] == "success" and q.get("response_media_type") == "Crossref deposit XML (UNIXREF)":
            parent = doi(unquote(q["endpoint_or_url"].split("/v1/works/",1)[-1].split("/transform")[0]))
            prior[parent] = q
    rows = []
    inputs = {OLD.relative_to(ROOT).as_posix():digest(OLD)}
    for parent, targets in sorted(grouped.items()):
        q = prior.get(parent)
        cached = q is not None
        if not cached:
            q = query("P4-DOC-CP12-"+str(targets[0]["ordinal"]), "crossref",
                      "https://api.crossref.org/v1/works/"+quote(parent,safe="/")+"/transform", {},
                      [dict(work_id=c["citing_work_id"],task_id=c["task_id"]) for c in targets],
                      "Locate unresolved version cases in the depositing member's reference list and inspect explicit revision fields.",
                      lambda document:reference_list(document,parent), decode=parse, accept="application/vnd.crossref.unixref+xml")
        path = OUT/(q["query_id"]+".json")
        inputs[path.relative_to(ROOT).as_posix()] = digest(path)
        for case in targets:
            registered = case["deposit_reference"] or {}
            key = registered.get("key")
            entries = q.get("records",[])
            matching = [entry for entry in entries if (key and entry["source_identifier"] == key) or
                        (not key and any(f["field"]=="doi" and doi(f["value"])==case["cited_registry_doi"] for f in entry["fields"]))]
            rows.append(dict(ordinal=case["ordinal"],task_id=case["task_id"],citing_work_id=case["citing_work_id"],
                        cited_work_id=case["cited_work_id"],citing_doi=parent,cited_registry_doi=case["cited_registry_doi"],
                        previous_status=case["status"],source_status=q["status"],query_id=q["query_id"],cached_parent_list=cached,
                        returned_list_positions=len(entries),expected_reference_key=key,previous_position=case["deposit_position"],
                        matching_positions=[dict(position=e["position"],source_key=e["source_identifier"],fields=e["fields"],links=e["links"],
                            revision_candidates=sorted(set(EXACT.findall(" ".join([*(v["value"] for v in e["fields"]),*e["links"]]))))) for e in matching]))
    rows.sort(key=lambda x:x["ordinal"])
    counts=dict(tickets=len(rows),distinct_parent_lists=len(grouped),reused_parent_lists=len(set(grouped)&set(prior)),
                positions_matched=sum(bool(r["matching_positions"]) for r in rows),position_unavailable=sum(not r["matching_positions"] for r in rows),
                explicit_revision_candidates=sum(any(m["revision_candidates"] for m in r["matching_positions"]) for r in rows))
    write(REPORT,dict(run_id=RUN,checkpoint_id=CP,scope_id=SCOPE,recorded_at_utc=stamp(),counts=counts,input_receipts=inputs,items=rows))
    print(counts,flush=True)


if __name__ == "__main__":
    main()
