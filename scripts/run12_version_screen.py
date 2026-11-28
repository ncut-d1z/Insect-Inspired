"""Screen inherited version tickets against the actual stored reference occurrences and publisher histories."""
import re
from collections import Counter, defaultdict

from run10_reference_records import doi, norm
from run12_reference_search import RUN
from search_run11_bibliography import OUT, ROOT, SCOPE, TEMP, digest, read, stamp, write
from storage import iter_logical

REPORT=TEMP/"reports/RUN-0012-version-screen.json"
OLD=TEMP/"reports/RUN-0011-cited-versions.json"
FAMILY=re.compile(r"10\.1101/(?:\d{4}\.\d{2}\.\d{2}\.)?\d{5,}",re.I)
EXACT=re.compile(r"(?:10\.7554/elife\.\d+\.[1-9]\d*|10\.1101/(?:\d{4}\.\d{2}\.\d{2}\.)?\d{5,}v[1-9]\d*|(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*)\d{4}\.\d{4,5}v[1-9]\d*)",re.I)


def main():
    if REPORT.exists():return
    original=read(OLD)
    inherited=[dict(task_id=r["task_id"],cohort=r["cohort"],prior_status=r["status"],
                    cited_work_id=r["cited_work_id"],citing_work_id=r["citing_work_id"],existing_evidence_count=len(r["evidence_queries"]),
                    action="retain_previous_evidence_and_open_version") for r in original["items"] if r["status"]!="original_version_supported"]
    pending={}
    for t in iter_logical("tasks.jsonl"):
        if t["task_id"].startswith("T-R11-CITED-"):pending[t["task_id"]]=t
    occmap=defaultdict(list)
    for tid,t in pending.items():
        for rid in t.get("supporting_record_ids",[]):
            if rid.startswith("R-"):occmap[rid].append(tid)
    selected=defaultdict(list);wids=set()
    for r in iter_logical("reference-occurrences.jsonl"):
        rid=r["occurrence_id"]
        if rid not in occmap:continue
        raw=r["raw_reference"]
        fam=sorted({s.lower() for s in FAMILY.findall(raw)})
        exact=sorted({s.lower() for s in EXACT.findall(raw)})
        editorial=re.search(r"\b(in press|forthcoming|in revision|in preparation|to appear)\b",raw,re.I)
        wids.update((r["citing_work_id"],r["cited_work_id"]))
        for tid in occmap[rid]:
            selected[tid].append(dict(occurrence_id=rid,citing_work_id=r["citing_work_id"],cited_work_id=r["cited_work_id"],reference_sha256=r["raw_fingerprint"],
                  source_id=r["source"]["source_id"],locator=r["section"],family_identifiers=fam,revision_strings=exact,
                  editorial_stage=editorial.group(0).lower() if editorial else None,
                  source_queries=[v["evidence_note"] for v in r["source"]["evidence_locator"] if v.get("evidence_note")]))
    works={w["work_id"]:w for w in iter_logical("works.jsonl") if w["work_id"] in wids}
    families={f for rows in selected.values() for r in rows for f in r["family_identifiers"]}
    histories=defaultdict(list);inputs={OLD.relative_to(ROOT).as_posix():digest(OLD)}
    for pattern in ("Q-RUN10-VBIO-*.json","Q-RUN11-VER-BIO-*.json","Q-RUN11-VER-PUB-*.json"):
        for p in sorted(OUT.glob(pattern)):
            q=read(p)
            if q["status"]!="success" or q["source_id"]!="publisher":continue
            matched=False
            for r in q.get("records",[]):
                f=doi(r.get("doi"))
                if f in families and r.get("version") and r.get("date") and r.get("title"):
                    histories[f].append(dict(revision=str(r["version"]),date=r["date"],title=r["title"],published_doi=doi(r.get("published")),query=q["query_id"]))
                    matched=True
            if matched:inputs[p.relative_to(ROOT).as_posix()]=digest(p)
    results=[];counts=Counter()
    for tid,t in sorted(pending.items()):
        occurrences=selected[tid]
        if not occurrences or len({(r["citing_work_id"],r["cited_work_id"]) for r in occurrences})!=1:raise ValueError("Unbound version ticket "+tid)
        a=works[occurrences[0]["citing_work_id"]];b=works[occurrences[0]["cited_work_id"]]
        revisions={s for r in occurrences for s in r["revision_strings"]}
        fam={s for r in occurrences for s in r["family_identifiers"]}
        stages={r["editorial_stage"] for r in occurrences if r["editorial_stage"]}
        status=("version_identifier_candidate" if revisions else "preprint_family_identifier" if fam else "editorial_stage" if stages else "no_explicit_revision_found")
        counts[status]+=1
        results.append(dict(task_id=tid,citing_work_id=a["work_id"],citing_key=a["work_key"],citing_date=a.get("publication_date"),citing_doi=a.get("doi"),
                 cited_work_id=b["work_id"],cited_key=b["work_key"],cited_doi=b.get("doi"),cited_date=b.get("publication_date"),
                 screening=status,publisher_histories_available=sorted(f for f in fam if histories.get(f)),occurrences=occurrences))
    write(REPORT,dict(run_id=RUN,scope_id=SCOPE,created_at_utc=stamp(),inputs=inputs,inherited_open=inherited,screening_counts=dict(counts),
         publisher_revision_histories=dict(histories),items=results,exact_versions_adjudicated=0,
         interpretation="Automated triage of registered source positions and release metadata. A Work-level matched identifier or earliest possible date does not on its own establish which revision was cited."))
    print("Inherited",len(inherited),"screened",len(results),dict(counts),"cached publisher families",len(histories),flush=True)


if __name__=="__main__":main()
