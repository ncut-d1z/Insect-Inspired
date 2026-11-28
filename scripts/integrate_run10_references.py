"""Integrate bibliographic evidence from RUN10. Retain unmatched reference occurrences and their cursors."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata
from urllib.parse import quote

from audit_cp10 import REQUEST_COUNT_BASIS
from checkpoint_cp10 import DIMENSIONS, TERMINAL
from escalate_unknown_run7 import IDS, require
from run9_metadata_transaction import apply_batch
from run10_reference_records import clean, doi, existing, fields, metadata, norm, source_lists, token
from search_run10_references import CP, FRONTIER, OUT, ROOT, RUN, SCOPE, TEMP, read, stamp
from storage import iter_logical


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(q, identifier, section, note):
    url=q["endpoint_or_url"]
    if q["source_id"]=="crossref" and doi(identifier):
        url="https://api.crossref.org/works/"+quote(identifier,safe="/")
    elif q["source_id"]=="europepmc" and re.fullmatch(r"(MED|PPR):[A-Z0-9]+",identifier):
        url="https://europepmc.org/article/"+identifier.replace(":","/")
    elif q["source_id"]=="openalex" and re.fullmatch(r"W[0-9]+",identifier):
        url="https://api.openalex.org/works/"+identifier
    loc=dict(source_id=q["source_id"],identifier=identifier,url=url,section=section,
             accessed_at=q["completed_at_utc"],evidence_note=note+" "+q["query_id"])
    return dict(source_id=q["source_id"],identifier=identifier,url=url,accessed_at=q["completed_at_utc"],
                verification_status="source_supported",license="Public bibliographic facts and reference-list metadata.",evidence_locator=[loc])


def nonapplicable(src,reason):
    return dict(status="not_applicable",reason=reason,evidence_locator=src["evidence_locator"],unknown_since_utc=None,review_task_id=None)


def document_type(r):
    types=r.get("publication_types",[])
    if r.get("document_type")=="posted-content" or "Preprint" in types:return "preprint"
    mapping={"journal-article":"journal_article","proceedings-article":"conference_paper","book":"book","monograph":"book",
             "edited-book":"book","reference-book":"book","book-chapter":"book_chapter","book-section":"book_chapter",
             "book-part":"book_chapter","reference-entry":"book_chapter","dissertation":"thesis","report":"technical_report",
             "dataset":"dataset","software":"software"}
    if r.get("document_type") in mapping:return mapping[r["document_type"]]
    if "Journal Article" in types or ((r.get("epmc") or "").startswith("MED:") and r.get("venue")):return "journal_article"
    return "other"


def conflicting_title(raw,provider,registered):
    # Container and series titles describe a different entity. Only explicit work
    # titles can contradict an identifier. Similarity never establishes a match.
    stated=raw.get("title") if provider=="europepmc" else raw.get("article-title") or raw.get("chapter-title")
    a,b=norm(stated),norm(registered)
    if not a or not b or a in b or b in a:return False
    return SequenceMatcher(None,a,b,autojunk=False).ratio()<0.55


def reference_source(q,owner,position):
    sid=q["source_id"]
    label={"crossref":"Publisher-deposited reference","europepmc":"Europe PMC indexed reference","openalex":"OpenAlex reference ID (index position)"}[sid]
    locator=owner.get("epmc") if sid=="europepmc" else q.get("corrected_identifier") or owner.get("doi")
    if sid=="openalex":
        locator=(q.get("source_bibliography") or {}).get("id") or owner.get("openalex") or owner.get("epmc")
        locator=locator.rsplit("/",1)[-1] if locator else None
    section=f"{label} {position}"
    return section,source(q,locator or owner["work_id"],section,"仅核实书目出现及索引身份，引用作用待核实。")


class Batch:
    def __init__(self):
        self.works,self.identities,self.names=existing()
        self.original_works=set(self.works)
        self.keys={w["work_key"] for w in self.works.values()}
        self.retired=defaultdict(set)
        for alias in iter_logical("aliases.jsonl",TEMP):
            if alias.get("historical_key"):self.retired[alias["historical_key"]].add(alias["target_id"])
        for merged in iter_logical("merged-work-audit.jsonl",TEMP):
            if merged.get("work_key"):self.keys.add(merged["work_key"])
        self.keys.update(self.retired)
        self.versions=list(iter_logical("versions.jsonl",TEMP))
        self.latest={t["task_id"]:t for t in iter_logical("tasks.jsonl",TEMP)}
        self.edges={(r["citing_key"],r["cited_key"]):r for r in iter_logical("citation-edges.jsonl",TEMP)}
        self.people={r["person_id"]:r for r in iter_logical("authors.jsonl",TEMP)}
        self.orcids=defaultdict(set)
        for person in self.people.values():
            if person.get("orcid"):self.orcids[person["orcid"].rsplit("/",1)[-1]].add(person["person_id"])
        self.adds=defaultdict(dict)
        self.changes=defaultdict(dict)
        self.now=stamp()
        self.source_credit=defaultdict(list)
        self.metas=defaultdict(list)
        self.registry_titles=defaultdict(set)
        for r,q in metadata():
            identifiers={r.get("doi"),r.get("epmc"),r.get("openalex"),r.get("requested_openalex")} - {"",None}
            if r.get("title") and r.get("year"):
                self.registry_titles[norm(r["title"]),str(r["year"])].update(identifiers)
            for k in identifiers:
                self.metas[k].append((r,q))
        self.resolution=Counter()
        self.new_frontier=[]
        self.stats=Counter()
        self.input_paths=set()
        self.task_queries=defaultdict(set)
        self.cutoff=read(TEMP/"snapshots/scope.json")["cutoff_at_utc"][:10]
        self.roots={}
        for row in iter_logical("discovery-paths.jsonl",TEMP):
            wid=row.get("work_id")
            if wid in self.works and row.get("root_seed_id") and row.get("steps")==self.works[wid].get("discovery_path"):
                self.roots.setdefault(wid,row["root_seed_id"])
        self.known_queries={r["query_id"] for r in iter_logical("queries.jsonl",TEMP)}
        self.cited_version_reviews={(r["work_id"],"W-D343f06a3bc764bf6"):r
            for r in read(TEMP/"reports/RUN-0010-cited-versions.json")["items"]}

    def add(self,name,row):
        key=row[IDS[name]]
        require(key not in self.adds[name],"Duplicate RUN10 record "+key)
        self.adds[name][key]=row
        return row

    def modify(self,name,old,row):
        key=row[IDS[name]]
        if key in self.adds[name]:
            self.adds[name][key]=row
        else:
            first=self.changes[name].get(key,(old,None))[0]
            self.changes[name][key]=(first,row)

    def task(self,tid,eid,kind,why,state="pending",qids=(),etype="work",source_id="europepmc"):
        t=self.adds["tasks"].get(tid)
        if t is None:
            if tid in self.latest:
                t=deepcopy(self.latest[tid]);t["event_sequence"]+=1
                require(t["entity_id"]==eid,"Inherited task owner changed "+tid)
            else:
                t=dict(task_id=tid,entity_type=etype,entity_id=eid,task_type=kind,scope_id=SCOPE,source_id=source_id,
                       normalized_parameters={},cursor=None,dependency_ids=[],query_ids=[],attempt_count=0,
                       error_code=None,retry_at=None,created_at_utc=self.now,event_sequence=1,assessment_id=None,
                       field_path=None,unknown_since_utc=None,deadline_at_utc=None,review_task_id=None,priority="normal",
                       overdue=False,supporting_record_ids=[])
            self.adds["tasks"][tid]=t
        t.update(task_state=state,updated_at_utc=self.now,checkpoint_id=getattr(self,"checkpoint",CP),review_condition=why,
                 failure_reason=None if state in TERMINAL else why)
        t["query_ids"]=list(dict.fromkeys([*t["query_ids"],*qids]))
        t["supporting_record_ids"]=list(dict.fromkeys([*t.get("supporting_record_ids",[]),*qids]))
        return t

    def unknown(self,etype,eid,key,src):
        tid="T-"+getattr(self,"id_prefix","R10")+"-F-"+token(eid,key)
        reason="当前已核对的书目字段不足，待以独立来源补核。"
        t=self.task(tid,eid,"field_review",reason,etype=etype,source_id=src["source_id"])
        when=t.get("unknown_since_utc") or self.now
        t.update(field_path=key,review_task_id=tid,unknown_since_utc=when,
                 deadline_at_utc=t.get("deadline_at_utc") or (datetime.fromisoformat(when)+timedelta(hours=24)).isoformat().replace("+00:00","Z"))
        return dict(status="unknown",reason=reason,evidence_locator=src["evidence_locator"],unknown_since_utc=when,review_task_id=tid)

    def people_for(self,work,record,src):
        result=[]
        for rank,a in enumerate(record.get("authors",[]),1):
            first,last=a.get("firstName"),a.get("lastName")
            display=clean(" ".join(filter(None,(first,last))) or a.get("collectiveName") or a.get("fullName"))
            if not display:continue
            info=a.get("authorId") or {}
            oid=(info.get("value") or "").rsplit("/",1)[-1] if isinstance(info,dict) and str(info.get("type") or "").upper()=="ORCID" else ""
            if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-[\dX]{4}",oid):oid=""
            known=self.orcids[oid] if oid else set()
            pid=next(iter(known)) if len(known)==1 else "P-"+getattr(self,"id_prefix","R10")+"-"+token(work,rank,display)
            if pid not in self.people:
                fs={} if oid else {"orcid":self.unknown("person",pid,"orcid",src)}
                row=dict(person_id=pid,display_name=display,name_variants=[display],orcid=oid or None,
                         external_ids={"orcid":oid} if oid else {},identity_confidence="probable",
                         verification_status="source_supported",affiliation_history=[],sources=[src],field_states=fs)
                self.people[pid]=self.add("authors",row)
                if oid:self.orcids[oid].add(pid)
            if oid:self.stats["bylines_with_orcid"]+=1
            self.stats["bylines"]+=1
            result.append(dict(person_id=pid,display_name=display,given_name=first,family_name=last,
                               is_corporate=bool(a.get("collectiveName")),organization_ids=[],source=src,field_states={}))
        return result

    @staticmethod
    def key_base(family,year,wid):
        spaced=re.sub(r"\s+","_",unicodedata.normalize("NFKD",family.strip()))
        stem=re.sub("[^a-zA-Z0-9_]","",spaced.encode("ascii","ignore").decode()).strip("_")
        return stem+str(year) if stem else "Temp"+wid.replace("-","")

    def allocate_key(self,base):
        key=base;n=0
        while key in self.keys:
            n+=1;s="";m=n
            while m:
                m,i=divmod(m-1,26);s=chr(97+i)+s
            key=base+s
        self.keys.add(key);return key

    def bibliographic_keys(self):
        path=TEMP/"reports/RUN-0010-integration-initial-79.json"
        if not path.is_file():return []
        initial=read(path);self.input_paths.add(path);log=[];replace={}
        for wid in initial["datasets"]["works"]["appended_ids"]:
            old=self.works[wid];key=old["work_key"];authors=old["authors"] or [{}]
            family=authors[0].get("family_name") or "";base=self.key_base(family,old["year"],wid)
            retired=bool(self.retired.get(key,set())-{wid})
            if not retired and (not re.search(r"\s",family.strip()) or re.fullmatch(re.escape(base)+"[a-z]*",key)):continue
            corrected=self.allocate_key(base);w=deepcopy(old);w["work_key"]=corrected
            self.modify("works",old,w);self.works[wid]=w;replace[key]=corrected
            src=w["discovery_sources"][-1]
            if not retired:
                self.add("aliases",dict(alias_id="AL-R10-KEY-"+token(wid,key),entity_type="work",raw_identifier=key,normalized_identifier=key,
                    target_id=wid,historical_key=key,reason="按已登记署名的空白转写修正 BibTeX key，保留原有定位。",source=src,
                    verification_status="source_supported",date=self.now[:10]))
            log.append(dict(work_id=wid,prior_key=key,corrected_key=corrected,prior_key_owner=sorted(self.retired.get(key,set())),
                            reason="retired_key_collision" if retired else "whitespace_transliteration"))
        for pair,edge in list(self.edges.items()):
            revised=tuple(replace.get(k,k) for k in pair)
            if pair==revised:continue
            require(revised not in self.edges,"Rekey would merge two edges")
            row=deepcopy(edge);row["citing_key"],row["cited_key"]=revised
            self.modify("citation-edges",edge,row);del self.edges[pair];self.edges[revised]=row
        return log

    def enroll(self,record,mq,owner,relation,ids,discovery_query_id):
        primary=record.get("doi") or record.get("epmc") or record["openalex"]
        tag=getattr(self,"id_prefix","R10")
        wid="W-"+tag+"-"+token(primary)
        require(wid not in self.works and record["year"] and record["title"],"Unbound Work "+wid)
        locator=record.get("source_identifier") or primary
        src=source(mq,locator,"Bibliographic metadata","作者署名、题名、标识和出版信息。")
        people=self.people_for(wid,record,src)
        dim={k:"pending" for k in DIMENSIONS}
        dim.update(metadata="partial",fulltext="restricted",authors="partial" if people else "pending")
        pk=owner["work_id"];parent=self.works[pk]
        path=[*parent["discovery_path"],dict(from_entity_id=pk,to_entity_id=wid,discovery_route=getattr(self,"discovery_route","backward_citation"),
             source_id=relation["source_id"],evidence_locator=relation["evidence_locator"],verification_status="source_supported",scope_id=SCOPE)]
        ids_meta={}
        if record.get("doi"):ids_meta["doi"]=record["doi"]
        if record.get("epmc"):
            ids_meta["europepmc"]=record["epmc"]
            if record["epmc"].startswith("MED:"):ids_meta["pmid"]=record["epmc"].split(":")[1]
        if record.get("pmcid"):ids_meta["pmcid"]=record["pmcid"]
        if record.get("openalex"):ids_meta["openalex"]=record["openalex"]
        if record.get("doi"):url="https://doi.org/"+record["doi"]
        elif record.get("epmc"):url="https://europepmc.org/article/"+record["epmc"].replace(":","/")
        else:url="https://openalex.org/"+record["openalex"]
        typ=document_type(record);family=(record.get("authors") or [{}])[0].get("lastName") or ""
        key=self.allocate_key(self.key_base(family,record["year"],wid))
        w=dict(work_id=wid,work_key=key,canonical_title=record["title"],title_variants=[],authors=people,document_type=typ,
               publication_status="preprint" if typ=="preprint" else "published",year=record["year"],publication_date=record.get("date"),
               venue=record.get("venue"),volume=record.get("volume"),number=record.get("number"),pages=record.get("pages"),
               eid=record.get("eid"),publisher=record.get("publisher"),identifiers=ids_meta,doi=record.get("doi") or None,url=url,
               language=record.get("language") or "und",discovery_sources=[relation,src],identity_confidence="probable",
               verification_status="source_supported",merge_history=[],fulltext_status="restricted",
               abstract_status="abstract_restricted" if record.get("abstract_available") else "abstract_missing",abstract_source=src,
               abstract_items=[],license="Public bibliographic facts. No attachment or article body obtained.",
               u00_reasons=["pending_assessment"],review_condition="按书目、摘要及参考列表继续消歧与扩展。",
               dimension_status=dim,discovery_depth=len(path),discovery_path=path,field_states={})
        for k in ("doi","venue","volume","number","pages","eid","publisher","language","publication_date","authors"):
            if not w[k] or (k=="language" and w[k]=="und"):w["field_states"][k]=self.unknown("work",wid,k,src)
        self.works[wid]=self.add("works",w);self.names[(norm(w["canonical_title"]),str(w["year"]))].add(wid)
        for k in ids:self.identities[k].add(wid)
        vid="V-"+wid+"-01"
        v=dict(version_id=vid,work_id=wid,version_type="preprint" if typ=="preprint" else "version_of_record",
               version_date=w["publication_date"],identifiers=ids_meta,source=src,url=url,file_records=[],
               verification_status="source_supported",related_version_ids=[],version_materialization="bibliographic_only",field_states={},
               notes="由版本书目登记。没有取得文件。")
        if mq["source_id"]=="openalex" and typ!="preprint" and record.get("location_version")!="publishedVersion":
            v["version_type"]="unknown";v["field_states"]["version_type"]=self.unknown("version",vid,"version_type",src)
        if not v["version_date"]:v["field_states"]["version_date"]=self.unknown("version",vid,"version_date",src)
        self.add("versions",v)
        self.add("aliases",dict(alias_id="AL-"+tag+"-"+token(wid,primary),entity_type="work",raw_identifier=primary,normalized_identifier=primary,
                 target_id=wid,historical_key=None,reason="公开书目稳定标识。",source=src,verification_status="source_supported",date=self.now[:10]))
        parent_discovery=self.roots.get(pk)
        self.add("discovery-paths",dict(discovery_id="D-"+tag+"-"+token(wid,pk),scope_id=SCOPE,work_id=wid,root_seed_id=parent_discovery,
                 depth=len(path),steps=path,source_supported_relation=True))
        self.roots[wid]=parent_discovery
        for dimname,state in dim.items():
            self.task("T-"+dimname+"-"+wid,wid,dimname,"继承发现路径，按允许资料继续检索与核验。",state,source_id=mq["source_id"])
        self.new_frontier.append(dict(work_id=wid,work_key=key,doi=w["doi"],epmc=ids_meta.get("europepmc"),
                                  task_id="T-references-"+wid,prior_cursor=None,prior_state="pending",prior_event=1,
                                  openalex=ids_meta.get("openalex"),depth=len(path),parent_work_id=pk))
        if getattr(self,"credit_discovery",False):
            credit=discovery_query_id
        else:
            credit=mq["query_id"] if mq["query_id"] not in self.known_queries else discovery_query_id
            require(credit not in self.known_queries,"Discovery needs a current query for "+wid)
        self.source_credit[credit].append(wid)
        return wid

    def resolve(self,raw,q,owner,relation):
        d,e,title,year,author=fields(raw,q["source_id"])
        ids={x for x in (d,e) if x}
        if q["source_id"]=="openalex" and raw.get("openalex"):ids.add(raw["openalex"])
        alternatives=[pair for ident in sorted(ids) for pair in self.metas.get(ident,[])]
        derived_dois={r["doi"] for r,_ in alternatives if r.get("doi")}
        if len(derived_dois | ({d} if d else set()))>1:
            return None,sorted(ids|derived_dois),"metadata_identifier_conflict"
        for r,_ in alternatives:
            ids.update(x for x in (r.get("doi"),r.get("epmc"),r.get("openalex")) if x)
        hit=set().union(*(self.identities.get(k,set()) for k in ids))
        titles=self.names.get((norm(title),year),set()) if title and year else set()
        explicit=raw.get("title") if q["source_id"]=="europepmc" else raw.get("article-title") or raw.get("chapter-title")
        other_ids=self.registry_titles.get((norm(explicit),year),set()) if explicit and year else set()
        if ids and other_ids and ids.isdisjoint(other_ids) and not hit.intersection(titles):
            return None,sorted(ids|other_ids|titles|hit),"identifier_title_conflict"
        if len(hit)>1 or (hit and titles and hit.isdisjoint(titles)):
            return None,sorted(hit|titles|ids),"canonical_identity_conflict"
        if hit:
            target=next(iter(hit));w=self.works[target]
            titles=[w["canonical_title"],*[v for v in w.get("title_variants",[]) if isinstance(v,str)]]
            if (owner["work_id"],target) not in self.cited_version_reviews and all(conflicting_title(raw,q["source_id"],t) for t in titles):
                return None,sorted(hit|ids),"identifier_title_conflict"
            return target,sorted(ids),"identifier"
        if len(titles)==1 and author:
            wid=next(iter(titles));people=self.works[wid].get("authors") or []
            if people:
                family=norm(people[0].get("family_name") or "")
                if len(family)>=3 and family in norm(re.split(r"[,;]",author)[0]):
                    return wid,sorted(ids),"title_year_byline"
        if titles:return None,sorted(titles|ids),"title_identity_open"
        valid=[(r,mq) for r,mq in alternatives if r.get("title") and r.get("year")]
        if valid:
            # Prefer an explicit Europe PMC crosswalk when the two records share a DOI.
            valid.sort(key=lambda x:(not bool(x[0].get("epmc")),not bool(x[0].get("authors")),x[1]["query_id"]))
            record,mq=valid[0]
            if conflicting_title(raw,q["source_id"],record["title"]):
                return None,sorted(ids),"identifier_title_conflict"
            reg_titles=self.names.get((norm(record["title"]),str(record["year"])),set())
            if reg_titles:
                return None,sorted(reg_titles|ids),"registered_title_identity_open"
            if record["year"]>int(self.cutoff[:4]) or (record["year"]==int(self.cutoff[:4]) and (not record.get("date") or
                    len(record["date"])<10 or record["date"][:10]>=self.cutoff)):
                return None,sorted(ids),"cutoff_date_review"
            return self.enroll(record,mq,owner,relation,ids,q["query_id"]),sorted(ids),"new_bibliographic_identity"
        return None,sorted(ids),"identifier_or_metadata_missing"

    def backward(self,queue):
        by_owner=defaultdict(list)
        wanted={o["work_id"] for o in queue}
        attempts=defaultdict(lambda:defaultdict(list))
        for p in sorted(OUT.glob("Q-RUN10-*.json")):
            if not p.name.startswith(("Q-RUN10-VCR-","Q-RUN10-BCR-","Q-RUN10-VEP-","Q-RUN10-BEP-","Q-RUN10-RCR-","Q-RUN10-REP-","Q-RUN10-ROA-","Q-RUN10-F-OA-","Q-RUN10-F-DOI-")):continue
            q=read(p)
            for own in q["owners"]:
                if own["work_id"] in wanted:attempts[own["work_id"]][q["source_id"]].append(q["query_id"])
        for owner,q,refs,declared,present in source_lists(queue):
            by_owner[owner["work_id"]].append((q,refs,declared,present))
        # Resolve printed title/year/byline entries against the complete batch,
        # including registry identities first encountered on a later source page.
        admissions={}
        for owner in queue:
            wid=owner["work_id"]
            require(wid in self.roots,"Missing admitted seed path "+wid)
            for q,refs,_,_ in by_owner[wid]:
                start=(int(q.get("page_index",1))-1)*1000
                for i,raw in enumerate(refs,start+1):
                    d,e,*_=fields(raw,q["source_id"])
                    if not any(k in self.metas for k in (d,e,raw.get("openalex")) if k):continue
                    _,relation=reference_source(q,owner,i)
                    target,_,reason=self.resolve(raw,q,owner,relation)
                    if reason=="new_bibliographic_identity":admissions[wid,q["query_id"],i]=target
        outcomes=[]
        for owner in queue:
            wid=owner["work_id"];work=self.works[wid];seen_sources=defaultdict(list)
            for provider,identifier in (("crossref","doi"),("europepmc","epmc")):
                if owner.get(identifier):require(attempts[wid].get(provider),"Unvisited source cursor "+wid+" "+provider)
            candidates=[v for v in self.versions if v["work_id"]==wid]
            exact=[v for v in candidates if owner.get("doi") and any(doi(t)==owner["doi"].lower() for t in v.get("identifiers",{}).values() if isinstance(t,str))]
            if len(candidates)==1:version=candidates[0]
            elif len(exact)==1:version=exact[0]
            else:raise ValueError("Ambiguous source Version "+wid)
            require(wid in self.roots,"Missing admitted seed path "+wid)
            counts=Counter();tids=set().union(*map(set,attempts[wid].values()));seen_occurrences=set();lists=[]
            for q,refs,declared,present in by_owner[wid]:
                sid=q["source_id"];qid=q["query_id"];self.input_paths.add(OUT/(qid+".json"))
                tids.add(qid);seen_sources[sid].append(qid)
                if sid=="crossref":
                    require(len(seen_sources[sid])==1,"Duplicate deposited list for "+wid)
                complete=present and declared is not None and (len(refs)==declared if sid=="crossref" else q["page_complete"])
                lists.append(dict(source_id=sid,query_id=qid,rows=len(refs),visible_total=declared,source_reconciled=complete))
                start=(int(q.get("page_index",1))-1)*1000
                for i,raw in enumerate(refs,start+1):
                    section,relation=reference_source(q,owner,i)
                    label=raw.get("key") if sid=="crossref" else raw.get("citedOrder")
                    ref_id="R-R10-"+token(wid,version["version_id"],sid,i)
                    require(ref_id not in seen_occurrences,"Duplicate provider reference position");seen_occurrences.add(ref_id)
                    target,choices,reason=self.resolve(raw,q,owner,relation)
                    if (wid,qid,i) in admissions:
                        require(target==admissions[wid,qid,i],f"Discovery and registered identity disagree {wid} {qid} {i}: admitted {admissions[wid,qid,i]}, now {target}, {reason}, {choices}")
                        reason="new_bibliographic_identity"
                    if target==wid:target=None;reason="possible_reference_to_another_version"
                    raw_text=raw.get("unstructured") if sid=="crossref" and raw.get("unstructured") else json.dumps(raw,ensure_ascii=False,separators=(",",":"))
                    fs={"page":nonapplicable(relation,"索引没有提供施引书目所在印刷页。")}
                    if label is None:fs["reference_label"]=nonapplicable(relation,"来源未给条目标识，已保存登记位置。")
                    self.add("reference-occurrences",dict(occurrence_id=ref_id,citing_work_id=wid,version_id=version["version_id"],
                             reference_label=str(label) if label is not None else None,section=section,page=None,raw_reference=raw_text,
                             raw_fingerprint=hashlib.sha256(raw_text.encode()).hexdigest(),candidate_ids=choices,cited_work_id=target,
                             identity_confidence="probable" if target else ("ambiguous" if choices else "unresolved"),
                             verification_status="source_supported" if target else "unverified",source=relation,
                             failure_reason=None if target else reason,field_states=fs))
                    self.resolution[reason]+=1;counts["occurrences"]+=1
                    if not target:
                        counts["unresolved"]+=1
                        t=self.task("T-R10-IDENT-"+token(ref_id),wid,"reference_identity",reason,"needs_disambiguation",[qid],source_id=sid)
                        t["normalized_parameters"]={"occurrence_id":ref_id,"candidate_ids":choices}
                        continue
                    counts["resolved"]+=1
                    cited=self.works[target]
                    if (version.get("version_date") and cited.get("publication_date") and
                        len(version["version_date"])==len(cited["publication_date"])==10 and cited["publication_date"]>version["version_date"]):
                        checked=self.cited_version_reviews.get((wid,target))
                        if not checked or not checked["original_citing_record_revision"]:
                            tid=checked["task_id"] if checked else "T-R10-CITED-"+token(wid,target)
                            old=self.latest.get(tid,{})
                            t=self.task(tid,wid,"cited_version_review",old.get("review_condition") or
                                  "被引 Work 所示日期晚于施引版本。只记 Work 级索引关系，待核实实际引用的版本。","needs_disambiguation",[qid],source_id=sid)
                            t["supporting_record_ids"]=list(dict.fromkeys([*t["supporting_record_ids"],ref_id]))
                            counts["later_dated_occurrences_for_review"]+=1
                    pair=(work["work_key"],self.works[target]["work_key"])
                    if pair in self.edges:
                        edge=self.edges[pair]
                        if edge["edge_id"] not in self.adds["citation-edges"] and edge["edge_id"] not in self.changes["citation-edges"]:
                            original=edge;edge=deepcopy(edge);self.modify("citation-edges",original,edge);self.edges[pair]=edge
                        edge["occurrence_ids"].append(ref_id)
                        if not any(s["source_id"]==sid and s.get("identifier")==relation["identifier"] and
                                   any(qid in l.get("evidence_note","") for l in s["evidence_locator"]) for s in edge["discovery_sources"]):
                            edge["discovery_sources"].append(relation)
                    else:
                        self.edges[pair]=self.add("citation-edges",dict(edge_id="CE-R10-"+token(*pair),citing_key=pair[0],cited_key=pair[1],
                            occurrence_ids=[ref_id],discovery_sources=[relation],verification_status="source_supported",
                            citation_roles=["unknown"],context_locators=[],date=self.now[:10]))
                        counts["new_edges"]+=1
            for sid,qids in seen_sources.items():
                selected=[v for v in lists if v["source_id"]==sid]
                declared=selected[-1]["visible_total"];n=sum(v["rows"] for v in selected)
                complete=selected[-1]["source_reconciled"] and n==declared
                self.add("source-list-coverage",dict(coverage_id="COV-R10-"+token(wid,sid),entity_id=wid,source_id=sid,
                         pagination_complete=bool(complete),total_reconciled=bool(complete),visible_total=declared,returned_count=n,
                         distinct_count=None,query_ids=qids,cursor=None if complete else "source_review",task_id=owner["task_id"],
                         coverage_note="按来源位置计数。索引零条、登记缺失或两个数据库条数不同均不证明原文无参考文献。"))
            state="partial" if counts["occurrences"] else "pending"
            reason="已保存来源分页、书目位置与逐项身份。未覆盖来源及未解身份继续复核。" if counts["occurrences"] else "本次来源未提供可用条目，保留其他书目来源工单。"
            t=self.task(owner["task_id"],wid,"references",reason,state,sorted(tids))
            t["cursor"]="source_reconciliation"
            w=deepcopy(work);w["dimension_status"]["references"]=state;self.modify("works",work,w);self.works[wid]=w
            outcomes.append(dict(work_id=wid,task_id=owner["task_id"],source_lists=lists,query_attempt_ids=dict(attempts[wid]),counts=dict(counts),task_state=state))
        return outcomes

    def reference_coverage(self,outcomes):
        prior={r["work_id"] for r in iter_logical("reference-coverage.jsonl",TEMP)}
        first=TEMP/"reports/RUN-0010-integration-initial-79.json"
        prior_outcomes=read(first)["coverage"] if first.is_file() else []
        pending={r["work_id"]:r for r in [*prior_outcomes,*outcomes] if r["work_id"] not in prior}
        if not pending:return
        if prior_outcomes:self.input_paths.add(first)
        targets=defaultdict(set);positions=Counter();unresolved=Counter()
        def observe(ref):
            wid=ref["citing_work_id"]
            if wid not in pending or not ref["occurrence_id"].startswith("R-R10-"):return
            pair=(wid,ref["source"]["source_id"]);positions[pair]+=1
            if ref["cited_work_id"]:targets[pair].add(ref["cited_work_id"])
            else:unresolved[pair]+=1
        for ref in iter_logical("reference-occurrences.jsonl",TEMP):observe(ref)
        for ref in self.adds["reference-occurrences"].values():observe(ref)
        for wid,item in pending.items():
            pages=item["source_lists"];attempts=item["query_attempt_ids"]
            cr=next((p for p in pages if p["source_id"]=="crossref"),None)
            source_coverage={}
            for provider,ids in attempts.items():
                reported=sum(p["rows"] for p in pages if p["source_id"]==provider)
                require(reported==positions[wid,provider],"Unreconciled per-source occurrences for "+wid)
                source_coverage[provider]=dict(queries=ids,returned_positions=reported,distinct_resolved_work_count=len(targets[wid,provider]),
                                               unresolved_positions=unresolved[wid,provider])
            all_targets=set().union(*(targets[wid,s] for s in attempts));all_queries=[q for ids in attempts.values() for q in ids]
            require(all_queries and sum(v["returned_positions"] for v in source_coverage.values())==item["counts"].get("occurrences",0),"Unbound source coverage")
            self.add("reference-coverage",dict(work_id=wid,doi=self.works[wid].get("doi"),query_id=cr["query_id"] if cr else all_queries[0],
                     deposited_reference_count=cr["visible_total"] if cr else None,returned_reference_count=cr["rows"] if cr else None,
                     original_fulltext_completeness="not_verified",indexed_sources=source_coverage,distinct_resolved_works=len(all_targets),
                     coverage_note="登记列表和索引位置按来源对账。原文书目边界及未解析位置继续开放。"))

    def version_reviews(self):
        path=TEMP/"reports/RUN-0010-cited-versions.json";report=read(path)
        self.input_paths.add(path)
        for item in report["items"]:
            tid=item["task_id"];old=self.latest[tid];require(old["entity_id"]==item["work_id"],"Cited-version owner differs")
            state="verified_complete" if item["exact_original_status"]=="supported" else "needs_disambiguation"
            t=self.task(tid,old["entity_id"],old["task_type"],item["interpretation"],state,item["supporting_query_ids"])
            rid="MR-R10-VERSION-"+token(item["doi"])
            t["supporting_record_ids"].append(rid)
            t["cursor"]=None if state=="verified_complete" else "original_citing_version_bibliography"
            self.add("manual-reviews",dict(review_id=rid,run_id=RUN,review_type="original_cited_version_bibliography",
                     entity_id=item["work_id"],reviewer="Codex 书目复核",recorded_at_utc=report["verified_at_utc"],
                     artifact=path.relative_to(ROOT).as_posix(),notes=item["interpretation"]))
        target="W-D343f06a3bc764bf6"
        primary="V-W-D343f06a3bc764bf6-01"
        bq=read(OUT/"Q-RUN10-VBIO-024703-A1.json");cq=read(OUT/"Q-RUN10-VTARGET-A1.json")
        for r in bq["records"]:
            if r["version"]=="1":continue
            identifier=r["doi"]+"v"+r["version"]
            src=source(bq,identifier,"bioRxiv metadata, version "+r["version"],"出版者登记的修订号、题名和日期。")
            self.add("versions",dict(version_id="V-R10-RAY-BIORXIV-"+r["version"],work_id=target,version_type="preprint",
                     version_date=r["date"],identifiers={"biorxiv_revision":identifier},source=src,
                     url="https://www.biorxiv.org/content/"+identifier,file_records=[],verification_status="source_supported",
                     related_version_ids=["V-W-D6538264ebfa49876-01"],version_materialization="bibliographic_only",
                     field_states={},notes=r["title"]))
        r=next(r for r in cq["records"] if doi(r["DOI"])=="10.7554/elife.102230.2");d=doi(r["DOI"])
        parts=r["published"]["date-parts"][0];src=source(cq,d,"Crossref posted-content registration","eLife 评审预印本第二版。")
        self.add("versions",dict(version_id="V-R10-RAY-ELIFE-2",work_id=target,version_type="preprint",
                 version_date="%04d-%02d-%02d"%tuple(parts),identifiers={"doi":d},source=src,url="https://doi.org/"+d,file_records=[],
                 verification_status="source_supported",related_version_ids=["V-CP4-Rayshubskiy-2024-reviewed-preprint",primary],
                 version_materialization="bibliographic_only",field_states={},notes="登记的第二版评审预印本。"))
        d="10.7554/elife.102230.3";src=source(cq,d,"Crossref version-of-record registration","与基础 DOI 同日、同文、同版本的登记标识。")
        self.add("aliases",dict(alias_id="AL-R10-RAY-ELIFE-3",entity_type="version",raw_identifier=d,normalized_identifier=d,
                 target_id=primary,historical_key=None,reason="将正式版的带后缀 DOI 映射到已有正式 Version。",source=src,
                 verification_status="source_supported",date=self.now[:10]))

    def corrected_doi(self):
        report=read(TEMP/"reports/RUN-0010-supplemental-reference-coverage.json")["corrected_parent_doi"]
        wid=report["work_id"];old=self.works[wid];d=report["canonical"]
        if old.get("doi")==d:return
        require(old.get("doi")==report["prior"] and not self.identities.get(d),"Canonical DOI requires disambiguation")
        cr,oa=(read(OUT/(i+".json")) for i in report["source_queries"])
        record=cr["records"][0];meta=oa["source_bibliography"]
        require(norm(record["title"][0])==norm(old["canonical_title"]) and doi(meta["doi"])==d and
                meta["ids"]["pmid"].rsplit("/",1)[-1]==old["identifiers"]["pmid"] and record["published"]["date-parts"][0][0]==old["year"],
                "Correction requires agreement on title, PMID and year")
        src=source(cr,d,"Crossref title and identifiers","与 OpenAlex 的既有 PMID 交叉辨认。")
        w=deepcopy(old);w.update(doi=d,url="https://doi.org/"+d)
        w["identifiers"].update(doi=d,doi_as_indexed_at_cp11=report["prior"]);w["discovery_sources"].append(src)
        self.modify("works",old,w);self.works[wid]=w;self.identities[d].add(wid)
        versions=[v for v in self.versions if v["work_id"]==wid]
        require(len(versions)==1,"Ambiguous version for DOI correction")
        v=deepcopy(versions[0]);v["identifiers"].update(doi=d,doi_as_indexed_at_cp11=report["prior"]);v["url"]=w["url"]
        self.modify("versions",versions[0],v)
        self.add("aliases",dict(alias_id="AL-R10-"+token(wid,d),entity_type="work",raw_identifier=record["DOI"],normalized_identifier=d,
                 target_id=wid,historical_key=None,reason="题名、年份、PMID 支持修正双斜杠 DOI；保留旧标识。",source=src,
                 verification_status="source_supported",date=self.now[:10]))

    def queries(self,paths):
        apis={"crossref":"Crossref REST v1","europepmc":"Europe PMC REST","publisher":"bioRxiv publisher metadata","openalex":"OpenAlex REST",
              "semantic_scholar":"Semantic Scholar Academic Graph v1","ror":"Research Organization Registry v2"}
        for path in sorted(paths):
            q=read(path);qid=q["query_id"]
            if qid in self.known_queries:continue
            self.input_paths.add(path);o=q["owners"][0];tid=o["task_id"];sid=q["source_id"]
            if tid not in self.latest and tid not in self.adds["tasks"]:
                raise ValueError("Unknown source task "+tid)
            src=source(q,qid,"Bibliographic query receipt","请求级书目登记。")
            received=q.get("returned_count");ok=q["status"]=="success"
            records=q.get("records",[]);result=[]
            for i,r in enumerate(records,1):
                if "version" in r and "doi" in r and sid=="publisher":ident=r["doi"]+"v"+r["version"]
                else:ident=r.get("source_identifier") or r.get("DOI") or r.get("doi") or r.get("openalex") or ((str(r.get("source"))+":"+str(r["id"])) if r.get("id") else f"{qid}#item-{i}")
                result.append(ident)
            fs={}
            if not ok:
                for key in ("returned_count","count_before_dedup","count_after_dedup","visible_total"):
                    fs[key]=nonapplicable(src,"请求失败，来源未提供结果总数。")
            credits=self.source_credit.get(qid,[])
            time_status=q.get("query_time_status","exact")
            date=q["requested_at_utc"][:10] if q["requested_at_utc"] else q["queried_date"]
            api=apis[sid]
            if sid=="publisher" and getattr(self,"id_prefix",None)=="R11" and "api.biorxiv.org/" not in q["endpoint_or_url"]:
                api="Publisher reference-list endpoint"
            row=dict(query_id=qid,task_id=tid,scope_id=SCOPE,checkpoint_id=getattr(self,"checkpoint",CP),entity_id=o["work_id"],source_id=sid,
                     endpoint_or_url=q["endpoint_or_url"],api_version=api,query_kind="bibliography_"+qid.split("-")[2].lower(),
                     raw_parameters=q["parameters"],normalized_parameters={**q["parameters"],"scope_id":SCOPE},
                     queried_at_utc=q["requested_at_utc"],cursor_in=q.get("cursor_in"),cursor_out=q.get("cursor_out"),
                     page_index=q["page_index"],page_complete=q.get("page_complete",False),visible_total=q.get("visible_total"),
                     returned_count=received,count_before_dedup=received,count_after_dedup=len(set(result)) if ok else None,
                     new_work_ids=credits,new_work_count=len(credits),result_identifiers=list(dict.fromkeys(result)),status=q["status"],
                     verification_status="source_supported" if ok else "unverified",error_code=None if ok else str(q.get("http_status") or "transport"),
                     error_message=q.get("error"),retry_count=q["attempt"]-1,retry_at=None,cache_path=path.relative_to(ROOT).as_posix(),
                     cache_hit=False,reused_query_id=None,rerun_reason=q["reason"],coverage_note="按来源、查询及分页计数；登记条目与索引匹配分别保留。",
                     license_note="Public bibliographic metadata and reference lists only.",query_time_status=time_status,
                     recorded_at_utc=q["completed_at_utc"],queried_date=date,field_states=fs)
            if time_status=="unavailable_exact":
                row.update(status="partial",verification_status="source_supported",
                           coverage_note="请求发生但原始时间与响应未保存。仅审计该请求，不认定取得任何结果。")
            self.add("queries",row)
            self.add("source-observations",dict(observation_id="OBS-"+qid,query_id=qid,task_id=tid,source_id=sid,
                     endpoint_or_url=q["endpoint_or_url"],queried_at_utc=q["requested_at_utc"],recorded_at_utc=q["completed_at_utc"],
                     query_time_status=time_status,status=q["status"],http_status=q["http_status"],response_kind=row["query_kind"],
                     returned_count=received,visible_total=q.get("visible_total"),page_complete=row["page_complete"],count_scope=row["coverage_note"],
                     receipt_path=row["cache_path"],receipt_sha256=file_hash(path),external_request_performed=True,external_request_count=1,
                     external_request_count_basis=REQUEST_COUNT_BASIS,cache_hit=False))
            for owner in q["owners"]:
                self.task_queries[owner["task_id"]].add(qid)
            if sid=="semantic_scholar" and not ok:
                t=self.task("T-"+getattr(self,"id_prefix","R10")+"-S2-"+token(o["work_id"]),o["work_id"],"reference_source_retry",
                            "公开书目接口限流，本轮已保留全部重试；来源恢复后按原 PMID 重试。","retryable_error",[qid],source_id=sid)
                t.update(cursor=o.get("epmc") or q["endpoint_or_url"],error_code=str(q["http_status"]))
                t["attempt_count"]+=1
        for tid,qids in self.task_queries.items():
            t=self.adds["tasks"].get(tid)
            if t is None:
                old=self.latest[tid]
                t=self.task(tid,old["entity_id"],old["task_type"],old["review_condition"] or "按来源继续复核。",
                            old["task_state"],sorted(qids),etype=old["entity_type"],source_id=old["source_id"])
            t["query_ids"]=list(dict.fromkeys(t["query_ids"]+sorted(qids)))
            t["attempt_count"]+=len(qids)

    def screened_abstracts(self):
        path=TEMP/"reports/RUN-0010-abstract-affiliation-review.json"
        review=read(path);self.input_paths.add(path)
        qp=ROOT/review["source_receipt"];q=read(qp)
        require(file_hash(qp)==review["source_receipt_sha256"],"Abstract source changed")
        orgs={o["org_id"]:o for o in iter_logical("organizations.jsonl",TEMP)}
        for row in review["items"]:
            wid=row["work_id"];old=self.works[wid];w=deepcopy(old)
            r=next(r for r in q["records"] if r["id"]==row["pmid"])
            require(r["abstract_sha256"]==row["abstract_sha256"] and doi(r["doi"])==w["doi"],"Wrong abstract or Work")
            src=source(q,"MED:"+row["pmid"],"Indexed abstract","依据索引摘要撰写中文概述。")
            vid=next(v["version_id"] for v in self.versions if v["work_id"]==wid and doi(v.get("identifiers",{}).get("doi"))==w["doi"])
            require(not w["abstract_items"],"Duplicate abstract screening")
            w["abstract_items"].append(dict(status="chinese_summary_from_abstract",text=row["summary_zh"],source=src,version_id=vid,
                                      license="Original Chinese summary; the source abstract is not reproduced.",
                                      summarizer="Codex 索引摘要复核",date=review["reviewed_at_utc"][:10],source_language="en",
                                      verification_status="source_supported"))
            w.update(abstract_status="chinese_summary_from_abstract",abstract_source=src)
            rid="MR-R10-ABSTRACT-"+row["pmid"]
            for link in row["publication_affiliation_links"]:
                rank=link["byline_position"]-1;org=link["org_id"];require(org in orgs,"Unknown organization")
                author=w["authors"][rank];byline=r["authors"][rank]
                require(byline["fullName"]==link["source_display"] and link["affiliation"] in byline["affiliations"],"Byline mismatch")
                require(org not in author["organization_ids"],"Duplicate author-organization relationship")
                author["organization_ids"].append(org)
                loc=source(q,"MED:"+row["pmid"],f"Byline {rank+1}, publication affiliation",link["affiliation"])
                person=self.people[author["person_id"]];revised=deepcopy(person)
                revised["affiliation_history"].append(dict(org_id=org,role="byline_affiliation_at_publication",valid_from=None,valid_to=None,work_id=wid,
                    evidence_locator=loc["evidence_locator"],field_states={k:nonapplicable(loc,"仅记发表时署名，不推定任职区间。") for k in ("valid_from","valid_to")}))
                self.modify("authors",person,revised);self.people[author["person_id"]]=revised
            for dim in ("abstract","affiliations_projects","assessment"):
                t=self.task("T-"+dim+"-"+wid,wid,dim,row["boundary"] if dim=="assessment" else "已记索引摘要及发表时署名，剩余维度继续复核。","partial",[q["query_id"]])
                t["supporting_record_ids"].append(rid);w["dimension_status"][dim]="partial"
            self.modify("works",old,w);self.works[wid]=w
            self.add("manual-reviews",dict(review_id=rid,run_id=RUN,review_type="abstract_and_publication_byline",
                     entity_id=wid,reviewer="Codex 摘要与署名复核",recorded_at_utc=review["reviewed_at_utc"],
                     artifact=path.relative_to(ROOT).as_posix(),notes=row["boundary"]))

    def index_editions(self):
        versions={v["version_id"]:v for v in self.versions};latest={}
        for path in sorted(OUT.glob("Q-RUN10-ED-*.json")):
            q=read(path)
            if q["query_id"] in self.known_queries:continue
            self.input_paths.add(path)
            records={r["source_identifier"]:r for r in q.get("records",[])}
            for owner in q["owners"]:latest[owner["version_id"]]=(owner,q,records.get(owner["openalex"]))
        counts=Counter()
        for vid,(owner,q,r) in latest.items():
            old=versions[vid];work=self.works[owner["work_id"]];oid=owner["openalex"]
            require(old["work_id"]==work["work_id"] and old["identifiers"].get("openalex")==oid,"Index edition owner mismatch")
            marker=(r or {}).get("location_version");same=not r or not (r.get("doi") and work.get("doi")) or doi(r["doi"])==doi(work["doi"])
            v=deepcopy(old)
            if marker=="publishedVersion" and same:
                v["version_type"]="version_of_record";note="OpenAlex 主位置的版本字段明确记为 publishedVersion。";counts["published_location"]+=1
            elif work["document_type"]=="preprint" and same:
                v["version_type"]="preprint";note="书目类型明示为预印本，位置字段未证实正式版。";counts["registered_preprint"]+=1
            else:
                v["version_type"]="unknown";note=f"OpenAlex 主位置的版本字段为 {marker or '未提供'}，书目所指的具体版本待核实。";counts["unknown_location"]+=1
            src=source(q,oid,"Indexed primary location version",note) if q["status"]=="success" else old["source"]
            v["source"]=src;v["notes"]=note+" 仅核对书目字段。"
            if v["version_type"]=="unknown":
                v["field_states"]["version_type"]=self.unknown("version",vid,"version_type",src)
            self.modify("versions",old,v)
        return dict(counts)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--versions",action="store_true")
    p.add_argument("--frontier",default=str(FRONTIER))
    p.add_argument("--name",required=True)
    p.add_argument("--apply",action="store_true")
    args=p.parse_args()
    from pathlib import Path
    require(re.fullmatch(r"[a-z0-9-]+",args.name),"Unsafe batch name")
    report_path=f"temp/reports/RUN-0010-integration-{args.name}.json"
    if (ROOT/report_path).exists():
        print("Existing integration receipt",report_path);return
    b=Batch();input_frontier=Path(args.frontier).resolve();selection=read(input_frontier);queue=selection["worklist"]
    key_changes=[]
    if args.versions:
        b.version_reviews();b.screened_abstracts();outcomes=[]
        paths={*OUT.glob("Q-RUN10-V*.json"),*OUT.glob("Q-RUN10-P56-*.json")}
    else:
        b.input_paths.add(input_frontier)
        b.corrected_doi()
        key_changes=b.bibliographic_keys()
        outcomes=b.backward(queue)
        b.reference_coverage(outcomes)
        # All currently unregistered request receipts belong to this resumed RUN.
        paths=set(OUT.glob("Q-RUN10-*.json"))
    edition_counts=b.index_editions() if not args.versions else {}
    b.queries(paths)
    for name,entries in b.changes.items():
        b.changes[name]={key:pair for key,pair in entries.items() if pair[0]!=pair[1]}
    report=dict(run_id=RUN,scope_id=SCOPE,target_checkpoint=CP,batch=args.name,updated_at_utc=b.now,
                counts={k:len(v) for k,v in b.adds.items()},identity_match_counts=dict(b.resolution),
                authorship_counts=dict(b.stats),indexed_edition_checks=edition_counts,bibliographic_key_corrections=key_changes,coverage=outcomes,
                input_receipts={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(b.input_paths)})
    extra={};run=read(TEMP/"runs/RUN-0010.json")
    run["external_requests_used"]=len(list(OUT.glob("Q-RUN10-*.json")))
    if args.versions:run["manual_review_items_used"]=len(b.adds["manual-reviews"])
    if not args.versions:
        frontier_path=f"temp/reports/RUN-0010-frontier-after-{args.name}.json"
        remaining=[]
        if selection.get("queue_source"):
            source_path=ROOT/selection["queue_source"]
            require(file_hash(source_path)==selection["queue_sha256"],"Recursive frontier changed")
            prior=read(source_path)["worklist"];end=selection["next_index"]
            require(selection["start_index"]==0 and prior[:end]==queue and len(prior)==selection["queue_total"],"Parent cursor mismatch")
            remaining=[{**item,"work_key":b.works[item["work_id"]]["work_key"]} for item in prior[end:]]
        # Rotate equal-depth, equal-priority discoveries across their parents.
        # A long first bibliography must not consume an entire recursive batch.
        per_parent=Counter();ranked=[]
        for ordinal,item in enumerate(b.new_frontier):
            parent=(item["depth"],item["parent_work_id"])
            ranked.append((item["depth"],per_parent[parent],ordinal,item));per_parent[parent]+=1
        forward=[*remaining,*(item for _,_,_,item in sorted(ranked))]
        require(len({r["work_id"] for r in forward})==len(forward),"Duplicate recursive queue entry")
        extra[frontier_path]=dict(run_id=RUN,parent_batch=report_path,scope_id=SCOPE,carried_unvisited=len(remaining),newly_discovered=len(b.new_frontier),worklist=forward)
        run["next_backward_frontier"]=frontier_path
    extra["temp/runs/RUN-0010.json"]=run
    print(json.dumps({k:report[k] for k in ("counts","identity_match_counts","authorship_counts")}),flush=True)
    additions={k:list(v.values()) for k,v in b.adds.items() if v}
    if args.apply:
        apply_batch(dict(b.changes),additions,report,report_path,extra)
    else:
        import gates
        schemas=read(TEMP/"schema.json")["x-entity-files"]
        for name in set(additions)|set(b.changes):
            if kind:=schemas.get(name+".jsonl"):
                for row in [*additions.get(name,[]),*(v[1] for v in b.changes.get(name,{}).values())]:
                    try:gates.validate(kind,row)
                    except Exception as exc:raise ValueError(f"{name} {row[IDS[name]]}: {exc}") from exc


if __name__=="__main__":
    main()
