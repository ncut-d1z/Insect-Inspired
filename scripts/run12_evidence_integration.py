"""Reconcile forward edges, publication affiliations, abstract summaries and cited versions in one guarded transaction."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json

from integrate_run10_references import nonapplicable, source
from integrate_run11_bibliography import evidence
from integrate_run11_reviews import Ledger
from run10_reference_records import doi, identifiers, norm, token
from run12_canonical import CurrentCanonical
from run12_followups import FORWARD
from run12_reference_search import CP, RUN
from run12_reviews import ABSTRACTS, VERSIONS
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

PAIRS=TEMP/"reports/RUN-0012-forward-reviewed.json"
TRANSACTION=TEMP/"reports/RUN-0012-scientific-integration.json"


def prepare():
    if PAIRS.exists():return
    original=read(FORWARD);items=deepcopy(original["items"])
    extra=OUT/"Q-RUN11-RAW-0065-W2005001755-A1.json"
    q=read(extra)
    item,=[r for r in items if r["citing_pmid"]=="14600796"]
    record=q["records"][26]
    if not (q["status"]=="success" and q["endpoint_or_url"].endswith("/W2005001755/references")
            and doi(record["raw_doi"])=="10.1016/s0042-6989(00)00243-1"
            and "redlick" in norm(record["raw_reference_string"]) and "humanscanuseopticflowtoestimatedistanceoftravel" in norm(record["raw_reference_string"])):
        raise ValueError("Indexed literal reference changed")
    versions=[v for v in iter_logical("versions.jsonl") if "W2005001755" in identifiers(v)]
    if {v["work_id"] for v in versions}!={"W-R10-309e3918d95e6bdaaafc"} or not any(item["citing_doi"] in identifiers(v) for v in versions):
        raise ValueError("Citing index ID not bound to citing DOI")
    for r in items:
        if r is item:
            r.update(status="forward_and_literal_reference_match",verified_list_query=q["query_id"],kind="literal_bibliography",parent="W2005001755",
                     matches=[dict(position=27,reference={**record,"openalex":record["work_id"].rsplit("/",1)[-1]})])
        else:
            if r["status"]!="forward_and_deposited_doi_match":raise ValueError("Missing deposited evidence")
            r.update(verified_list_query=r["deposited_query"],kind="deposited",parent=r["citing_doi"])
    write(PAIRS,dict(run_id=RUN,reviewed_at_utc=stamp(),items=items,counts=dict(examined=5,located=5,deposited=4,literal_index=1,new_roles=0),
              input_receipts={**original["input_receipts"],FORWARD.relative_to(ROOT).as_posix():digest(FORWARD),extra.relative_to(ROOT).as_posix():digest(extra)}))


class Evidence(CurrentCanonical):
    discovery_route="forward_citation"
    run_id=RUN
    version_report=VERSIONS
    manual=Ledger.manual
    cited=Ledger.cited
    abstracts=Ledger.abstracts

    def forward(self,rows):
        results=[]
        for r in rows:
            target=r["cited_work_id"];seed=self.works[target]
            fq=read(OUT/(r["forward_query"]+".json"));mq=read(OUT/(r["citing_metadata_query"]+".json"));q=read(OUT/(r["verified_list_query"]+".json"))
            meta,=[m for m in mq["records"] if m["epmc"]==r["citing_metadata_identifier"]]
            if doi(meta["doi"])!=r["citing_doi"]:raise ValueError("Conflicting citing identifiers")
            keys={x for x in (meta.get("doi"),meta.get("epmc"),meta.get("openalex")) if x}
            existing=set().union(*(self.identities.get(k,set()) for k in keys))
            _,relation=evidence(q,r["parent"],r["kind"],r["matches"][0]["position"],r["matches"][0]["reference"])
            added=False
            if not existing:
                if self.names.get((norm(meta["title"]),str(meta["year"]))):raise ValueError("Possible duplicate citing Work")
                wid=self.enroll(meta,mq,{"work_id":target},relation,keys,fq["query_id"]);added=True
            elif len(existing)==1:
                wid,=existing
                if not any(norm(t)==norm(meta["title"]) for t in [self.works[wid]["canonical_title"],*self.works[wid].get("title_variants",[])] if isinstance(t,str)):
                    from search_run11_bibliography import compatible_parent
                    if not compatible_parent(meta["title"],[self.works[wid]["canonical_title"]]):raise ValueError("Citing title mismatch")
            else:raise ValueError("Conflicting citing Work identities")
            citing=self.works[wid];vs=[v for v in [*self.versions,*self.adds["versions"].values()] if v["work_id"]==wid and r["citing_doi"] in identifiers(v)]
            if len(vs)!=1:raise ValueError("Ambiguous citing version")
            version=vs[0]["version_id"];pair=(citing["work_key"],seed["work_key"]);edge=self.edges.get(pair);fresh=edge is None
            forward=source(fq,"MED:"+r["target_pmid"],"Forward index, MED:"+r["citing_pmid"],"施引索引命中与实际书目逐项核对。")
            if edge:
                old=edge;edge=deepcopy(edge);self.modify("citation-edges",old,edge)
            else:
                edge=self.add("citation-edges",dict(edge_id="CE-R12-"+token(*pair),citing_key=pair[0],cited_key=pair[1],occurrence_ids=[],
                     discovery_sources=[],verification_status="source_supported",citation_roles=["unknown"],context_locators=[],date=self.now[:10]))
            self.edges[pair]=edge;edge["discovery_sources"].append(forward)
            for match in r["matches"]:
                pos=match["position"];raw=match["reference"];section,refsrc=evidence(q,r["parent"],r["kind"],pos,raw)
                literal=raw.get("unstructured") or raw.get("raw_reference_string") or json.dumps(raw,ensure_ascii=False,separators=(",",":"))
                finger=hashlib.sha256(literal.encode()).hexdigest()
                prior=self.prior_positions.get((wid,version,q["source_id"],section,finger))
                if prior:
                    if prior["cited_work_id"]!=target or prior["occurrence_id"] not in edge["occurrence_ids"]:raise ValueError("Existing occurrence differs")
                else:
                    rid="R-R12-"+token(wid,version,r["kind"],pos)
                    ref_label=raw.get("key") if r["kind"]=="deposited" else None
                    fs={"page":nonapplicable(refsrc,"书目接口未给施引页码。")}
                    if not ref_label:fs["reference_label"]=nonapplicable(refsrc,"按该参考列表的条目顺序定位。")
                    self.add("reference-occurrences",dict(occurrence_id=rid,citing_work_id=wid,version_id=version,reference_label=ref_label,
                         section=section,page=None,raw_reference=literal,raw_fingerprint=finger,candidate_ids=[seed["doi"]],cited_work_id=target,
                         identity_confidence="probable",verification_status="source_supported",source=refsrc,failure_reason=None,field_states=fs))
                    edge["occurrence_ids"].append(rid);edge["discovery_sources"].append(refsrc)
            rid="MR-R12-FORWARD-"+r["citing_pmid"]+"-"+r["target_pmid"]
            self.manual(rid,target,PAIRS,self.now,"forward_citation_bibliography",
                        "逐项匹配施引索引、施引文献身份和参考文献位置。引用作用待核实。")
            results.append(dict(cited_work_id=target,citing_work_id=wid,citing_key=citing["work_key"],edge_id=edge["edge_id"],new_work=added,new_edge=fresh,
                         verified_source=q["source_id"],position=r["matches"][0]["position"]))
        for target in {r["cited_work_id"] for r in rows}:
            group=[r for r in rows if r["cited_work_id"]==target]
            fq=read(OUT/(group[0]["forward_query"]+".json"));tasks=[r["verified_list_query"] for r in group]
            event=self.task("T-citations-"+target,target,"citations","首个来源已遍历；尚有施引候选、其他来源与引用作用待核实。","partial",
                   [fq["query_id"],*tasks],source_id="europepmc")
            event["cursor"]="review_remaining_forward_candidates_and_sources"
            event["normalized_parameters"].update(reviewed_source=fq["source_id"],reported_index_count=fq["visible_total"],
                   next_source_page=fq["cursor_out"],compared_citing_pmids=[r["citing_pmid"] for r in group],frozen_cutoff=read(TEMP/"snapshots/scope.json")["cutoff_at_utc"])
            old=self.works[target];changed=deepcopy(old);changed["dimension_status"]["citations"]="partial"
            self.modify("works",old,changed);self.works[target]=changed
        return results


def integrate():
    if TRANSACTION.exists():raise ValueError("Already integrated")
    ap=read(ABSTRACTS);vp=read(VERSIONS);pairs=read(PAIRS)
    paths=set(OUT.glob("Q-RUN12-P*.json"))
    wids={r["work_id"] for r in ap["items"]}
    citing_ids={r["citing_doi"] for r in pairs["items"]}
    for v in iter_logical("versions.jsonl"):
        if identifiers(v)&citing_ids:wids.add(v["work_id"])
    data=[({"work_id":wid},{},{},set(),[]) for wid in sorted(wids)]
    inputs={ABSTRACTS,VERSIONS,PAIRS,*[ROOT/p for p in pairs["input_receipts"]],*[ROOT/p for p in vp["input_receipts"]]}
    b=Evidence(data,inputs,paths);b.counts=Counter()
    b.versions=list(iter_logical("versions.jsonl"))
    tids={r["task_id"] for r in vp["items"]};org_ids={l["ror"] for i in ap["items"] for l in i["publication_affiliation_links"]}
    onames={norm(l["institution"]) for i in ap["items"] for l in i["publication_affiliation_links"]}
    orgs={o["org_id"] for o in iter_logical("organizations.jsonl") if o.get("ror") in org_ids or norm(o["canonical_name"]) in onames}
    for task in iter_logical("tasks.jsonl"):
        if task["task_id"] in tids or task["entity_id"] in orgs:b.latest[task["task_id"]]=task
    b.cited(vp);b.abstracts(ap,ABSTRACTS);forward=b.forward(pairs["items"])
    b.account(paths)
    counts={k:len(v) for k,v in b.adds.items() if v}
    report=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,created_at_utc=b.now,version_review=vp["counts"],abstract_byline_review=ap["counts"],
             forward=forward,byline_activity=dict(b.stats),added_counts=counts,discovered_worklist=b.new_frontier,
             input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in b.input_paths})
    print("Scientific transaction",report["version_review"],report["abstract_byline_review"],counts,flush=True)
    apply_batch(b.changes,{k:list(v.values()) for k,v in b.adds.items() if v},report,TRANSACTION.relative_to(ROOT).as_posix())


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("mode",choices=("prepare","integrate"));a=p.parse_args()
    if a.mode=="prepare":prepare()
    else:integrate()
