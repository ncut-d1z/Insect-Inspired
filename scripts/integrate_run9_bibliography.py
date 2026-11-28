"""Integrate the recorded Europe PMC/Crossref bibliographies by stable identifiers and explicit discovery paths."""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

from audit_cp10 import REQUEST_COUNT_BASIS
from checkpoint_cp10 import DIMENSIONS, TERMINAL, latest_tasks
from escalate_unknown_run7 import IDS, logical_lines, require, sha
from run9_metadata_transaction import BASE, ROOT, apply_batch, read

RUN, CP, SCOPE="RUN-0009","CP-0011","SCOPE-0001"
TARGETS={"RAY":"W-D343f06a3bc764bf6","SUNKARA":"W-R24649f4879cc831d","KRESS":"W-D3726e94bf3bda20c"}
REPORT="temp/reports/RUN-0009-bibliographic-integration.json"


def normtitle(text):
    clean=re.sub(r"<[^>]+>","",html.unescape(text or ""))
    return re.sub(r"[\W_]+","",unicodedata.normalize("NFKC",clean).casefold())


def label(text):
    return " ".join(re.sub(r"<[^>]+>","",html.unescape(text or "")).split()).rstrip(".")


def token(*pieces):
    return hashlib.sha256("\n".join(pieces).encode()).hexdigest()[:18]


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--apply",action="store_true");apply=p.parse_args().apply
    manifest=read("temp/partitions/manifest.json")
    def dataset(name):
        return (json.loads(raw) for raw in logical_lines(ROOT,name,manifest))
    facts={x["query_id"]:x for x in (json.loads(p.read_bytes()) for p in BASE.glob("query-results/Q-RUN09-BIB-*.json"))}
    require(len(facts)==15,"Incomplete bibliography query ledger")
    run=read("temp/runs/RUN-0009.json")
    require(run["external_requests_used"]==9+len(facts) and run["manual_review_items_used"]==13,"Run accounting differs")
    original={name:{r[IDS[name]]:r for r in dataset(name)} for name in ["works","authors","versions","aliases","citation-edges"]}
    latest=latest_tasks(dataset("tasks"))
    adds=defaultdict(dict);changes=defaultdict(dict)
    now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    def update(name,row):
        key=row[IDS[name]]
        if key in original.get(name,{}):changes[name][key]=(original[name][key],row)
        else:adds[name][key]=row
    def current(name,key):
        return adds[name].get(key) or (changes[name][key][1] if key in changes[name] else original[name][key])
    def push(name,row):
        k=row[IDS[name]];require(k not in adds[name] and k not in original.get(name,{}),"Duplicate new ID "+k);adds[name][k]=row
    def task(tid,etype,eid,kind,source,qids,why,state="pending"):
        if tid in adds["tasks"]: t=deepcopy(adds["tasks"][tid])
        elif tid in latest:
            t=deepcopy(latest[tid]);t["event_sequence"]+=1
        else:
            t=dict(task_id=tid,entity_type=etype,entity_id=eid,task_type=kind,scope_id=SCOPE,source_id=source,normalized_parameters={},
                   task_state=state,cursor=None,dependency_ids=[],query_ids=[],attempt_count=0,error_code=None,failure_reason=None,retry_at=None,
                   review_condition=why,created_at_utc=now,updated_at_utc=now,checkpoint_id=CP,event_sequence=1,assessment_id=None,
                   field_path=None,unknown_since_utc=None,deadline_at_utc=None,review_task_id=None,priority="normal",overdue=False,supporting_record_ids=[])
        require(t["entity_id"]==eid,"Original task entity differs "+tid)
        t.update(task_state=state,checkpoint_id=CP,updated_at_utc=now,review_condition=why,
                 failure_reason=None if state in TERMINAL else why,query_ids=list(dict.fromkeys(t["query_ids"]+qids)))
        t["supporting_record_ids"]=list(dict.fromkeys(t.get("supporting_record_ids",[])+qids))
        adds["tasks"][tid]=t;return t
    def field(etype,eid,key,why,source,when=now):
        tid="T-BIB-F-"+token(eid,key)
        t=task(tid,etype,eid,"field_review",source["source_id"],[],why)
        t.update(field_path=key,review_task_id=tid,unknown_since_utc=when,deadline_at_utc=(datetime.fromisoformat(when)+timedelta(hours=24)).isoformat().replace("+00:00","Z"))
        return dict(status="unknown",reason=why,evidence_locator=source["evidence_locator"],unknown_since_utc=when,review_task_id=tid)
    def provenance(q,ident,note,section="Bibliographic metadata"):
        url=q["endpoint_or_url"];loc=dict(source_id=q["source_id"],identifier=ident,url=url,section=section,
                                      accessed_at=q["completed_at_utc"],evidence_note=note)
        return dict(source_id=q["source_id"],identifier=ident,url=url,accessed_at=q["completed_at_utc"],
                    verification_status="source_supported",license="Bibliographic facts and original Chinese summaries only.",evidence_locator=[loc])
    def reported(source):
        return dict(status="reported",reason=None,evidence_locator=source["evidence_locator"],unknown_since_utc=None,review_task_id=None)
    def source_id(r):return str(r.get("source","MED"))+":"+str(r["id"])
    def identifiers(r):
        result={"europepmc":source_id(r)}
        if r.get("doi"):result["doi"]=r["doi"].lower()
        if r["source"]=="MED":result["pmid"]=str(r["id"])
        if r.get("pmcid"):result["pmcid"]=r["pmcid"]
        return result
    keys={w["work_key"] for w in original["works"].values()}
    names=defaultdict(set);authority=defaultdict(set);orcid=defaultdict(set)
    for w in original["works"].values():
        for t in [w["canonical_title"],*w.get("title_variants",[])]:
            if isinstance(t,str):names[normtitle(t)].add(w["work_id"])
    def idkey(k,v):
        value=str(v).casefold().strip()
        if "doi" in k.lower() or value.startswith(("10.","https://doi.org/")):return value.removeprefix("https://doi.org/")
        if k.lower() in ("pmid","pubmed","pubmed_id"):return "med:"+value
        if k.lower() in ("europepmc","pmcid"):return value
        return None
    for name in ("works","versions","aliases"):
        for v in original[name].values():
            wid=v.get("work_id") or (v.get("target_id") if v.get("entity_type")=="work" else None)
            if not wid:continue
            ids={**v.get("identifiers",{}),"doi":v.get("doi")}
            if name=="aliases":
                for k in ("raw_identifier","normalized_identifier"):
                    ids[k]=v.get(k)
            for k,val in ids.items():
                for a in val if isinstance(val,list) else [val]:
                    if a and (key:=idkey(k,a)):authority[key].add(wid)
    for person in original["authors"].values():
        if person.get("orcid"):orcid[person["orcid"].split("/")[-1]].add(person["person_id"])
    def lookup(r):
        sets=[authority[k] for k in [r.get("doi","").lower(),source_id(r).lower(),str(r.get("pmcid","")).lower()] if k and authority[k]]
        idhits=set.union(*sets) if sets else set()
        titlehits=names.get(normtitle(r.get("title")),set())
        if idhits and titlehits and idhits.isdisjoint(titlehits):return idhits|titlehits
        # Weak name-only variants require the indexed year to agree.
        if not idhits:return {wid for wid in titlehits if str(current("works",wid)["year"])==str(r.get("pubYear"))}
        return idhits
    def allocate(author,year,wid):
        family=(author or {}).get("lastName","")
        stem=re.sub("[^A-Za-z0-9_]","",unicodedata.normalize("NFKD",family).encode("ascii","ignore").decode().replace(" ","_"))
        base=(stem+str(year)) if stem and year else "Temp"+wid.replace("-","")
        out=base;n=0
        while out in keys:
            n+=1;x=n;s=""
            while x:x,k=divmod(x-1,26);s=chr(97+k)+s
            out=base+s
        keys.add(out);return out
    def byline(r,wid,source):
        people=[]
        for i,a in enumerate(r.get("authors",[]),1):
            given=a.get("firstName");family=a.get("lastName")
            display=" ".join(x for x in (given,family) if x) or a.get("collectiveName") or a.get("fullName")
            if not display:continue
            identifier=a.get("authorId",{})
            value=identifier.get("value") if isinstance(identifier,dict) and str(identifier.get("type","")).upper()=="ORCID" else None
            oid=value.rsplit("/",1)[-1] if value else None
            if oid and not re.fullmatch(r"\d{4}-\d{4}-\d{4}-[\dX]{4}",oid):oid=None
            existing=orcid.get(oid,set()) if oid else set()
            pid=next(iter(existing)) if len(existing)==1 else "P-BIB-"+token(wid,str(i),display)
            if pid not in original["authors"] and pid not in adds["authors"]:
                fs={}
                if not oid:fs["orcid"]=field("person",pid,"orcid","书目记录未给出可核验的 ORCID，署名消歧待查。",source)
                push("authors",dict(person_id=pid,display_name=display,name_variants=list(dict.fromkeys(x for x in (a.get("fullName"),display) if x)),
                       orcid=oid,external_ids={"orcid":oid} if oid else {},identity_confidence="probable",verification_status="source_supported",
                       affiliation_history=[],sources=[source],field_states=fs))
                if oid:orcid[oid].add(pid)
            people.append(dict(person_id=pid,display_name=display,given_name=given,family_name=family,is_corporate=bool(a.get("collectiveName")),
                               organization_ids=[],source=source,field_states={}))
        return people
    new_by=defaultdict(list)
    hits=Counter();human=[]
    qabs=facts["Q-RUN09-BIB-ABSTRACTS-001"];summ=read("temp/reports/RUN-0009-bibliographic-abstracts.json")
    sums={x["work_id"]:x for x in summ["items"]}
    for target,wid in TARGETS.items():
        q=facts[f"Q-RUN09-BIB-{target}-IDENTITY-001"];record=q["records"][0];w=deepcopy(current("works",wid))
        require(wid in lookup(record) and w["doi"].casefold()==record["doi"].casefold(),"DOI identity differs")
        prov=provenance(q,source_id(record),"核对同期署名、期刊、首发日期和标识符。")
        w["identifiers"].update(identifiers(record));w["discovery_sources"].append(prov)
        title=label(record["title"])
        if title!=w["canonical_title"] and title not in w["title_variants"]:w["title_variants"].append(title)
        if target=="SUNKARA" and not w["authors"]:
            people=byline(record,wid,prov);require(len(people)==3,"Sunkara byline differs")
            old=w["field_states"]["authors"].get("review_task_id")
            w["authors"]=people;w["field_states"]["authors"]=reported(prov);w["dimension_status"]["authors"]="partial"
            if old:task(old,"work",wid,"field_review","europepmc",[q["query_id"]],"Crossref 与 Europe PMC 书目均列出三位署名作者，个体消歧单列。","verified_complete")
        src=provenance(qabs,source_id(record),"根据索引中的论文摘要撰写原创中文概述。","Indexed abstract")
        v=[v for v in original["versions"].values() if v["work_id"]==wid and v["version_type"]=="version_of_record"]
        if not v:v=[v for v in original["versions"].values() if v["work_id"]==wid]
        version=v[0]["version_id"];item=sums[wid]
        if target=="SUNKARA":
            bound=deepcopy(v[0])
            require(bound["version_materialization"]=="bibliographic_only" and not bound["file_records"],"Unexpected original Sunkara file")
            bound.update(version_type="version_of_record",version_date=record["firstPublicationDate"],identifiers=identifiers(record),
                         source=prov,url="https://doi.org/"+record["doi"],verification_status="source_supported")
            update("versions",bound)
        qid=qabs["query_id"]
        w["abstract_items"].append(dict(status="chinese_summary_from_abstract",text=item["summary"],source=src,version_id=version,
            license="Original Chinese paraphrase of the indexed author abstract.",summarizer="Codex / RUN-0009",date=now[:10],source_language="en",verification_status="source_supported",field_states={}))
        # Preserve a previously displayed licensed abstract when present.
        if w["abstract_status"] in ("abstract_missing","abstract_restricted"):
            w["abstract_status"]="chinese_summary_from_abstract";w["abstract_source"]=src
        if w["dimension_status"]["abstract"]!="verified_complete":w["dimension_status"]["abstract"]="partial"
        task("T-abstract-"+wid,"work",wid,"abstract","europepmc",[qid],"已核对索引摘要并留存中文概述，原任务按资料覆盖继续复查。",w["dimension_status"]["abstract"])
        push("manual-reviews",dict(review_id="MR-RUN09-ABSTRACT-"+target,run_id=RUN,review_type="indexed_abstract_screen",entity_id=wid,
                reviewer="Codex 摘要复核",recorded_at_utc=summ["recorded_at_utc"],artifact="temp/reports/RUN-0009-bibliographic-abstracts.json",
                notes=item["boundary"]))
        update("works",w)
    print("Prepared three abstract records",flush=True)
    lookup_rows={}
    leading={};route_counts=Counter()
    actual_edges={(e["citing_key"],e["cited_key"]):e["edge_id"] for e in original["citation-edges"].values()}
    versionreview=read("temp/reports/RUN-0009-bibliographic-citation-versions.json")
    checks={x["citing_doi"]:x for x in versionreview["items"]}
    for target,kind,route in [("SUNKARA","references","backward_citation"),("RAY","citations","forward_citation")]:
        parent=TARGETS[target];parent_work=current("works",parent)
        candidates=facts[f"Q-RUN09-BIB-{target}-{kind.upper()}-001"];qp=facts[f"Q-RUN09-BIB-{target}-LIST-METADATA-001"]
        lst=candidates["records"];records={source_id(r):r for r in qp["records"]}
        require(set(records)=={source_id(r) for r in lst} and candidates["visible_total"]==len(lst)==len(records),"Incomplete source pagination")
        parent_path=parent_work["discovery_path"]
        for index,raw in enumerate(lst,1):
            sid=source_id(raw);r=records[sid];doi=r["doi"].lower()
            date=r["firstPublicationDate"]
            require(date<run["research_cutoff_at_utc"][:10],"Publication requires cutoff timestamp review")
            src=provenance(qp,sid,"书目数据库的题名、标识符、发表日期和署名。")
            relation=provenance(candidates,sid,"来源索引明确列入此书目清单，引用作用尚待核实。","Indexed "+kind+", item "+str(index))
            hit=lookup(r)
            if len(hit)>1:
                tid="T-BIB-IDENTITY-"+token(parent,sid)
                task(tid,"work",parent,"reference_identity","europepmc",[qp["query_id"]],"书目标识或题名存在多个候选，逐一核验。","needs_disambiguation")
                human.append(dict(provider_id=sid,candidates=sorted(hit),task_id=tid));continue
            if hit:wid=next(iter(hit));hits[kind+"_existing"]+=1
            else:
                wid="W-BIB-"+token(sid);require(wid not in original["works"] and wid not in adds["works"],"Conflicting new Work ID")
                people=byline(r,wid,src);authors=r.get("authors",[])
                year=int(r["pubYear"]);key=allocate(authors[0] if authors else None,year,wid)
                ids=identifiers(r);venue=r.get("journal",{}).get("title") or raw.get("journalAbbreviation")
                issue=r.get("issue_details",{});preprint=r["source"]=="PPR" or "Preprint" in r.get("pubTypeList",{}).get("pubType",[])
                path=deepcopy(parent_path)+[dict(from_entity_id=parent,to_entity_id=wid,discovery_route=route,source_id="europepmc",
                            evidence_locator=relation["evidence_locator"],verification_status="source_supported",scope_id=SCOPE)]
                tstatus={k:"pending" for k in DIMENSIONS}
                tstatus.update(metadata="partial",fulltext="restricted",authors="partial" if people else "pending")
                w=dict(work_id=wid,work_key=key,canonical_title=label(r["title"]),title_variants=[],authors=people,
                       document_type="preprint" if preprint else "journal_article",publication_status="preprint" if preprint else "published",
                       year=year,publication_date=date,venue=venue,volume=issue.get("volume"),number=issue.get("issue"),pages=r.get("pageInfo"),
                       eid=None,publisher=None,identifiers=ids,doi=doi,url="https://doi.org/"+doi,language="und",discovery_sources=[relation,src],
                       identity_confidence="probable",verification_status="source_supported",merge_history=[],fulltext_status="restricted",
                       abstract_status="abstract_restricted" if r.get("abstract_available") else "abstract_missing",abstract_source=src,abstract_items=[],
                       license="Bibliographic facts only. Indexed abstract availability is recorded separately from permission to reproduce its text.",
                       u00_reasons=["pending_assessment"],review_condition="在书目、摘要和参考文献列表范围内核查署名消歧、文献关系及检索覆盖。",
                       dimension_status=tstatus,discovery_depth=len(path),discovery_path=path,field_states={})
                for k in ("venue","volume","number","pages","eid","publisher","language"):
                    if w[k] is None or (k=="language" and w[k]=="und"):
                        w["field_states"][k]=field("work",wid,k,"当前书目回执不足以确定此字段。",src)
                if not people:w["field_states"]["authors"]=field("work",wid,"authors","待补充可核验的署名书目。",src)
                push("works",w);names[normtitle(w["canonical_title"])].add(wid);authority[doi].add(wid);authority[sid.lower()].add(wid)
                version="V-"+wid+"-01";push("versions",dict(version_id=version,work_id=wid,version_type="preprint" if preprint else "version_of_record",
                     version_date=date,identifiers=ids,source=src,url=w["url"],file_records=[],verification_status="source_supported",related_version_ids=[],
                     version_materialization="bibliographic_only",field_states={},notes="根据出版书目登记，未获取文件。"))
                push("aliases",dict(alias_id="AL-BIB-"+token(wid,doi),entity_type="work",raw_identifier=r["doi"],normalized_identifier=doi,
                     target_id=wid,historical_key=None,reason="登记索引 DOI，保留来源形式。",source=src,verification_status="source_supported",date=now[:10]))
                push("discovery-paths",dict(discovery_id="D-BIB-"+token(wid,parent),scope_id=SCOPE,work_id=wid,root_seed_id="S06",depth=len(path),
                     steps=path,source_supported_relation=True))
                for dim in DIMENSIONS:
                    task("T-"+dim+"-"+wid,"work",wid,dim,"europepmc",[],"按当前阅读范围继续该维度的书目复核。" if dim!="fulltext" else "用户限定只查阅书目信息、摘要和参考文献列表。",tstatus[dim])
                new_by[candidates["query_id"]].append(wid);hits[kind+"_new"]+=1
            w=current("works",wid)
            sourcekey,targetkey=(parent_work["work_key"],w["work_key"]) if kind=="references" else (w["work_key"],parent_work["work_key"])
            ids=[]
            if kind=="references":
                occurrence="R-BIB-"+token(parent,sid)
                string=json.dumps(raw,ensure_ascii=False,separators=(",",":"))
                push("reference-occurrences",dict(occurrence_id=occurrence,citing_work_id=parent,version_id="V-W-R24649f4879cc831d-01",
                     reference_label=None,section="Europe PMC indexed references, item "+str(index),page=None,raw_reference=string,
                     raw_fingerprint=sha(string.encode()),candidate_ids=[wid],cited_work_id=wid,identity_confidence="probable",
                     verification_status="source_supported",source=relation,failure_reason=None,
                     field_states={k:dict(status="not_applicable",reason="索引记录只给列表位置，未传递印刷页码或原文标签。",evidence_locator=relation["evidence_locator"],unknown_since_utc=None,review_task_id=None) for k in ("page","reference_label")}))
                ids=[occurrence]
            earlier=checks.get(doi) if kind=="citations" else None
            if earlier and earlier["status"]!="version_supported_by_reference":
                tid="T-BIB-CITED-VERSION-"+token(doi)
                task(tid,"work",wid,"cited_version_review","crossref",[candidates["query_id"]],"来源索引指向同一 Work 的版本组。核对所引版本 DOI 与首发日期。")
            pair=(sourcekey,targetkey);eid=actual_edges.get(pair)
            if eid:
                edge=deepcopy(current("citation-edges",eid))
                edge["occurrence_ids"]=list(dict.fromkeys(edge["occurrence_ids"]+ids))
                edge["discovery_sources"].append(relation)
            else:
                eid="CE-BIB-"+token(*pair);actual_edges[pair]=eid
                edge=dict(edge_id=eid,citing_key=sourcekey,cited_key=targetkey,occurrence_ids=ids,discovery_sources=[relation],
                          verification_status="source_supported",citation_roles=["unknown"],context_locators=[],date=now[:10])
                hits[kind+"_new_edges"]+=1
            update("citation-edges",edge)
            lookup_rows[(parent,sid)]=wid;route_counts[route]+=1
        parent_work=deepcopy(current("works",parent))
        parent_work["dimension_status"][kind]="partial";update("works",parent_work)
        cov="COV-BIB-"+target+"-"+kind.upper()
        push("source-list-coverage",dict(coverage_id=cov,entity_id=parent,source_id="europepmc",pagination_complete=True,total_reconciled=True,
             visible_total=len(lst),returned_count=len(lst),distinct_count=len(records),query_ids=[candidates["query_id"]],cursor=None,
             task_id=candidates["task_id"],coverage_note="Europe PMC 本次公开索引全页已对账。其他来源、引用版本和总体覆盖仍待查。"))
    # Register every actual attempt, including the failed projection; timestamp and count stay source-specific.
    for qid,q in sorted(facts.items()):
        success=q["status"]=="success";records=q["records"]
        result_ids=[source_id(r) if r.get("id") else r["doi"] for r in records]
        number=q["returned_count"]; prov=provenance(q,qid,"请求级书目检索回执。")
        fs={}
        if number is None:
            for key in ("returned_count","count_before_dedup","count_after_dedup","visible_total"):
                fs[key]=dict(status="not_applicable",reason="HTTP 错误响应未生成书目结果列表。",evidence_locator=prov["evidence_locator"],unknown_since_utc=None,review_task_id=None)
        mapped=new_by.get(qid,[])
        qr=dict(query_id=qid,task_id=q["task_id"],scope_id=SCOPE,checkpoint_id=CP,entity_id=q["entity_id"],source_id=q["source_id"],
                endpoint_or_url=q["endpoint_or_url"],api_version="Europe PMC REST" if q["source_id"]=="europepmc" else "Crossref REST v1",
                query_kind=q["query_kind"],raw_parameters=q["raw_parameters"],normalized_parameters=dict(q["raw_parameters"],scope_id=SCOPE),
                queried_at_utc=q["queried_at_utc"],cursor_in=q.get("cursor_in"),cursor_out=q.get("cursor_out"),page_index=q["page_index"],
                page_complete=q["page_complete"],visible_total=q["visible_total"],returned_count=number,count_before_dedup=number,
                count_after_dedup=len(set(result_ids)) if success else None,new_work_count=len(mapped),new_work_ids=mapped,result_identifiers=list(dict.fromkeys(result_ids)),
                status=q["status"],verification_status="source_supported" if success else "unverified",error_code=q.get("error_code"),error_message=q.get("error_message"),
                retry_count=int(bool(q.get("rerun_reason") and "HTTP 400" in q["rerun_reason"])),retry_at=None,cache_path="temp/query-results/"+qid+".json",
                cache_hit=False,reused_query_id=None,rerun_reason=q.get("rerun_reason"),coverage_note="本次具体检索式及来源的可见记录与分页。",
                license_note=q["license_note"],query_time_status="exact",recorded_at_utc=q["completed_at_utc"],queried_date=q["queried_at_utc"][:10],field_states=fs)
        push("queries",qr)
        push("source-observations",dict(observation_id="OBS-"+qid,query_id=qid,task_id=q["task_id"],source_id=q["source_id"],
             endpoint_or_url=q["endpoint_or_url"],queried_at_utc=q["queried_at_utc"],recorded_at_utc=q["completed_at_utc"],query_time_status="exact",
             status=qr["status"],http_status=q.get("http_status"),response_kind=q["query_kind"],returned_count=number,visible_total=q["visible_total"],page_complete=q["page_complete"],
             count_scope=qr["coverage_note"],receipt_path=qr["cache_path"],receipt_sha256=sha((ROOT/qr["cache_path"]).read_bytes()),
             external_request_performed=True,external_request_count=1,external_request_count_basis=REQUEST_COUNT_BASIS,cache_hit=False))
        tid=q["task_id"]; old=latest.get(tid);eid=old["entity_id"] if old else q["entity_id"]
        t=task(tid,"work",eid,old["task_type"] if old else "indexed_abstract_screen",q["source_id"],[qid],"已保存本次来源回执，其他来源和未决版本继续复核。",
               "partial" if old else "verified_complete")
        t["attempt_count"]+=1
    receipts={f"temp/query-results/{qid}.json":sha((BASE/"query-results"/(qid+".json")).read_bytes()) for qid in facts}
    for rel in ("temp/reports/RUN-0009-bibliographic-abstracts.json","temp/reports/RUN-0009-bibliographic-citation-versions.json","temp/reports/RUN-0009-bibliography-cutover.json"):
        receipts[rel]=sha((ROOT/rel).read_bytes())
    stats=dict(registered_works=len(adds["works"]),new_versions=len(adds["versions"]),byline_person_records=len(adds["authors"]),
               added_reference_occurrences=len(adds["reference-occurrences"]),new_citation_edges=len(adds["citation-edges"]),
               sources=15,failed_source_operations=1,abstract_reviews=3,new_eligible_assessments=0,scope_wide_closure=False)
    report=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,integrated_at_utc=now,input_receipts=receipts,counts=stats,
                matches=dict(hits),identity_conflicts=human,earlier_citation_version_counts=versionreview["counts"],
                unique_worklist=[dict(parent=parent,source_identifier=sid,work_id=wid) for (parent,sid),wid in lookup_rows.items()])
    print(json.dumps(stats,ensure_ascii=False),flush=True)
    if apply:
        apply_batch(changes,{k:list(v.values()) for k,v in adds.items() if v},report,REPORT)
        print(REPORT,flush=True)
    else:
        import gates
        schema=read("temp/schema.json")["x-entity-files"]
        for n in sorted(set(changes)|set(adds)):
            kind=schema.get(n+".jsonl")
            if kind:
                for row in [*(x[1] for x in changes.get(n,{}).values()),*adds.get(n,{}).values()]:
                    try:gates.validate(kind,row)
                    except Exception as exc:raise ValueError(f"{n} {row.get(IDS[n])} {exc}") from exc
        print("schema preview passed",flush=True)


if __name__=="__main__":
    main()
