"""Record reviewed abstracts and independently matched publication affiliations for four CP12 parents."""
import argparse
from integrate_run11_reviews import Ledger
from run10_reference_records import doi, norm, token
from run9_metadata_transaction import apply_batch
from search_run11_bibliography import CP, OUT, ROOT, RUN, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

REPORT=TEMP/"reports/RUN-0011-motion-abstracts.json"
SOURCE=OUT/"Q-RUN11-P56-VISUAL-MOTION-ABS-REST-A1.json"
# These fingerprints bind each original Chinese summary to the abstract actually read.
NOTES={
    "24108792":("3ca7b1392467e5ef653443ed562ac4b51348c09ffe067f7d0728a41bcab8717f",
        "作者比较了果蝇静止与系留飞行时中央复合体的活动。扇形体内一组被标记的神经元在静止时对视觉运动缺乏响应；飞行时基线活动升高，视野中从前向后的运动还会引起相对基线的响应变化。",
        "摘要支持该组神经元对视觉运动的反应随行为状态而变。速度标定、全部神经元的普遍性及六自由度恢复能力仍待核实。",[]),
    "28869583":("b7afb0c1f059b1db5914feac6e9043852419afb94f476ba40ec4500b008a9101",
        "飞行模拟器中的果蝇能够依据刚出现过的地标选择方向。作者报告，抑制脑内 bulb 区的神经元会损害这项行为。飞行中的成像显示，该区背侧编码近期地标的位置，腹侧跟踪转向相关自运动，两条通路分别进入导航中枢。",
        "证据限于摘要所述模拟器、地标和转向条件。摘要未给出可核验的三维速度重建误差。",[]),
    "10896169":("6f4428789d4370067db946b13606872c94a314b3d0d8984f7157647528c7ff49",
        "作者研究观察方向既平移又转动时，视觉流与眼动速度信号如何共同影响航向判断。摘要报告视网膜光流限制了判断精度。作者据此倾向于眼动速度在较晚阶段调制响应的解释，并对早期向量相减的解释提出质疑。",
        "作者区分了两种信号组合解释。模型参数、精度数值及其对昆虫视觉的适用性仍待核实。",["L06"]),
    "10195110":("4c60a1dee0521d4123d1bf5f4eb9e655bc975049d723d43281a076e79d972f34",
        "研究者训练猴用光流判断自身运动方向，再在任务中对 MST 皮层区施加微电刺激。摘要报告刺激常使猴的航向选择发生偏移，为 MST 参与基于光流的航向知觉提供了干预证据。",
        "摘要未提供足以核验效应量的具体数字。结论限于所述猴航向判断任务。",[]),
}
LINKS={"10195110":(0,0,"UC Davis Center for Neuroscience, California, USA","University of California, Davis"),
       "10896169":(0,0,"Erasmus University Rotterdam","Erasmus University Rotterdam"),
       "24108792":(0,0,"University of Washington, Seattle","University of Washington"),
       "28869583":(1,1,"The University of Tokyo, Tokyo, Japan","The University of Tokyo")}


def prepare():
    if REPORT.exists():
        return
    q=read(SOURCE);assert q["status"]=="success" and len(q["records"])==len(NOTES)
    by_pmid={w["identifiers"].get("pmid"):w for w in iter_logical("works.jsonl") if w["identifiers"].get("pmid") in NOTES}
    rows=[];receipts={};unbound=[]
    for r in q["records"]:
        pmid=r["id"];w=by_pmid[pmid];h,summary,boundary,themes=NOTES[pmid]
        assert w["doi"]==doi(r["doi"]) and norm(w["canonical_title"])==norm(r["title"]) and r["abstract_sha256"]==h
        assert len(w["authors"])==len(r["authors"]) and all(norm(a["family_name"])==norm(b["lastName"]) for a,b in zip(w["authors"],r["authors"]))
        rank,aff_index,term,institution=LINKS[pmid];a=r["authors"][rank];aff=a["affiliations"][aff_index]
        oq=OUT/("Q-RUN11-P56-MOTION-ROR-"+token(term)+"-A1.json");record=read(oq)
        selected,=[x for x in record["records"] if x["chosen"]]
        assert selected["status"]=="active" and any(n["value"]==institution and "ror_display" in n["types"] for n in selected["names"])
        link=dict(byline_position=rank+1,source_display=a["fullName"],affiliation=aff,institution=institution,ror=selected["source_identifier"],
                  ror_query=record["query_id"],ror_receipt_sha256=digest(oq))
        receipts[oq.relative_to(ROOT).as_posix()]=digest(oq)
        if pmid=="28869583":
            study="RIKEN Brain Science Institute, Saitama, Japan"
            rp=OUT/("Q-RUN11-P56-MOTION-ROR-"+token(study)+"-A1.json");rq=read(rp)
            proposed,=[x for x in rq["records"] if x["chosen"]]
            display=next(n["value"] for n in proposed["names"] if "ror_display" in n["types"])
            assert display=="Brain Science Institute, Tamagawa University" and study in r["authors"][0]["affiliations"] and study in r["authors"][1]["affiliations"]
            receipts[rp.relative_to(ROOT).as_posix()]=digest(rp)
            unbound.extend(dict(work_id=w["work_id"],byline_position=i+1,source_display=by["fullName"],literal=study,rejected_ror=proposed["source_identifier"],
                                proposed_name=display,query_id=rq["query_id"],reason="论文署名为 RIKEN，ROR 建议属于玉川大学。历史单位身份待核实。")
                           for i,by in enumerate(r["authors"]))
        rows.append(dict(work_id=w["work_id"],work_key=w["work_key"],doi=w["doi"],pmid=pmid,query_id=q["query_id"],abstract_sha256=h,
                         summary_zh=summary,topic_candidates=themes,admission="no_new_eligible_assessment",boundary=boundary,
                         byline_count=len(r["authors"]),publication_affiliation_links=[link],project_role_verified=False))
    write(REPORT,dict(run_id=RUN,scope_id=SCOPE,reviewed_at_utc=stamp(),source_receipt=SOURCE.relative_to(ROOT).as_posix(),source_receipt_sha256=digest(SOURCE),
         additional_receipts=receipts,items=rows,unresolved_affiliations=unbound,counts=dict(records_checked=len(rows),summaries=len(rows),missing_abstracts=0,
         bylines=sum(r["byline_count"] for r in rows),publication_affiliations=4,unresolved_historical_affiliations=len(unbound),new_project_attributions=0,new_eligible_claims=0)))


def register():
    report=read(REPORT);paths={SOURCE,*(ROOT/f for f in report["additional_receipts"]),OUT/"Q-RUN11-P56-VISUAL-MOTION-ABS-A1.json"}
    assert all(digest(ROOT/p)==h for p,h in report["additional_receipts"].items())
    owners={o["task_id"] for p in paths for o in read(p)["owners"]};work_ids={r["work_id"] for r in report["items"]}
    names={norm(l["institution"]) for r in report["items"] for l in r["publication_affiliation_links"]}
    rors={l["ror"] for r in report["items"] for l in r["publication_affiliation_links"]}
    orgs={o["org_id"] for o in iter_logical("organizations.jsonl") if o.get("ror") in rors or norm(o["canonical_name"]) in names}
    b=Ledger(owners,work_ids,orgs);b.abstracts(report,REPORT)
    for a in report["unresolved_affiliations"]:
        tid="T-R11-AFFIL-"+token(a["work_id"],a["byline_position"],a["literal"])
        t=b.task(tid,a["work_id"],"affiliations_projects",a["reason"],"needs_disambiguation",[a["query_id"]],source_id="ror")
        t["normalized_parameters"]={k:a[k] for k in ("byline_position","literal","rejected_ror")}
    b.queries(paths)
    inputs={p.relative_to(ROOT).as_posix():digest(p) for p in paths|{REPORT}}
    rep=dict(run_id=RUN,scope_id=SCOPE,checkpoint_id=CP,recorded_at_utc=b.now,counts=report["counts"],input_receipts=inputs)
    apply_batch(b.changes,{k:list(v.values()) for k,v in b.adds.items() if v},rep,"temp/reports/RUN-0011-motion-abstract-integration.json")
    print(rep["counts"],flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("prepare","register"));args=p.parse_args()
    if args.action=="prepare":prepare()
    else:register()
