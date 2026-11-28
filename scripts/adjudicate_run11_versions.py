"""Record manual bibliography-only decisions for the frozen CP12 version-review inventory."""
from collections import Counter, defaultdict
import re
from pathlib import Path

from run10_reference_records import doi, norm
from review_run11_versions import CARDS, INPUT, PREPRINT, parents
from search_run11_bibliography import OUT, ROOT, RUN, SCOPE, TEMP, digest, read, stamp, write

# Positions are one-based in the named CP12 deposited DOI receipt, never a
# projection from an index ordinal. Zero means no matching deposit was identified.
POSITIONS=[36,32,49,26,0,0,0,20,0,15,36,14,66,22,21,18,51,33,71,23,8,23,51,62,68,4,7,19,57,48,31,46,37,92,39,54,20,7,41,47,48,103,178,244,223,114,176,215,3,86,117,30,52,50,36,62,47,37,28,27,23,67,11,0,0]
RAY="10.1101/2020.04.04.024703"
FAMILIES={4:RAY,13:"10.1101/2024.04.23.590808",17:RAY,18:RAY,20:"10.1101/2023.06.27.546656",
  26:RAY,27:"10.1101/2023.11.30.569086",28:"10.1101/2023.06.07.543976",29:"10.1101/2022.07.20.500311",
  30:"10.1101/2023.05.30.542725",31:"10.1101/2023.06.27.546656",32:"10.1101/2022.11.10.516026",
  33:"10.1101/2023.09.25.559438",34:"10.1101/2022.03.20.485047",35:"10.1101/2023.10.15.562426",
  36:"10.1101/2023.09.06.555791",37:"10.1101/2023.05.30.542725",38:"10.1101/2023.06.27.546656",
  39:RAY,40:"10.1101/2021.09.25.461804",41:"10.1101/2022.03.20.485047",42:RAY,43:RAY,
  44:"10.1101/2022.11.10.516039",45:"10.1101/2022.06.09.495452",46:"10.1101/2022.08.17.504092",
  47:"10.1101/2022.11.10.516026",48:"10.1101/2022.05.13.491877",50:RAY,51:"10.1101/2022.11.24.517785",
  52:RAY,53:RAY,54:RAY,55:RAY,56:"10.1101/2020.01.16.909465",57:RAY,58:"10.1101/2020.12.22.424001",
  59:"10.1101/2020.12.08.413955",60:RAY,62:RAY}
EXACT_BIO={17:2,26:2,28:1,29:1,30:1,33:1,34:1,37:1,39:2,40:1,41:1,42:2,43:2,44:1,45:1,46:1,47:1,50:2,51:1,52:2,53:2,54:2,55:2,57:2,58:1,60:2,62:2}
ELIFE={11:"10.7554/elife.96084.1",12:"10.7554/elife.102230.1",14:"10.7554/elife.96084.1",
       15:"10.7554/elife.102230.1",16:"10.7554/elife.96084.1",19:"10.7554/elife.96084.1"}
NOTES={
 1:"eLife 卷号和 RP 编号未给修订后缀。OpenAlex 对该行匹配 .3，晚于施引首发；同一聚合列表还含 bioRxiv 行，不能据此倒推原始版次。",
 2:"出版商条目明确 bioRxiv，施引时 v2 与 v3 已公开且同题。独立索引未提供修订后缀。",
 3:"登记键明确对应施引 v2，当时可支持被引 eLife .1。原始 v1 的专用书目地址跳转离开该版本的参考列表，独立 DOI 检索又指向后来的期刊记录。",
 4:"登记条目只给题名、作者与 2020 年；OpenAlex 把该行匹配到预印本 DOI，而 Europe PMC 匹配后来期刊。v2 与时序及题名一致，原始条目没有标明来源或修订号。",
 5:"两篇陈姓作者论文是不同的稳定书目。原索引将后发 Neuron 记录列为前作；出版商可用条目未定位到可确认的早期版本。",
 6:"OpenAlex 只保留后出图书的 Work 匹配，该行既没有原始文字，也没有原始 DOI；无法从匹配中确定 1988 年实际使用的版次。",
 7:"OpenAlex 只保留后出章节的 Work 匹配。未见原书目文字、期刊卷页或初版标识。",
 8:"原书目逐字注明 in the press。它证实当时处于待刊状态，未给出具体作者稿或校样的独立标识。",
 10:"原书目写 2006 年、J Vision 6、408a；注册方将相同题名的 DOI 记在 2010 年。保留会议摘要与登记日期的差异。",
 13:"印刷 DOI 能定位预印本，但在施引前已有三次同题发布，缩写署名无法区分。",
 17:"登记题名排除 v1；署名明确含 D’Alessandro，v2 有该作者，v3 的署名已变更，施引时 v4 尚未发布。",
 18:"预印本 DOI 明确，v2 和 v3 同题且施引前均已发布。缩略署名未区分二者。",
 32:"登记字段只给题名、Pires 与 2022 年。找到唯一匹配的已发布预印本 v1，但原条目未标明场所或稳定标识。",
 49:"原书目明确写 in revision。可确认引用的是修订中的稿件，缺少唯一版本号或修订日期。",
 56:"引文明确写 Clements、2020、bioRxiv；同题预印本只有 v1。其首作者、题名与索引关联的 Plaza 期刊文献不同；出版社没有确认这两条记录的版本关系。",
 61:"出版商书目明确登记 eLife 正式 DOI；该正式版与公开的预印本均不能仅凭后来更新的书目确定为施引首发时实际用到的版次。",
 63:"题名和 DOI 匹配后出期刊文章，原条目写 1998 年；未给出施引时可区分的在印版本。"}
MISMATCH={9,64,65}
LATER={21,22,23,24,25}


def main():
    if digest(INPUT)!="767577fb884ee62c8c71a295cfdeb1d7e5ff1503d83caf29260d61d25ca87f7a":raise ValueError("Different version-review input")
    rows=parents();cards=read(CARDS)["items"];assert len(rows)==len(cards)==len(POSITIONS)==65
    paths=list(OUT.glob("Q-RUN11-VER-*.json"))+list(OUT.glob("Q-RUN10-VBIO-*-A1.json"))+[OUT/"Q-RUN10-VTARGET-A1.json"]
    records={p.stem:read(p) for p in paths}
    bio={};published={};registry={};inputs={INPUT.relative_to(ROOT).as_posix():digest(INPUT),CARDS.relative_to(ROOT).as_posix():digest(CARDS)}
    for key,q in records.items():
        for r in q.get("records",[]):
            if "version" in r and "date" in r and r.get("doi"):
                bio.setdefault(doi(r["doi"]),{})[str(r["version"])]=(r,key)
            if r.get("published_doi") and r.get("preprint_doi"):published[doi(r["published_doi"])]=(doi(r["preprint_doi"]),key)
            if r.get("DOI") and "title" in r:registry[doi(r["DOI"])]=(r,key)
    out=[]
    for n,(x,card,pos) in enumerate(zip(rows,cards,POSITIONS),1):
        a,b=x["citing"],x["cited"];family=FAMILIES.get(n);tid=x["task_id"];qids=set(x["query_ids"]);ref={};pre=[];manifest=None
        qids.update(k for k,q in records.items() if any(o["task_id"]==tid for o in q.get("owners",[])))
        if card["deposited_receipt"]:
            p=OUT/(card["deposited_receipt"]+".json");assert digest(p)==card["deposited_receipt_sha256"]
            qids.add(p.stem)
            if pos:
                rec=next(r for r in read(p)["records"] if doi(r["DOI"])==doi(a["doi"]))
                ref=rec["reference"][pos-1]
        cutoff=a["publication_date"]
        if family:
            for r,k in bio[family].values():
                qids.add(k)
                if r["date"]<=cutoff:pre.append(dict(revision=str(r["version"]),posted_date=r["date"],title=r["title"],source=k))
        status="unresolved";note=NOTES.get(n);printed_only=None
        if n in EXACT_BIO:
            suffix=str(EXACT_BIO[n]);assert any(v["revision"]==suffix for v in pre)
            biorow,k=bio[family][suffix]
            literal=norm(ref.get("unstructured") or ref.get("article-title") or ref.get("series-title"))
            assert norm(biorow["title"]) in literal or literal in norm(biorow["title"])
            assert literal and ("biorxiv" in norm(str(ref)) or family in str(ref).lower())
            manifest={"provider":"bioRxiv","doi":family,"revision":suffix,"date":biorow["date"],"title":biorow["title"],"query_id":k}
            status="original_version_supported"
            note=note or "出版商条目给出预印本书目。显式修订 URL 或施引日期之前的修订题名和署名可唯一定位该版。"
        elif n in ELIFE:
            ident=ELIFE[n];r,k=registry[ident];qids.add(k);dt=(r.get("published") or r.get("posted"))["date-parts"][0];date="-".join(f"{v:02}" for v in dt)
            title=r["title"][0]
            assert date<=cutoff
            if n in (11,19):
                assert norm(title) in norm(str(ref))
            else: assert ident in str(ref).lower()
            manifest={"provider":"eLife","doi":ident,"revision":ident.rsplit(".",1)[-1],"date":date,"title":title,"query_id":k}
            status="original_version_supported"
            note="施引书目所列 eLife 题名和发表时序唯一对应 .1，邻近修订的题名及公开日期均已逐项核对。" if n in (11,19) else "施引书目直接给出评审预印本 .1 的版本 DOI，与注册元数据相符。"
        elif n in MISMATCH:
            status="indexed_identity_conflict"
            qids.update(k for k in records if "-YOUGH-" in k)
            note="Europe PMC 给 2022 年微重力论文与 1999 年运动学习论文分配同一 DOI。Crossref 与独立 OpenAlex DOI/PMID 检索区分两篇；该索引关系不能证明原始引用的目标或版本。"
        elif n in LATER or n==3:
            status="later_citing_revision_only"
            if n in LATER:note="条目键指向施引预印本 v2；书目可用于描述后续修订，不能回填 2024-04-16 首发版本。"
            if n==3:qids.add("Q-RUN11-VER-PUBLISHER-GATTUSOV1-A1")
            printed_only={"citing_revision":"v2","position":pos,"source_doi":ref.get("DOI"),"scope":"later_citing_version"}
        elif n==56:
            printed_only={"doi":family,"revision":"1","source":bio[family]["1"][1],"scope":"printed_item_only_target_link_open"}
        elif n in (8,49):
            printed_only={"scope":"editorial_stage_only","state":"in press" if n==8 else "in revision"}
        elif not note:
            assert len(pre)>1,(n,pre)
            note="同一预印本在施引首发前已有多个相同或未能区分的修订。条目未给出版本后缀，保留所有适用候选。"
        if doi(b["doi"]) in published:qids.add(published[doi(b["doi"])][1])
        if doi(b["doi"]) in registry:qids.add(registry[doi(b["doi"])][1])
        for qid in qids:
            p=OUT/(qid+".json");assert p.is_file(),qid;inputs[p.relative_to(ROOT).as_posix()]=digest(p)
        out.append(dict(ordinal=n,cohort=x["cohort"],task_id=tid,citing_work_id=a["work_id"],cited_work_id=b["work_id"],
                  citing_doi=a["doi"],cited_registry_doi=b["doi"],citing_date=cutoff,cited_catalog_date=b["publication_date"],status=status,
                  exact_original_version=manifest,partial_finding=printed_only,preprint_family=family,available_preprint_revisions=pre,
                  deposit_query=card["deposited_receipt"],deposit_position=pos or None,deposit_reference=ref or None,
                  occurrence_ids=[o["occurrence_id"] for o in x["occurrences"]],evidence_queries=sorted(qids),interpretation=note,citation_role="unknown"))
    totals={k:dict(Counter(r["status"] for r in out if r["cohort"]==k)) for k in ("CP11-original","CP12-crossdate")}
    name=TEMP/"reports/RUN-0011-cited-versions.json";write(name,dict(run_id=RUN,scope_id=SCOPE,reviewed_at_utc=stamp(),counts=totals,
      reviewed=len(out),newly_supported_citing_roles=0,items=out,input_receipts=inputs))
    print(totals,flush=True)


if __name__=="__main__":main()
