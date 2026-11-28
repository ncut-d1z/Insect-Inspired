"""Apply the documented Chao/Jeannerod identifier and reference corrections in one transaction."""
from collections import Counter
from copy import deepcopy

from integrate_run10_references import source
from integrate_run11_bibliography import Canonical, definitely_later
from integrate_run11_reviews import Ledger
from review_run11_chao import CHAO, REVIEW
from run10_reference_records import norm, token
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import CP, OUT, ROOT, RUN, SCOPE, TEMP, digest, read
from storage import iter_logical


def main():
    report = read(REVIEW)
    if any(digest(ROOT/name) != expected for name, expected in report["inputs"].items()):
        raise ValueError("Identity review evidence changed")
    grasp, chao = report["items"]
    assert (grasp["pmid"], chao["pmid"]) == ("7571012", "7571013")
    bad, right = grasp["registered_doi"], chao["registered_doi"]
    decisions = {}
    linked = [o for o in iter_logical("reference-occurrences.jsonl") if o.get("cited_work_id") == CHAO]
    for o in linked:
        raw = norm(o["raw_reference"])
        matches = [r for r in (grasp,chao) if norm(r["title"]) in raw and norm(r["byline"][0]) in raw and norm(r["pages"]) in raw]
        decisions[o["occurrence_id"]] = matches[0]["pmid"] if len(matches)==1 else None
    supported = [o for o in linked if decisions[o["occurrence_id"]] == grasp["pmid"]]
    assert supported and chao["pmid"] in decisions.values()
    first = supported[0]
    discovery = first["source"]["evidence_locator"][0]["evidence_note"]
    assert discovery.startswith("Q-RUN11-") and " " not in discovery
    crp, oap, dep = [OUT/("Q-RUN11-PARENT-CHAO-"+s+"-A1.json") for s in ("CR","OA","DEP")]
    qr, qo, qd = map(read,(crp,oap,dep))
    paths = {crp,oap,dep,OUT/(discovery+".json")}
    parents = {o["citing_work_id"] for o in linked}
    b = Canonical([({"work_id":wid},[]) for wid in parents|{CHAO}], {REVIEW, *(ROOT/n for n in report["inputs"])}, paths)
    old = b.works[CHAO]
    assert old["doi"] == bad and old["identifiers"]["pmid"] == chao["pmid"]
    src = source(qr,right,"Registered DOI, authors and pages","Chao 与 Hempstead，321–326 页。")
    second = source(qo,chao["openalex"],"PMID, DOI and journal pages","用 PMID 和卷页交叉核对。")
    w = deepcopy(old)
    w.update(doi=right, url="https://doi.org/"+right)
    w["identifiers"].update(doi=right, openalex=chao["openalex"])
    w["discovery_sources"].extend([src,second])
    b.modify("works",old,w)
    b.works[CHAO]=w
    for v in b.versions:
        if v["work_id"]==CHAO:
            updated=deepcopy(v)
            assert updated["identifiers"]["doi"]==bad
            updated["identifiers"].update(doi=right,openalex=chao["openalex"])
            updated.update(url=w["url"],source=src)
            b.modify("versions",v,updated)
    aliases=[a for a in iter_logical("aliases.jsonl") if a.get("target_id")==CHAO and a.get("normalized_identifier")==bad]
    assert len(aliases)==1
    a=aliases[0]
    b.modify("aliases",a,{**a,"verification_status":"conflicting","reason":"保留历史索引误配。原 DOI 属于 314–320 页的 Jeannerod 等论文。"})
    b.add("aliases",dict(alias_id="AL-R11-"+token(CHAO,right),entity_type="work",raw_identifier=right,normalized_identifier=right,
                         target_id=CHAO,historical_key=None,reason="按 Crossref 和 OpenAlex 核对题名、署名、PMID、卷页。",source=src,verification_status="source_supported",date=b.now[:10]))
    for k in (right,"MED:"+chao["pmid"],chao["openalex"]):
        b.identities[k].add(CHAO)
    b.identities[bad].discard(CHAO)
    keys={bad,"MED:"+grasp["pmid"],grasp["openalex"]}
    existing=set.union(*(b.identities[k] for k in keys)) | b.names[norm(grasp["title"]),"1995"]
    if len(existing)>1:raise ValueError("Multiple candidate identities for the DOI correction")
    if existing:
        target=next(iter(existing))
        assert norm(b.works[target]["canonical_title"])==norm(grasp["title"])
    else:
        rec=next(dict(r) for r in qr["records"] if r["doi"]==bad)
        rec.update(epmc="MED:"+grasp["pmid"],openalex=grasp["openalex"])
        target=b.enroll(rec,qr,{"work_id":first["citing_work_id"]},first["source"],keys,discovery)
        b.works[target]["discovery_sources"].append(source(qo,grasp["openalex"],"PMID, DOI and byline","Jeannerod 等，314–320 页。"))
    actual={grasp["pmid"]:target,chao["pmid"]:CHAO}
    indexed={r["pmid"]:{r["registered_doi"],r["openalex"],"MED:"+r["pmid"]} for r in (chao,grasp)}
    states={}
    for o in linked:
        rid=o["occurrence_id"];pmid=decisions[rid];updated=deepcopy(o);owner=o["citing_work_id"]
        if pmid:
            updated.update(cited_work_id=actual[pmid],candidate_ids=sorted(indexed[pmid]))
        else:
            updated.update(cited_work_id=None,identity_confidence="ambiguous",verification_status="conflicting",failure_reason="indexed_target_identity_conflict",
                           candidate_ids=sorted(set(o["candidate_ids"])|keys|indexed[chao["pmid"]]))
            event=b.task("T-R11-IDENT-"+token(rid),owner,"reference_identity","索引存在错配；书目原项未能区分两篇相邻页文章。","needs_disambiguation",[qr["query_id"],qo["query_id"]])
            event["normalized_parameters"]={"occurrence_id":rid,"candidate_ids":updated["candidate_ids"]}
        b.modify("reference-occurrences",o,updated);states[rid]=updated
        if updated["cited_work_id"]==CHAO:continue
        parent=b.works[owner]
        oldpair=(parent["work_key"],w["work_key"])
        previous=b.edges[oldpair];edge=deepcopy(previous);edge["occurrence_ids"].remove(rid)
        if not edge["occurrence_ids"]:
            edge["verification_status"]="conflicting"
            edge["discovery_sources"].append(src)
        b.modify("citation-edges",previous,edge);b.edges[oldpair]=edge
        if not pmid:continue
        newpair=(parent["work_key"],b.works[target]["work_key"])
        if newpair in b.edges:
            previous=b.edges[newpair];edge=deepcopy(previous);assert rid not in edge["occurrence_ids"]
            edge["occurrence_ids"].append(rid);b.modify("citation-edges",previous,edge);b.edges[newpair]=edge
        else:
            b.edges[newpair]=b.add("citation-edges",dict(edge_id="CE-R11-"+token(*newpair),citing_key=newpair[0],cited_key=newpair[1],
                occurrence_ids=[rid],discovery_sources=[o["source"]],verification_status="source_supported",citation_roles=["unknown"],context_locators=[],date=b.now[:10]))
        if definitely_later(parent["publication_date"],parent["year"],b.works[target]["publication_date"],b.works[target]["year"]):
            event=b.task("T-R11-CITED-"+token(owner,target),owner,"cited_version_review","核对该施引版与所引版本。","needs_disambiguation",[qr["query_id"]])
            event["supporting_record_ids"].append(rid)
    rows={k:[] for k in parents}
    for o in iter_logical("reference-occurrences.jsonl"):
        if o["citing_work_id"] in rows:rows[o["citing_work_id"]].append(states.get(o["occurrence_id"],o))
    for cov in iter_logical("reference-coverage.jsonl"):
        if cov["work_id"] not in parents:continue
        updated=deepcopy(cov);all_rows=rows[cov["work_id"]]
        for sid,c in updated["indexed_sources"].items():
            obs=[o for o in all_rows if o["source"]["source_id"]==sid]
            assert len(obs)==c["returned_positions"]
            c["unresolved_positions"]=sum(o["cited_work_id"] is None for o in obs)
            c["distinct_resolved_work_count"]=len({o["cited_work_id"] for o in obs if o["cited_work_id"]})
        updated["distinct_resolved_works"]=len({o["cited_work_id"] for o in all_rows if o["cited_work_id"]})
        if updated!=cov:b.modify("reference-coverage",cov,updated)
    cov=next(c for c in iter_logical("source-list-coverage.jsonl") if c["coverage_id"]=="COV-R11-"+CHAO+"-crossref")
    paper,=qd["records"];assert paper["reference-count"]==len(paper["reference"])
    count=paper["reference-count"]
    b.modify("source-list-coverage",cov,{**cov,"query_ids":[*cov["query_ids"],qd["query_id"]],"pagination_complete":True,
        "total_reconciled":True,"visible_total":count,"returned_count":count,"cursor":None,
        "coverage_note":"按更正的 DOI 逐项取得 Crossref 存放的 35 条书目，保留先前错配的查询。原始参考表完整性待核实。"})
    Ledger.manual(b,"MR-R11-CHAO-PAIR",CHAO,REVIEW,report["reviewed_at_utc"],"adjacent_paper_identifier_crosswalk","逐一核对相邻两文的题名、作者、PMID、DOI 和页码，并复核受影响的引用位置。")
    b.account(paths)
    rep=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,created_at_utc=b.now,corrected_parent=CHAO,other_work=target,
             occurrence_decisions=decisions,discovered_worklist=b.new_frontier,registered_positions_recovered=count,
             added_counts={k:len(v) for k,v in b.adds.items() if v},input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in b.input_paths})
    apply_batch(b.changes,{k:list(v.values()) for k,v in b.adds.items() if v},rep,"temp/reports/RUN-0011-Chao1995-integration.json")
    print("Corrected identifier, registered positions and occurrence targets",right,count,dict(Counter(decisions.values())),flush=True)


if __name__ == "__main__":
    main()
