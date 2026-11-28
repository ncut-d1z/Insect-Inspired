"""Seal the validated partial CP14 state and report research, maintenance and remaining work."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from audit_cp10 import input_digest, input_snapshot
from checkpoint_cp10 import require, validate_checkpoint
from checkpoint_run12 import CANDIDATE, HISTORY, INPUTS, POST, frozen_files, head
from escalate_unknown_run7 import git, sha
from finalize_run11 import gather
from partitioned_checkpoint import load_checkpoint, write_checkpoint
from partitioned_research_json import encode, put
from run12_progress import FRONTIER, SOURCES, TIMING
from run12_reference_search import CP, RUN, STATE
from search_run11_bibliography import ROOT, TEMP, digest, read, stamp

PHASE=TEMP/"reports/P3-P6-CP0014.md"
PRE=TEMP/"validation/cp14-export-readback.json"


def report(study,counts,coverage,timing,proof):
    s=study["study"];v=study["scientific_reviews"];resources=study["identifier_lookup"]
    start=datetime.fromisoformat(read(STATE)["started_at_utc"])
    measured=(datetime.fromisoformat(study["observed_at_utc"])-start).total_seconds()
    historical=read(TEMP/"reports/RUN-0012-throughput-baseline.json")
    return f"""# CP-0014 研究进度

本检查点继承最近有效的 CP-0012，并从 CP-0013 已独立回读的数据继续。CP-0013 的原始状态及回执保存在历史中。P3–P6 均在继续。

| 阶段 | 本轮实质成果 | 剩余缺口 |
| --- | --- | --- |
| P3 向后检索 | 按序登记 {s['canonical_parents']:,} 篇母文献，其中 {s['with_entries']:,} 篇取得条目。{s['canonical_positions']:,} 个来源位置中，{s['resolved_positions']:,} 个已绑定目标。新增 {s['new_backward_works']:,} 篇规范文献和 {s['new_backward_edges']:,} 条去重引用边。 | {s['without_entries']:,} 篇目前没有可归属条目，另有 {s['unresolved_positions']:,} 个位置身份待查。原队列尚余 {s['remaining_original_parents']:,} 篇。 |
| P4 施引与版本 | 两组施引索引共返回 154 项。已定位 5 对引文，其中 4 对来自出版商登记书目，1 对来自含书目原文的索引。新增 {s['new_forward_works']} 篇规范文献和 {s['new_forward_edges']} 条边。20 项跨日期工单逐条复核，{v['versions']['original_version_supported']} 项已定位版次。 | 最早 4 项回查登记 XML 后仍未定位原始修订。继承的 32 项与 627 项中共余 {32+627-v['versions']['original_version_supported']} 项。P3 又产生 {s['new_crossdate_tasks']:,} 项。其余施引命中、来源覆盖和引用作用继续核验。 |
| P5 研究主体 | 核对 {v['abstracts']['byline_positions']} 个署名位置，其中 {v['abstracts']['publication_affiliations']} 条发表时机构关系有来源支持。两家同名 York University 经国家和城市区分。另依据出版社 RIS 的唯一署名将 H. Schöne 的姓氏恢复为原拼写，保留原记录及文献键。 | 两条历史署名的机构身份待核实。出版登记中的资助方和编号见下文。 |
| P6 主题证据 | 新增 {v['abstracts']['abstracts']+v['insect_abstracts']['reviewed_abstracts']} 份与来源指纹绑定的中文摘要，其中 {v['insect_abstracts']['reviewed_abstracts']} 份为本轮专项核查的昆虫里程计或学习飞行文献。人类虚拟走廊距离判断、猕猴航向线索、鸟类飞行流场和计算模型的适用条件分别登记。 | 新增达到主题验收门槛的判断为 0。累计 {counts['assessments']} 项活动评估，其中 {counts['eligible_claims']} 项已达标。 |

CP12 后续的 {v['cp12_xml']['tickets']} 条疑义另按施引论文合并复核。{v['cp12_xml']['distinct_parent_lists']} 份登记书目中复用了 {v['cp12_xml']['reused_parent_lists']} 份现有回执，{v['cp12_xml']['positions_matched']} 条定位到同一条目，{v['cp12_xml']['position_unavailable']} 条仍未定位。新确定原始版次 {v['cp12_xml']['newly_resolved']} 条。[逐项复核依据](RUN-0012-CP12-deposit-reviews.json)

本轮另核对了 {v.get('publication_funding',{}).get('works_checked',0)} 篇的出版登记资助字段。其中 {v.get('publication_funding',{}).get('works_with_funder_metadata',0)} 篇列有资助方，共 {v.get('publication_funding',{}).get('distinct_funder_award_pairs',0)} 组不同的资助方与编号。项目负责人和正式成果归属继续待核实。

## 检索与同步效率

上轮 2,620 篇母文献从开跑至最后规范更新用了 4 小时 56 分 06 秒。随后到封存另用 64 分 22 秒，其中一次完整数据审计约 31 分 56 秒。本轮通过批量查标识、跨来源并行和同来源互斥，保留来源顺序、条目位置与错误回执。

从本轮启动至已同步规范数据冻结共 {measured/3600:.2f} 小时。按此口径，每小时处理 {s['canonical_parents']*3600/measured:,.0f} 篇母文献、登记 {s['canonical_positions']*3600/measured:,.0f} 个来源位置。上轮对应均值为 {historical['parents']*3600/historical['seconds_until_canonical_watermark']:,.0f} 篇与 {historical['positions']*3600/historical['seconds_until_canonical_watermark']:,.0f} 个位置。两批文献每篇的参考数不同。这两个速率均包含入库期间的 Git 推送与回读，冻结后的完整验收另外计时。

第 513–768 篇的规范入库用时 163 秒，Git 提交、推送及独立回读用时 172 秒，其中推送用时 159 秒。第 1,537–1,792 篇首次推送中断后暂停了检索。原提交经独立回读确认后恢复，后续来源批次缩到 128 篇。[同步恢复记录](RUN-0012-sync-recovery-01792.json)

本轮在 {resources['identifier_request_groups']} 个身份查询组中安排了 {resources['identifier_candidates']:,} 个标识候选。各批已有规范身份或元数据命中合计 {resources['plan_identifier_cache_memberships']:,} 个标识，该数按计划内去重。所有来源实际请求 {timing['requests']:,} 次，人工复核 {study['manual_review_items']} 项。各来源时间窗重叠 {len(timing['overlapping_source_windows'])} 次，Crossref 起始间隔少于一秒 {len(timing['crossref_short_intervals'])} 次。

欧洲 PMC 的 56 个实测样本中，批量字段标记为无的 54 个列表均为空，标记为有的 2 个列表共给出 59 条。对同一批 63 个零匹配 OpenAlex 父记录另查条目接口，均返回零条。后续优先取回阳性、缺失和来源矛盾项，低收益接口仍有复查入口。原文书目完整性保持待核实。

## 数据维护与验收

工单事件、分片校验、导出和 Git 同步均单列为维护工作。到期工单原有时限保留。数据审计发现 {proof['cp14-data-audit.json']['error_count']} 个错误、{proof['cp14-data-audit.json']['warning_count']} 个继承警告。{proof['cp14-determinism.json']['artifact_count']} 个导出文件已独立生成两次并逐文件比对。BibTeX 在 Windows 上按完整文件与分批回读检查，Chrome 与 Edge 已通过离线书目检查。

恢复时从 `{s['next_original_key']}` 接续。合并剩余母文献与本轮新发现后，向后队列共有 {s['next_frontier_count']:,} 个任务。来源缺口、精确版次与机构消歧另保存在各自工单。阶段门禁和证据要求沿用 README。

[逐批来源与规范计数](RUN-0012-reference-accounting.json) · [递归游标](RUN-0012-next-frontier.json) · [版本复核](RUN-0012-version-decisions.json) · [署名与摘要](RUN-0012-motion-reviews.json) · [昆虫视觉里程计摘要](RUN-0012-insect-odometry-reviews.json) · [前向引文定位](RUN-0012-forward-reviewed.json)
"""


def finalize(qa):
    require(not git(ROOT,"status","--porcelain").strip(),"Publish stable received data before sealing")
    cp_path=ROOT/CANDIDATE
    public=read(cp_path);candidate_hash=digest(cp_path);candidate_commit=head()
    require(public["checkpoint_id"]==CP and public["status"]=="invalid" and public["validation_results"]["state"]=="pending","Unexpected candidate")
    inputs=read(ROOT/INPUTS)
    require(set(inputs)==frozen_files() and inputs==input_snapshot(ROOT,inputs) and input_digest(inputs)==public["validation_results"]["input_digest_sha256"]
            and digest(ROOT/HISTORY)==public["validation_results"]["history_sha256"],"Frozen research or export recipe changed")
    proofs=gather(qa,public,candidate_hash,checkpoint=CP,prereadback=PRE)
    study=read(SOURCES);timing=read(TIMING);run=read(STATE);counts=public["counts"];coverage=public["coverage"]
    require(not timing["overlapping_source_windows"] and not timing["crossref_short_intervals"] and coverage["unknown_review"]["unupgraded_overdue_tasks"]==0,
            "Current source timing or field-review maintenance needs attention")
    deadline=datetime.fromisoformat(run["started_at_utc"])+timedelta(hours=run["budget"]["wall_clock_hours"])
    require(datetime.now(timezone.utc)<deadline,"Run budget reached before sealing")
    cp=load_checkpoint(cp_path)
    files={TEMP/"validation"/k:encode(v)+b"\n" for k,v in proofs.items()}
    now=stamp()
    files[PHASE]=report(study,counts,coverage,timing,proofs).encode()
    local_time=datetime.fromisoformat(now).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M UTC+8")
    prog=TEMP/"progress.md";old=prog.read_text("utf-8");title,rest=old.split("\n",1)
    require("## CP-0014" not in rest,"CP14 already in progress log")
    files[prog]=(title+"\n\n## CP-0014\n\n"+local_time+"。已通过数据验收，P3–P6 持续开放。"
        +f"已入库 {study['canonical_parents']:,} 篇母文献的检索进度，下一游标为 `{study['next_original_key']}`。"
        +"[本轮研究及缺口](reports/P3-P6-CP0014.md) · [检查点](snapshots/checkpoints/CP-0014.json)\n\n"+rest.lstrip()).encode()
    log=TEMP/"change-log.md";old=log.read_text("utf-8")
    files[log]=(old.rstrip()+"\n\n## CP-0014\n\n"+local_time+"。保存向后检索、具体版次、施引定位、署名和摘要证据。"
        +"阶段统计及维护明细见[本轮报告](reports/P3-P6-CP0014.md)。\n").encode()
    rd=ROOT/"README.md";old=rd.read_text("utf-8");a=old.index("执行状态统一记录于 ");b=old.index("\n\n",a)
    files[rd]=(old[:a]+"执行状态统一记录于 [进度追踪](temp/progress.md)。最近有效检查点为 [CP-0014](temp/snapshots/checkpoints/CP-0014.json)。"
        +"[本轮研究报告](temp/reports/P3-P6-CP0014.md)给出 P3–P6 的实质成果、来源缺口和继续检索的游标。CP-0013 保留为 invalid 历史。"+old[b:]).encode()
    run.update(status="checkpoint_validated_partial",sealed_at_utc=now,final_checkpoint_id=CP,closure=False)
    files[STATE]=encode(run)+b"\n"
    cp["status"]="valid";cp["failure_reasons"]=[reason for reason in cp["failure_reasons"] if "正在进行" not in reason]
    cp["coverage"]["derived_views"]=dict(state="validated",counts=proofs["cp14-export-validation.json"]["counts"],hash_manifest="temp/validation/cp14-determinism.json")
    cp["validation_results"].update(state="passed",data_audit="passed",exports="passed",native_bibtex="passed",offline_browsers=2,data_audit_errors=0,
        data_audit_warnings=proofs["cp14-data-audit.json"]["warning_count"],existing_records_lost=0,audited_candidate_sha256=candidate_hash,
        audited_candidate_commit=candidate_commit,updated_at_utc=now,post_commit_receipt=POST,run_finalization_fields=["status","sealed_at_utc","final_checkpoint_id","closure"])
    tracked=set(git(ROOT,"ls-files","-z").decode().split("\0"))-{""}
    names=(tracked|{p.relative_to(ROOT).as_posix() for p in files})-{CANDIDATE.as_posix(),POST}
    cp["artifact_hashes"]={k:sha(files[ROOT/k]) if ROOT/k in files else digest(ROOT/k) for k in sorted(names)}
    validate_checkpoint(ROOT,cp)
    require(datetime.now(timezone.utc)<deadline,"Run budget reached during final validation")
    for path,data in files.items():put(path,data)
    write_checkpoint(cp_path,cp)
    sealed=read(cp_path)
    require(sealed["task_collections_sha256"]==public["task_collections_sha256"] and
            all(digest(ROOT/k)==h for k,h in cp["artifact_hashes"].items()),"Final artifact or cursor change")
    if datetime.now(timezone.utc)>=deadline:
        cp["status"]="invalid";cp["validation_results"]["state"]="paused_budget"
        write_checkpoint(cp_path,cp)
        raise RuntimeError("Run budget reached before local closure. Reconcile provisional status files before publication.")
    print(CP,"valid",len(names),"bound artifacts",len(cp["unresolved_tasks"]),"open task cursors",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--qa",type=Path,required=True)
    finalize(parser.parse_args().qa.resolve())
