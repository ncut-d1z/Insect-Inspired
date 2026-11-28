"""Bind RUN11 version, abstract, byline and corrected discovery evidence to the canonical datasets."""
from collections import Counter, defaultdict
from copy import deepcopy

from integrate_run10_references import Batch, nonapplicable, source
from run10_reference_records import doi, identifiers, norm, token
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import CP, OUT, ROOT, RUN, SCOPE, TEMP, digest, read, stamp
from storage import iter_logical

VREPORT=TEMP/"reports/RUN-0011-cited-versions.json"
AREPORT=TEMP/"reports/RUN-0011-abstract-affiliation-review.json"
YOUGH="W-R10-b7df2a3ab7ba7062945d"


class Ledger(Batch):
    checkpoint=CP
    id_prefix="R11"
    run_id=RUN
    version_report=VREPORT

    def __init__(self,wanted_tasks,work_ids,other_entities=()):
        self.adds=defaultdict(dict);self.changes=defaultdict(dict)
        self.source_credit=defaultdict(list);self.task_queries=defaultdict(set);self.input_paths=set()
        self.now=stamp()
        self.works={r["work_id"]:r for r in iter_logical("works.jsonl") if r["work_id"] in work_ids}
        entities=work_ids|set(other_entities)
        self.latest={r["task_id"]:r for r in iter_logical("tasks.jsonl") if r["task_id"] in wanted_tasks or r["entity_id"] in entities}
        self.known_queries={r["query_id"] for r in iter_logical("queries.jsonl")}
        self.versions=list(iter_logical("versions.jsonl"))
        self.counts=Counter()

    def manual(self,rid,wid,artifact,when,kind,note):
        self.add("manual-reviews",dict(review_id=rid,run_id=self.run_id,review_type=kind,entity_id=wid,reviewer="Codex 书目复核",
                 recorded_at_utc=when,artifact=artifact.relative_to(ROOT).as_posix(),notes=note))

    def cited(self,report):
        for item in report["items"]:
            tid=item["task_id"];old=self.latest[tid];wid=item["citing_work_id"];assert old["entity_id"]==wid
            qids=set(item["evidence_queries"]);ordinal=item["ordinal"];m=item["exact_original_version"];binding=None;distinct=None
            pairs=(OUT/f"Q-RUN11-VER-PAIR-{ordinal}-A1.json",OUT/f"Q-RUN11-VER-PAIR-EPMC-{ordinal}-A1.json") if self.run_id==RUN else ()
            for p in pairs:
                if p.exists():qids.add(p.stem)
            if m:
                ident=doi(m["doi"]);revision=m["revision"];items=[*self.versions,*self.adds["versions"].values()]
                versions=[v for v in items if v.get("version_date")==m["date"] and
                          (ident in identifiers(v) or ident+"v"+revision in v["identifiers"].values())]
                if not versions:
                    evidence=read(OUT/(m["query_id"]+".json"))
                    record=next(r for r in evidence["records"] if doi(r.get("doi"))==ident and str(r.get("version"))==revision)
                    families={v["work_id"] for v in self.versions if ident in identifiers(v)}
                    if len(families)==1:
                        version_work=next(iter(families))
                    else:
                        assert not families and doi(record["published"])==doi(item["cited_registry_doi"]),"No publisher crosswalk for a new Version"
                        version_work=item["cited_work_id"]
                    original=[v for v in self.versions if v["work_id"]==version_work]
                    src=source(evidence,ident+"v"+revision,"bioRxiv version history",item["interpretation"])
                    v=dict(version_id="V-"+self.id_prefix+"-"+token(ident,revision),work_id=version_work,version_type="preprint",version_date=m["date"],
                           identifiers={"biorxiv_revision":ident+"v"+revision},source=src,url="https://www.biorxiv.org/content/"+ident+"v"+revision,
                           file_records=[],verification_status="source_supported",related_version_ids=[v["version_id"] for v in original],
                           version_materialization="bibliographic_only",field_states={},notes=m["title"])
                    versions=[self.add("versions",v)]
                assert len(versions)==1,(ordinal,versions)
                binding=versions[0]["version_id"];distinct=versions[0]["work_id"]!=item["cited_work_id"]
                self.counts["printed_original_versions_supported"]+=1
            rid="MR-"+self.id_prefix+"-VERSION-"+token(tid)
            note=item["interpretation"]
            if self.run_id==RUN and ordinal==46:
                note+=" 两条 DOI 登记的四名作者及顺序一致，但题名有变；数据库未登记版本关系，另留正式条目关联工单。"
                follow=self.task("T-R11-VERSION-LINK-"+token(tid),item["cited_work_id"],"bibliographic_version_link",
                                 "已定位原始书目的预印本。登记作者相同、题名略异，待出版社或预印本库明示版本关系。","needs_disambiguation",sorted(qids))
                follow["normalized_parameters"]={"printed_version_id":binding,"published_doi":item["cited_registry_doi"]}
            state="verified_complete" if binding else "needs_disambiguation"
            event=self.task(tid,wid,old["task_type"],note,state,sorted(qids),source_id=old["source_id"])
            event["cursor"]=None if binding else (old.get("cursor") or "original_citing_version_bibliography")
            event["supporting_record_ids"]=list(dict.fromkeys([*event["supporting_record_ids"],rid,*([binding] if binding else [])]))
            event["normalized_parameters"]={**event["normalized_parameters"],"reviewed_target_work_id":item["cited_work_id"],
                      "cited_manifestation":binding,"printed_and_indexed_work_records_differ":distinct,
                      "deposit_position":item["deposit_position"],"review_disposition":item["status"]}
            self.manual(rid,wid,self.version_report,report["reviewed_at_utc"],"original_cited_version_bibliography",note)

    def abstracts(self,report,artifact=AREPORT):
        q=read(ROOT/report["source_receipt"]);assert digest(ROOT/report["source_receipt"])==report["source_receipt_sha256"]
        orgs={r["org_id"]:r for r in iter_logical("organizations.jsonl")}
        people_wanted={a["person_id"] for row in report["items"] for a in self.works[row["work_id"]]["authors"]}
        people={p["person_id"]:p for p in iter_logical("authors.jsonl") if p["person_id"] in people_wanted}
        for row in report["items"]:
            wid=row["work_id"];old=self.works[wid];w=deepcopy(old)
            r=next(r for r in q["records"] if r["id"]==row["pmid"])
            assert doi(r["doi"])==doi(old["doi"]) and r.get("abstract_sha256")==row["abstract_sha256"]
            src=source(q,"MED:"+row["pmid"],"Abstract and publication byline",row["boundary"])
            rid="MR-"+self.id_prefix+"-ABSTRACT-"+row["pmid"];qids={q["query_id"]}
            if row["summary_zh"]:
                versions=[v for v in self.versions if v["work_id"]==wid and w["doi"] in identifiers(v)]
                assert len(versions)==1 and not w["abstract_items"]
                w["abstract_items"].append(dict(status="chinese_summary_from_abstract",text=row["summary_zh"],source=src,
                 version_id=versions[0]["version_id"],license="Original Chinese summary; source abstract not reproduced.",
                 summarizer="Codex 摘要复核",date=report["reviewed_at_utc"][:10],source_language="en",verification_status="source_supported"))
                w.update(abstract_status="chinese_summary_from_abstract",abstract_source=src)
            else:qids.add("Q-RUN11-P56-HILDRETH-CR-A1")
            for link in row["publication_affiliation_links"]:
                p=OUT/(link["ror_query"]+".json");assert digest(p)==link["ror_receipt_sha256"];oq=read(p)
                place=link.get("registry_location")
                rr=[o for o in oq["records"] if o["source_identifier"]==link["ror"] and (o.get("chosen") or (place and any(all(loc.get(k)==v for k,v in place.items()) for loc in o.get("locations",[]))))]
                assert len(rr)==1 and any(n["value"]==link["institution"] and "ror_display" in n["types"] for n in rr[0]["names"])
                matches=[o for o in orgs.values() if o.get("ror")==link["ror"] or norm(o["canonical_name"])==norm(link["institution"])]
                assert len(matches)<=1;osrc=source(oq,link["ror"],"ROR organization identity",link["institution"])
                if matches:
                    org=matches[0];changed=deepcopy(org);changed.update(ror=link["ror"],organization_level="university")
                    changed["external_ids"]["ror"]=link["ror"];changed["sources"].append(osrc)
                    f=changed["field_states"].pop("ror",None)
                    if f and f.get("review_task_id"):
                        tid=f["review_task_id"];oldtask=self.latest[tid]
                        e=self.task(tid,org["org_id"],oldtask["task_type"],"ROR 登记已确认机构身份。","verified_complete",[p.stem],
                                    etype=oldtask["entity_type"],source_id=oldtask["source_id"]);e["overdue"]=False
                    self.modify("organizations",org,changed)
                else:
                    orgid="ORG-"+self.id_prefix+"-"+link["ror"].rsplit("/",1)[-1]
                    changed=dict(org_id=orgid,canonical_name=link["institution"],name_variants=[n["value"] for n in rr[0]["names"]],
                                 raw_affiliations=[link["affiliation"]],ror=link["ror"],external_ids={"ror":link["ror"]},
                                 organization_level="university",parent_org_id=None,historical_relations=[],valid_from=None,valid_to=None,
                                 verification_status="source_supported",sources=[osrc],field_states={})
                    for k in ("parent_org_id","valid_from","valid_to"):changed["field_states"][k]=self.unknown("organization",orgid,k,osrc)
                    self.add("organizations",changed)
                oid=changed["org_id"];orgs[oid]=changed;qids.add(p.stem)
                rank=link["byline_position"]-1;a=w["authors"][rank];by=r["authors"][rank]
                assert link["source_display"]==by["fullName"] and link["affiliation"] in by["affiliations"] and oid not in a["organization_ids"]
                a["organization_ids"].append(oid)
                loc=source(q,"MED:"+row["pmid"],f"Byline {rank+1}, publication affiliation",link["affiliation"])
                oldperson=people[a["person_id"]];person=deepcopy(oldperson)
                person["affiliation_history"].append(dict(org_id=oid,role="byline_affiliation_at_publication",valid_from=None,valid_to=None,work_id=wid,
                         evidence_locator=loc["evidence_locator"],field_states={k:nonapplicable(loc,"仅登记该次发表的署名。") for k in ("valid_from","valid_to")}))
                self.modify("authors",oldperson,person);people[a["person_id"]]=person
            for dim in ("abstract","affiliations_projects","assessment"):
                if dim=="assessment" and not row["summary_zh"]:continue
                state="partial" if dim!="abstract" or row["summary_zh"] else "pending"
                event=self.task("T-"+dim+"-"+wid,wid,dim,row["boundary"] if dim!="affiliations_projects" else "已核对本次发表署名；其他归属与项目继续复查。",
                                state,sorted(qids))
                event["supporting_record_ids"].append(rid);w["dimension_status"][dim]=state
            self.modify("works",old,w);self.works[wid]=w
            self.manual(rid,wid,artifact,report["reviewed_at_utc"],"abstract_and_publication_byline",row["boundary"])

    def correct_yough(self,vreport):
        affected=[r for r in vreport["items"] if r["status"]=="indexed_identity_conflict"];assert len(affected)==3
        old=self.works[YOUGH];w=deepcopy(old);bad=doi(w["doi"]);pmid=w["identifiers"]["pmid"]
        qa=read(OUT/"Q-RUN11-VER-YOUGH-OA-PMID-A1.json");qb=read(OUT/"Q-RUN11-VER-YOUGH-OA-DOI-A1.json")
        assert pmid=="37234941" and qa["records"][0]["doi"] is None and norm(qa["records"][0]["display_name"])==norm(w["canonical_title"])
        assert doi(qb["records"][0]["doi"])==bad and qb["records"][0]["ids"]["pmid"].endswith("/10493757")
        src=source(qa,"W4378516163","DOI/PMID identity reconciliation","此 2022 年学术记录与 1999 年 DOI 对应不同的题名及 PMID。")
        w["identifiers"].pop("doi");w["identifiers"]["openalex"]="W4378516163";w.update(doi=None,url="https://europepmc.org/article/MED/"+pmid)
        w["field_states"]["doi"]=self.unknown("work",YOUGH,"doi",src);w["discovery_sources"].append(src)
        for v in self.versions:
            if v["work_id"]==YOUGH:
                revised=deepcopy(v);assert doi(v["identifiers"]["doi"])==bad
                revised.update(identifiers=deepcopy(w["identifiers"]),url=w["url"],source=src);self.modify("versions",v,revised)
        for a in iter_logical("aliases.jsonl"):
            if a.get("target_id")==YOUGH and a.get("normalized_identifier")==bad:
                revised=deepcopy(a);revised.update(verification_status="conflicting",reason="历史索引误配。该 DOI 由 Crossref 和独立 PMID 交叉定位到 1999 年另一篇文章。")
                self.modify("aliases",a,revised)
        oq=read(OUT/"Q-RUN11-VER-PRINT-W4378516163-A1.json");eq=read(OUT/"Q-RUN11-VER-YOUGH-OWNLIST-A1.json")
        anchor=self.works["W-D44fb71abffbaed85"];target=anchor["doi"]
        source_matches=[(i,r) for i,r in enumerate(oq["records"],1) if target in (r.get("raw_reference_string") or "").lower()]
        assert len(source_matches)==1 and norm(anchor["canonical_title"]) in norm(source_matches[0][1]["raw_reference_string"])
        pos=source_matches[0][0];assert norm(eq["records"][12]["title"])==norm(anchor["canonical_title"])
        ls=source(oq,"W4378516163",f"OpenAlex literal bibliography position {pos}",f"条目明示 {anchor['canonical_title']} 与 DOI {target}。")
        ls["url"]=oq["endpoint_or_url"];ls["evidence_locator"][0]["url"]=ls["url"]
        es=source(eq,"MED:"+pmid,"Europe PMC reference 13","匹配 Wolpert 和 Ghahramani 的原登记题名、作者及年份。")
        w["discovery_sources"].extend([ls,es])
        w["discovery_path"]=[*deepcopy(anchor["discovery_path"]),dict(from_entity_id=anchor["work_id"],to_entity_id=YOUGH,
                discovery_route="forward_citation",source_id="openalex",evidence_locator=ls["evidence_locator"],verification_status="source_supported",scope_id=SCOPE)]
        w["discovery_depth"]=len(w["discovery_path"]);self.modify("works",old,w);self.works[YOUGH]=w
        oldpaths=list(d for d in iter_logical("discovery-paths.jsonl") if d["work_id"] in (YOUGH,anchor["work_id"]))
        for path in oldpaths:
            if path["work_id"]==YOUGH:
                revised=deepcopy(path);revised["source_supported_relation"]=False;revised["steps"][-1]["verification_status"]="conflicting"
                self.modify("discovery-paths",path,revised)
        base=next(d for d in oldpaths if d["work_id"]==anchor["work_id"] and anchor["discovery_path"]==d["steps"])
        self.add("discovery-paths",dict(discovery_id="D-R11-"+token(anchor["work_id"],YOUGH),scope_id=SCOPE,work_id=YOUGH,
                 root_seed_id=base["root_seed_id"],depth=w["discovery_depth"],steps=w["discovery_path"],source_supported_relation=True))
        occurrences={o for row in affected for o in row["occurrence_ids"]};assert len(occurrences)==3
        parents={r["citing_work_id"] for r in affected};personal=list(r for r in iter_logical("reference-occurrences.jsonl") if r["citing_work_id"] in parents)
        for i,o in enumerate(personal):
            if o["occurrence_id"] not in occurrences:continue
            assert o["cited_work_id"]==YOUGH
            rev=deepcopy(o);rev.update(cited_work_id=None,identity_confidence="ambiguous",verification_status="conflicting",
                    failure_reason="indexed_target_identity_conflict",candidate_ids=sorted(set(o["candidate_ids"])|{"MED:10493757","MED:37234941"}))
            self.modify("reference-occurrences",o,rev);personal[i]=rev
            t=self.task("T-R11-IDENT-"+token(o["occurrence_id"]),o["citing_work_id"],"reference_identity",
                        "Europe PMC 原匹配与期刊书目、论文发表时间不符；等待可定位的真实引用目标。","needs_disambiguation",[qa["query_id"],qb["query_id"]])
            t["normalized_parameters"]={"occurrence_id":o["occurrence_id"],"candidate_ids":rev["candidate_ids"]}
        new_pair=(w["work_key"],anchor["work_key"]);pairs=0
        for edge in iter_logical("citation-edges.jsonl"):
            assert (edge["citing_key"],edge["cited_key"])!=new_pair
            if not set(edge["occurrence_ids"]).intersection(occurrences):continue
            assert edge["cited_key"]==w["work_key"] and set(edge["occurrence_ids"])<=occurrences
            rev=deepcopy(edge);rev.update(occurrence_ids=[],verification_status="conflicting");rev["discovery_sources"].append(src)
            self.modify("citation-edges",edge,rev);pairs+=1
        assert pairs==3
        self.add("citation-edges",dict(edge_id="CE-R11-"+token(*new_pair),citing_key=new_pair[0],cited_key=new_pair[1],occurrence_ids=[],
                 discovery_sources=[ls,es],verification_status="source_supported",citation_roles=["unknown"],context_locators=[],date=self.now[:10]))
        for c in iter_logical("reference-coverage.jsonl"):
            if c["work_id"] not in parents:continue
            rev=deepcopy(c);refs=[o for o in personal if o["citing_work_id"]==c["work_id"]]
            for sid,k in rev["indexed_sources"].items():
                rows=[o for o in refs if o["source"]["source_id"]==sid];assert len(rows)==k["returned_positions"]
                k["distinct_resolved_work_count"]=len({o["cited_work_id"] for o in rows if o["cited_work_id"]})
                k["unresolved_positions"]=sum(not o["cited_work_id"] for o in rows)
            rev["distinct_resolved_works"]=len({o["cited_work_id"] for o in refs if o["cited_work_id"]})
            self.modify("reference-coverage",c,rev)
        self.counts.update(conflicting_inherited_matches=3,corrected_work_doi=1,independent_forward_paths=1)


def main():
    vr,ar=read(VREPORT),read(AREPORT)
    paths=set(OUT.glob("Q-RUN11-VER-*.json"))|set(OUT.glob("Q-RUN11-P56-*.json"))
    owners={o["task_id"] for p in paths for o in read(p)["owners"]}
    works={r["citing_work_id"] for r in vr["items"]}|{r["work_id"] for r in ar["items"]}|{YOUGH,"W-D44fb71abffbaed85"}
    batch=Ledger(owners,works,{"ORG-Raad2547418aaa242"})
    batch.cited(vr);batch.abstracts(ar);batch.correct_yough(vr);batch.queries(paths)
    inputs={p.relative_to(ROOT).as_posix():digest(p) for p in paths|{VREPORT,AREPORT}}
    inputs.update(vr["input_receipts"])
    report=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,recorded_at_utc=batch.now,input_receipts=inputs,
                version_outcomes=vr["counts"],abstract_byline_counts=ar["counts"],canonical_changes=dict(batch.counts))
    out="temp/reports/RUN-0011-review-integration.json"
    apply_batch(batch.changes,{k:list(v.values()) for k,v in batch.adds.items()},report,out)
    print("review records",dict(batch.counts),{k:len(v) for k,v in batch.adds.items()},flush=True)


if __name__=="__main__":main()
