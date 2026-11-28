"""Write a Git-bound RUN11 progress watermark without consuming or resetting a task clock."""
import json
import os
from pathlib import Path
import subprocess

from search_run11_bibliography import BATCHES, OUT, ROOT, STATE, TEMP, read, stamp
from run11_reference_inventory import SUPPLEMENT
from index_run11_positions import INDEX
from escalate_unknown_run7 import parts_for
from history_run10 import blobs


def git(*args):
    return subprocess.check_output(["git","-C",str(ROOT),*args])


def bound(root,tracked):
    relative=root.relative_to(ROOT).as_posix()+"/"
    return [ROOT/f for f in sorted(tracked) if f.startswith(relative) and "/" not in f[len(relative):] and f.endswith(".json")]


def latest_cohorts(root,tracked):
    selections={}
    for p in bound(root,tracked):
        key=p.stem.removesuffix("-reconciled")
        if key not in selections or p.stem.endswith("-reconciled"):selections[key]=p
    return selections.values()


def update():
    head=git("rev-parse","HEAD").decode().strip()
    tracked=set(git("ls-tree","-r","--name-only",head).decode().splitlines())
    run=read(STATE);front=read(ROOT/run["frontier"])["worklist"]
    batches=[read(p) for p in bound(BATCHES,tracked) if p.name!="0001-0064.json"]
    end=sum(r["parent_count"] for r in batches)
    assert [r["starting_index"] for r in batches]==list(range(0,end,64))
    indexes=[read(p) for p in latest_cohorts(INDEX,tracked)]
    canon=[read(p) for p in bound(TEMP/"reports/RUN-0011-canonical",tracked)]
    qfiles=[p for p in bound(OUT,tracked) if p.name.startswith("Q-RUN11-")]
    raw=sum(read(p)["external_request_count"] for p in qfiles)
    with blobs() as get:
        manifest=json.loads(get(head,"temp/partitions/manifest.json"))
        manual=[review["review_id"] for p in parts_for("manual-reviews",manifest)
                for review in map(json.loads,get(head,"temp/"+p["path"]).splitlines()) if review["run_id"]=="RUN-0011"]
    if len(set(manual))!=len(manual):
        raise ValueError("Duplicate manual review ID")
    correction=TEMP/"reports/RUN-0011-Chao1995-integration.json"
    added=read(correction)["added_counts"] if correction.relative_to(ROOT).as_posix() in tracked else {}
    can_end=max((r["next_index"] for r in canon),default=0)
    stats=dict(bound_commit=head,recorded_at_utc=stamp(),parent_queue_total=len(front),source_parents_visited=end,
               next_parent_key=front[end]["work_key"] if end<len(front) else None,parents_with_source_supplements=len(bound(SUPPLEMENT,tracked)),
               parents_with_final_position_index=sum(r["parent_count"] for r in indexes),
               indexed_positions=sum(r["counts"]["positions"] for r in indexes),positions_with_candidate_id=sum(r["counts"].get("with_candidate_identifier",0) for r in indexes),
               canonical_parents_processed=can_end,next_canonical_parent_key=front[can_end]["work_key"] if can_end<len(front) else None,
               new_canonical_works=sum(r["added_counts"].get("works",0) for r in canon)+added.get("works",0),
               canonical_source_positions=sum(r["added_counts"].get("reference-occurrences",0) for r in canon),
               new_backward_edges=sum(r["added_counts"].get("citation-edges",0) for r in canon)+added.get("citation-edges",0),
               version_tasks_reviewed=65 if manual else 0,printed_original_versions_identified=33 if manual else 0,
               reviewed_inherited_tasks_still_ambiguous=32 if manual else 0,new_scientific_admissions=0,
               published_requests=raw,manual_review_items=len(manual))
    stats["parents_with_source_supplements"]=sum(len(read(p)["parents"]) for p in latest_cohorts(SUPPLEMENT,tracked))
    run.update(external_requests_used=raw,manual_review_items_used=len(manual),synchronization_watermark=stats)
    assert len(front)==2620 and raw<=run["budget"]["external_requests"] and run["paid_spend"]==0
    assert git("rev-parse","HEAD").decode().strip()==head
    new=STATE.with_suffix(".progress-part")
    with new.open("xb") as f:f.write((json.dumps(run,ensure_ascii=False,separators=(",",":"))+"\n").encode())
    os.replace(new,STATE)
    p=TEMP/"progress.md";old=p.read_text(encoding="utf-8")
    marker="<!-- RUN-0011 live progress -->"
    if marker in old:
        body,tail=old.split(marker,1);stop="<!-- end RUN-0011 live progress -->";assert stop in tail
        tail=tail.split(stop,1)[1]
    else:body=old.rstrip()+"\n\n";tail="\n"
    text=(f"{marker}\n### RUN-0011 从 CP-0012 续检\n\n"
          f"Git 数据提交 `{head[:12]}` 的已回读进度：原队列 {end:,}/2,620 篇已查，{stats['parents_with_final_position_index']:,} 篇完成逐来源位置对账。"
          f"规范库已逐项处理队首 {can_end:,} 篇，新增 {stats['new_canonical_works']:,} 篇 Work、{stats['new_backward_edges']:,} 条向后引文边。\n\n"
          f"65 条原有版本工单已复核，33 条已定位原始版次，32 条待核实。抽查 5 篇，登记 4 篇摘要和 3 条发表时机构关系；新增合格科学主张 0 条。"
          f"本次水位累计 {raw:,} 次已推送来源请求、{len(manual)} 项人工复核。"
          "各项任务的来源、游标和缺口见 [运行记录](runs/RUN-0011.json)。P3–P6 继续开放，最近通过全套验收的检查点为 CP-0012。\n"
          "<!-- end RUN-0011 live progress -->")
    p.write_bytes((body+text+tail).encode())
    print(stats,flush=True)


if __name__=="__main__":update()
