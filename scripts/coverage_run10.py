"""Count CP12 from the complete partitioned registry, source receipts and latest task events."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json

from audit_cp10 import REQUEST_COUNT_BASIS
from checkpoint_cp10 import CURSOR_FIELDS, DIMENSIONS, TERMINAL, latest_tasks, objects, require, utc
from escalate_unknown_run7 import logical_lines, logical_names
from search_run10_references import CP, OUT, ROOT, RUN, SCOPE, TEMP, read


def collect(frozen):
    parent = read(TEMP / "snapshots/checkpoints/CP-0011.json")
    run = read(TEMP / "runs/RUN-0010.json")
    scope = read(TEMP / "snapshots/scope.json")
    manifest = read(TEMP / "partitions/manifest.json")
    now = datetime.fromisoformat(frozen)
    def rows(name):
        return (json.loads(line) for line in logical_lines(ROOT, name, manifest))

    totals = {}
    fields = Counter()
    for name in logical_names(ROOT, manifest):
        totals[name] = 0
        for raw in logical_lines(ROOT, name, manifest):
            totals[name] += 1
            if b'"unknown_since_utc"' in raw and b'"review_task_id"' in raw:
                for value in objects(json.loads(raw)):
                    state = value.get("status")
                    if state in {"unknown", "unknown_review_required"} and value.get("unknown_since_utc") and value.get("review_task_id"):
                        if (now-utc(value["unknown_since_utc"])).total_seconds() >= 86400:
                            require(state == "unknown_review_required", "Overdue unknown field")
                        fields[state] += 1
    latest = latest_tasks(rows("tasks"))
    opened = sorted(k for k,v in latest.items() if v["task_state"] not in TERMINAL)
    clocks = {tid:utc(latest[tid]["deadline_at_utc"]) for tid in opened if latest[tid].get("unknown_since_utc")}
    due = {tid for tid,end in clocks.items() if end<=now}
    require(all(latest[k]["overdue"] and latest[k]["priority"] in {"high","critical","urgent"} for k in due), "Unprocessed deadline")
    cursor = {k:{f:t.get(f) for f in CURSOR_FIELDS} for k,t in sorted(latest.items())}
    dims = defaultdict(Counter)
    work_ids = set()
    for w in rows("works"):
        work_ids.add(w["work_id"])
        for k in DIMENSIONS: dims[k][w["dimension_status"][k]] += 1
    active = [a for a in rows("assessments") if a["assessment_status"]=="active"]
    eligible = [a for a in active if a["evidence_admission_status"]=="eligible"]
    themes = {f"L{i:02d}":set() for i in range(1,10)}
    for a in eligible: themes[a["limitation_id"]].add(a["work_id"])
    union=set.union(*themes.values())
    require(union <= work_ids and len(work_ids)==totals["works"], "Work or topic identity mismatch")
    queries=list(rows("queries")); current={q["query_id"]:q for q in queries if q["checkpoint_id"]==CP}
    observations=[o for o in rows("source-observations") if o["query_id"] in current]
    require(Counter(o["query_id"] for o in observations)==Counter({k:1 for k in current}),"Missing observation")
    require(set(current)=={p.stem for p in OUT.glob("Q-RUN10-*.json")},"Unregistered request receipt")
    requests=0
    for o in observations:
        path=ROOT/o["receipt_path"];raw=path.read_bytes();receipt=json.loads(raw)
        require(hashlib.sha256(raw).hexdigest()==o["receipt_sha256"] and receipt["query_id"]==o["query_id"] and
                receipt["status"]==o["status"] and receipt["external_request_count"]==o["external_request_count"]==1 and
                o["external_request_count_basis"]==REQUEST_COUNT_BASIS and not o["cache_hit"],"Unbound source receipt")
        requests+=o["external_request_count"]
    reviews=[r for r in rows("manual-reviews") if r["run_id"]==RUN]
    require(len(reviews)==len({r["review_id"] for r in reviews})==run["manual_review_items_used"] and
            all((ROOT/r["artifact"]).is_file() for r in reviews),"Review budget binding")
    require(run["scope_id"]==scope["scope_id"]==SCOPE and run["research_cutoff_at_utc"]==scope["cutoff_at_utc"] and
            requests==run["external_requests_used"]<=run["budget"]["external_requests"] and len(reviews)<=run["budget"]["manual_review_items"] and
            run["paid_spend"]==0 and (now-utc(run["started_at_utc"])).total_seconds()<=3600*run["budget"]["wall_clock_hours"],"Frozen scope or budget mismatch")
    resolved=sum(r["cited_work_id"] is not None for r in rows("reference-occurrences"))
    contexts=sum(bool(e["context_locators"]) and any(role!="unknown" for role in e["citation_roles"]) for e in rows("citation-edges"))
    maint=[read(p) for p in (TEMP/"reports").glob("RUN-0010-deadlines-*.json")]
    count={k:v for k,v in parent["counts"].items() if not k.startswith("run9_")}
    count.update(canonical_works=len(work_ids),versions=totals["versions"],people_records=totals["authors"],organizations=totals["organizations"],projects=totals["projects"],
        reference_occurrences=totals["reference-occurrences"],resolved_occurrences=resolved,unresolved_occurrences=totals["reference-occurrences"]-resolved,
        citation_edges=totals["citation-edges"],context_reviewed_edges=contexts,assessments=len(active),eligible_claims=len(eligible),
        insufficient_claims=sum(a["evidence_admission_status"]=="insufficient_evidence" for a in active),counter_evidence_claims=sum(a["counter_evidence"] for a in active),
        fully_resolved_claims=sum(a["handling_level"]=="fully_resolved" for a in active),topic_work_union=len(union),u00_works=len(work_ids-union),
        task_events=totals["tasks"],unique_tasks=len(latest),unresolved_tasks=len(opened),queries=len(queries),
        exact_query_timestamps=sum(q.get("query_time_status","exact")=="exact" for q in queries),unavailable_exact_query_timestamps=sum(q.get("query_time_status")=="unavailable_exact" for q in queries),
        manual_review_activities=totals["manual-reviews"],unknown_fields=sum(fields.values()),open_unknown_review_tasks=len(clocks),overdue_open_unknown_review_tasks=len(due),
        run10_external_requests=requests,run10_manual_reviews=len(reviews),run10_deadline_task_events=sum(m["task_events"] for m in maint),
        run10_deadline_field_transitions=sum(m["field_transitions"] for m in maint))
    count.update({k+"_works":len(v) for k,v in themes.items()})
    delta={k:v-parent["counts"][k] for k,v in count.items() if k in parent["counts"]}
    require(delta["eligible_claims"]==delta["assessments"]==delta["context_reviewed_edges"]==0,"Unexpected change to scientific admissions")
    discovered=[w for q in current.values() for w in q["new_work_ids"]]
    require(len(discovered)==len(set(discovered))==delta["canonical_works"] and set(discovered)<=work_ids,"New Work credits differ")
    frontier=read(ROOT/run["next_backward_frontier"])["worklist"]
    require(len({w["work_id"] for w in frontier})==len(frontier) and all(latest[w["task_id"]]["entity_id"]==w["work_id"] and
            latest[w["task_id"]]["task_state"] not in TERMINAL for w in frontier),"Recursive frontier disconnected")
    coverage={k:dict(denominator=len(work_ids),states=dict(v)) for k,v in dims.items()}
    coverage.update(phase_status={**parent["coverage"]["phase_status"],**{f"P{i}":"iterated_partial" for i in range(3,7)}},
        closure=dict(established=False,reason="尚有未检索的递归队列、版本歧义、身份缺口及未核实科学主张。"),
        reconciliation=dict(K=len(work_ids),T_union=len(union),U=len(work_ids-union),T_i={k:len(v) for k,v in themes.items()}),
        scientific_gates=parent["coverage"]["scientific_gates"],unknown_review=dict(field_states=dict(fields),open_tasks=len(clocks),overdue_open_tasks=len(due),
            unupgraded_overdue_tasks=0,next_deadline_utc=min((v.isoformat().replace("+00:00","Z") for v in clocks.values() if v>now),default=None)),
        task_states=dict(Counter(t["task_state"] for t in latest.values())),logical_record_counts=totals,delta_from_cp11=delta,
        source_requests=dict(by_source=dict(Counter(o["source_id"] for o in observations)),by_status=dict(Counter(o["status"] for o in observations))),
        backward_queue=dict(path=run["next_backward_frontier"],work_count=len(frontier)),
        version_review=read(TEMP/"reports/RUN-0010-cited-versions.json")["counts"],abstract_review=read(TEMP/"reports/RUN-0010-abstract-affiliation-review.json")["counts"],
        reading_policy={"allowed_materials":run["read_scope"]},synchronization={"status_at_freeze":"pending_post_commit_readback"})
    return count,coverage,cursor,opened
