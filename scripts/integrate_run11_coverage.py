"""Apply the source-level cursor for every CP12 parent while keeping later identity processing distinct."""
from collections import Counter, defaultdict
from copy import deepcopy
import argparse

from index_run11_positions import INDEX
from integrate_run11_reviews import Ledger
from run11_reference_inventory import BATCHES, OUT, ROOT, SUPPLEMENT, TEMP, WIDTH, digest, preferred, read, receipt, stamp
from integrate_run10_references import source
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import CP, RUN, SCOPE, STATE


def coverage():
    overall=TEMP/"reports/RUN-0011-CP12-parent-reconciliation.json";audit=read(overall)
    assert audit["visited"]==2620 and all(digest(ROOT/f)==h for f,h in audit["inputs"].items())
    worklist=read(ROOT/read(STATE)["frontier"])["worklist"]
    paths={p for p in OUT.glob("Q-RUN11-*.json") if "-ID-" not in p.name or p.name.startswith("Q-RUN11-VER-")}
    # Include every attempted list query, including failed identity checks sharing a parent task.
    for b in BATCHES.glob("*.json"):paths.update(ROOT/f for f in read(b)["input_receipts"])
    qowners={o["task_id"] for p in paths for o in read(p)["owners"]}
    reg=Ledger(qowners,{o["work_id"] for o in worklist})
    inputs={overall,*(ROOT/f for f in audit["inputs"])}
    prepared={r["work_id"] for p in (TEMP/"reports/RUN-0011-canonical").glob("*.json") for r in read(p)["coverage"]}
    totals=Counter();states=Counter()
    for start in range(0,len(worklist),WIDTH):
        end=min(start+WIDTH,len(worklist));label=f"{start+1:04}-{end:04}";m=read(preferred(INDEX,label))
        bp=ROOT/m["primary_manifest"];sp=ROOT/m["supplement_manifest"];base=read(bp);supp=read(sp);inputs.update((bp,sp))
        attempts=defaultdict(lambda:defaultdict(list))
        for file in base["input_receipts"]:
            q=receipt((ROOT/file).stem)
            for o in q["owners"]:attempts[o["work_id"]][q["source_id"]].append(q["query_id"])
        for r,x,p in zip(base["worklist"],supp["parents"],m["parents"],strict=True):
            wid=r["work_id"];assert wid==x["work_id"]==p["work_id"]
            rawq=x.get("openalex_literal_query")
            if rawq:attempts[wid]["openalex"].append(rawq)
            invalid={c["query_id"] for c in x["excluded_parent_identities"]}
            for sid,qids in attempts[wid].items():
                qids=list(dict.fromkeys(qids));obs=[z for z in r["sources"] if z["source_id"]==sid and z["query_id"] not in invalid]
                good=[z for z in obs if (z["available"] or z["query_id"] in x.get("certified_parent_queries",())) and z["status"]=="success"]
                by_kind=p["positions_by_channel"];total=None;number=None;complete=False
                if sid=="crossref":
                    number=by_kind.get("deposited",0) if good else None
                    if good:
                        total=good[-1]["source_declared"];complete=(good[-1]["source_reconciled"] or good[-1]["query_id"] in x.get("certified_parent_queries",())) and number==total
                elif sid=="europepmc":
                    number=by_kind.get("indexed_bibliography",0) if good else None
                    if good:
                        total=good[-1]["source_declared"];complete=good[-1]["source_reconciled"] and number==total
                elif sid=="openalex":
                    number=by_kind.get("index_ids",0)+by_kind.get("literal_bibliography",0) if good or rawq else None
                    literal=receipt(rawq) if rawq else None
                    if literal and literal["status"]=="success" and not by_kind.get("index_ids",0):
                        total=literal["visible_total"];complete=literal["page_complete"] and number==total
                    elif good and not (literal and literal["status"]=="success"):
                        total=good[-1]["source_declared"];complete=good[-1]["source_reconciled"] and number==total
                else:raise ValueError(sid)
                reg.add("source-list-coverage",dict(coverage_id="COV-R11-"+wid+"-"+sid,entity_id=wid,source_id=sid,
                        pagination_complete=bool(complete),total_reconciled=bool(complete),visible_total=total,returned_count=number,
                        distinct_count=None,query_ids=qids,cursor=None if complete else "alternate_source_or_identity_review",
                        task_id=r["task_id"],coverage_note="仅指该来源可见列表。OpenAlex 保留未匹配位置，列表无条目不证明原始参考文献为空。"))
                totals[sid]+=1
            tid=r["task_id"];t=reg.latest[tid];w=reg.works[wid];has=p["counts"].get("positions",0)>0
            if wid in prepared:
                states[t["task_state"]]+=1;continue
            state="partial" if has else "pending";states[state]+=1
            condition="源列表及位置已对账；逐条工作身份、引文边和原始版次继续核实。" if has else "已核对可用书目接口；等待可归属的替代参考文献列表。"
            qids=[qid for ids in attempts[wid].values() for qid in ids]
            event=reg.task(tid,wid,"references",condition,state,qids,source_id=t["source_id"])
            event["cursor"]={"next":"canonical_reference_identity" if has else "alternative_bibliographic_source","queue_position":p["queue_position"],
                             "index_file":m["position_file"],"positions":p["counts"].get("positions",0)}
            if w["dimension_status"]["references"]!=state:
                revised=deepcopy(w);revised["dimension_status"]["references"]=state;reg.modify("works",w,revised);reg.works[wid]=revised
    review_path=TEMP/"reports/RUN-0011-parent-identity-review.json";review=read(review_path);inputs.add(review_path)
    for r in review["items"]:
        wid=r["work_id"];w=reg.works[wid];updated=deepcopy(w)
        q=receipt("Q-RUN11-PARENT-IDENTITY-CROSSREF-A1")
        if r["registered_title"] not in updated["title_variants"]:updated["title_variants"].append(r["registered_title"])
        updated["discovery_sources"].append(source(q,r["doi"],"Registered title, byline and pages","与 PMID 和 OpenAlex 记录交叉核对原题名或短题名。"))
        reg.modify("works",w,updated);reg.works[wid]=updated
        reg.manual("MR-R11-PARENT-"+wid,wid,review_path,review["reviewed_at_utc"],"abbreviated_or_translated_parent_identity",
                   "已核对题名变体、两种稳定标识、署名及卷页；保留原始匹配疑义与恢复的来源列表。")
    reg.queries(paths)
    rep=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,recorded_at_utc=stamp(),stage="source_coverage",parents=len(worklist),
             parent_task_states=dict(states),source_coverage_records=dict(totals),previously_materialized_parents=len(prepared),
             input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in paths|inputs})
    apply_batch(reg.changes,{k:list(v.values()) for k,v in reg.adds.items() if v},rep,"temp/reports/RUN-0011-source-integration.json")
    print("source cursors",dict(totals),dict(states),flush=True)


def queries():
    paths=set(OUT.glob("Q-RUN11-*.json"));reg=Ledger({o["task_id"] for p in paths for o in read(p)["owners"]},set())
    pending={p for p in paths if p.stem not in reg.known_queries};assert pending
    reg.queries(pending)
    report=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,recorded_at_utc=stamp(),registered=len(pending),
                input_receipts={p.relative_to(ROOT).as_posix():digest(p) for p in pending})
    label=digest(sorted(pending)[-1])[:12]
    apply_batch(reg.changes,{k:list(v.values()) for k,v in reg.adds.items() if v},report,"temp/reports/RUN-0011-query-integration-"+label+".json")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("coverage","queries"));a=p.parse_args()
    if a.action=="coverage":coverage()
    else:queries()
