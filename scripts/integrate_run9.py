"""Integrate the reviewed RUN9 S06 source batch without reserializing untouched rows."""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import gates
from audit_cp10 import REQUEST_COUNT_BASIS
from advance_review_deadlines import transaction_directory
from escalate_unknown_run7 import IDS, encoded, git, info, logical_lines, publish, require, sha, stage_dataset
from review_figure5h_run9 import figure_claim

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "temp"
RUN, CP, SCOPE = "RUN-0009", "CP-0011", "SCOPE-0001"
IDENTITY = "W-R24649f4879cc831d"
PROJECT = "PRJ-CONGENTO-LISBOA-01-0145-FEDER-022170"
REPORT = "temp/reports/RUN-0009-S06-integration.json"
BASE_COMMIT = "65fb9d47fc8db45d85c6386ebd96cb8243099aa1"


def read(path):
    return json.loads(path.read_bytes())


def build():
    manifest = read(BASE / "partitions/manifest.json")
    citation = read(BASE / "reports/RUN-0009-S06-citations-and-project.json")
    figure = read(BASE / "reports/RUN-0009-S06-figure5h-review.json")
    qfiles = sorted((BASE / "query-results").glob("Q-RUN09-*.json"))
    receipts = {q["query_id"]: q for q in map(read, qfiles)}
    require(len(receipts) == 9, "This batch requires its nine original observations")
    now = max(figure["recorded_at_utc"], citation["recorded_at_utc"])
    rows = citation["references"]
    changes, additions = defaultdict(dict), defaultdict(list)
    task_updates, task_new = {}, {}
    guards = {"temp/partitions/manifest.json": info((BASE/"partitions/manifest.json").read_bytes())}
    for path in [*qfiles, BASE / "reports/RUN-0009-S06-citations-and-project.json", BASE / "reports/RUN-0009-S06-figure5h-review.json"]:
        guards[path.relative_to(ROOT).as_posix()] = info(path.read_bytes())

    def selected(dataset, wanted):
        result = {}
        for raw in logical_lines(ROOT,dataset,manifest):
            r=json.loads(raw)
            key=r[IDS[dataset]]
            if key in wanted:
                if key in result:
                    require(dataset=="tasks" and r["event_sequence"]>result[key]["event_sequence"],"Duplicate "+key)
                result[key]=r
        require(set(result)==set(wanted),"Missing "+dataset+": "+str(set(wanted)-set(result)))
        return result

    def mutate(dataset, old, new):
        key=old[IDS[dataset]]
        require(key==new[IDS[dataset]] and key not in changes[dataset],"Unstable or duplicate change")
        changes[dataset][key]=(old,new)

    def task(tid, typ, eid, kind, source, qids, reason, state="pending", when=now):
        return dict(task_id=tid,entity_type=typ,entity_id=eid,task_type=kind,scope_id=SCOPE,source_id=source,
            normalized_parameters={"run_id":RUN},task_state=state,cursor=None,dependency_ids=[],query_ids=qids,
            attempt_count=0,error_code=None,failure_reason=None if state=="verified_complete" else reason,retry_at=None,
            review_condition=reason,created_at_utc=when,updated_at_utc=when,checkpoint_id=CP,event_sequence=1,
            assessment_id=eid if typ=="assessment" else None,field_path=None,unknown_since_utc=None,deadline_at_utc=None,
            review_task_id=None,priority="normal",overdue=False,supporting_record_ids=list(qids))

    def unknown(typ,eid,path,reason,loc,when=now):
        token=hashlib.sha256((eid+" "+path).encode()).hexdigest()[:18]
        tid="T-RUN09-F-"+token
        t=task(tid,typ,eid,"field_review",loc["source_id"],[],reason,when=when)
        deadline=(datetime.fromisoformat(when.replace("Z","+00:00"))+timedelta(hours=24)).isoformat().replace("+00:00","Z")
        t.update(field_path=path,unknown_since_utc=when,deadline_at_utc=deadline,review_task_id=tid)
        require(tid not in task_new,"Duplicate unknown");task_new[tid]=t
        return dict(status="unknown",reason=reason,evidence_locator=[loc],unknown_since_utc=when,review_task_id=tid)

    def reported(loc):
        return dict(status="reported",reason=None,evidence_locator=[loc],unknown_since_utc=None,review_task_id=None)

    original=receipts["Q-RUN09-S06-JATS-001"]
    def locate(section,note):
        return dict(source_id="europepmc",version_id="V-S06-01",identifier=citation["article_doi"],url=original["endpoint_or_url"],
                    section=section,accessed_at=original["completed_at_utc"],evidence_note=note)

    def source(loc):
        return dict(source_id=loc["source_id"],url=loc["url"],identifier=loc["identifier"],accessed_at=loc["accessed_at"],
                    verification_status="verified",license="Bibliographic facts, evidence locators and original review only.",evidence_locator=[loc])

    occ=selected("reference-occurrences",{r[k] for r in rows for k in ("deposit_occurrence","printed_occurrence")})
    edges=selected("citation-edges",{r["existing_edge"] for r in rows})
    for r in rows:
        printed=occ[r["printed_occurrence"]]; old=occ[r["deposit_occurrence"]]; edge=edges[r["existing_edge"]]
        require(old["cited_work_id"] is None and printed["cited_work_id"]==r["target_work"] and
                old["version_id"]==printed["version_id"]=="V-S06-01" and r["printed_occurrence"] in edge["occurrence_ids"],
                "Occurrence or Version precondition failed")
        require(edge["cited_key"]==r["target_key"] and edge["citation_roles"]==["unknown"],"Edge precondition failed")
        rr=deepcopy(old)
        certainty="probable" if r["ref_number"]==14 else "confirmed"
        cite=locate("back/ref-list/ref[@id='"+r["jats_ref"]+"']",r["interpretation"])
        rr.update(candidate_ids=[r["target_work"]],cited_work_id=r["target_work"],identity_confidence=certainty,
                  verification_status="source_supported" if certainty=="probable" else "verified",
                  failure_reason="原书目拼写与暂定身份仍待独立版本核验。" if certainty=="probable" else None)
        rr["source"].setdefault("evidence_locator",[]).append(cite)
        mutate("reference-occurrences",old,rr)
        locs=[dict(locate(path,r["interpretation"]),paragraph=path) for path in r["context_locators"]]
        ee=deepcopy(edge);ee["occurrence_ids"].append(r["deposit_occurrence"])
        ee.update(citation_roles=["background"],context_locators=locs)
        ee["discovery_sources"].append(source(cite));mutate("citation-edges",edge,ee)
        additions["citation-context-audit"].append(dict(context_id="CTX-RUN09-S06-"+r["jats_ref"],citing_work_id="W-S06",
            cited_work_id=r["target_work"],citation_roles=["background"],evidence_locator=locs,edge_id=edge["edge_id"],
            verification_status="verified",summary=r["interpretation"]))

    authority=receipts["Q-RUN09-P3-SUNKARA-006"]; meta=authority["records"][0]
    loc=dict(source_id="crossref",identifier=meta["DOI"],url=authority["endpoint_or_url"],section="DOI singleton: title, authors, article number and publication date",
             accessed_at=authority["completed_at_utc"],evidence_note="题名、三位作者、期刊和年份与正式书目 CR78 对照。")
    old=selected("works",{IDENTITY})[IDENTITY]; w=deepcopy(old)
    require(old["doi"] is None and old["canonical_title"].casefold()==meta["title"][0].casefold(),"Authority conflict")
    w.update(doi=meta["DOI"],document_type="journal_article",volume=meta["volume"],eid=meta["article-number"],publisher=meta["publisher"],
             venue=meta["container-title"][0],publication_date="-".join(f"{v:02d}" for v in meta["published"]["date-parts"][0]),
             url="https://doi.org/"+meta["DOI"],identity_confidence="confirmed",verification_status="verified")
    w["identifiers"]["doi"]=meta["DOI"]; w["discovery_sources"].append(source(loc))
    old_review_ids={}
    for key in ["volume","eid","publisher","doi"]:
        old_review_ids[old["field_states"][key]["review_task_id"]]=key
        w["field_states"][key]=reported(loc)
    w["notes"]=(w.get("notes") or "")+" RUN9：注册 DOI 与原文 CR78 对照；保留现有 key 和既有署名消歧队列。"
    mutate("works",old,w)
    additions["aliases"].append(dict(alias_id="AL-RUN09-SUNKARA-DOI",entity_type="work",raw_identifier="10.7554/eLife.04693",
        normalized_identifier=meta["DOI"],target_id=IDENTITY,historical_key=None,reason="原始 JATS DOI 与注册记录核实，保留原有 Work ID、key。",source=source(loc),verification_status="verified",date=now[:10]))

    qfund=receipts["Q-RUN09-P5-CONGENTO-005"]; grant=citation["project"]
    gloc=dict(source_id="official_projects",identifier=grant["grant_id"],url=qfund["endpoint_or_url"],section="Ficha de projeto; Código de operação; Data de conclusão; Beneficiário principal",
              accessed_at=qfund["completed_at_utc"],evidence_note="项目编号、实际结项日期及主要受益机构来自葡萄牙官方门户。")
    ack=locate("back/ack, final funding paragraph","论文明确致谢 Congento 基础设施支持，列出同一项目编号。")
    proj=dict(project_id=PROJECT,canonical_name="Congento",grant_id=grant["grant_id"],org_ids=[grant["canonical_org_id"]],
              person_ids=[],start_date=None,end_date="2021-01-24",objective=None,url=qfund["endpoint_or_url"],output_work_ids=["W-S06"],
              project_relation="funding_acknowledgment",evidence_locator=[gloc,ack],verification_status="source_supported",sources=[source(gloc),source(ack)],notes=grant["notes"])
    proj["field_states"]={k:reported(ack if k in {"canonical_name","output_work_ids"} else gloc) for k in ["canonical_name","org_ids","end_date","url","output_work_ids"]}
    for k,reason in {"person_ids":"已查材料未核实项目 PI 或完整参与名单。","objective":"正式目标及项目版本待核验。","start_date":"核对初始批准日期、实际启动日期与历史版本。"}.items():
        proj["field_states"][k]=unknown("project",PROJECT,k,reason,gloc)
    additions["projects"].append(proj)
    additions["project-relations"].append(dict(relation_id="ER-RUN09-S06-CONGENTO",relation_type="funded_by",
        from_id="W-S06",to_id=PROJECT,valid_from=None,valid_to=None,verification_status="source_supported",evidence_locator=[ack,gloc],work_id="W-S06"))
    task_new["T-RUN09-CONGENTO-OUTPUTS"]=task("T-RUN09-CONGENTO-OUTPUTS","project",PROJECT,"project_output_bibliography","official_projects",
        ["Q-RUN09-P5-CONGENTO-003","Q-RUN09-P5-CONGENTO-005"],"逐项核验检索回执中的官方项目资源、可独立引用报告及个别成果的关系与范围。")

    claim=figure_claim(figure,locate,unknown)
    require(gates.evidence_gate(claim)["rejection_codes"]==[], "Quantitative/scale gate failed")
    additions["assessments"].append(claim)
    new_contexts=[r["context_id"] for r in additions["citation-context-audit"]]
    audit_refs={"P3":[r["deposit_occurrence"] for r in rows],"P4":new_contexts,"P5":[PROJECT],"P6":[claim["assessment_id"]]}
    for phase,ids in audit_refs.items():
        for index,eid in enumerate(ids,1):
            additions["manual-reviews"].append(dict(review_id=f"MR-RUN09-{phase}-{index:02}",run_id=RUN,review_type={
                "P3":"reference_identity_review","P4":"citation_context_review","P5":"project_funding_review","P6":"quantitative_fulltext_review"}[phase],
                entity_id=eid,reviewer="Codex 原文复核",recorded_at_utc=now,
                artifact="temp/reports/RUN-0009-S06-"+("figure5h-review.json" if phase=="P6" else "citations-and-project.json"),
                notes="原文、源表或资助登记与该条记录逐项对照；只覆盖所列对象。"))

    by_task=defaultdict(list)
    for q in receipts.values():by_task[q["task_id"]].append(q["query_id"])
    existing=selected("tasks",{"T-References-S06",*old_review_ids})
    for tid,qs in by_task.items():
        if tid in existing:
            t=deepcopy(existing[tid]); t["event_sequence"]+=1; t["updated_at_utc"]=now; t["checkpoint_id"]=CP
            t["attempt_count"]+=len(qs);t["query_ids"]=list(dict.fromkeys(t["query_ids"]+qs))
            t["supporting_record_ids"]=list(dict.fromkeys(t.get("supporting_record_ids",[])+audit_refs["P3"]))
            task_updates[tid]=t
        else:
            ok=any(receipts[q]["status"]=="success" for q in qs)
            t=task(tid,"work","W-S06","recorded_source_operation",receipts[qs[-1]]["source_id"],qs,
                   "仅核对本次指定资源；原文版本受限时通过出版历史继续复核。","verified_complete" if ok else "restricted")
            t["attempt_count"]=len(qs);task_new[tid]=t
    for tid,key in old_review_ids.items():
        t=deepcopy(existing[tid]);require(t["task_state"] not in {"verified_complete","not_applicable"},"Already closed "+tid)
        t.update(task_state="verified_complete",updated_at_utc=now,checkpoint_id=CP,event_sequence=t["event_sequence"]+1,
                 query_ids=list(dict.fromkeys(t["query_ids"]+[authority["query_id"]])),failure_reason=None,
                 review_condition="注册记录及 S06 原文定位核实字段："+key)
        task_updates[tid]=t

    for q in receipts.values():
        qid=q["query_id"]; ids=q["result_identifiers"]; count=q["returned_count"]
        kind=q["query_kind"]; failed=q["status"] in {"retryable_error","restricted"}
        ref=dict(source_id=q["source_id"],identifier=qid,url=q["endpoint_or_url"],section=kind,accessed_at=q["queried_at_utc"],evidence_note="独立保存的来源访问回执。")
        nonlist=dict(status="not_applicable",reason="指定资源的单次读取，没有索引列表总量。",evidence_locator=[ref],unknown_since_utc=None,review_task_id=None)
        field=unknown("source",q["source_id"],"queries."+qid+".visible_total","搜索服务未披露可见总量或分页游标。",ref,when=q["queried_at_utc"]) if qid.endswith("003") else nonlist
        record=dict(query_id=qid,task_id=q["task_id"],scope_id=SCOPE,checkpoint_id=CP,entity_id=q["entity_id"],source_id=q["source_id"],
            endpoint_or_url=q["endpoint_or_url"],api_version=q.get("api_version") or "public web / retrieved representation",query_kind=kind,
            raw_parameters=q["raw_parameters"],normalized_parameters=dict(q["raw_parameters"],scope_id=SCOPE),
            queried_at_utc=q["queried_at_utc"],cursor_in=None,cursor_out=None,page_index=1,page_complete=q["page_complete"],visible_total=None,
            returned_count=count,count_before_dedup=count,count_after_dedup=len(set(ids)),new_work_ids=[],new_work_count=0,result_identifiers=ids,
            status="error" if q["status"]=="retryable_error" else q["status"],verification_status="unverified" if failed else "source_supported",
            error_code=q.get("error_code"),error_message=q.get("error_message"),retry_count=1 if qid.endswith("005") else 0,retry_at=None,
            cache_path="temp/query-results/"+qid+".json",cache_hit=False,reused_query_id=None,rerun_reason=q.get("rerun_reason"),
            coverage_note=q.get("coverage_note") or "本次访问失败，未取得目标数据。",license_note=q["license_note"],query_time_status="exact",
            recorded_at_utc=q["completed_at_utc"],queried_date=q["queried_at_utc"][:10],field_states={"visible_total":field})
        additions["queries"].append(record)
        additions["source-observations"].append(dict(observation_id="OBS-"+qid,query_id=qid,task_id=q["task_id"],source_id=q["source_id"],
            endpoint_or_url=q["endpoint_or_url"],queried_at_utc=q["queried_at_utc"],recorded_at_utc=q["completed_at_utc"],query_time_status="exact",
            status=record["status"],http_status=q.get("http_status"),response_kind=kind,returned_count=count,visible_total=None,page_complete=q["page_complete"],
            count_scope=record["coverage_note"],receipt_path=record["cache_path"],receipt_sha256=sha((ROOT/record["cache_path"]).read_bytes()),verification_status=record["verification_status"],
            external_request_performed=True,external_request_count=q['external_request_count'],external_request_count_basis=REQUEST_COUNT_BASIS,cache_hit=False))
    additions["tasks"].extend([*task_updates.values(),*task_new.values()])
    return changes,additions,manifest,guards,now


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--apply",action="store_true");args=parser.parse_args()
    git(ROOT,"merge-base","--is-ancestor",BASE_COMMIT,"HEAD")
    require(not (ROOT/REPORT).exists(),"Batch already integrated; use its published receipt")
    changes,additions,manifest,guards,now=build()
    schema=read(BASE/"schema.json")["x-entity-files"]
    for name in set(changes)|set(additions):
        kind=schema.get(name+".jsonl")
        if kind:
            for row in [*(x[1] for x in changes.get(name,{}).values()),*additions.get(name,[])]:
                try:gates.validate(kind,row)
                except Exception as exc:raise ValueError(f"{name} {row.get(IDS[name])}: {exc}") from exc
    print("validated", {n:len(v) for n,v in changes.items()}, {n:len(v) for n,v in additions.items()},flush=True)
    if not args.apply:return
    head=git(ROOT,"rev-parse","HEAD").decode().strip()
    require(not git(ROOT,"status","--porcelain").strip(),"Commit inputs before integration")
    with transaction_directory(ROOT) as stage:
        newmanifest=deepcopy(manifest); bindings={}
        for name in sorted(set(additions)|set(changes)):
            incoming=additions.get(name,[]); ids=[r[IDS[name]] for r in incoming]; by_id=dict(zip(ids,incoming))
            require(len(set(ids))==len(ids),"Duplicate additions in "+name)
            matched=set(); latest={}; before=hashlib.sha256(); record_log=[]
            def output():
                for raw in logical_lines(ROOT,name,manifest,guards):
                    before.update(raw);r=json.loads(raw);key=r[IDS[name]]
                    if key in by_id:
                        require(name=="tasks","Previously registered "+key)
                        latest[key]=r
                    if key in changes.get(name,{}):
                        old,new=changes[name][key];require(r==old and key not in matched,"Changed original "+key)
                        revised=encoded(new);record_log.append(dict(id=key,before_sha256=sha(raw),after_sha256=sha(revised)))
                        matched.add(key);yield revised
                    else:yield raw
                require(matched==set(changes.get(name,{})),"Missing replacement in "+name)
                for r in incoming:
                    key=r[IDS[name]]
                    if name=="tasks":
                        original=latest.get(key)
                        require(r["event_sequence"]==(original["event_sequence"]+1 if original else 1),"Task sequence "+key)
                        if original and original.get("unknown_since_utc"):
                            require(all(r[k]==original[k] for k in ["unknown_since_utc","deadline_at_utc"]),"Task clock "+key)
                    yield encoded(r)
            after=stage_dataset(stage,name,output(),manifest,newmanifest)
            bindings[name]=dict(before_logical_sha256=before.hexdigest(),after=after,changed=record_log,appended_ids=ids)
        (stage/"files/temp/partitions/manifest.json").write_bytes((json.dumps(newmanifest,indent=2,ensure_ascii=False)+"\n").encode())
        audit=dict(run_id=RUN,scope_id=SCOPE,target_checkpoint=CP,status="integrated_pending_checkpoint_qa",before_commit=head,
             reviewed_at_utc=now,integrated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),datasets=bindings,
             new_work_count=0,new_edges=0,new_resolved_occurrences=4,new_verified_context_edges=4,new_projects=1,new_project_work_relations=1,
             new_active_assessments=1,new_eligible_assessments=1,new_manual_reviews=10,external_requests=9,closed_authority_field_reviews=4,closure=False)
        path=stage/"files"/REPORT;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+"\n").encode())
        old={p["path"] for d in manifest["datasets"].values() for p in d["parts"]};live={p["path"] for d in newmanifest["datasets"].values() for p in d["parts"]}
        publish(ROOT,stage,{"temp/"+p for p in old-live if p.startswith("partitions/")},head,guards)
        print(REPORT,flush=True)


if __name__=="__main__":main()
