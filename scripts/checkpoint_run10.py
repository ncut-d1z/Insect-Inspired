"""Freeze, regenerate, audit and certify the bibliographic continuation of CP11."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import audit_run
from audit_cp10 import input_digest, input_snapshot
from checkpoint_cp10 import require, validate_checkpoint
from checkpoint_run9_bibliography import dump, write
from coverage_run10 import collect
from escalate_unknown_run7 import git, sha
from export_checkpoint_windows import EXPORTS, generate
from history_run10 import verify
from search_run10_references import CP, ROOT, RUN, TEMP, read, stamp

CANDIDATE="temp/snapshots/checkpoints/CP-0012.json"
INPUTS="temp/validation/cp12-inputs.json"
HISTORY="temp/validation/cp12-history.json"
RUN_FILE="temp/runs/RUN-0010.json"
REPORT="temp/reports/P3-P6-CP0012.md"
PUBLISHED="temp/validation/cp12-post-push.json"


def tracked():
    return {p for p in git(ROOT,"ls-files","-z","--cached","--others","--exclude-standard").decode().split("\0") if p and (ROOT/p).is_file()}


def inputs():
    excluded={CANDIDATE,INPUTS,HISTORY,REPORT,"README.md","temp/change-log.md","temp/progress.md",*EXPORTS}
    return {p for p in tracked()-excluded if not p.startswith("temp/validation/cp12-")}


def prepare():
    require(not git(ROOT,"status","--porcelain").strip() and not (ROOT/CANDIDATE).exists(),"Freeze clean committed research inputs")
    run=read(ROOT/RUN_FILE);parent=read(TEMP/"snapshots/checkpoints/CP-0011.json")
    require(run["start_checkpoint_id"]==parent["checkpoint_id"]=="CP-0011" and parent["status"]=="valid","CP11 parent mismatch")
    history=verify(run["start_commit_sha"])
    require(history["parent_checkpoint_sha256"]==run["start_sync_gate"]["checkpoint_sha256"],"Published parent digest differs")
    created=stamp();counts,coverage,cursor,opened=collect(created)
    source=input_snapshot(ROOT,inputs());digest=input_digest(source)
    cp=dict(checkpoint_id=CP,parent_checkpoint_id=parent["checkpoint_id"],scope_id=run["scope_id"],schema_version=parent["schema_version"],
            created_at_utc=created,task_cursor_state=cursor,query_log_high_watermark=counts["queries"],counts=counts,coverage=coverage,
            unresolved_tasks=opened,failure_reasons=["候选待全量校验。","版本、书目身份、递归队列和科学证据缺口仍开放。"],artifact_hashes={},
            validation_results=dict(state="pending",input_manifest=INPUTS,input_digest_sha256=digest,input_commit=git(ROOT,"rev-parse","HEAD").decode().strip(),
                history_file=HISTORY,history_sha256=sha(dump(history)),research_closure_established=False,post_commit_receipt=PUBLISHED),status="invalid")
    validate_checkpoint(ROOT,cp)
    write(ROOT/HISTORY,dump(history));write(ROOT/INPUTS,dump(source));write(ROOT/CANDIDATE,dump(cp,True))
    print("frozen",created,counts["canonical_works"],len(opened),digest,flush=True)


def bound():
    cp=read(ROOT/CANDIDATE);v=cp["validation_results"];manifest=read(ROOT/INPUTS)
    require(cp["status"]=="invalid" and cp["parent_checkpoint_id"]=="CP-0011" and set(manifest)==inputs() and
            manifest==input_snapshot(ROOT,manifest) and input_digest(manifest)==v["input_digest_sha256"] and
            audit_run.sha(ROOT/HISTORY)==v["history_sha256"],"Candidate or frozen study inputs changed")
    return cp


def exports(qa):
    cp=bound();ch=audit_run.sha(ROOT/CANDIDATE)
    first=qa/"first";second=qa/"independent"
    a=generate(first,CP);b=generate(second,CP)
    require(a==b and all(0<v["bytes"]<100*1024**2 for v in a.values()),"Output differs or exceeds the GitHub file limit")
    application=read(first/"export-validation.json");stats=cp["counts"];ec=application["counts"]
    require(ec["bibtex_entries"]==ec["graph_nodes"]==stats["canonical_works"] and ec["graph_edges"]==stats["citation_edges"] and
            ec["unresolved_pointers"]==stats["unresolved_occurrences"] and ec["active_assessments"]==stats["assessments"],"Export counts differ")
    require(audit_run.sha(ROOT/CANDIDATE)==ch,"Checkpoint moved during export")
    for name in EXPORTS:write(ROOT/name,(first/name).read_bytes())
    require(input_snapshot(ROOT,EXPORTS)==a,"Installed outputs differ")
    write(qa/"determinism.json",dump(dict(status="passed",checkpoint_id=CP,candidate_sha256=ch,input_digest=cp["validation_results"]["input_digest_sha256"],
         checked_at_utc=stamp(),artifact_count=len(a),artifacts=a)))
    print("identical exports",len(a),flush=True)


class FullAudit(audit_run.Audit):
    def load_json(self,path,kind=None):
        data=super().load_json(path,kind)
        if kind=="checkpoint" and data is not None:
            return {k:data[k] for k in ("checkpoint_id","scope_id","status","parent_checkpoint_id","artifact_hashes")}
        return data


def audit(qa):
    cp=bound();ch=audit_run.sha(ROOT/CANDIDATE);run=read(ROOT/RUN_FILE);base=run["checkpoint_commit"]
    manifest=json.loads(git(ROOT,"show",base+":temp/partitions/manifest.json"));parts=manifest["datasets"].get("assessments.jsonl",{"parts":[{"path":"assessments.jsonl"}]})["parts"]
    previous=[json.loads(line) for p in parts for line in git(ROOT,"show",base+":temp/"+p["path"]).splitlines() if line]
    out=qa/"data-audit.json";engine=FullAudit(ROOT,out,datetime.fromisoformat(cp["created_at_utc"]));del cp
    engine._manual_assessment_baselines=[(base+":temp/assessments.jsonl",previous)];engine.stats["candidate_sha256"]=ch
    engine.run();result=read(out)
    require(result["status"]=="passed" and not result["changed_inputs"] and result["error_count"]==0 and audit_run.sha(ROOT/CANDIDATE)==ch,"Full data audit failed: "+str(result["findings"]["error"].keys()))
    warnings={k:v["count"] for k,v in result["findings"]["warning"].items()}
    baseline=read(TEMP/"validation/cp11-data-audit.json")["findings"]["warning"]
    require(all(k in baseline and n<=baseline[k]["count"] for k,n in warnings.items()),"Review newly introduced audit warnings")
    print("data audit passed",result["warning_count"],flush=True)


def finalize(qa):
    cp=bound();candidate=audit_run.sha(ROOT/CANDIDATE);c=cp["counts"];cov=cp["coverage"]
    require(not git(ROOT,"status","--porcelain").strip(),"Publish candidate and exports before certification")
    audited_commit=git(ROOT,"rev-parse","HEAD").decode().strip()
    require(sha(git(ROOT,"show",audited_commit+":"+CANDIDATE))==candidate,"Unpublished audit subject")
    det=read(qa/"determinism.json");data=read(qa/"data-audit.json");meta=read(qa/"first/export-validation.json")
    require(data["status"]==det["status"]=="passed" and data["error_count"]==0 and not data["changed_inputs"] and
            data["statistics"]["candidate_sha256"]==det["candidate_sha256"]==candidate and det["artifacts"]==input_snapshot(ROOT,EXPORTS) and not meta["schema_errors"],"Incomplete data or export audit")
    qa_files={"cp12-data-audit.json":data,"cp12-determinism.json":det,"cp12-export-validation.json":meta}
    for browser in ("chrome","edge"):
        ui=read(qa/browser/"ui-audit-final.json")
        require(ui["passed"] and ui["checkpoint_id"]==CP and not ui["errors"] and len(ui["checks"])==9 and all(ui["checks"].values()) and
                all(len(ui["samples"][k])==3 for k in ("topics","misc")) and all(det["artifacts"][p]==v for p,v in ui["artifacts"].items()) and
                datetime.fromisoformat(ui["started_at_utc"].replace("Z","+00:00"))>=datetime.fromisoformat(cp["created_at_utc"]),"Offline browser validation differs")
        qa_files["cp12-ui-"+browser+".json"]=ui
    end=stamp();run=read(ROOT/RUN_FILE)
    remain=cov["unknown_review"].get("next_deadline_utc")
    require(not remain or datetime.fromisoformat(end)<datetime.fromisoformat(remain),"Re-evaluate deadlines before accepting")
    hours=(datetime.fromisoformat(end)-datetime.fromisoformat(run["started_at_utc"])).total_seconds()/3600
    require(hours<=run["budget"]["wall_clock_hours"],"Elapsed run budget")
    run.update(status="checkpointed_open",end_checkpoint_id=CP,checkpoint_status="valid",checkpoint_validation_state="passed",checkpoint_completed_at_utc=end,
               checkpoint_wall_clock_hours=hours,closure=False,sync_state="See independent post-push receipt",post_commit_verification_url=PUBLISHED)
    delta=cov["delta_from_cp11"];queue=cov["backward_queue"]
    batches=[read(p) for p in sorted((TEMP/"reports").glob("RUN-0010-integration-*.json"))];recursive=[r for r in batches if r["coverage"] and r["batch"]!="initial-79"]
    def num(x):return f"{x:,}"
    report=f"""# CP-0012 阶段报告

从已验证的 CP-0011 延续 SCOPE-0001。文献截止为 {run['research_cutoff_at_utc']}。本轮只使用书目信息、摘要和参考文献列表。P3–P6 均已迭代，递归队列仍开放。

| 阶段 | 本轮研究结果 | 尚待核实 |
| --- | --- | --- |
| P3 向后检索 | CP11 新增的 79 篇均已查询，78 篇取得条目。三种来源共给出 9,125 个位置。随后再查 {sum(len(r['coverage']) for r in recursive)} 篇递归发现的文献。两层共新增 {num(delta['canonical_works'])} 篇、{num(delta['citation_edges'])} 条独立边、{num(delta['reference_occurrences'])} 个来源位置。 | {num(delta['unresolved_occurrences'])} 个新增位置端点待核实，{num(queue['work_count'])} 篇排入下一批。PMID 3548572 仍未取得可用列表。 |
| P4 施引版本 | 13 条全部复核。其中 8 条定位到 bioRxiv v2，1 条定位到 eLife 评审预印本第一版。 | 4 条仍有版本疑义，其中 1 条仅核实施引文献的后续版本。新增已证实引用作用 0 条。 |
| P5 作者及机构 | 对照 3 篇的 8 个署名位置，入库 5 条发表时作者与机构的关系。 | 新核实项目归属 0 条。仅据署名登记的作者身份仍按来源置信度保存。 |
| P6 摘要及主题 | 新增 3 篇带来源的中文摘要概述。合格主张 {c['eligible_claims']} 条，活跃 Assessment {c['assessments']} 条，本轮新增合格主张 0 条。 | 摘要未提供的条件、量值和引用作用继续待核实。 |

## 数据维护与覆盖

到期维护共追加 {c['run10_deadline_task_events']} 个事件、变更 {c['run10_deadline_field_transitions']} 个字段状态。保留原始时限。已逾期且未升级 {cov['unknown_review']['unupgraded_overdue_tasks']} 个。书目校正保留了旧 DOI。实际来源请求 {c['run10_external_requests']} 次，人工复核 {c['run10_manual_reviews']} 项，付费 0。

主库有 {num(c['canonical_works'])} 篇、{num(c['versions'])} 个版本、{num(c['citation_edges'])} 条边、{num(c['unresolved_occurrences'])} 个未解析位置、{num(c['unresolved_tasks'])} 个开放工单。下一批按[递归队列](../../{queue['path']})继续。来源空列表、缺失标识及限流均保留在工单和查询日志中。

有一条 1979 年的引文展示了版本以外的书目歧义。施引书目第 64 项的题名以 *Deficit* 开头，登记的 DOI 末尾为 `sp012690`。该 DOI 的注册题名以 *Facilitation* 开头，*Deficit* 一文对应 `sp012691`。逐项记录保留了两个候选。[施引书目](../query-results/Q-RUN10-BCR-071-079-A1.json) · [两篇的标识和题名](../query-results/Q-RUN10-ID-EP-4da91f61dfaa6bb17f45-A1.json)

[版本逐条复核](RUN-0010-cited-versions.json) · [首轮来源覆盖](RUN-0010-supplemental-reference-coverage.json) · [摘要与署名](RUN-0010-abstract-affiliation-review.json) · [规范库审计](../validation/cp12-data-audit.json) · [历史重放](../validation/cp12-history.json) · [导出哈希](../validation/cp12-determinism.json) · [远端回读](../validation/cp12-post-push.json)
"""
    outputs={ROOT/REPORT:report.encode(),ROOT/RUN_FILE:dump(run)}
    for name,obj in qa_files.items():outputs[TEMP/"validation"/name]=dump(obj)
    for name,text in (("temp/change-log.md",f"\n\n## RUN-0010 / CP-0012\n\n{end}。检索 CP11 的 79 篇并展开下一层，新增 {num(delta['canonical_works'])} 篇及 {num(delta['citation_edges'])} 条边。[阶段报告](reports/P3-P6-CP0012.md)。\n"),
                      ("temp/progress.md",f"\n\n## CP-0012\n\n{end}。P3–P6 部分完成。共 {num(c['canonical_works'])} 篇，下一批 {num(queue['work_count'])} 篇。[阶段报告](reports/P3-P6-CP0012.md)。\n")):
        old=(ROOT/name).read_bytes();require(b"RUN-0010 / CP-0012" not in old and b"## CP-0012" not in old,"Existing progress entry")
        outputs[ROOT/name]=old.rstrip()+text.encode()
    rd=(ROOT/"README.md").read_text(encoding="utf8");start=rd.index("执行状态统一记录于 ");end_p=rd.index("\n\n",start)
    outputs[ROOT/"README.md"]=(rd[:start]+"执行状态统一记录于 [进度追踪](temp/progress.md)。[CP-0012 阶段报告](temp/reports/P3-P6-CP0012.md)记录本轮研究、覆盖和缺口。[CP-0012](temp/snapshots/checkpoints/CP-0012.json) 已通过数据验收，父检查点为 [CP-0011](temp/snapshots/checkpoints/CP-0011.json)。CP-0003 保留为 invalid 历史。"+rd[end_p:]).encode()
    cp["status"]="valid";cp["failure_reasons"]=cp["failure_reasons"][1:];cov["derived_views"]={"state":"validated","counts":meta["counts"],"artifacts":det["artifacts"]}
    cp["validation_results"].update(state="passed",completed_at_utc=end,audited_candidate_sha256=candidate,audited_candidate_commit=audited_commit,
           data_audit_errors=0,data_audit_warnings=data["warning_count"],deterministic_artifacts=len(EXPORTS),offline_browser_engines=2,existing_records_lost=0)
    allnames=(tracked()|{p.relative_to(ROOT).as_posix() for p in outputs})-{CANDIDATE,PUBLISHED}
    cp["artifact_hashes"]={p:sha(outputs[ROOT/p]) if ROOT/p in outputs else audit_run.sha(ROOT/p) for p in sorted(allnames)}
    validate_checkpoint(ROOT,cp)
    for p,raw in outputs.items():write(p,raw)
    write(ROOT/CANDIDATE,dump(cp,True));print("validated",len(allnames),c["canonical_works"],flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("mode",choices=["prepare","exports","audit","finalize"]);p.add_argument("--qa",type=Path)
    a=p.parse_args()
    if a.mode=="prepare":prepare()
    else:
        require(a.qa and a.qa.is_absolute() and not a.qa.resolve().is_relative_to(ROOT),"Use an external QA directory")
        {"exports":exports,"audit":audit,"finalize":finalize}[a.mode](a.qa)
