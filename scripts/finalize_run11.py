"""Certify CP13 only against its frozen research input, actual data audit and independently published exports."""
import argparse
from datetime import datetime
from pathlib import Path

from audit_cp10 import input_digest, input_snapshot
from checkpoint_cp10 import require, validate_checkpoint
from checkpoint_run11 import CANDIDATE, FRONTIER, HISTORY, INPUTS, TIMING, frozen_files, head
from escalate_unknown_run7 import git
from partitioned_checkpoint import load_checkpoint, write_checkpoint
from partitioned_research_json import encode, put, sha
from search_run11_bibliography import CP, ROOT, RUN, STATE, TEMP, digest, read, stamp

REPORT = TEMP / "reports/P3-P6-CP0013.md"
POST = "temp/validation/cp13-post-push.json"
PRE = TEMP / "validation/cp13-export-readback.json"
CHECKS = TEMP / "reports/RUN-0011-source-rechecks.json"


def gather(qa, candidate, candidate_hash):
    det = read(qa/"determinism.json")
    data = read(qa/"data-audit.json")
    meta = read(qa/"first/export-validation.json")
    bib = read(qa/"biber/bibtex-parse.json")
    remote = read(PRE)
    require(det["status"] == data["status"] == bib["status"] == remote["status"] == "passed" and
            not data["changed_inputs"] and data["error_count"]==0 and not meta["schema_errors"] and
            data["statistics"]["candidate_sha256"] == det["candidate_sha256"] == remote["checkpoint_sha256"] == candidate_hash,
            "Data QA subjects differ")
    require(det["artifacts"] == input_snapshot(ROOT,det["artifacts"]) and
            meta["artifact_hashes"]=={k:v["sha256"] for k,v in det["artifacts"].items()} and
            remote["physical_exports_compared_with_double_generation"] == len(det["artifacts"]), "Remote or local exports differ")
    require(bib["input_sha256"]==det["artifacts"]["ref.bib"]["sha256"] and bib["parser_exit_code"]==bib["missing_keys"]==bib["extra_keys"]==0 and
            bib["bibtex_entries"]==bib["checked_original_titles"]==bib["roundtripped_distinct_keys"]==candidate["counts"]["canonical_works"], "BibTeX title or key set differs")
    parts = bib["roundtrip_parts"]
    whole = bib["whole_file_parse"]
    require(parts and bib["roundtrip_input_sha256"]==bib["input_sha256"] and sum(p["entries"] for p in parts)==bib["bibtex_entries"] and
            sum(p["bytes"] for p in parts)==det["artifacts"]["ref.bib"]["bytes"] and all(p["exit_code"]==0 and p["returned_keys"]==p["entries"] for p in parts),
            "Native Biber coverage is incomplete")
    if len(parts)>1:
        require(whole and whole["input_sha256"]==bib["input_sha256"] and whole["parsed_entries"]==whole["distinct_keys"]==bib["bibtex_entries"],
                "The complete bibliography must also parse as a single file")
    out = {"cp13-data-audit.json":data,"cp13-determinism.json":det,"cp13-export-validation.json":meta,"cp13-bibtex-parse.json":bib}
    for browser in ("chrome","edge"):
        ui = read(qa/browser/"ui-audit-final.json")
        require(ui["passed"] and ui["checkpoint_id"]==CP and not ui["errors"] and ui["offline"] and len(ui["checks"])==9 and all(ui["checks"].values()) and
                all(len(ui["samples"][k])==3 for k in ("topics","misc")) and all(det["artifacts"][p]==v for p,v in ui["artifacts"].items()) and
                datetime.fromisoformat(ui["started_at_utc"])>=datetime.fromisoformat(candidate["created_at_utc"]), "Offline browser evidence differs")
        out["cp13-ui-"+browser+".json"] = ui
    schema_digest = data["statistics"].get("schema_validation_ledger_sha256")
    if schema_digest:
        ledger = qa/"schema-parts.json"
        require(digest(ledger)==schema_digest,"Final schema ledger differs")
        out["cp13-schema-parts.json"] = read(ledger)
    return out


def source_evidence(counts):
    timing = read(ROOT/TIMING)
    plan = read(TEMP/"reports/RUN-0011-source-rechecks-plan.json")
    checks = read(CHECKS)
    require(checks["plan_sha256"]==digest(TEMP/"reports/RUN-0011-source-rechecks-plan.json"),"Source recheck plan changed")
    ids = set(timing["unavailable_exact"])
    pairs = timing["overlapping_receipt_windows"]
    for p in pairs + timing["crossref_start_intervals_under_one_second"]:
        ids.update((p["first"],p["second"]))
    planned = {v["query_id"] for v in plan["successful_originals"]+plan["originals_without_returned_data"]}
    require(counts["run11_external_requests"]==timing["actual_requests"] and planned==ids and len(planned)==plan["affected"] and
            all(not p["earlier_guarded"] and not p["later_guarded"] for p in pairs) and
            all(not p["both_guarded"] for p in timing["crossref_start_intervals_under_one_second"]),"Provider controls or request ledger need review")
    expected = {r["query_id"]:r["sha256"] for r in plan["successful_originals"]}
    require(len(checks["results"])==len(expected) and {r["original_query_id"] for r in checks["results"]}==set(expected),"Missing source recheck")
    matching = 0
    for r in checks["results"]:
        evidence = TEMP/"query-results"/(r["final_query"]+".json")
        q = read(evidence)
        require(r["original_receipt_sha256"]==expected[r["original_query_id"]] and
                r["final_receipt_sha256"]==digest(evidence) and q.get("execution_limits",{}).get("per_provider_concurrency")==1,
                "Unbound source reobservation")
        matching += bool(r["matches"] and q["status"]=="success" and q["comparison"]["original_receipt_sha256"]==expected[r["original_query_id"]] and q["comparison"]["matches"])
    return dict(affected_originals=len(planned), original_failures_without_data=len(plan["originals_without_returned_data"]),
                original_observations_with_data=len(expected), independently_matched=matching, unresolved_observations=len(expected)-matching,
                overlapping_windows=len(pairs), short_crossref_start_intervals=len(timing["crossref_start_intervals_under_one_second"]),
                exact_time_unavailable=len(timing["unavailable_exact"]), overlapping_guarded_windows=0,historical_control_compliance_certified=False)


def narrative(cp, qa, source_control, accepted):
    counts=cp["counts"];cov=cp["coverage"];delta=cov["delta_from_cp12"];frontier=read(ROOT/FRONTIER)
    sources=cov["parent_reference_search"];abstract=cov["abstract_review"];version=cov["version_review"]
    original=version["CP11-original"];new=version["CP12-crossdate"]
    outcomes=[read(p) for p in sorted((TEMP/"reports/RUN-0011-canonical").glob("*.json"))]
    unresolved=sum(sum(r["unresolved"].values()) for b in outcomes for r in b["coverage"])
    version_tasks={tid for b in outcomes for tid in b["datasets"]["tasks"]["appended_ids"] if tid.startswith("T-R11-CITED-")}
    bib=qa["cp13-bibtex-parse.json"];ui=qa["cp13-ui-chrome.json"];edge=qa["cp13-ui-edge.json"]
    assets=qa["cp13-determinism.json"]["artifacts"]
    entity=read(PRE)["reconstructed_json"]["temp/exports/research_entities.json"]
    index=read(TEMP/"exports/research_entities/index.json")
    parts=[p for group in index["collections"].values() for p in group["parts"]]
    entities=entity["collection_counts"]
    status="已通过数据验收" if accepted else "尚未通过本轮验收，具体原因见检查点与运行记录"
    child=frontier["worklist"][0]["work_key"] if frontier["worklist"] else "无"
    return f"""# CP-0013 阶段报告

从已验收的 CP-0012 延续 SCOPE-0001，读取书目信息、摘要和参考文献列表。CP-0013 {status}。P3–P6 均继续开放。

| 阶段 | 本轮研究结果 | 尚待核实 |
| --- | --- | --- |
| P3 向后检索 | 从 Hildreth1987 至 Lurito1991 共查 {sources['visited']:,} 篇，{sources['with_entries']:,} 篇取得条目。登记 {frontier['canonical_positions']:,} 个来源位置，其中 {frontier['canonical_positions']-unresolved:,} 个已定位到文献。新增 {delta['canonical_works']:,} 篇文献、{delta['citation_edges']:,} 条引文边。 | {sources['without_entries']:,} 篇仍缺可归属列表，{unresolved:,} 个本轮位置的端点仍待核实，原始书目完整性核实 {sources['original_bibliographies_verified_complete']} 篇。下一层有 {frontier['discovered_work_count']:,} 篇，首项为 {child}。 |
| P4 施引版本 | 原有 4 条和 CP12 新增 61 条全部复核。确认 33 条所引原版，其中 bioRxiv 27 条、eLife 6 条。 | 原 4 条仍开放，61 条中有 28 条仍开放。合计 {original['unresolved']+new['unresolved']} 条证据不足、{original['later_citing_revision_only']+new['later_citing_revision_only']} 条仅支持施引后续版本、{new['indexed_identity_conflict']} 条索引冲突。新检索另产生 {len(version_tasks):,} 个版次复核任务，新增已证实引用作用 0 条。 |
| P5 作者和机构 | 对照 {abstract['records_checked']} 篇论文的 {abstract['bylines']} 个署名位置，登记 {abstract['publication_affiliations']} 条发表时机构关系。 | {abstract['unresolved_historical_affiliations']} 个 RIKEN 历史署名保留待核实。新增已证实项目归属 {abstract['new_project_attributions']} 条。 |
| P6 摘要与证据 | 新增 {abstract['summaries']} 篇带来源的中文摘要概述，Hildreth1987 的两个来源均未给出可用摘要。已有 {counts['assessments']} 个活跃 Assessment，其中 {counts['eligible_claims']} 条达到主题表标准。 | 本轮新增合格科学主张 {abstract['new_eligible_claims']} 条。摘要未给出的实验条件、量值和引用作用继续待核实。 |

[参考文献来源对账](RUN-0011-CP12-parent-reconciliation-reconciled.json) · [下一层队列](RUN-0011-frontier-after-CP12.json) · [施引版本逐条复核](RUN-0011-cited-versions.json) · [摘要与署名记录](RUN-0011-abstract-affiliation-review.json) · [另四篇运动视觉论文](RUN-0011-motion-abstracts.json)

第 56 条版本工单的参考文献列出 Clements 等人的 neuPrint 预印本，公开版本记录可定位到 v1。索引连接的期刊文献首作者是 Plaza，题名也不同。两条记录的版本关系继续待核实。[书目及版本证据](RUN-0011-cited-versions.json)

Weir 等人的摘要报告，果蝇扇形体内一组神经元在静止时对视觉运动缺乏响应，在系留飞行时基线活动升高，视野中从前向后的运动还会改变其响应。该记录支持行为状态影响这组细胞的视觉运动响应，速度标定和六自由度恢复能力仍待核实。[摘要和适用边界](RUN-0011-motion-abstracts.json)

书目消歧时，Yough 2022 的 PMID 与 1999 年论文 DOI 在索引中串接。Chao 与 Hempstead 1995 的文献也被分配了同一期相邻页 Jeannerod 等人的 DOI。已保存原始冲突、独立登记记录及修订前后的发现路径。[Yough 校正与版本记录](RUN-0011-cited-versions.json) · [Chao 与 Jeannerod 核对](RUN-0011-Chao1995-identifier-review.json)

## 数据维护、发布与缺口

累计 {counts['run11_external_requests']:,} 次来源请求，人工复核 {counts['run11_manual_reviews']} 项，付费 0。到期维护新增 {counts['run11_deadline_task_events']:,} 个事件、变更 {counts['run11_deadline_field_transitions']:,} 个字段状态。原时限保留，未升级的逾期工单为 {cov['unknown_review']['unupgraded_overdue_tasks']} 个。

早期请求有 {source_control['overlapping_windows']} 对回执时间窗重叠，Crossref 有 {source_control['short_crossref_start_intervals']} 对开始间隔短于一秒，{source_control['exact_time_unavailable']} 条缺少精确时刻。{source_control['affected_originals']} 条受影响回执中有 {source_control['original_failures_without_data']} 条未返回数据。其余 {source_control['original_observations_with_data']} 条在共享来源锁下重新核对，{source_control['independently_matched']} 条重现，{source_control['unresolved_observations']} 条仍待核实。所有原始时间与失败回执均已保留。[请求时间核对](RUN-0011-provider-timing.json) · [逐条重新观察](RUN-0011-source-rechecks.json)

规范库累计有 {counts['canonical_works']:,} 篇文献、{counts['versions']:,} 个版本、{counts['citation_edges']:,} 条引文边、{counts['unresolved_occurrences']:,} 个未解析位置和 {counts['unresolved_tasks']:,} 个开放工单。活跃主题文献并集 {counts['topic_work_union']:,} 篇，U00 有 {counts['u00_works']:,} 篇。后续沿已存游标从 {child} 继续，并优先复核缺少来源的列表、歧义版本和冲突机构。

独立 Biber 读回 {bib['roundtripped_distinct_keys']:,} 个书目键，原始导出题名亦已逐项核对。主题页 ref.html 为 {assets['ref.html']['bytes']:,} 字节，U00 独立入口 misc.html 为 {assets['misc.html']['bytes']:,} 字节。离线首屏可操作中位数在 Chrome 为主题 {ui['median_seconds']['topics']:.3f} 秒、U00 {ui['median_seconds']['misc']:.3f} 秒，在 Edge 为主题 {edge['median_seconds']['topics']:.3f} 秒、U00 {edge['median_seconds']['misc']:.3f} 秒。

标准 Biber 往返最初漏读了 9 个含特殊署名分隔符的条目。导出器现用 BibTeX 花括号保护来源中的完整姓名。传统 bibtex.exe 遇到仅大小写不同的稳定键时，将 {bib['classic_bibtex_compatibility']['missing_keys']:,} 个键视作重复，实际输出 {bib['classic_bibtex_compatibility']['output_keys']:,} 条。原始书目键和规范署名均保留。[两种解析器的实测记录](../validation/cp13-bibtex-parse.json)

Q2 独立目录含 {len(parts):,} 个数据分片，最大一片 {max(p['bytes'] for p in parts):,} 字节。GitHub 回读重建的完整 JSON 为 {entity['logical_bytes']:,} 字节，含 {entities['people']:,} 条人员记录、{entities['organizations']:,} 个机构、{entities['projects']:,} 个项目、{entities['work_refs']:,} 个书目指针和 {entities['relations']:,} 条关系。各组文件可单独读取。[Q2 文件清单与校验和](../exports/research_entities/index.json)

[Q2 人员、机构、项目及关系索引](../exports/research_entities/index.json) · [Q3 引文图索引](../exports/citation_graph/index.json) · [数据审计](../validation/cp13-data-audit.json) · [Git 历史重放](../validation/cp13-history.json) · [双生成导出哈希](../validation/cp13-determinism.json) · [独立远程导出核验](../validation/cp13-export-readback.json)
"""


def finalize(qa):
    require(not git(ROOT,"status","--porcelain").strip(), "Publish stable candidate and exports before certification")
    cp_path=ROOT/CANDIDATE; candidate_hash=digest(cp_path);public=read(cp_path); inputs=read(ROOT/INPUTS)
    recipe=read(TEMP/"validation/cp13-bibtex-repair.json")
    current=input_snapshot(ROOT,inputs)
    frozen_commit=public["validation_results"]["input_commit"]
    repaired_commit=recipe["repair_commit"]
    git(ROOT,"merge-base","--is-ancestor",frozen_commit,repaired_commit)
    git(ROOT,"merge-base","--is-ancestor",repaired_commit,"HEAD")
    changed={p for p in inputs if inputs[p]!=current[p]}
    require(changed==set(recipe["script_bindings"])=={"scripts/export_run.py","scripts/finalize_run11.py"} and
            recipe["frozen_input_commit"]==frozen_commit and recipe["status"]=="passed",
            "Unexpected change to the frozen input or export recipe")
    for path in changed:
        before=git(ROOT,"show",frozen_commit+":"+path)
        after=git(ROOT,"show",repaired_commit+":"+path)
        require(inputs[path]=={"bytes":len(before),"sha256":sha(before)} and
                current[path]=={"bytes":len(after),"sha256":sha(after)} and
                recipe["script_bindings"][path]=={"before":sha(before),"after":sha(after)},
                "Unbound export script correction: "+path)
    require(public["status"]=="invalid" and public["parent_checkpoint_id"]=="CP-0012" and set(inputs)==frozen_files() and
            input_digest(inputs)==public["validation_results"]["input_digest_sha256"] and
            digest(ROOT/HISTORY)==public["validation_results"]["history_sha256"], "Frozen canonical evidence changed")
    proofs=gather(qa,public,candidate_hash)
    require(recipe["after_bibliography_sha256"]==proofs["cp13-bibtex-parse.json"]["input_sha256"] and
            recipe["determinism_sha256"]==digest(qa/"determinism.json")==proofs["cp13-data-audit.json"]["statistics"]["staged_export_manifest_sha256"],
            "Repaired bibliography differs from the independently audited generations")
    source_control=source_evidence(public["counts"])
    run=read(STATE);now=stamp();hours=(datetime.fromisoformat(now)-datetime.fromisoformat(run["started_at_utc"])).total_seconds()/3600
    due=public["coverage"]["unknown_review"].get("next_deadline_utc")
    require(not due or datetime.fromisoformat(now)<datetime.fromisoformat(due), "Re-evaluate task deadlines before finalization")
    accepted=source_control["unresolved_observations"]==0 and hours<=run["budget"]["wall_clock_hours"]
    phase="valid" if accepted else "invalid"
    state="passed" if accepted else "pending_source_review" if source_control["unresolved_observations"] else "paused_budget"
    report=narrative(public,proofs,source_control,accepted)
    run.update(status="checkpointed_open" if accepted else ("paused_budget" if state=="paused_budget" else "validation_pending"),
               checkpoint_status=phase,checkpoint_validation_state=state,checkpoint_completed_at_utc=now,checkpoint_wall_clock_hours=hours,
               end_checkpoint_id=CP,closure=False,sync_state="Publication and final independent data readback are recorded in a separate receipt.",
               post_commit_verification_url=POST)
    files={REPORT:report.encode(),STATE:encode(run)+b"\n"}
    for name,doc in proofs.items():
        files[TEMP/"validation"/name]=encode(doc)+b"\n"
    log=TEMP/"change-log.md";log_text=log.read_text(encoding="utf-8");require("## RUN-0011 / CP-0013" not in log_text,"Existing final entry")
    files[log]=(log_text.rstrip()+f"\n\n## RUN-0011 / CP-0013\n\n{now}。查完 CP12 队列的 2,620 篇，登记 {public['coverage']['recursive_cursor']['new_child_tasks']:,} 个下一层任务。[阶段报告](reports/P3-P6-CP0013.md)\n").encode()
    progress=TEMP/"progress.md";old=progress.read_text(encoding="utf-8");marker="<!-- RUN-0011 live progress -->"
    if marker in old:
        body,tail=old.split(marker,1);old=body+tail.split("<!-- end RUN-0011 live progress -->",1)[1]
    title,rest=old.split("\n",1)
    require("## CP-0013" not in rest,"Already published CP13")
    view_status="CP-0013 已通过数据验收" if accepted else "CP-0013 待完成验收，最近通过验收的是 CP-0012"
    files[progress]=(title+f"\n\n## CP-0013\n\n{now}。{view_status}。P3–P6 继续开放。已查原队列 2,620 篇，原有版本疑义 65 条已复核，32 条待核实。[阶段报告](reports/P3-P6-CP0013.md) · [检查点](snapshots/checkpoints/CP-0013.json)\n\n"+rest.strip()+"\n").encode()
    rd=ROOT/"README.md";current=rd.read_text(encoding="utf-8");a=current.index("执行状态统一记录于 ");b=current.index("\n\n",a)
    files[rd]=(current[:a]+f"执行状态统一记录于 [进度追踪](temp/progress.md)。{view_status}。[CP-0013 阶段报告](temp/reports/P3-P6-CP0013.md)记录本轮研究与缺口。[检查点](temp/snapshots/checkpoints/CP-0013.json)继承 [CP-0012](temp/snapshots/checkpoints/CP-0012.json) 的数据和任务游标。CP-0003 保留为 invalid 历史。"+current[b:]).encode()
    cp=load_checkpoint(cp_path)
    cp["status"]=phase;cp["failure_reasons"]=cp["failure_reasons"][1:]
    if not accepted:cp["failure_reasons"].append("来源复核仍有缺口或本轮预算已经用尽，保留原始记录和可恢复游标。")
    cp["coverage"]["derived_views"]={"state":"validated","counts":proofs["cp13-export-validation.json"]["counts"],
                                    "hash_manifest":"temp/validation/cp13-determinism.json"}
    cp["coverage"]["historical_source_controls"]=source_control
    cp["validation_results"]["export_recipe_amendment"]="temp/validation/cp13-bibtex-repair.json"
    cp["validation_results"].update(state=state,data_audit="passed",exports="passed",native_bibtex="passed",offline_browsers=2,
        data_audit_errors=0,data_audit_warnings=proofs["cp13-data-audit.json"]["warning_count"], existing_records_lost=0,
        audited_candidate_sha256=candidate_hash,audited_candidate_commit=head(),updated_at_utc=now,post_commit_receipt=POST)
    tracked={p for p in git(ROOT,"ls-files","-z").decode().split("\0") if p}
    names=(tracked|{p.relative_to(ROOT).as_posix() for p in files})-{CANDIDATE.as_posix(),POST}
    cp["artifact_hashes"]={k:sha(files[ROOT/k]) if ROOT/k in files else digest(ROOT/k) for k in sorted(names)}
    validate_checkpoint(ROOT,cp)
    for path,data in files.items():put(path,data)
    write_checkpoint(cp_path,cp)
    final=read(cp_path)
    require(final["task_collections_sha256"]==public["task_collections_sha256"] and final["task_collections"]==public["task_collections"]
           and all(digest(ROOT/k)==v for k,v in cp["artifact_hashes"].items()),"Final files or queues changed")
    print("Checkpoint data status, bound artifacts, open tasks:",phase,len(names),cp["counts"]["unresolved_tasks"],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa",type=Path,required=True)
    a=parser.parse_args()
    require(a.qa.is_absolute() and not a.qa.resolve().is_relative_to(ROOT),"Use an independent QA directory")
    finalize(a.qa.resolve())
