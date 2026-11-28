"""Record eight abstract-bounded topical reviews and publication- or revision-specific evidence."""
from collections import Counter
import hashlib
import json

from run10_reference_records import doi, norm
from run12_followups import INSTITUTIONS, SOURCE
from run12_reference_search import CP, RUN
from run12_version_screen import OLD, REPORT as SCREEN
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

ABSTRACTS=TEMP/"reports/RUN-0012-motion-reviews.json"
VERSIONS=TEMP/"reports/RUN-0012-version-decisions.json"
NOTES={
"22036184":("26fc168535f3a7794c5287e164799b9d9f3fda45c468dc6ac8c8bf307a489c9b",
"作者拍摄虎皮鹦鹉飞过不同壁面图案走廊时的轨迹。摘要报告，鸟利用双眼所见图像运动的速度差维持侧向位置，并利用双眼的图像运动调节飞行速度。",
"证据限于鸟类狭窄通道中的行为。昆虫神经机制和一般三维速度误差待核实。",["L04","L06"]),
"18161592":("0450904cb85d889aa62d25ba449ad97f7fef1a05232fd56e202dc45bd6eca729",
"作者比较三个椭球体开放相关果蝇等位型。三者偏航力矩的小幅波动均减弱。ebo(678) 在图案反向后达到新力矩水平较慢，摘要还报告其在飞行模拟器中对单条纹的注视常较不稳定。",
"结果涉及中央复合体与飞行行为。椭球体和胸部表型的关联限制了对单一结构的归因。",["L03"]),
"9472485":("b64a9109ddd6776483365dd9d160553f9170edbee2ebc079caac843689e6a610",
"作者用自组织网络学习眼动指令与其引发的光流之间的关系，再从剩余光流中表征航向、场景深度和运动目标位置。摘要报告了在有噪声和无噪声的仿真中进行避障与追踪的测试。",
"模型使用眼位和眼动指令。纯视觉条件下的可观测量、深度尺度及真实场景误差待核实。",["L01","L06"]),
"8724666":("d9f77cc1dcbd3d45e749af6ef4d178da0946702f2d256ab52d55ed710d12adec",
"作者用不同虚拟环境中的拟自然光流刺激记录猕猴上颞沟高级运动区的神经元活动。摘要报告，相比其他视觉线索，神经响应主要随扩张中心位置变化。",
"结果支持航向线索的神经表征。真实自由运动中的解码误差及向昆虫的外推待核实。",["L04","L06"]),
"8723207":("99e3a3fd8399070197a4529861295007ef47b07b9ae06ac3c92d2145ea6113c0",
"这篇综述讨论观察者运动引起的视网膜变化如何参与三维知觉，也讨论自运动信号对深度知觉的反馈。作者结合计算模型、行为研究和下顶叶生理研究提出尚待检验的问题。",
"综述摘要提供研究背景。各原始实验的条件、量化误差和尺度依据待核实。",["L01","L06"]),
"11954696":("08b684709a7a71b2f339c0c1babd02b72133966256fe636aec548c1300162e61",
"研究以虚拟场景中的三角形闭合任务考察路径积分。操纵杆实验中，地面和墙面的纹理改变旋转和平移光流的作用。主动行走时，转向偏差由不足变为过度，变异减小，摘要据此认为身体感觉在该条件下占优势。",
"结论限于这些纹理和运动条件下的人类返回路径判断。各感觉通道的定量权重和昆虫对应关系待核实。",["L02","L06"]),
"11163855":("653cfe888855caeab062ad1c2c58e44d66c3e0f3667701af0ff473397b14d52c",
"11 名受试者在给定尺度线索的虚拟走廊中判断何时到达先前呈现的目标。作者报告，加速度高于 0.1 m/s² 时距离判断较准确，较慢的加速引起高估，恒速条件下报告的高估达 170%。",
"数值取自摘要。尺度线索已给定，170% 的精确定义、个体离散程度及其他场景的误差待核实。",["L04","L06"]),
"8917793":("e01ca07129a781b16d3659d313e660c59a2513d488080ea05ff3bbd4e41c6f66",
"作者在以视点为顶点的 45° 锥形范围内短暂呈现径向扩张点阵，让受试者判断平移方向。摘要报告五名观察者的仰角判断方差较方位角高 3% 至 45%，上下视野的误差分布也有差别。",
"结果涉及短时平移刺激下的方向判断。含旋转时的表现、速度幅值和绝对尺度待核实。",["L06"])}
ORG_NAMES={"22036184":"Australian National University","11954696":"Brown University","9472485":"Boston University",
           "8917793":"University of Minnesota","8724666":"Ruhr University Bochum"}
# Each suffix identifies a source position inspected in this review.
ADJUDICATED={"db83ad","0ff04f","d3bf61","c43085","6e82b9","baa0a1","757d32","831922","a51ab4",
             "11470b","be64af","f60b15","f283fe","402a7f","4082e5","395a25","8a76c3","253ed6","95e054","011c45"}


def abstracts():
    if ABSTRACTS.exists():return
    q=read(SOURCE);target={r["work_id"] for r in q["records"]}
    works={w["work_id"]:w for w in iter_logical("works.jsonl") if w["work_id"] in target}
    items=[];extra={};unresolved=[]
    for r in q["records"]:
        pid=r["id"];w=works[r["work_id"]];h,summary,bound,topics=NOTES[pid]
        if r["abstract_sha256"]!=h or not r["identifier_agreement"] or doi(r["doi"])!=doi(w["doi"]) or not w["authors"]:
            raise ValueError("Abstract or identity differs "+pid)
        if len(w["authors"])!=len(r["authors"]):raise ValueError("Byline size differs "+pid)
        # Full names and initials can use different ordering. Require the surname at its original position in both records.
        byline=[]
        for pos,(a,reg) in enumerate(zip(w["authors"],r["authors"],strict=True),1):
            short=norm(reg.get("lastName","")).replace(" ","")
            if not short or short not in norm(a["display_name"]).replace(" ",""):raise ValueError("Byline mismatch "+pid)
            byline.append(dict(position=pos,registered_display=reg["fullName"],canonical_person_id=a["person_id"]))
        links=[]
        if pid in INSTITUTIONS:
            p=OUT/f"Q-RUN12-P5-ROR-{pid}-A1.json";rq=read(p);extra[p.relative_to(ROOT).as_posix()]=digest(p)
            hits=[o for o in rq.get("records",[]) if o["chosen"] and o.get("status")=="active"]
            name=ORG_NAMES.get(pid)
            if name:
                org,=[o for o in hits if any(n["value"]==name and "ror_display" in n["types"] for n in o["names"])]
                links.append(dict(byline_position=1,source_display=r["authors"][0]["fullName"],affiliation=r["authors"][0]["affiliations"][0],
                       institution=name,ror=org["source_identifier"],ror_query=rq["query_id"],ror_receipt_sha256=digest(p)))
            else:
                direct=[]
                for registry in (o for o in rq["records"] if any(n["value"]=="York University" and "ror_display" in n["types"] for n in o["names"])):
                    follow=OUT/("Q-RUN12-P5-YORK-"+registry["source_identifier"].rsplit("/",1)[-1]+"-A1.json")
                    if follow.exists():
                        fq=read(follow);extra[follow.relative_to(ROOT).as_posix()]=digest(follow)
                        if fq["status"]=="success":
                            rec,=fq["records"];direct.append((follow,fq,rec))
                exact=[(f,qq,v) for f,qq,v in direct if v["status"]=="active" and any(l["name"]=="Toronto" and l["country_code"]=="CA" for l in v["locations"])]
                if len(direct)==2 and len(exact)==1:
                    f,qq,v=exact[0]
                    links.append(dict(byline_position=1,source_display=r["authors"][0]["fullName"],affiliation=r["authors"][0]["affiliations"][0],
                         institution="York University",ror=v["source_identifier"],ror_query=qq["query_id"],ror_receipt_sha256=digest(f),
                         registry_location={"name":"Toronto","country_code":"CA"}))
                else:
                    unresolved.append(dict(work_id=w["work_id"],pmid=pid,literal=r["authors"][0]["affiliations"][0],
                        reason="同名机构仍缺少唯一对应的地点证据。",query=rq["query_id"]))
        else:
            unresolved.append(dict(work_id=w["work_id"],pmid=pid,literal=r["authors"][0]["affiliations"][0],
                reason="保存当次署名原文。历史机构实体及边界待核实。",query=q["query_id"]))
        items.append(dict(pmid=pid,work_id=w["work_id"],work_key=w["work_key"],doi=w["doi"],query_id=q["query_id"],abstract_sha256=h,
                summary_zh=summary,topic_candidates=topics,admission="no_new_eligible_assessment",boundary=bound,byline_count=len(byline),
                verified_byline_positions=byline,publication_affiliation_links=links,grant_identifiers=r["grants"]))
    counts=dict(abstracts=len(items),byline_positions=sum(i["byline_count"] for i in items),publication_affiliations=sum(len(i["publication_affiliation_links"]) for i in items),
                open_affiliation_identities=len(unresolved),registered_grant_identifiers=sum(len(i["grant_identifiers"]) for i in items),new_eligible_assessments=0)
    write(ABSTRACTS,dict(run_id=RUN,scope_id=SCOPE,reviewed_at_utc=stamp(),source_receipt=SOURCE.relative_to(ROOT).as_posix(),
          source_receipt_sha256=digest(SOURCE),additional_receipts=extra,items=items,unresolved_affiliations=unresolved,counts=counts))
    print(counts,flush=True)


def versions():
    if VERSIONS.exists():return
    screen=read(SCREEN);inputs={SCREEN.relative_to(ROOT).as_posix():digest(SCREEN)}
    results=[];counts=Counter()
    for t in screen["items"]:
        suffix=t["task_id"][-6:]
        if suffix not in ADJUDICATED:continue
        o=next(i for i in t["occurrences"] if i["source_id"]=="crossref" and (i["family_identifiers"] or i["revision_strings"]))
        qid,=o["source_queries"];p=OUT/(qid+".json");q=read(p);inputs[p.relative_to(ROOT).as_posix()]=digest(p)
        paper,=[r for r in q["records"] if doi(r.get("DOI"))==doi(t["citing_doi"])]
        pos=int(o["locator"].split(", ")[-1]);ref=paper["reference"][pos-1]
        literal=ref.get("unstructured") or json.dumps(ref,ensure_ascii=False,separators=(",",":"))
        if hashlib.sha256(literal.encode()).hexdigest()!=o["reference_sha256"]:raise ValueError("Printed occurrence changed")
        qids={qid};m=None;stage=None
        if suffix=="011c45":
            if "543976v3." not in ref["key"] or doi(ref["DOI"])!="10.7554/elife.97769.1":raise ValueError("Revision-specific deposit changed")
            status="later_citing_revision_only"
            note="Crossref 条目键明确标为施引预印本 v3，第 132 条给出被引 eLife .1。只能定位 v3 的书目，首发 v1 的该项继续待核实。"
            stage={"citing_revision":"3","cited_revision_doi":doi(ref["DOI"])}
        else:
            fam,=o["family_identifiers"];history=screen["publisher_revision_histories"][fam]
            valid={}
            for h in history:
                qids.add(h["query"])
                f=OUT/(h["query"]+".json");inputs[f.relative_to(ROOT).as_posix()]=digest(f)
                if h["date"]<=t["citing_date"]:valid[h["revision"]]=h
            text=norm(ref.get("article-title") or ref.get("unstructured") or "").replace(" ","")
            matches=[h for h in valid.values() if norm(h["title"]).replace(" ","") in text]
            if suffix=="831922":
                status="conflicting_venue";note="条目给出预印本 DOI 和相应题名，期刊字段却写 Neuron。版本归属保留待核实。"
            elif len(matches)==1 and "biorxiv" in norm(literal):
                h=matches[0];m=dict(provider="bioRxiv",doi=fam,revision=h["revision"],date=h["date"],title=h["title"],query_id=h["query"])
                status="original_version_supported"
                note=f"施引书目明确标注 bioRxiv 并列出对应题名和 DOI。逐项比对当时已发布的修订，只有 v{h['revision']} 同时符合题名和公开日期。"
            else:
                status="unresolved";note="同一预印本家族的生效修订和书目条目不足以唯一定位，保留版次疑义。"
        counts[status]+=1
        results.append(dict(ordinal=len(results)+1,task_id=t["task_id"],citing_work_id=t["citing_work_id"],cited_work_id=t["cited_work_id"],
             citing_doi=t["citing_doi"],cited_registry_doi=t["cited_doi"],status=status,exact_original_version=m,later_revision=stage,
             deposit_position=pos,occurrence_id=o["occurrence_id"],evidence_queries=sorted(qids),interpretation=note))
    if len(results)!=len(ADJUDICATED):raise ValueError("Version-review selection changed")
    write(VERSIONS,dict(run_id=RUN,scope_id=SCOPE,reviewed_at_utc=stamp(),items=results,counts=dict(counts),input_receipts=inputs))
    print(dict(counts),flush=True)


if __name__=="__main__":
    abstracts()
    versions()
