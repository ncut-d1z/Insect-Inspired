"""Prepare or certify CP11 using the full dataset audit, seven byte-identical exports and ten offline UI checks."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import audit_cp10 as legacy
import audit_run
from checkpoint_cp10 import UI_CHECKS, DIMENSIONS, validate_checkpoint
from coverage_run9 import collect
from escalate_unknown_run7 import git, require
from export_checkpoint_windows import generate
from history_run9 import BASE, TREE, ROOT, CP, RUN, read, verify_history

CANDIDATE="temp/snapshots/checkpoints/CP-0011.json"
RUN_FILE="temp/runs/RUN-0009.json"
REPORT="temp/reports/P3-P6-CP0011.md"
HISTORY="temp/validation/cp11-history.json"
MUTABLE={CANDIDATE,RUN_FILE,REPORT,"README.md","temp/change-log.md","temp/progress.md"}
RECEIPT="temp/validation/cp11-post-push.json"


def stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")


def dump(value,compact=False):
    return (json.dumps(value,ensure_ascii=False,indent=None if compact else 2,separators=(",",":") if compact else None,allow_nan=False)+"\n").encode()


def tracked():
    names=git(ROOT,"ls-files","-z","--cached","--others","--exclude-standard").decode().split("\0")
    return {p for p in names if p and (ROOT/p).is_file()}


def frozen_names():
    return {p for p in tracked() if p not in MUTABLE and (not p.startswith("temp/validation/cp11-") or p==HISTORY)}


def inventory(names):
    return legacy.input_snapshot(ROOT,names)


def write(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+".cp11-part")
    require(not temporary.exists(),"Unexpected write residue "+str(temporary))
    temporary.write_bytes(raw);temporary.replace(path)


def history_check(qa):
    real=verify_history()
    require(real["old_records_lost"]==0,"Historical loss")
    write(qa/"bibliographic-history.json",dump(real))
    return real


def prepare(qa):
    if (ROOT/CANDIDATE).exists():require(read(CANDIDATE)["status"]=="invalid","Cannot rewrite accepted CP11")
    run=read(RUN_FILE)
    require(run["start_commit_sha"]==BASE and run["start_checkpoint_id"]=="CP-0010","Wrong run baseline")
    parent=read("temp/snapshots/checkpoints/CP-0010.json");require(parent["status"]=="valid","Invalid parent")
    facts=json.loads((qa/"bibliographic-first/export-validation.json").read_bytes())
    outputs=inventory(legacy.EXPORTS)
    require(not facts["schema_errors"] and facts["checkpoint_id"]==CP and all(facts["artifact_hashes"].get(k)==v["sha256"] for k,v in outputs.items()),"Installed export mismatch")
    h=history_check(qa);write(ROOT/HISTORY,dump(h))
    c,coverage,cursor,open_tasks=collect()
    base=read("temp/reports/RUN-0009-bibliographic-integration.json")
    require(c["canonical_works"]==facts["counts"]["bibtex_entries"]==parent["counts"]["canonical_works"]+base["counts"]["registered_works"],"Work coverage")
    require(c["citation_edges"]==facts["counts"]["graph_edges"] and c["unresolved_occurrences"]==facts["counts"]["unresolved_pointers"]
            and c["assessments"]==facts["counts"]["active_assessments"],"View counters differ")
    coverage["derived_views"]={"state":"generated_pending_validation","artifacts":outputs,"counts":facts["counts"]}
    frozen=inventory(frozen_names())
    created=stamp()
    cp=dict(checkpoint_id=CP,scope_id=run["scope_id"],parent_checkpoint_id="CP-0010",schema_version=parent["schema_version"],created_at_utc=created,
            task_cursor_state=cursor,query_log_high_watermark=c["queries"],counts=c,coverage=coverage,unresolved_tasks=open_tasks,
            failure_reasons=["候选待全量数据审计、独立导出和离线界面验收。","未决书目、施引版本、主体身份及科学证据任务仍然开放。"],
            artifact_hashes={},validation_results=dict(state="pending",baseline_commit=BASE,baseline_tree=TREE,input_frozen_at_utc=created,
                canonical_input_hashes=frozen,canonical_input_digest_sha256=legacy.input_digest(frozen),
                run_accounting_projection=legacy.run_accounting_projection(run),run_at_freeze_sha256=audit_run.sha(ROOT/RUN_FILE),
                research_closure_established=False,post_commit_receipt=RECEIPT,history_file=HISTORY),status="invalid")
    validate_checkpoint(ROOT,cp);write(ROOT/CANDIDATE,dump(cp,True));print("frozen",len(frozen),c["canonical_works"],len(open_tasks),flush=True)


def bound(cp):
    v=cp["validation_results"];expected=v["canonical_input_hashes"]
    require(cp["checkpoint_id"]==CP and cp["parent_checkpoint_id"]=="CP-0010" and cp["status"]=="invalid","Expected frozen candidate")
    require(set(expected)==frozen_names() and inventory(expected)==expected and legacy.input_digest(expected)==v["canonical_input_digest_sha256"],"Frozen input set differs")
    require(v["run_accounting_projection"]==legacy.run_accounting_projection(read(RUN_FILE)) and audit_run.sha(ROOT/RUN_FILE)==v["run_at_freeze_sha256"],"Run changed after freeze")
    return v["canonical_input_digest_sha256"]


class FullAudit(audit_run.Audit):
    def load_json(self,path,kind=None):
        result=super().load_json(path,kind)
        # Validate each historical checkpoint in full, then retain only the fields
        # used by the general audit. This keeps the Windows working set bounded.
        if kind=="checkpoint" and result is not None:
            return {k:result[k] for k in ("checkpoint_id","scope_id","status","parent_checkpoint_id","artifact_hashes")}
        return result

    def load(self):
        cp=read(CANDIDATE);digest=bound(cp);self.candidate_sha=audit_run.sha(ROOT/CANDIDATE)
        self.stats["cp11_input_digest"]=digest;self.stats["candidate_sha256"]=self.candidate_sha
        del cp
        old_manifest=json.loads(git(ROOT,"show",BASE+":temp/partitions/manifest.json"))
        entry=old_manifest["datasets"].get("assessments.jsonl",{"parts":[{"path":"assessments.jsonl"}]})
        previous=[json.loads(line) for p in entry["parts"] for line in git(ROOT,"show",BASE+":temp/"+p["path"]).splitlines() if line]
        self._manual_assessment_baselines=[(BASE+":temp/assessments.jsonl",previous)]
        super().load()

    def finish(self):
        if hasattr(self,"candidate_sha"):
            try:
                self.require(audit_run.sha(ROOT/CANDIDATE)==self.candidate_sha,"cp11_frozen_candidate_changed","Candidate SHA-256 differs")
                self.require(bound(read(CANDIDATE))==self.stats["cp11_input_digest"],"cp11_frozen_inputs_changed","Input digest differs")
            except Exception as error:self.note("cp11_finish_binding_error",str(error))
        return super().finish()


def independent(qa):
    cp=read(CANDIDATE);digest=bound(cp);candidate=audit_run.sha(ROOT/CANDIDATE)
    out=qa/("independent-"+datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
    bindings=generate(out,CP);checks=inventory(legacy.EXPORTS)
    require(checks==bindings and bound(cp)==digest and audit_run.sha(ROOT/CANDIDATE)==candidate,"Seven outputs or frozen inputs differ")
    write(qa/"cp11-determinism.json",dump(dict(status="passed",checkpoint_id=CP,checked_at_utc=stamp(),candidate_sha256=candidate,
         input_digest=digest,independent_output=out.name,checks=checks,artifact_count=len(checks),unchanged_inputs=True)))


def documents(cp,raw_audit,det,ui,meta):
    c=cp["counts"]; cov=cp["coverage"]; now=stamp()
    targets={"ref.bib":c["canonical_works"],"ref.html":ui["summary"]["table_rows"],
       "temp/exports/citation_graph.json":c["citation_edges"],"temp/exports/research_entities.json":meta["counts"]["entity_relations"],
       "temp/exports/evidence_matrix.csv":c["assessments"],"temp/exports/research_implications.csv":c["assessments"],
       "temp/exports/research_paths.json":meta["counts"]["paths"]}
    dims="\n".join("| "+k+" | "+str(v["denominator"])+" | "+json.dumps(v["states"],ensure_ascii=False,sort_keys=True)+" |" for k,v in cov.items() if k in DIMENSIONS)
    artifacts="\n".join(f"| {k} | {targets[k]:,} | {v['bytes']:,} | {v['sha256']} |" for k,v in det["checks"].items())
    changes="\n".join(f"| {k} | {read_parent[k]:,} | {c[k]:,} | {c[k]-read_parent[k]:+,} |" for k in [
        "canonical_works","versions","people_records","organizations","projects","reference_occurrences","resolved_occurrences","unresolved_occurrences",
        "citation_edges","context_reviewed_edges","assessments","eligible_claims","insufficient_claims","counter_evidence_claims","unresolved_tasks"] if (read_parent:=cp["coverage"].get("_parent_counts",{})) and k in read_parent)
    report=f"""# CP-0011 书目检索阶段报告

SCOPE-0001，RUN-0009。CP-0010 为有效父检查点。文献截止为 2026-11-26T05:24:08Z。P3–P6 均为部分完成。P7 最终验收未启动，P8 未触发。

## 本轮研究

- P3 从 Sunkara 等的 Europe PMC 参考文献列表取得 55/55 条。对 S06 既有参考列表另解析 4 条未决书目。保留印刷和登记来源各自的出现项。
- P4 从 Rayshubskiy 等的 Europe PMC 施引索引取得 44/44 条。35 条早于正式版，按参考文献 DOI 及日期核实 22 条，10 条缺少版本 DOI，3 条存在版本或时序冲突。该轮没有新增已确认的引用作用。
- P3/P4 合计 99 条索引记录，匹配已有 Work 20 条，新登记 Work 79 条及书目 Version 79 条，增加 89 条 Work 级引文边。新发现的 Work 已返回队列。
- P5 在允许查阅的书目中处理署名。新建 283 条署名身份记录，Sunkara 等的三位署名作者已对应到 Work。跨文献个人消歧、机构归属和项目输出仍须逐项核查。Congento 项目线索待核实。
- P6 保存三篇索引摘要的原创中文概述和主题线索。新增合格科学主张 0 条。阅读限制收到前形成的一个实验主张已转待核实，四条正文语境也转待核实。

[书目入库清单](RUN-0009-bibliographic-integration.json) · [引用版本逐条记录](RUN-0009-bibliographic-citation-versions.json) · [摘要审阅](RUN-0009-bibliographic-abstracts.json) · [六分支阅读范围](RUN-0009-bibliography-roadmap.json)

## 覆盖及验收

| 指标 | CP10 | CP11 | 增量 |
| --- | ---: | ---: | ---: |
{changes}

| 维度 | Work 分母 | 状态及数量 |
| --- | ---: | --- |
{dims}

独立 Work 共 {c['canonical_works']:,} 条，主题并集 {c['topic_work_union']} 条，U00 为 {c['u00_works']:,} 条。各主题 Work 数为 {json.dumps(cov['reconciliation']['T_i'],ensure_ascii=False)}。出版身份置信度分布见检查点。缺少独立挂钩证据的事项仍在开放队列。

保留 {c['seed_records']} 条种子、{c['retained_uploads']} 个已接纳上传、{c['distinct_files']} 个不同文件哈希及 {c['file_backed_versions']} 个带文件的 Version。历史合并对 {c['merged_work_pairs']}，拒绝上传事件 {c['rejected_upload_events']}，级联事件 {c['cascade_events']}。本轮合并 Work 0。

证据门禁的拒收代码与绝对尺度检查见 {json.dumps(cov['scientific_gates'],ensure_ascii=False)}。本次只用书目信息、摘要及参考文献列表。版本匹配或摘要概述不足以确认引用作用、实验误差或绝对尺度。

## 数据维护与缺口

本轮来源请求 {c['run9_external_requests']} 次、人工复核 {c['run9_manual_reviews']} 项、付费 0。新限制生效后的 15 次来源请求含一次 HTTP 400，后续按 DOI 重新检索成功。7 篇施引论文复用了既有书目出现项。到期维护追加 15,502 个工单事件，变更 15,673 个字段状态，保留原始时钟。开放 unknown 工单 {c['open_unknown_review_tasks']:,} 个，其中到期 {c['overdue_open_unknown_review_tasks']:,} 个，到期未升级 0 个。下一到期时刻为 {cov['unknown_review']['next_deadline_utc']}。未结任务 {c['unresolved_tasks']:,} 个，未解析引文出现项 {c['unresolved_occurrences']:,} 条。递归闭包未成立。

## 派生视图

| 文件 | 条目、行或关系数 | 字节 | SHA-256 |
| --- | ---: | ---: | --- |
{artifacts}

HTML 按十张表的 Work 行计数。图谱按引用边计数，实体视图按关系计数。字段、排序、外键、作用域和集合对账见[完整数据审计](../validation/cp11-data-audit.json)。审计有 {raw_audit['error_count']} 项错误、{raw_audit['warning_count']} 项警告，警告类别详见该文件。[七项导出确定性](../validation/cp11-determinism.json) · [十项离线界面检查](../validation/cp11-ui-validation.json) · [历史保留](../validation/cp11-history.json) · [发布后回读](../validation/cp11-post-push.json)。
"""
    brief=f"# 当前研究进度\n\nSCOPE-0001 / RUN-0009 / CP-0011，已通过检查点验收。P3–P6 部分完成，递归闭包仍开放。\n\n{c['canonical_works']:,} 条 Work、{c['versions']:,} 个 Version、{c['citation_edges']:,} 条引文边、{c['eligible_claims']} 条合格主张。新增 79 篇书目，3 篇摘要概述，新增合格科学主张 0 条。未解析引文出现项 {c['unresolved_occurrences']:,} 条，未结任务 {c['unresolved_tasks']:,} 个。\n\n[阶段报告](reports/P3-P6-CP0011.md) · [检查点](snapshots/checkpoints/CP-0011.json) · [后置同步凭据](validation/cp11-post-push.json)\n"
    rd=(ROOT/"README.md").read_text(encoding="utf8")
    start=rd.index("执行状态统一记录于 ");end=rd.index("\n\n",start)
    rd=rd[:start]+"执行状态统一记录于 [进度追踪](temp/progress.md)。[CP-0011 阶段报告](temp/reports/P3-P6-CP0011.md)列出本轮书目检索、覆盖及缺口。[CP-0011](temp/snapshots/checkpoints/CP-0011.json) 已通过数据检查点验收，有效父检查点为 [CP-0010](temp/snapshots/checkpoints/CP-0010.json)。CP-0003 保留为 invalid 历史。"+rd[end:]
    log=(ROOT/"temp/change-log.md").read_text(encoding="utf8")
    require("## RUN-0009 / CP-0011" not in log,"Duplicate change-log entry")
    log=log.rstrip()+f"\n\n## RUN-0009 / CP-0011\n\n{now}。已验证 CP10 恢复与远端回读。当前书目范围下新增 79 条 Work、89 条引文边，保留 13 条未决的早期施引版本复核。P3–P6 持续部分完成。[本轮报告](reports/P3-P6-CP0011.md)。\n"
    return {REPORT:report.encode(),"temp/progress.md":brief.encode(),"temp/change-log.md":log.encode(),"README.md":rd.encode()}


def finalize(qa,ui_dir):
    cp=read(CANDIDATE);digest=bound(cp);ch=audit_run.sha(ROOT/CANDIDATE)
    data=json.loads((qa/"data-audit.json").read_bytes());det=json.loads((qa/"cp11-determinism.json").read_bytes())
    ui=json.loads((ui_dir/"ui-audit-final.json").read_bytes());meta=json.loads((qa/"bibliographic-first/export-validation.json").read_bytes())
    require(data["status"]=="passed" and not data["changed_inputs"] and data["error_count"]==0 and
            data["statistics"]["candidate_sha256"]==ch and data["statistics"]["cp11_input_digest"]==digest,"Full data audit incomplete")
    require(det["status"]=="passed" and det["candidate_sha256"]==ch and det["input_digest"]==digest and det["checks"]==inventory(legacy.EXPORTS),"Independent export verification failed")
    require(ui["checkpoint_id"]==CP and ui["passed"] and not ui["errors"] and not ui["input_changed"] and set(ui["checks"])==UI_CHECKS and all(ui["checks"].values()) and
            ui["html_sha256"]==ui["html_sha256_after"]==audit_run.sha(ROOT/"ref.html"),"Offline browser audit failed")
    frozen_at=cp["validation_results"]["input_frozen_at_utc"]
    require(datetime.fromisoformat(ui["started_at_utc"])>=datetime.fromisoformat(frozen_at) and
            datetime.fromisoformat(data["audited_at_utc"])>=datetime.fromisoformat(frozen_at),"QA predates freeze")
    require(datetime.now(timezone.utc)<datetime.fromisoformat(cp["coverage"]["unknown_review"]["next_deadline_utc"]),"Re-evaluate due tasks before certification")
    now=stamp()
    run=read(RUN_FILE);projection=legacy.run_accounting_projection(run)
    run.update(status="checkpointed_open",end_checkpoint_id=CP,checkpoint_status="valid",checkpoint_validation_state="passed",
               checkpoint_completed_at_utc=now,checkpoint_wall_clock_hours=round((datetime.fromisoformat(now)-datetime.fromisoformat(run["started_at_utc"])).total_seconds()/3600,4),
               sync_state="post_commit_independent_readback",post_commit_verification_url=RECEIPT)
    require(legacy.run_accounting_projection(run)==projection,"Run authorization or accounting changed")
    cp["coverage"]["_parent_counts"]=read("temp/snapshots/checkpoints/CP-0010.json")["counts"]
    out=documents(cp,data,det,ui,meta);del cp["coverage"]["_parent_counts"]
    out[RUN_FILE]=dump(run)
    out["temp/validation/cp11-data-audit.json"]=(qa/"data-audit.json").read_bytes()
    out["temp/validation/cp11-determinism.json"]=(qa/"cp11-determinism.json").read_bytes()
    out["temp/validation/cp11-ui-validation.json"]=(ui_dir/"ui-audit-final.json").read_bytes()
    out["temp/validation/cp11-export-validation.json"]=(qa/"bibliographic-first/export-validation.json").read_bytes()
    require(set(ui["screenshots"])=={"html-desktop.png","html-topic.png","html-mobile.png","html-mobile-controls.png"},"UI evidence incomplete")
    for name in ui["screenshots"]:
        raw=(ui_dir/name).read_bytes();require(raw.startswith(b"\x89PNG\r\n\x1a\n"),"Invalid screenshot")
        out["temp/validation/cp11-qa/"+name]=raw
    out["temp/validation/cp11-qa/audited-candidate.json"]=(ROOT/CANDIDATE).read_bytes()
    out["temp/validation/cp11-qa/receipt.json"]=dump(dict(checked_at_utc=now,candidate_sha256=ch,input_digest=digest,
        checks={k:legacy.sha_bytes(v) for k,v in out.items() if k.startswith("temp/validation/")}))
    cp["status"]="valid";cp["failure_reasons"]=cp["failure_reasons"][1:]
    cp["coverage"]["derived_views"]["state"]="validated_seven_artifacts"
    cp["validation_results"].update(state="passed",data_audit="passed",determinism="passed",ui_validation="passed",
        final_artifact_hashes="verified",completed_at_utc=now,audited_candidate_sha256=ch,data_audit_errors=0,data_audit_warnings=data["warning_count"],
        existing_records_lost=0,ui_checks_passed=10,deterministic_artifacts=7)
    names=(tracked()|set(out))-{CANDIDATE}
    cp["artifact_hashes"]={k:legacy.sha_bytes(out[k]) if k in out else audit_run.sha(ROOT/k) for k in sorted(names)}
    validate_checkpoint(ROOT,cp)
    for p,raw in out.items():write(ROOT/p,raw)
    write(ROOT/CANDIDATE,dump(cp,True))
    print("validated",CP,len(cp["artifact_hashes"]),ch,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["prepare","audit","determinism","finalize"])
    parser.add_argument("--qa",type=Path,required=True);parser.add_argument("--ui",type=Path)
    a=parser.parse_args();qa=a.qa.resolve()
    require(not qa.is_relative_to(ROOT) and qa.is_dir(),"External QA directory required")
    if a.mode=="prepare":prepare(qa)
    if a.mode=="audit":sys.exit(FullAudit(ROOT,qa/"data-audit.json",datetime.now(timezone.utc),12).run())
    if a.mode=="determinism":independent(qa)
    if a.mode=="finalize":finalize(qa,a.ui.resolve() if a.ui else qa/"ui")
