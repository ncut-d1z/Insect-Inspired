"""Materialize a contiguous slice of the CP12 frontier against the retained bibliographic receipts."""
import argparse
from calendar import monthrange
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

from integrate_run10_references import Batch, nonapplicable
from run10_reference_records import doi, fields, identifiers, norm, token
from run11_reference_inventory import BATCHES, SUPPLEMENT, manifest, preferred, queue_inputs, raw_ids, receipt, source_pages
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import CP, OUT, ROOT, RUN, SCOPE, TEMP, WIDTH, digest, read, stamp
from storage import iter_logical

OUTCOMES=TEMP/"reports/RUN-0011-canonical"
BAD_DOI="10.1523/jneurosci.19-19-08573.1999"


def publication_interval(value,year=None):
    text=str(value or year or "")
    try:
        if len(text)==4 and text.isdigit():
            y=int(text);return date(y,1,1),date(y,12,31)
        if len(text)==7 and text[4]=="-":
            y,m=map(int,text.split("-"));return date(y,m,1),date(y,m,monthrange(y,m)[1])
        if len(text)==10:
            d=date.fromisoformat(text);return d,d
    except ValueError:
        pass
    return None


def definitely_later(citing_date,citing_year,cited_date,cited_year):
    a=publication_interval(citing_date,citing_year);b=publication_interval(cited_date,cited_year)
    return bool(a and b and b[0]>a[1])


def evidence(q,parent,kind,position,raw=None):
    labels={"deposited":"Deposited bibliography","indexed_bibliography":"Indexed bibliography","index_ids":"Matched index",
            "literal_bibliography":"Reference-list entry"}
    sid=q["source_id"];section=f"{labels[kind]}, {position}"
    if kind=="literal_bibliography" and raw is not None and not (raw.get("raw_reference_string") or raw.get("raw_doi")):
        section=f"OpenAlex index match without original text, {position}"
    locator=dict(source_id=sid,identifier=parent,section=section,evidence_note=q["query_id"],accessed_at=q["completed_at_utc"])
    return section,dict(source_id=sid,identifier=parent,verification_status="source_supported",evidence_locator=[locator])


def index_rows(queue,titles,start,count):
    end=min(start+count,len(queue));data=[];inputs=set();qpaths=set()
    for base in range(start//WIDTH*WIDTH,end,WIDTH):
        finish=min(base+WIDTH,len(queue));path,m=manifest(base,finish)
        sp=preferred(SUPPLEMENT,f"{base+1:04}-{finish:04}");extra=read(sp)
        assert extra["base_sha256"]==digest(path)
        for p,h in extra["receipts"].items():assert digest(ROOT/p)==h
        inputs.update((path,sp))
        request_owners=defaultdict(set)
        for name in m["input_receipts"]:
            request=receipt(Path(name).stem)
            for owner in request["owners"]:
                request_owners[owner["work_id"]].add(request["query_id"])
        for n in range(max(base,start),min(end,finish)):
            owner=queue[n];row=m["worklist"][n-base];ext=extra["parents"][n-base]
            assert row["work_id"]==ext["work_id"]==owner["work_id"] and row["queue_position"]==n+1
            attempts={s["query_id"] for s in row["sources"]}
            attempts.update(request_owners[owner["work_id"]])
            if ext["openalex_literal_query"]:attempts.add(ext["openalex_literal_query"])
            if ext.get("corrected_deposited_query"):attempts.add(ext["corrected_deposited_query"]["query_id"])
            pages=list(source_pages(owner,row,titles[owner["work_id"]],ext))
            qpaths.update(OUT/(qid+".json") for qid in attempts)
            data.append((owner,row,ext,attempts,pages))
    return data,inputs,qpaths


class Canonical(Batch):
    checkpoint=CP
    id_prefix="R11"
    credit_discovery=True
    metadata_prefixes=("Q-RUN10-ID-","Q-RUN11-ID-")

    def __init__(self,data,inputs,qpaths):
        owners={o["work_id"] for o,*_ in data}
        self.adds=defaultdict(dict);self.changes=defaultdict(dict);self.now=stamp()
        self.stats=Counter();self.resolution=Counter();self.new_frontier=[];self.task_queries=defaultdict(set)
        self.source_credit=defaultdict(list);self.input_paths=set(inputs)|qpaths
        self.works={};self.names=defaultdict(set);self.identities=defaultdict(set);self.keys=set()
        for w in iter_logical("works.jsonl"):
            wid=w["work_id"];self.keys.add(w["work_key"])
            for t in (w["canonical_title"],*w.get("title_variants",[])):
                if isinstance(t,str) and t:self.names[norm(t),str(w.get("year"))].add(wid)
            for k in identifiers(w):self.identities[k].add(wid)
            if wid not in owners:
                w={k:w.get(k) for k in ("work_id","work_key","canonical_title","title_variants","year","publication_date","authors","doi")}
                w["authors"]=[{"family_name":a.get("family_name")} for a in (w["authors"] or [])[:1]]
            self.works[wid]=w
        self.versions=[]
        for v in iter_logical("versions.jsonl"):
            if v["work_id"] in owners:self.versions.append(v)
            if v["verification_status"] not in ("rejected","conflicting"):
                for k in identifiers(v):self.identities[k].add(v["work_id"])
        for a in iter_logical("aliases.jsonl"):
            if a.get("historical_key"):self.keys.add(a["historical_key"])
            if a["entity_type"]=="work" and a["target_id"] in self.works and a["verification_status"] not in ("rejected","conflicting"):
                for k in identifiers(a):self.identities[k].add(a["target_id"])
        self.keys.update(r["work_key"] for r in iter_logical("merged-work-audit.jsonl") if r.get("work_key"))
        self.roots={}
        for r in iter_logical("discovery-paths.jsonl"):
            wid=r["work_id"]
            if wid in owners and r.get("source_supported_relation") and r["steps"]==self.works[wid]["discovery_path"]:
                self.roots[wid]=r["root_seed_id"]
        assert self.roots.keys()==owners
        qowners={o["task_id"] for p in qpaths for o in receipt(p.stem)["owners"]}
        self.latest={r["task_id"]:r for r in iter_logical("tasks.jsonl") if r["entity_id"] in owners or r["task_id"] in qowners}
        self.known_queries=set();self.prior_queries={}
        for q in iter_logical("queries.jsonl"):
            self.known_queries.add(q["query_id"])
            if (OUT/(q["query_id"]+".json")) in qpaths:self.prior_queries[q["query_id"]]=q
        keys={self.works[k]["work_key"] for k in owners}
        self.edges={(r["citing_key"],r["cited_key"]):r for r in iter_logical("citation-edges.jsonl") if r["citing_key"] in keys}
        self.prior_positions={}
        if getattr(self,"reuse_citing_positions",False) and self.edges:
            known_ids={rid for e in self.edges.values() for rid in e["occurrence_ids"]}
            for occurrence in iter_logical("reference-occurrences.jsonl"):
                if occurrence["occurrence_id"] in known_ids:
                    key=(occurrence["citing_work_id"],occurrence["version_id"],occurrence["source"]["source_id"],occurrence["section"],occurrence["raw_fingerprint"])
                    self.prior_positions.setdefault(key,occurrence)
        self.people={};self.orcids=defaultdict(set)
        for a in iter_logical("authors.jsonl"):
            if a.get("orcid"):
                self.people[a["person_id"]]=True
                self.orcids[a["orcid"].rsplit("/",1)[-1]].add(a["person_id"])
        self.cutoff=read(TEMP/"snapshots/scope.json")["cutoff_at_utc"][:10]
        self.cited_version_reviews={}
        self.metas=defaultdict(list);self.registry_titles=defaultdict(set)
        review=TEMP/"reports/RUN-0011-Chao1995-identifier-review.json"
        corrected={("MED:"+r["pmid"],norm(r["title"])):r["registered_doi"] for r in read(review)["items"]} if review.exists() else {}
        wanted={k for *_,pages in data for q,kind,refs,parent,positions in pages for raw in refs for k in raw_ids(raw,q["source_id"])}
        title_years=set()
        for *_,pages in data:
            for q,kind,refs,parent,positions in pages:
                for raw in refs:
                    d,e,t,y,a=fields(raw,q["source_id"])
                    if t and y:title_years.add((norm(t),y))
        for prefix in self.metadata_prefixes:
            for path in sorted(OUT.glob(prefix+"*.json")):
                q=read(path)
                if q["status"]!="success":continue
                for r in q.get("records",[]):
                    if r.get("epmc")=="MED:37234941" and r.get("doi")==BAD_DOI:r={**r,"doi":None}
                    registered=corrected.get((r.get("epmc"),norm(r.get("title") or "")))
                    if registered and r.get("doi")!=registered:
                        r={**r,"doi":registered}
                        self.input_paths.add(review)
                    keys={s for s in (r.get("doi"),r.get("epmc"),r.get("openalex"),r.get("requested_openalex")) if s}
                    ty=(norm(r.get("title")),str(r.get("year"))) if r.get("year") and r.get("title") else None
                    if ty and ty in title_years:self.registry_titles[ty].update(keys)
                    if not wanted.isdisjoint(keys):
                        for k in keys:self.metas[k].append((r,q))
                        self.input_paths.add(path)

    def resolve(self,raw,q,owner,relation):
        if q["source_id"]=="crossref" and raw.get("DOI") and not doi(raw["DOI"]):
            # A truncated substring of an invalid deposited DOI cannot establish identity.
            return None,[],"malformed_deposited_doi"
        keys=raw_ids(raw,q["source_id"])
        if len({k for k in keys if doi(k)})>1:return None,sorted(keys),"printed_and_assigned_doi_conflict"
        if q["source_id"]=="crossref" and raw.get("DOI") and raw.get("unstructured"):
            printed=fields({"unstructured":raw["unstructured"]},"crossref")[0]
            if printed and printed!=doi(raw["DOI"]):return None,sorted({printed,doi(raw["DOI"])}),"printed_and_assigned_doi_conflict"
        return super().resolve(raw,q,owner,relation)

    def register(self,data):
        outcomes=[]
        for owner,prior,extra,attempts,pages in data:
            wid=owner["work_id"];work=self.works[wid];versions=[v for v in self.versions if v["work_id"]==wid]
            if len(versions)>1:
                primary=doi(work.get("doi")) or owner.get("epmc") or owner.get("openalex")
                versions=[v for v in versions if primary in identifiers(v)]
            assert len(versions)==1,("Unbound bibliography registration",wid,len(versions))
            version=versions[0];known=defaultdict(set);unresolved=Counter();positions=Counter();status=Counter();edges_added=0
            by_source=defaultdict(list)
            for qid in sorted(attempts):by_source[receipt(qid)["source_id"]].append(qid)
            # Identify stable targets first, then resolve text-only rows against those same Works.
            cached_admissions={}
            for q,kind,refs,parent,locs in pages:
                for pos,raw in zip(locs,refs,strict=True):
                    if not any(self.metas.get(k) for k in raw_ids(raw,q["source_id"])):continue
                    _,rel=evidence(q,parent,kind,pos,raw)
                    target,choices,reason=self.resolve(raw,q,owner,rel)
                    if reason=="new_bibliographic_identity":cached_admissions[kind,q["query_id"],pos]=target
            seen=set()
            for q,kind,refs,parent,locs in pages:
                sid=q["source_id"];qid=q["query_id"]
                for pos,raw in zip(locs,refs,strict=True):
                    section,rel=evidence(q,parent,kind,pos,raw)
                    rid="R-"+self.id_prefix+"-"+token(wid,version["version_id"],kind,pos);assert rid not in seen;seen.add(rid)
                    target,choices,reason=self.resolve(raw,q,owner,rel)
                    if (kind,qid,pos) in cached_admissions:
                        assert cached_admissions[kind,qid,pos]==target
                        reason="new_bibliographic_identity"
                    if target==wid:target=None;reason="possible_reference_to_another_version"
                    label=raw.get("key") if sid=="crossref" else raw.get("citedOrder")
                    literal=raw.get("unstructured") or raw.get("raw_reference_string") or json.dumps(raw,ensure_ascii=False,separators=(",",":"))
                    fs={"page":nonapplicable(rel,"书目接口未提供施引页码。")}
                    if label is None:fs["reference_label"]=nonapplicable(rel,"无来源标签，保留来源顺序。")
                    fingerprint=hashlib.sha256(literal.encode()).hexdigest()
                    previous=self.prior_positions.get((wid,version["version_id"],sid,section,fingerprint))
                    if previous:
                        if previous["cited_work_id"]!=target:raise ValueError("Previously verified reference target differs: "+previous["occurrence_id"])
                        rid=previous["occurrence_id"]
                        self.stats["existing_positions_reused"]+=1
                    else:self.add("reference-occurrences",dict(occurrence_id=rid,citing_work_id=wid,version_id=version["version_id"],
                             reference_label=None if label is None else str(label),section=section,page=None,raw_reference=literal,
                             raw_fingerprint=fingerprint,candidate_ids=choices,cited_work_id=target,
                             identity_confidence="probable" if target else ("ambiguous" if choices else "unresolved"),
                             verification_status="source_supported" if target else "unverified",source=rel,failure_reason=None if target else reason,field_states=fs))
                    positions[sid]+=1;status[reason]+=1
                    if not target:
                        unresolved[sid]+=1
                        event=self.task("T-"+self.id_prefix+"-IDENT-"+token(rid),wid,"reference_identity",reason,"needs_disambiguation",[qid],source_id=sid)
                        event["normalized_parameters"]={"occurrence_id":rid,"candidate_ids":choices}
                        continue
                    known[sid].add(target);cited=self.works[target]
                    if definitely_later(version.get("version_date"),work.get("year"),cited.get("publication_date"),cited.get("year")):
                        tid="T-"+self.id_prefix+"-CITED-"+token(wid,target)
                        event=self.task(tid,wid,"cited_version_review","登记目标晚于施引版，需以原始书目定位实际版次。","needs_disambiguation",[qid],source_id=sid)
                        event["supporting_record_ids"]=list(dict.fromkeys([*event["supporting_record_ids"],rid]))
                    pair=(work["work_key"],cited["work_key"]);edge=self.edges.get(pair)
                    if edge:
                        if edge["edge_id"] not in self.adds["citation-edges"] and edge["edge_id"] not in self.changes["citation-edges"]:
                            original=edge;edge=deepcopy(edge);self.modify("citation-edges",original,edge);self.edges[pair]=edge
                        if rid not in edge["occurrence_ids"]:edge["occurrence_ids"].append(rid)
                        elif not previous:raise ValueError("Duplicate unbound reference position: "+rid)
                        if not any(s["source_id"]==sid and s.get("identifier")==parent and any(qid in l.get("evidence_note","") for l in s.get("evidence_locator",[])) for s in edge["discovery_sources"]):
                            edge["discovery_sources"].append(rel)
                    else:
                        self.edges[pair]=self.add("citation-edges",dict(edge_id="CE-"+self.id_prefix+"-"+token(*pair),citing_key=pair[0],cited_key=pair[1],
                                 occurrence_ids=[rid],discovery_sources=[rel],verification_status="source_supported",citation_roles=["unknown"],context_locators=[],date=self.now[:10]))
                        edges_added+=1
            indexed={sid:dict(queries=ids,returned_positions=positions[sid],distinct_resolved_work_count=len(known[sid]),unresolved_positions=unresolved[sid])
                     for sid,ids in by_source.items()}
            cr=next((s for s in prior["sources"] if s["source_id"]=="crossref" and s["status"]=="success" and
                     (s["available"] or s["query_id"] in extra.get("certified_parent_queries",())) and
                     not any(c["query_id"]==s["query_id"] for c in extra["excluded_parent_identities"])),None)
            if extra.get("corrected_deposited_query"):
                correction=extra["corrected_deposited_query"]
                assert not cr and doi(work["doi"])==correction["doi"]
                cr={"source_declared":correction["declared"],"query_id":correction["query_id"]}
            query=cr["query_id"] if cr else sorted(attempts)[0]
            if not cr and getattr(self,"prefer_supporting_coverage_query",False):
                supported=[q["query_id"] for q,kind,refs,identifier,locs in pages if refs]
                successful=[qid for qid in sorted(attempts) if receipt(qid)["status"]=="success"]
                query=next(iter(supported or successful),query)
            self.add("reference-coverage",dict(work_id=wid,doi=work.get("doi"),query_id=query,
                 deposited_reference_count=cr["source_declared"] if cr else None,returned_reference_count=positions["crossref"] if cr else None,
                 original_fulltext_completeness="not_verified",indexed_sources=indexed,distinct_resolved_works=len(set().union(*known.values())),
                 coverage_note="逐个来源对账。OpenAlex 两种表示只登记一次重合位置。原始书目完整性、未解身份和引用作用仍待核实。"))
            state="partial" if seen else "pending"
            note="已查登记书目及替代索引。继续消歧、补缺和向后扩展。" if seen else "可用接口未返回可归属的书目位置；保留替代来源检索入口。"
            event=self.task(owner["task_id"],wid,"references",note,state,sorted(attempts))
            event["cursor"]="unresolved_reference_identities_and_source_coverage" if seen else "alternative_bibliographic_source"
            if prior.get("reference_index_indicator") or prior.get("deferred_sources"):
                event["normalized_parameters"]={**event["normalized_parameters"],"reference_index_indicator":prior.get("reference_index_indicator"),
                                                  "deferred_reference_sources":prior.get("deferred_sources",{})}
            if work["dimension_status"]["references"]!=state:
                w=deepcopy(work);w["dimension_status"]["references"]=state;self.works[wid]=w;self.modify("works",work,w)
            else:w=work
            outcomes.append(dict(ordinal=prior["queue_position"],work_id=wid,work_key=w["work_key"],task_id=owner["task_id"],
                         positions=dict(positions),unresolved=dict(unresolved),new_edges=edges_added,resolution=dict(status),task_state=state))
        return outcomes

    def account(self,paths):
        self.queries(paths)
        for qid,wids in self.source_credit.items():
            if qid not in self.known_queries:continue
            old=self.prior_queries[qid];q=deepcopy(old);assert q["checkpoint_id"]==self.checkpoint
            assert set(wids).isdisjoint(q["new_work_ids"])
            q["new_work_ids"].extend(wids);q["new_work_count"]=len(q["new_work_ids"])
            self.modify("queries",old,q)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("start",type=int);parser.add_argument("count",type=int)
    parser.add_argument("--preview",action="store_true");args=parser.parse_args()
    queue,titles=queue_inputs();start=args.start;end=min(start+args.count,len(queue))
    assert 0<=start<end<=len(queue)
    label=f"{start+1:04}-{end:04}";rel=f"temp/reports/RUN-0011-canonical/{label}.json"
    if (ROOT/rel).exists():raise ValueError("This transaction already exists")
    prior=sorted(OUTCOMES.glob("*.json")) if OUTCOMES.exists() else []
    if (read(prior[-1])["next_index"] if prior else 0)!=start:raise ValueError("Resume at the last canonical cursor")
    data,inputs,paths=index_rows(queue,titles,start,args.count)
    b=Canonical(data,inputs,paths);out=b.register(data);b.account(paths)
    counts={k:len(v) for k,v in b.adds.items() if v}
    print(label,counts,dict(b.stats),flush=True)
    if args.preview:return
    rep=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,starting_index=start,next_index=end,created_at_utc=b.now,
             source_frontier="temp/reports/RUN-0010-frontier-after-recursive-24.json",coverage=out,discovered_worklist=b.new_frontier,
             input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in b.input_paths},added_counts=counts)
    apply_batch(b.changes,{k:list(v.values()) for k,v in b.adds.items() if v},rep,rel)


if __name__=="__main__":main()
