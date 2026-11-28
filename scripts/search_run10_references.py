"""Resume the CP11 bibliography frontier. Read only registry metadata and reference lists."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / "temp"
OUT = TEMP / "query-results"
RUN = "RUN-0010"
CP = "CP-0012"
SCOPE = "SCOPE-0001"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
CR = "https://api.crossref.org/works"
FRONTIER = TEMP / "reports/RUN-0010-initial-frontier.json"
VERSION_INPUT = TEMP / "reports/RUN-0009-bibliographic-citation-versions.json"


def read(path):
    return json.loads(Path(path).read_bytes())


def stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode()
    part = path.with_suffix(".part")
    with part.open("xb") as f:
        f.write(raw)
    try:
        if path.exists():
            raise FileExistsError(path)
        os.rename(part, path)
    finally:
        part.unlink(missing_ok=True)


def result_path(key, attempt):
    return OUT / f"Q-RUN10-{key}-A{attempt}.json"


def fetch(key, provider, endpoint, params, owners, reason, transform, page=1):
    url = endpoint + ("?" + urlencode(params) if params else "")
    for attempt in range(1, 5):
        dest = result_path(key, attempt)
        if dest.exists():
            previous = read(dest)
            if previous["endpoint_or_url"] != url or previous["owners"] != owners:
                raise ValueError("Cache key mismatch " + key)
            if previous["status"] == "success":
                return previous
            if not previous.get("retryable"):
                return previous
            continue
        run = read(TEMP / "runs/RUN-0010.json")
        hold=TEMP/"runs/RUN-0010-source-hold.json"
        if hold.is_file() and (state:=read(hold)).get("status","open")=="open":
            raise RuntimeError("Source work paused for the recorded data correction: "+state["reason"])
        start = datetime.fromisoformat(run["started_at_utc"])
        if (datetime.now(timezone.utc) - start).total_seconds() >= run["budget"]["wall_clock_hours"] * 3600:
            raise RuntimeError("RUN10 wall-clock budget reached")
        if sum(1 for _ in OUT.glob("Q-RUN10-*.json")) >= run["budget"]["external_requests"]:
            raise RuntimeError("RUN10 source request budget reached")
        entry = dict(query_id=dest.stem, run_id=RUN, scope_id=SCOPE, target_checkpoint=CP,
                     source_id=provider, requested_at_utc=stamp(), endpoint_or_url=url, parameters=params,
                     page_index=page, owners=owners, reason=reason, external_request_count=1,
                     attempt=attempt, status="error", http_status=None, retryable=False)
        req = Request(url, headers={"User-Agent": "Insect-Inspired-Bibliography/1.2", "Accept": "application/json"})
        try:
            with urlopen(req, timeout=25) as res:
                raw = res.read()
                entry["http_status"] = res.status
            entry["response_sha256"] = hashlib.sha256(raw).hexdigest()
            entry["response_bytes"] = len(raw)
            entry.update(transform(json.loads(raw)))
            entry["status"] = "success"
        except HTTPError as exc:
            entry.update(http_status=exc.code, error=str(exc), retryable=exc.code in {408,429,500,502,503,504})
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                entry["retry_after"] = retry_after
        except (OSError, ValueError, KeyError, TypeError) as exc:
            entry.update(error=str(exc), retryable=isinstance(exc, OSError))
        entry["completed_at_utc"] = stamp()
        write(dest, entry)
        print(dest.name, entry["status"], entry.get("returned_count"), flush=True)
        if entry["status"] == "success" or not entry["retryable"] or attempt == 4:
            return entry
        delay = [2,5,15][attempt-1]
        if entry.get("retry_after"):
            try:
                delay = max(delay, int(entry["retry_after"]))
            except ValueError:
                from email.utils import parsedate_to_datetime
                delay = max(delay, (parsedate_to_datetime(entry["retry_after"]) - datetime.now(timezone.utc)).total_seconds())
        time.sleep(delay)
    return previous


def crossref(key, owners, reason):
    dois = [x["doi"].lower() for x in owners]
    params = {"filter": ",".join("doi:" + d for d in dois), "rows": len(dois)}
    def project(data):
        msg = data["message"]
        records = []
        for item in msg["items"]:
            # Keep the complete reference entries, including their literal text and keys.
            # Registry articles, abstracts and links to attachments are not copied.
            record = {k:item[k] for k in ("DOI","title","published","published-online","posted",
                         "container-title","type","reference-count","reference") if k in item}
            records.append(record)
        actual = [r["DOI"].lower() for r in records]
        if len(actual) != len(set(actual)) or set(actual)-set(dois) or len(records) != msg["total-results"]:
            raise ValueError("DOI-filter response not reconciled")
        return dict(records=records, visible_total=msg["total-results"], returned_count=len(records),
                    page_complete=True, missing_dois=sorted(set(dois)-set(actual)))
    return fetch(key,"crossref",CR,params,owners,reason,project)


def europe(owner, prefix):
    provider, identifier = owner["epmc"].split(":", 1)
    if provider not in {"PPR","MED"} or not identifier.isalnum():
        raise ValueError(owner["epmc"])
    endpoint = EPMC + provider + "/" + quote(identifier) + "/references"
    page = int(owner.get("prior_cursor") or 1)
    total = None
    while True:
        def project(data):
            n = int(data["hitCount"])
            refs = data.get("referenceList", {}).get("reference", [])
            end = (page-1)*1000 + len(refs)
            if end > n or (not refs and end < n) or (total is not None and n != total):
                raise ValueError("Inconsistent reference pagination")
            return dict(records=refs, visible_total=n, returned_count=len(refs), page_complete=end==n,
                        cursor_in=str(page), cursor_out=None if end==n else str(page+1))
        r = fetch(f"{prefix}-{identifier}-P{page}","europepmc",endpoint,
                  {"page":page,"pageSize":1000,"format":"json"},[owner],
                  "CP11 unresolved reference or cited-version task; Europe PMC indexed bibliography.",project,page)
        if r["status"] != "success" or r["page_complete"]:
            return
        total = r["visible_total"]
        page += 1


def review_owners():
    # Several citing DOIs identify a version or alias of the canonical Work.
    integrated=read(TEMP/"reports/RUN-0009-bibliographic-integration.json")
    report=read(VERSION_INPUT)
    by_source={r["source_identifier"]:r["work_id"] for r in integrated["unique_worklist"]
               if r["parent"]==report["work_id"]}
    owners=[]
    for row in report["items"]:
        if not row["status"].startswith("unresolved"):
            continue
        doi = row["citing_doi"]
        ident = row["citing_epmc_id"]
        epmc=("PPR:" if ident.startswith("PPR") else "MED:")+ident
        owners.append(dict(doi=doi,work_id=by_source[epmc],epmc=epmc,
                           task_id="T-BIB-CITED-VERSION-"+hashlib.sha256(doi.encode()).hexdigest()[:18]))
    if len(owners)!=13:
        raise ValueError("Unbound CP11 version review set")
    return owners


def version_identities():
    review=read(VERSION_INPUT)
    owner={"work_id":review["work_id"], "task_id":"T-citations-"+review["work_id"]}
    dois=list(review["cited_versions"])+["10.7554/elife.102230.2","10.7554/elife.102230.3"]
    def metadata(data):
        msg=data["message"]
        rows=[{k:r[k] for k in ("DOI","title","type","subtype","published","published-online","posted",
              "container-title","publisher","relation","group-title","article-number","volume") if k in r}
              for r in msg["items"]]
        actual=[r["DOI"].lower() for r in rows]
        if len(set(actual))!=len(rows) or len(rows)!=msg["total-results"] or set(actual)-set(dois):
            raise ValueError("Target version identities do not reconcile")
        return dict(records=rows,visible_total=msg["total-results"],returned_count=len(rows),page_complete=True,
                    missing_dois=sorted(set(dois)-set(actual)))
    fetch("VTARGET","crossref",CR,{"filter":",".join("doi:"+d for d in dois),"rows":len(dois)},[owner],
          "Disambiguate registered and reviewed-preprint version dates, including neighboring version suffixes.",metadata)
    for doi,item in [("10.1101/2020.04.04.024703",owner),
                     ("10.1101/2024.04.15.589655",next(r for r in review_owners() if r["epmc"].startswith("PPR:")))]:
        def revisions(data):
            rows=[{k:r[k] for k in ("doi","title","authors","date","version","published","server") if k in r}
                  for r in data["collection"]]
            if not rows or any(r["doi"].lower()!=doi for r in rows) or len({r["version"] for r in rows})!=len(rows):
                raise ValueError("Publisher preprint version inventory missing or ambiguous")
            return dict(records=rows,returned_count=len(rows),visible_total=len(rows),page_complete=True)
        fetch("VBIO-"+doi.rsplit(".",1)[-1],"publisher","https://api.biorxiv.org/details/biorxiv/"+doi,
              {},[item],"Publisher bibliographic version history and dates only.",revisions)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation",choices=["versions","version-index","version-identities","references","deposits"])
    p.add_argument("start",type=int)
    p.add_argument("end",type=int)
    args=p.parse_args()
    if args.operation=="version-identities":
        version_identities()
        return
    reviews=review_owners()
    frontier=read(FRONTIER)["worklist"]
    if args.operation in {"versions","version-index"}:
        queue=reviews
    else:
        queue=frontier
        if not (TEMP/"reports/RUN-0010-cited-versions.json").exists():
            raise ValueError("Finish and register the 13 version decisions before backward expansion")
    if not 1<=args.start<=args.end<=len(queue):
        raise ValueError("Invalid inclusive frontier range")
    portion=queue[args.start-1:args.end]
    if args.operation in {"versions","deposits"}:
        # Version-review deposits already contain the full reference list for overlapping parents.
        if args.operation=="deposits":
            covered={r["DOI"].lower() for path in OUT.glob("Q-RUN10-VCR-*.json")
                     for r in read(path).get("records",[]) if "reference" in r}
            portion=[o for o in portion if o["doi"].lower() not in covered]
        if portion:
            key=("VCR" if args.operation=="versions" else "BCR")+f"-{args.start:03}-{args.end:03}"
            crossref(key,portion,"Read literal deposited reference fields omitted by the CP11 DOI-only version projection."
                     if args.operation=="versions" else "Complement indexed bibliography with deposited reference positions and identifiers.")
    else:
        for owner in portion:
            if args.operation=="references":
                cached=[read(p) for p in OUT.glob("Q-RUN10-VEP-"+owner["epmc"].split(":")[1]+"-P*-A*.json")]
                if any(r["status"]=="success" and r["page_complete"] for r in cached):
                    continue
            europe(owner,"VEP" if args.operation=="version-index" else "BEP")


if __name__ == "__main__":
    main()
