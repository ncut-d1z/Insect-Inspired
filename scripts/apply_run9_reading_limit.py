"""Apply the user's material limit to unaccepted RUN9 records; leave published checkpoints intact."""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import gates
from advance_review_deadlines import transaction_directory
from escalate_unknown_run7 import IDS, encoded, git, info, logical_lines, publish, require, sha, stage_dataset

ROOT = Path(__file__).resolve().parents[1]
POLICY = "temp/reports/RUN-0009-bibliography-roadmap.json"
PREVIOUS = "f0f545cc4ad90f0af0be23610a68af2d0692ed99"
OUTPUT = "temp/reports/RUN-0009-bibliography-cutover.json"


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--apply",action="store_true")
    apply = args.parse_args().apply
    require(not (ROOT/OUTPUT).exists(), "This decision was already recorded")
    head = git(ROOT,"rev-parse","HEAD").decode().strip()
    git(ROOT,"merge-base","--is-ancestor",PREVIOUS,head)
    policy=json.loads((ROOT/POLICY).read_bytes())
    require(policy["allowed_publication_materials"]==["bibliographic_metadata","abstract","reference_list"],"Reading rule changed")
    manifest_path = ROOT/"temp/partitions/manifest.json"
    manifest=json.loads(manifest_path.read_bytes())
    deltas=json.loads((ROOT/"temp/reports/RUN-0009-S06-integration.json").read_bytes())["datasets"]
    inputs={POLICY:info((ROOT/POLICY).read_bytes()),"temp/partitions/manifest.json":info(manifest_path.read_bytes())}
    now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    rows_changed=defaultdict(list)
    keep={n:{e["id"] for e in deltas[n]["changed"]} for n in ["reference-occurrences","citation-edges"]}
    keep.update({n:set(deltas[n]["appended_ids"]) for n in ["citation-context-audit","projects","project-relations","assessments"]})
    reason="按当前论文检索要求，仅凭书目信息、摘要和参考文献列表尚不能核实。"
    new_tasks=[]
    def review(eid, etype, typ):
        tid="T-BIB-REVIEW-"+eid
        new_tasks.append(dict(task_id=tid,entity_type=etype,entity_id=eid,task_type=typ,scope_id="SCOPE-0001",
            source_id="europepmc",normalized_parameters={"allowed_materials":policy["allowed_publication_materials"]},
            task_state="pending",cursor=None,dependency_ids=[],query_ids=[],attempt_count=0,error_code=None,
            failure_reason=reason,retry_at=None,review_condition="出现可核对的书目、摘要或参考文献列表证据。",created_at_utc=now,
            updated_at_utc=now,checkpoint_id="CP-0011",event_sequence=1,assessment_id=eid if etype=="assessment" else None,
            field_path=None,unknown_since_utc=None,deadline_at_utc=None,review_task_id=None,priority="normal",overdue=False,
            supporting_record_ids=[POLICY]))
    def edit(name,r):
        if name=="assessments":
            r.update(assessment_status="pending_review",evidence_admission_status="pending_review",verification_status="unverified")
            review(r["assessment_id"],"assessment","bibliographic_claim_review")
        elif name=="citation-edges":
            r.update(citation_roles=["unknown"],context_locators=[])
            for source in r["discovery_sources"]:
                if any("back/ref-list" in l.get("section","") for l in source.get("evidence_locator",[])):
                    for loc in source["evidence_locator"]:
                        loc["evidence_note"]="已核对文后参考文献列表中的书目条目。"
        elif name=="reference-occurrences":
            for loc in r["source"].get("evidence_locator",[]):
                if "back/ref-list" in loc.get("section",""):
                    loc["evidence_note"]="已核对该条参考文献及保留的书目身份状态。"
        elif name=="citation-context-audit":
            r.update(verification_status="unverified",citation_roles=["unknown"],evidence_locator=[],summary=reason+" 原始审计记录见修订前 Git 提交。")
        elif name=="projects":
            r.update(verification_status="unverified",project_relation="unknown",output_work_ids=[])
            r["notes"]=reason+" 在当前阶段须以论文书目中的登记资助信息核对归属。此前的项目登记与致谢定位留作历史。"
            review(r["project_id"],"project","bibliographic_funding_review")
            field_task=deepcopy(new_tasks[-1])
            field_id=field_task["task_id"]+"-outputs"
            field_task.update(task_id=field_id,task_type="field_review",field_path="output_work_ids",review_task_id=field_id,
                              unknown_since_utc=now,deadline_at_utc=(datetime.fromisoformat(now)+timedelta(hours=24)).isoformat().replace("+00:00","Z"))
            new_tasks.append(field_task)
            r["field_states"]["output_work_ids"]=dict(status="unknown",reason=reason,evidence_locator=[],
                                                       unknown_since_utc=now,review_task_id=field_id)
        elif name=="project-relations":
            r["verification_status"]="unverified"
        return r
    schema=json.loads((ROOT/"temp/schema.json").read_bytes())["x-entity-files"]
    with transaction_directory(ROOT) as stage:
        updated=deepcopy(manifest)
        for name in sorted(keep):
            found=set()
            def amended():
                for raw in logical_lines(ROOT,name,manifest,inputs):
                    row=json.loads(raw)
                    key=row[IDS[name]]
                    if key in keep[name]:
                        require(key not in found,"Duplicate row")
                        found.add(key)
                        updated_row=edit(name,row)
                        kind=schema.get(name+".jsonl") or ("entity_export_relation" if name=="project-relations" else None)
                        if kind:gates.validate(kind,updated_row)
                        after=encoded(updated_row)
                        rows_changed[name].append(dict(id=key,before_sha256=sha(raw),after_sha256=sha(after)))
                        yield after
                    else:yield raw
                require(found==keep[name],"Missing "+name)
            stage_dataset(stage,name,amended(),manifest,updated)
        ids={t["task_id"] for t in new_tasks}
        def tasks():
            for raw in logical_lines(ROOT,"tasks",manifest,inputs):
                require(json.loads(raw)["task_id"] not in ids,"Review task already exists")
                yield raw
            for t in new_tasks:
                gates.validate("task",t)
                yield encoded(t)
        stage_dataset(stage,"tasks",tasks(),manifest,updated)
        proof=dict(run_id="RUN-0009",scope_id="SCOPE-0001",policy_receipt=POLICY,recorded_at_utc=now,
            original_commit=PREVIOUS,parent_commit=head,changed_rows=rows_changed,new_tasks=sorted(ids),
            historical_queries_preserved=9,historical_manual_reviews_preserved=10,new_external_requests=0,new_scientific_claims=0,
            new_active_fulltext_assessments_in_current_scope=0,current_role_confirmations_from_former_batch=0,
            notes="保留前一提交中的原始记录。当前统计排除待复核的科学主张，书目匹配独立计数。")
        target=stage/"files"/OUTPUT;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(encoded(proof))
        (stage/"files/temp/partitions/manifest.json").write_bytes((json.dumps(updated,ensure_ascii=False,indent=2)+"\n").encode())
        runfile=ROOT/"temp/runs/RUN-0009.json"; inputs["temp/runs/RUN-0009.json"]=info(runfile.read_bytes())
        run=json.loads(runfile.read_bytes());run["scope_cutover"]=OUTPUT
        (stage/"files/temp/runs").mkdir(parents=True,exist_ok=True)
        (stage/"files/temp/runs/RUN-0009.json").write_bytes((json.dumps(run,ensure_ascii=False,indent=2)+"\n").encode())
        if apply:
            old={p["path"] for d in manifest["datasets"].values() for p in d["parts"]}
            live={p["path"] for d in updated["datasets"].values() for p in d["parts"]}
            publish(ROOT,stage,{"temp/"+p for p in old-live if p.startswith("partitions/")},head,inputs)
        print(json.dumps({k:len(v) for k,v in rows_changed.items()}),sorted(ids),flush=True)


if __name__=="__main__":
    main()
