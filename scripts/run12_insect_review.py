"""Register abstract-level findings for insect visual navigation with source fingerprints and explicit limits."""
from copy import deepcopy
from hashlib import sha256

from integrate_run10_references import source
from run10_reference_records import doi, identifiers, token
from run12_insect_recovery import REPORT as ALTERNATES
from run12_insect_ris import REPORT as PUBLISHER
from run11_source_limits import private_directory
from run12_reference_search import CP, RUN
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

REPORT=TEMP/"reports/RUN-0012-insect-odometry-reviews.json"
NOTES={
    "9320443": [
        "49467dd1f5e583c96ab183686ef5e7c9b47e862821758fb9c622c9fd8e192155",
        "作者在实验室短程飞行中分别操控蜜蜂可能使用的里程线索。摘要报告，蜜蜂依靠图像运动估距，以侧视野输入为主。经过显著地标后，距离累计重新开始。实验中的食源距离主要在去程习得。",
        "适用条件为受控短程飞行。摘要未列出各操控的样本量与误差分布，无法据此定量外推到长程自然飞行。"
    ],
    "10708632": [
        "70924f3b2f7ee7aaf115372866cfc7b85de3727eaed6166b8dbab4cff6c9cd2e",
        "沙漠蚁 Cataglyphis fortis 在条纹通道训练后，被转入宽度加倍或减半的测试通道。摘要报告，在所试条件下，步速及开始寻巢前走过的距离均未随通道宽度、高度或条纹波长变化。遮挡腹侧视野后，仍未观察到侧向光流对距离判断的影响。",
        "这是特定步行任务和视野操控下的无效应结果。摘要未给出置信区间或等效性检验，也不足以排除其他视觉条件下的作用。"
    ],
    "12928953": [
        "7f2a44eb75a19f8deda5080bb82561a9616dcf0735b90527f4522c169b65c90f",
        "无刺蜂 Melipona seminigra 从有条纹的通道转入无食源测试后，会在先前食源附近折返搜索。改变通道宽度影响距离判断，去除腹侧或侧方的图像运动线索均削弱表现。隐蔽移动饲喂器使去程、返程距离不同时，后续搜索主要对应返程距离。",
        "证据来自通道中的觅食和折返位置。摘要没有给出各条件的数值误差、方差和样本量。"
    ],
    "22915710": [
        "2a91d04059b8cc6d9e4758f0d5a5190e7a048888050a7132904238b7d63d3bef",
        "无刺蜂 Melipona panamica 在条纹垂直通道中学会食源高度。换到无食源测试通道后，较窄通道使搜索高度下降，较宽通道使其上升，去除视觉线索后搜索高度分散。水平通道也有相似变化，但搜索位置的方差较大。作者认为侧视野光流参与高度和距离估计。",
        "结果限于受训蜂和通道条件。摘要未报告各组样本量、搜索高度效应量或不确定区间。"
    ],
    "23036665": [
        "a93153353ea3f727bbfed13c79c00fa126004028fcad2726a2255f3e4e002657",
        "沙漠蚁 Melophorus bagoti 在一维通道中往返搜索。把巢口设在通道侧面后，向前漂移并非总会出现。食源在端部时向食源方向的漂移较明显，食源在侧面时较弱。作者据此提出训练布局影响搜索惯例。",
        "摘要比较的是通道布局与搜索行为，没有给出可归因于光流的里程增益或度量轨迹误差。"
    ],
    "25079890": [
        "cece81ee0c51dac06b197b51f4bfc9c7f0e937957ef44d77b23eef1f8ea2d5e4",
        "熊蜂离巢学习飞行时，两次快速转向之间头部仍缓慢转动。在部分位置，残余旋转形成以巢口为中心的视差，使近巢地物更突出。作者提出，这种运动可能帮助熊蜂判断地物相对巢口的距离。",
        "观测对象为熊蜂的学习飞行。摘要未给出深度判断误差、样本数或对照效应量，距离功能保留为作者解释。"
    ],
    "10.1007/bf00192324": [
        "8ae69bb1cfaa5e2d053663732f28eacf972f365016c8706590b29630e7b09fbe",
        "返巢蜜蜂步行穿过带多个侧出口的狭窄通道。研究者分别移动脚下基底或黑白图案。图案流速降低时，蜜蜂加快步行并更常选择较远出口。流速提高时，步速下降并更常选择较近出口。作者据此提出，调节步速的视觉线索也可能参与估计步行距离。",
        "结果来自步行通道和出口选择。摘要未给出步速或出口偏好的效应量、样本量，估距机制仍是作者提出的解释。"
    ],
    "10.1007/bf00243395": [
        "b8e2174a3dd7628ae6048d808f3b6083ea4495b741731479159ad6607e248bc8",
        "研究者在透明步行平台下移动图案，改变沙漠蚁 Cataglyphis fortis 经历的腹侧图像运动。部分图案速度超过蚁步速的一半。摘要报告，操控会改变归巢距离，结果与图像运动速度有关。无纹理地面和遮眼条件显示，蚁还可利用其他线索，作者推测其中包括运动觉。",
        "受操控的是脚下图案。摘要未给出各条件归巢距离的数值差、样本数或不确定区间，运动觉解释仍待核实。"
    ]
}


def prepare():
    if REPORT.is_file():return
    candidates=[(p,read(p)) for p in sorted(OUT.glob("Q-RUN12-P6-INSECT-ODOMETRY-*.json"))]
    path,q=next((p,q) for p,q in reversed(candidates) if q["status"]=="success")
    primary=read(private_directory(RUN)/"insect-odometry-abstracts.json")
    data={r["id"]:(r["work_id"],r["work_key"],doi(r["doi"]),r["title"],q["source_id"],"MED:"+r["id"],q["query_id"],
                      r["abstract_sha256"],primary[r["id"]]) for r in q["records"] if r.get("abstract_sha256") and r["parent_title_checked"]}
    coverage=read(ALTERNATES);publishers=read(PUBLISHER)
    inputs={**coverage["input_receipts"],**publishers["input_receipts"],ALTERNATES.relative_to(ROOT).as_posix():digest(ALTERNATES),
            PUBLISHER.relative_to(ROOT).as_posix():digest(PUBLISHER)}
    for d,row in coverage["selected"].items():
        cache=read(private_directory(RUN)/("insect-odometry-alt-"+row["source_id"]+".json"))
        data[d]=(row["work_id"],row["work_key"],d,row["title"],row["source_id"],row["source_identifier"],row["query_id"],row["abstract_sha256"],cache[d])
    for subject in publishers["items"]:
        d=subject["canonical_doi"]
        for r in subject["records"]:
            if r.get("abstract_sha256") and d not in data:
                body=read(private_directory(RUN)/("insect-publisher-"+d.rsplit("/",1)[-1].upper()+".json"))
                data[d]=(r["work_id"],r["work_key"],d,r["title"],"publisher",d,subject["query_id"],r["abstract_sha256"],body)
    if set(data)!=set(NOTES):
        raise ValueError("The available abstracts differ from the manually reviewed inventory")
    items=[]
    for item,(expected,summary,bound) in NOTES.items():
        wid,key,d,title,provider,ident,qid,observed,body=data[item]
        if sha256(body.encode()).hexdigest()!=expected or observed!=expected:
            raise ValueError("Published abstract differs from the reviewed fingerprint")
        items.append(dict(work_id=wid,work_key=key,doi=d,title=title,source_id=provider,source_identifier=ident,query_id=qid,
                          abstract_sha256=expected,summary_zh=summary,boundary=bound))
    spelling=next(s for s in publishers["items"] if s["canonical_doi"]=="10.1007/bf00192324")
    printed,=spelling["records"]
    if printed["authors"]!=["Schöne, H."]:raise ValueError("Publisher byline changed")
    correction=dict(work_id=spelling["work_id"],work_key=spelling["work_key"],position=1,
          prior_display="H. Sch\ufffdne",printed_display=printed["authors"][0],canonical_display="H. Schöne",
          family_name="Schöne",given_name="H.",query_id=spelling["query_id"])
    covered={r["work_id"] for r in items}
    gaps=[dict(work_id=s["work_id"],work_key=s["work_key"],doi=s["canonical_doi"],publisher_query=s["query_id"])
          for s in publishers["items"] if s["work_id"] not in covered]
    counts=dict(reviewed_abstracts=len(items),primary_abstracts=len(primary),publisher_abstracts=publishers["counts"]["published_abstracts"],
                still_without_abstract=len(gaps),publication_byline_corrections=1,new_eligible_assessments=0)
    write(REPORT,dict(run_id=RUN,checkpoint_id=CP,scope_id=SCOPE,reviewed_at_utc=stamp(),counts=counts,
                source_receipt=path.relative_to(ROOT).as_posix(),source_sha256=digest(path),input_receipts=inputs,open_abstracts=gaps,byline_correction=correction,items=items))
    print(counts,flush=True)


def register(ledger):
    d=read(REPORT);path=ROOT/d["source_receipt"];q=read(path)
    if digest(path)!=d["source_sha256"]:raise ValueError("Abstract metadata receipt changed")
    for relative,expected in d["input_receipts"].items():
        source_path=ROOT/relative
        if digest(source_path)!=expected:raise ValueError("A bibliographic source used for an abstract changed")
        ledger.input_paths.add(source_path)
    ledger.input_paths.update((path,REPORT))
    for gap in d["open_abstracts"]:
        wid=gap["work_id"];tid="T-abstract-"+wid
        if tid not in ledger.latest:raise ValueError("The open abstract task is missing")
        old=ledger.latest[tid]
        sources=[q["query_id"],gap["publisher_query"]]
        for rel in read(ALTERNATES)["input_receipts"]:
            if rel.startswith("temp/query-results/"):
                other=read(ROOT/rel)
                if any(owner["work_id"]==wid for owner in other["owners"]):sources.append(other["query_id"])
        event=ledger.task(tid,wid,"abstract","所查书目来源未返回可归属的摘要，保留其他摘要来源复查。",old["task_state"],sorted(set(sources)))
        event["normalized_parameters"]["insect_abstract_source_review"]=REPORT.relative_to(ROOT).as_posix()
    targets={r["work_id"]:r for r in d["items"]}
    holdings={w["work_id"]:w for w in iter_logical("works.jsonl") if w["work_id"] in targets}
    versions={wid:[] for wid in targets}
    for v in iter_logical("versions.jsonl"):
        wid=v["work_id"]
        if wid in targets and targets[wid]["doi"] in identifiers(v):versions[wid].append(v["version_id"])
    need={"T-"+kind+"-"+wid for wid in targets for kind in ("abstract","assessment")}
    for old in iter_logical("tasks.jsonl"):
        if old["task_id"] in need:ledger.latest[old["task_id"]]=old
    for wid,r in targets.items():
        old=holdings[wid];current=ledger.changes["works"].get(wid,(old,old))[1]
        if doi(current.get("doi"))!=r["doi"] or current["abstract_items"] or len(versions[wid])!=1:
            raise ValueError("Older abstract material or version must be reconciled: "+r["work_key"])
        work=deepcopy(current)
        receipt=read(OUT/(r["query_id"]+".json"))
        src=source(receipt,r["source_identifier"],"Published abstract",r["boundary"])
        work["abstract_items"].append(dict(status="chinese_summary_from_abstract",text=r["summary_zh"],source=src,
             version_id=versions[wid][0],license="Original Chinese summary; source abstract not reproduced.",summarizer="Codex 摘要复核",
             date=d["reviewed_at_utc"][:10],source_language="en",verification_status="source_supported"))
        work.update(abstract_status="chinese_summary_from_abstract",abstract_source=src)
        correction=d["byline_correction"]
        if wid==correction["work_id"]:
            author,=work["authors"]
            if author["display_name"]!=correction["prior_display"] or author["given_name"]!=correction["given_name"]:
                raise ValueError("Existing author must be reconciled against the publisher byline")
            person=next(p for p in iter_logical("authors.jsonl") if p["person_id"]==author["person_id"])
            if person["display_name"]!=correction["prior_display"]:raise ValueError("Author identity changed")
            edited=deepcopy(person)
            name_source=source(receipt,r["doi"],"Publisher RIS byline, AU 1",correction["printed_display"])
            edited["display_name"]=correction["canonical_display"]
            edited["name_variants"]=list(dict.fromkeys([*edited["name_variants"],correction["prior_display"],
                correction["canonical_display"],correction["printed_display"]]))
            for attribution in (author.get("source"),name_source):
                if attribution and attribution not in edited["sources"]:edited["sources"].append(attribution)
            ledger.modify("authors",person,edited)
            author.update(display_name=correction["canonical_display"],family_name=correction["family_name"],source=name_source)
        rid="MR-R12-INSECT-ABSTRACT-"+token(wid)
        for dim in ("abstract","assessment"):
            state=work["dimension_status"][dim]
            if state in ("pending","restricted","retryable_error"):state="partial"
            work["dimension_status"][dim]=state
            event=ledger.task("T-"+dim+"-"+wid,wid,dim,r["boundary"],state,[r["query_id"]],source_id=r["source_id"])
            event["supporting_record_ids"].append(rid)
            event["normalized_parameters"].update(insect_abstract_identifier=r["source_identifier"],insect_abstract_sha256=r["abstract_sha256"])
        ledger.modify("works",old,work);ledger.works[wid]=work
        ledger.add("manual-reviews",dict(review_id=rid,run_id=RUN,review_type="published_abstract_evidence",entity_id=wid,
                    reviewer="Codex 摘要复核",recorded_at_utc=d["reviewed_at_utc"],artifact=REPORT.relative_to(ROOT).as_posix(),notes=r["boundary"]))
    return d["counts"]


if __name__=="__main__":prepare()
