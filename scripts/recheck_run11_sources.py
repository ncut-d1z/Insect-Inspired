"""Reobserve the bibliographic data returned in early overlapping request windows, retaining both observations."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from urllib.parse import urlencode, urlsplit

from checkpoint_cp10 import require
from escalate_unknown_run7 import git
from partitioned_research_json import encode, put, sha
from run10_reference_records import request_identities, token
from run11_reference_inventory import literal_project
from search_run9_bibliography import facts
from search_run11_bibliography import OUT, ROOT, STATE, TEMP, deposited, digest, indexed, read, request, stamp

PLAN = TEMP / "reports/RUN-0011-source-rechecks-plan.json"
RESULT = TEMP / "reports/RUN-0011-source-rechecks.json"
HOSTS = {"api.crossref.org", "api.openalex.org", "www.ebi.ac.uk"}


def capture(old):
    def callback(key, provider, endpoint, params, owners, reason, project):
        url = endpoint + ("?"+urlencode(params) if params else "")
        require(url == old["endpoint_or_url"] and owners == old["owners"] and provider == old["source_id"],
                "Original bibliographic query no longer reproduces its URL or owners: " + old["query_id"])
        return project
    return callback


def project_for(old, frontier):
    ident = old["query_id"]
    url = urlsplit(old["endpoint_or_url"])
    require(url.scheme == "https" and url.hostname in HOSTS and
            (url.path.startswith("/works") or url.path.startswith("/europepmc/webservices/rest/")),
            "Unexpected bibliographic endpoint")
    if "-ID-" in ident and ident.startswith("Q-RUN11-ID-"):
        return request_identities(old["requested_identifiers"], old["source_id"], old["owners"], capture(old))
    if "-IDX-" in ident or "-DEP-" in ident:
        group = [frontier[o["work_id"]] for o in old["owners"]]
        if "-IDX-" in ident:
            field = ident.split("-IDX-")[1].split("-")[0].lower()
            return indexed(ident, group, field, capture(old))
        return deposited(ident, group, capture(old))
    if url.path.endswith("/references"):
        if old["source_id"] == "openalex":
            return literal_project
        def ep_list(data):
            records = data.get("referenceList",{}).get("reference",[])
            total = int(data["hitCount"])
            return dict(records=records, visible_total=total, returned_count=len(records),
                        page_complete=(old["page_index"]-1)*1000+len(records)==total)
        return ep_list
    def remaining(data):
        if "-VER-PARENT-" in ident:
            records = [{k:data.get(k) for k in ("id","doi","display_name","publication_date","type","ids")}]
            n = 1
        elif "-VER-YOUGH-IDENTITY-" in ident:
            records = []
            for item in data["resultList"]["result"]:
                row = facts(item)
                row["source_identifier"] = row["source"] + ":" + str(row["id"])
                records.append(row)
            n = int(data["hitCount"])
        elif "-VER-PAIR-EPMC-" in ident:
            keep = ("source","id","doi","title","authorString","firstPublicationDate","pubYear","commentCorrectionList","pubTypeList")
            records = [{k:r[k] for k in keep if k in r} for r in data["resultList"]["result"]]
            n = int(data["hitCount"])
        elif "-VER-PAIR-" in ident:
            msg = data["message"]
            keep = ("DOI","title","author","published","subtype","type","relation")
            records = [{k:r[k] for k in keep if k in r and (k!="relation" or r[k])} for r in msg["items"]]
            n = int(msg["total-results"])
        elif "-P56-HILDRETH-CR-" in ident:
            item = data["message"]
            raw = item.get("abstract") or ""
            records = [{**{k:item.get(k) for k in ("DOI","title","published")},
                        "abstract_available":bool(raw), "abstract_sha256":sha(raw.encode()) if raw else None}]
            n = 1
        else:
            raise ValueError("Unknown projection " + ident)
        return dict(records=records, visible_total=n, returned_count=len(records), page_complete=len(records)==n)
    require(any(k in ident for k in ("-VER-PARENT-","-VER-YOUGH-IDENTITY-","-VER-PAIR-","-P56-HILDRETH-CR-")), "Unhandled projection " + ident)
    return remaining


def original_frontier():
    return {w["work_id"]:w for w in read(ROOT/read(STATE)["frontier"])["worklist"]}


def plan():
    if PLAN.exists():
        return read(PLAN)
    head = git(ROOT,"rev-parse","HEAD").decode().strip()
    older = [p for p in git(ROOT,"ls-tree","--name-only",head+":temp/query-results").decode().splitlines() if p.startswith("Q-RUN11-")]
    spans, affected, receipts = defaultdict(list), set(), {}
    for name in older:
        q = read(OUT/name)
        if q.get("execution_limits"):
            continue
        k = q["query_id"]
        receipts[k] = (q["status"], digest(OUT/name))
        if q.get("requested_at_utc"):
            spans[q["source_id"]].append((datetime.fromisoformat(q["requested_at_utc"]),datetime.fromisoformat(q["completed_at_utc"]),k))
        else:
            affected.add(k)
    for provider, items in spans.items():
        previous, active = None, []
        for a,b,k in sorted(items):
            active = [item for item in active if item[1] > a]
            for other in active:
                affected.update((other[2],k))
            if provider=="crossref" and previous and (a-previous[0]).total_seconds()<1:
                affected.update((previous[2],k))
            active.append((a,b,k))
            previous = (a,b,k)
    verified, failed = [], []
    frontier = original_frontier()
    for k in sorted(affected):
        q = read(OUT/(k+".json"))
        entry = dict(query_id=k, sha256=receipts[k][1], status=q["status"])
        if q["status"]=="success":
            project_for(q, frontier)
            verified.append(entry)
        else:
            require(not q.get("records"), "Unsuccessful original has records requiring review")
            failed.append(entry)
    result = dict(run_id="RUN-0011", source_commit=head, created_at_utc=stamp(), affected=len(affected),
                  successful_originals=verified, originals_without_returned_data=failed)
    put(PLAN, encode(result)+b"\n")
    return result


def reobserve(item, frontier):
    old = read(OUT/(item["query_id"]+".json"))
    require(digest(OUT/(old["query_id"]+".json")) == item["sha256"], "Original source evidence changed")
    url = old["endpoint_or_url"].split("?",1)[0]
    params = old["parameters"]
    require(url+("?"+urlencode(params) if params else "")==old["endpoint_or_url"], "Unreproducible original parameters")
    project = project_for(old, frontier)
    ordered = urlsplit(url).path.endswith("/references")
    def signature(rows):
        data = [sha(encode(r)) for r in rows]
        if not ordered:
            data.sort()
        return sha(encode(data))
    def compare(raw):
        observed = project(json.loads(raw))
        before, after = signature(old["records"]), signature(observed["records"])
        fields = ("returned_count", "visible_total", "page_complete")
        same = before==after and all(old.get(k)==observed.get(k) for k in fields)
        original_raw = sha(raw)==old.get("response_sha256")
        if original_raw and not same:
            # An identical complete API response independently binds the historical projection.
            same = True
        ids = []
        for i,r in enumerate(observed["records"], 1):
            ident = r.get("source_identifier") or r.get("DOI") or r.get("doi") or r.get("id") or r.get("work_id") or (old["query_id"]+"#"+str(i))
            ids.append({"source_identifier":str(ident)})
        check = dict(original_query_id=old["query_id"], original_receipt_sha256=item["sha256"], same_response_bytes=original_raw,
                     same_projected_sha256=before==after, matches=same, original_projection_sha256=before, observed_projection_sha256=after,
                     require_source_position_order=ordered)
        if not same:
            check["changed_projection"] = observed["records"]
        return {**{k:observed[k] for k in fields}, "records":ids, "comparison":check}
    return request("CHK-"+token(old["query_id"]),old["source_id"],url,params,old["owners"],
                   "Reobserve previously returned bibliography under the shared provider lock and compare it to "+old["query_id"]+".",
                   compare,old["page_index"],decode=lambda raw:raw)


def finish(data):
    results = []
    for item in data["successful_originals"]:
        files = sorted(OUT.glob("Q-RUN11-CHK-"+token(item["query_id"])+"-A*.json"))
        require(files, "Missing guarded reobservation " + item["query_id"])
        q = read(files[-1])
        require(q.get("execution_limits",{}).get("per_provider_concurrency")==1, "Unguarded reobservation")
        results.append(dict(original_query_id=item["query_id"], original_receipt_sha256=item["sha256"], final_query=q["query_id"],
                            final_receipt_sha256=digest(files[-1]), attempts=len(files), status=q["status"],
                            matches=q.get("comparison",{}).get("matches",False),
                            same_response_bytes=q.get("comparison",{}).get("same_response_bytes",False)))
    stats = dict(affected=data["affected"], original_failed_without_data=len(data["originals_without_returned_data"]),
                 successful_originals=len(results), reobserved_matches=sum(r["matches"] for r in results),
                 original_bytes_reproduced=sum(r["same_response_bytes"] for r in results), outstanding=sum(not r["matches"] for r in results))
    out = dict(run_id="RUN-0011", completed_at_utc=stamp(), plan_sha256=digest(PLAN), counts=stats,
               research_admissions=0, results=results)
    put(RESULT, encode(out)+b"\n")
    print(stats)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("plan","check","finish"))
    p.add_argument("start", type=int, nargs="?", default=0)
    p.add_argument("--count", type=int, default=6)
    a=p.parse_args()
    data=plan()
    if a.action=="plan":
        print(data["affected"], len(data["successful_originals"]))
    elif a.action=="finish":
        finish(data)
    else:
        frontier=original_frontier()
        for item in data["successful_originals"][a.start:a.start+a.count]:
            q=reobserve(item,frontier)
            print(item["query_id"],q["status"],q.get("comparison",{}).get("matches"),flush=True)
