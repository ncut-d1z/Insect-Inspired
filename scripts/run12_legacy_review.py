"""Record reviewed reference positions for the 28 still-open CP12 version cases."""
from collections import Counter

from run10_reference_records import token
from run12_legacy_deposits import OLD, REPORT
from run12_reference_search import CP, RUN
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

REVIEW = TEMP/"reports/RUN-0012-CP12-deposit-reviews.json"
REVIEWED_SHA = "a4d1dd1a350a75f10d7a71c404b680e880c1dbeb4b59184bd956255f2b77d32e"
GROUPS = [
    ((5,), "target_not_located", "59 个登记条目中未能按目标 DOI 或题名定位该 Neuron 文献，无法确认早期版本。"),
    ((6,7), "no_deposited_entries", "这篇 1988 年论文的登记 XML 没有返回参考条目。索引匹配的后出图书或章节仍无法确定原引版次。"),
    ((9,64,65), "conflicting_index_identity", "分别核对索引误配涉及的两篇不同文献。登记条目中没有找到与其题名或涉争 DOI 对应的位置。"),
    ((8,), "editorial_stage", "书目原文写 in the press。待刊状态可确认，原条目缺作者稿或校样标识。"),
    ((49,), "editorial_stage", "原条目写 in revision。可定位修订中的稿件，缺少唯一修订编号或日期。"),
    ((10,), "bibliographic_date_conflict", "书目记载 2006 年 J Vision 摘要，后补 DOI 的登记日期与之不同。按原有工单保留日期、版本缺口。"),
    ((13,18,20,27,31,35,36,38,48,59), "multiple_revisions", "书目给出的预印本家族、题名或场所与既有候选相容。未找到能区分施引时多个候选修订的字段或链接。"),
    ((21,22,23,24,25), "later_citing_revision", "条目键明示施引预印本 v2。该条目可定位到 v2，首发 v1 的参考列表待查。"),
    ((32,), "published_link_unconfirmed", "作者、题名和年份与一个预印本候选相容，登记条目缺少可确认原引用载体的标识或场所。"),
    ((56,), "published_link_unconfirmed", "Clements 的 2020 年 bioRxiv 条目可定位。该条目没有给出与索引所指 Plaza 期刊记录之间的版本关联。"),
    ((61,63), "later_publication_metadata", "登记条目指向具体期刊论文。施引时实际可取得的修订或在印稿未在条目中标明。"),
]


def prepare():
    if REVIEW.is_file():
        return
    if digest(REPORT) != REVIEWED_SHA:
        raise ValueError("The reviewed source positions changed")
    positions = read(REPORT)
    cases = {r["ordinal"]:r for r in read(OLD)["items"]}
    notes = {n:(k,note) for numbers,k,note in GROUPS for n in numbers}
    if set(notes) != {r["ordinal"] for r in positions["items"]}:
        raise ValueError("Reviewed ticket coverage differs")
    results = []
    for row in positions["items"]:
        number = row["ordinal"]; previous = cases[number]
        matches = row["matching_positions"]
        if row["source_status"] != "success" or len(matches)>1 or any(m["revision_candidates"] for m in matches):
            raise ValueError("Unreviewed evidence for ticket "+str(number))
        if matches and (matches[0]["position"] != previous["deposit_position"] or matches[0]["source_key"] != previous["deposit_reference"]["key"]):
            raise ValueError("Registered and deposited reference positions disagree")
        category, note = notes[number]
        results.append(dict(ordinal=number,task_id=row["task_id"],citing_work_id=row["citing_work_id"],cited_work_id=row["cited_work_id"],
                 query_id=row["query_id"],position=matches[0]["position"] if matches else None,
                 reference_key=matches[0]["source_key"] if matches else None,source_positions=row["returned_list_positions"],
                 category=category,finding=note,exact_original_version=None,
                 previous_queries=previous["evidence_queries"]))
    counts={**positions["counts"],"reviewed_items":len(results),"newly_resolved":0,"still_open":len(results),
            "findings":dict(Counter(r["category"] for r in results))}
    write(REVIEW,dict(run_id=RUN,checkpoint_id=CP,scope_id=SCOPE,reviewed_at_utc=stamp(),source_locator_sha256=REVIEWED_SHA,
              input_receipts={**positions["input_receipts"],REPORT.relative_to(ROOT).as_posix():REVIEWED_SHA},counts=counts,items=results))
    print(counts,flush=True)


def register(ledger):
    review=read(REVIEW)
    for relative,expected in review["input_receipts"].items():
        path=ROOT/relative
        if digest(path)!=expected:raise ValueError("Previously reviewed source changed")
        ledger.input_paths.add(path)
    ledger.input_paths.add(REVIEW)
    needed={r["task_id"] for r in review["items"]}
    for prior in iter_logical("tasks.jsonl"):
        if prior["task_id"] in needed:
            ledger.latest[prior["task_id"]]=prior
    for row in review["items"]:
        tid=row["task_id"];old=ledger.latest[tid];wid=row["citing_work_id"]
        if old["entity_id"]!=wid or old["task_state"] in {"done","rejected","not_applicable"}:
            raise ValueError("Historical version task changed")
        rid="MR-R12-CP12XML-"+token(tid)
        event=ledger.task(tid,wid,old["task_type"],row["finding"],old["task_state"],[row["query_id"]],source_id="crossref")
        event["normalized_parameters"]["cp12_xml_recheck"]={k:row[k] for k in ("category","query_id","source_positions","position","reference_key","exact_original_version")}
        event["supporting_record_ids"].append(rid)
        ledger.add("manual-reviews",dict(review_id=rid,run_id=RUN,review_type="bibliographic_version_comparison",entity_id=wid,
                        reviewer="Codex 书目复核",recorded_at_utc=review["reviewed_at_utc"],artifact=REVIEW.relative_to(ROOT).as_posix(),notes=row["finding"]))
    return review["counts"]


if __name__=="__main__":
    prepare()
