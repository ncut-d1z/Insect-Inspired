"""Verify eight previously unreviewed deposited references using their saved publisher revision histories."""
from collections import Counter
import hashlib
import json

from integrate_run11_reviews import Ledger
from run10_reference_records import doi, norm
from run12_reference_search import CP, RUN
from run12_reviews import VERSIONS
from run12_version_screen import REPORT as SCREEN
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write

REPORT = TEMP / "reports/RUN-0012-cached-version-reviews.json"
# Each expected version here describes the citing reference list, as printed in its deposited item key.
CASES = {
    "ee3a964f": (3, 152), "8fa74480": (2, 43), "a9f646b2": (2, 31), "3ed8b3ac": (2, 20),
    "9be3e4f7": (1, 27), "a17662ed": (2, 23), "6c072b61": (2, 55), "f2ef58d7": (3, 108),
}


def prepare():
    if REPORT.exists():
        raise ValueError("An immutable comparison already exists")
    screen = read(SCREEN)
    reviewed = {x["task_id"] for x in read(VERSIONS)["items"]}
    cases = [x for x in screen["items"] if x["task_id"] not in reviewed and x["publisher_histories_available"]]
    if {x["task_id"][-8:] for x in cases} != set(CASES) or len(cases) != len(CASES):
        raise ValueError("The cached unreviewed cohort changed")
    inputs = {p.relative_to(ROOT).as_posix(): digest(p) for p in (SCREEN, VERSIONS)}
    items = []
    for task in cases:
        tid = task["task_id"]
        revision, position = CASES[tid[-8:]]
        occ, = [o for o in task["occurrences"] if o["source_id"] == "crossref" and o["family_identifiers"]]
        qid, = occ["source_queries"]
        p = OUT / (qid + ".json")
        listing = read(p)
        inputs[p.relative_to(ROOT).as_posix()] = digest(p)
        parent, = [r for r in listing["records"] if doi(r["DOI"]) == doi(task["citing_doi"])]
        ref = parent["reference"][position - 1]
        literal = ref.get("unstructured") or json.dumps(ref, ensure_ascii=False, separators=(",", ":"))
        family, = occ["family_identifiers"]
        citing_suffix = task["citing_doi"].split("/", 1)[1] + f"v{revision}.{position}"
        if (listing["status"] != "success" or int(occ["locator"].split(", ")[-1]) != position
                or hashlib.sha256(literal.encode()).hexdigest() != occ["reference_sha256"]
                or not ref["key"].endswith(citing_suffix) or doi(ref["DOI"]) != family):
            raise ValueError("Deposited reference changed " + tid)
        history = screen["publisher_revision_histories"][family]
        queries = {qid}
        editions = {}
        for row in history:
            rp = OUT / (row["query"] + ".json")
            inputs[rp.relative_to(ROOT).as_posix()] = digest(rp)
            hits = [h for h in read(rp)["records"] if doi(h.get("doi")) == family and str(h.get("version")) == row["revision"]]
            if not any(h["date"] == row["date"] and h["title"] == row["title"] for h in hits):
                raise ValueError("Publisher release changed " + tid)
            editions[row["revision"]] = row
            queries.add(row["query"])
        selected = None
        if revision == 1:
            matches = [r for r in editions.values() if r["date"] <= task["citing_date"] and norm(r["title"]) in norm(literal)]
            if (len(matches) != 1 or matches[0]["revision"] != "1" or "preprint" not in literal.casefold()
                    or "rayshubskiy" not in literal.casefold()):
                raise ValueError("No unique contemporary printed-title match " + tid)
            match = matches[0]
            selected = dict(provider="bioRxiv", doi=family, revision=match["revision"], date=match["date"],
                            title=match["title"], query_id=match["query"])
            outcome = "original_version_supported"
            note = "Pires 首发 v1 的第 27 条明示预印本、作者、题名与家族 DOI。2022 年前可用的两版中，印出的题名匹配 2020-04-05 的 v1，2020-07-18 的 v2 已改题。"
        else:
            if ref.get("unstructured") or ref.get("article-title") or ref.get("doi-asserted-by") != "publisher":
                raise ValueError("Re-examine newly available reference text " + tid)
            outcome = "later_citing_revision_only"
            note = (f"登记条目键将第 {position} 条定位于施引预印本 v{revision}，出版方给出被引预印本家族 DOI。"
                    "未给被引修订号，也未取得施引首发 v1 的对应条目。")
        items.append(dict(ordinal=len(items) + 1, task_id=tid, citing_work_id=task["citing_work_id"],
                          cited_work_id=task["cited_work_id"], citing_doi=task["citing_doi"], cited_registry_doi=task["cited_doi"],
                          deposit_position=position, deposited_key=ref["key"], citing_revision=revision, printed_family=family,
                          occurrence_id=occ["occurrence_id"], reference_sha256=occ["reference_sha256"], status=outcome,
                          exact_original_version=selected, evidence_queries=sorted(queries), interpretation=note))
    counts = dict(Counter(x["status"] for x in items))
    counts["reviewed_items"] = len(items)
    write(REPORT, dict(run_id=RUN, checkpoint_id=CP, scope_id=SCOPE, reviewed_at_utc=stamp(), counts=counts,
                       items=items, input_receipts=inputs, additional_external_requests=0))
    print(counts, flush=True)


class CachedReviewLedger(Ledger):
    checkpoint = CP
    id_prefix = "R12"
    run_id = RUN
    version_report = REPORT


def register(canonical):
    review = read(REPORT)
    for filename, expected in review["input_receipts"].items():
        path = ROOT / filename
        if digest(path) != expected:
            raise ValueError("A version source changed " + filename)
        canonical.input_paths.add(path)
    canonical.input_paths.add(REPORT)
    tids = {item["task_id"] for item in review["items"]}
    ledger = CachedReviewLedger(tids, set())
    if set(ledger.latest) != tids or any(t["task_state"] == "verified_complete" for t in ledger.latest.values()):
        raise ValueError("Prior version task state changed")
    ledger.cited(review)
    for dataset, rows in ledger.adds.items():
        for key, row in rows.items():
            if key in canonical.adds[dataset]:
                raise ValueError("Overlapping canonical review " + key)
            canonical.add(dataset, row)
    return review["counts"]


if __name__ == "__main__":
    prepare()
