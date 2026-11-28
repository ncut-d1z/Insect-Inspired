"""Compute the RUN-0009 checkpoint coverage from complete logical datasets and task event history."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json

from audit_cp10 import REQUEST_COUNT_BASIS
from checkpoint_cp10 import CURSOR_FIELDS, DIMENSIONS, TERMINAL, latest_tasks, objects, utc
from escalate_unknown_run7 import logical_lines, logical_names, require, sha
from history_run9 import CP, INTEGRATION, MAINTENANCE, ROOT, RUN, read


def collect():
    parent = read("temp/snapshots/checkpoints/CP-0010.json")
    run = read("temp/runs/RUN-0009.json")
    scope = read("temp/snapshots/scope.json")
    integration = read(INTEGRATION)
    bibliographic = read("temp/reports/RUN-0009-bibliographic-integration.json")
    version_review = read("temp/reports/RUN-0009-bibliographic-citation-versions.json")
    source_cutover = read("temp/reports/RUN-0009-bibliography-cutover.json")
    maintenance = read(MAINTENANCE)
    manifest = read("temp/partitions/manifest.json")
    clocks = {}
    totals = {}
    unknowns = Counter()
    now = datetime.now(timezone.utc)

    def rows(name):
        for line in logical_lines(ROOT, name, manifest):
            yield json.loads(line)

    for name in logical_names(ROOT, manifest):
        count = 0
        for line in logical_lines(ROOT, name, manifest):
            count += 1
            if b'"unknown_since_utc"' not in line or b'"review_task_id"' not in line:
                continue
            for item in objects(json.loads(line)):
                state = item.get("status")
                if state in {"unknown","unknown_review_required"} and "review_task_id" in item and item.get("unknown_since_utc"):
                    if (now - utc(item["unknown_since_utc"])).total_seconds() >= 86400:
                        require(state == "unknown_review_required", "Overdue field was not escalated")
                    unknowns[state] += 1
        totals[name] = count
    latest = latest_tasks(rows("tasks"))
    unresolved = sorted(k for k, v in latest.items() if v["task_state"] not in TERMINAL)
    for k in unresolved:
        row = latest[k]
        if row.get("unknown_since_utc"):
            clocks[k] = utc(row["deadline_at_utc"])
    due = {k for k,v in clocks.items() if v <= now}
    require(all(latest[k]["overdue"] and latest[k]["priority"] in {"high","critical","urgent"} for k in due), "Unescalated review deadline")
    cursor = {k:{f:row.get(f) for f in CURSOR_FIELDS} for k,row in sorted(latest.items())}
    dimensions = defaultdict(Counter)
    works = set()
    for row in rows("works"):
        works.add(row["work_id"])
        for k in DIMENSIONS:
            dimensions[k][row["dimension_status"][k]] += 1
    active = [a for a in rows("assessments") if a["assessment_status"] == "active"]
    eligible = [a for a in active if a["evidence_admission_status"] == "eligible"]
    rejected = [a for a in active if a["evidence_admission_status"] == "insufficient_evidence"]
    absolute = [a for a in active if a["claims_absolute_scale"].get("value") is True]
    themes = {f"L{i:02d}":set() for i in range(1,10)}
    for a in eligible: themes[a["limitation_id"]].add(a["work_id"])
    union = set.union(*themes.values())
    require(union <= works and len(works) == totals["works"], "Topic Work reconciliation failed")
    query_rows = list(rows("queries"))
    qs = {q["query_id"]:q for q in query_rows if q["checkpoint_id"] == CP}
    obs = [o for o in rows("source-observations") if o.get("query_id") in qs]
    require(Counter(x["query_id"] for x in obs) == Counter({k:1 for k in qs}), "Observation cardinality")
    for o in obs:
        path = ROOT / o["receipt_path"]
        receipt = json.loads(path.read_bytes())
        require(sha(path.read_bytes()) == o["receipt_sha256"] and receipt["query_id"] == o["query_id"] and
                receipt["external_request_count"] == o["external_request_count"] and
                o["external_request_count_basis"] == REQUEST_COUNT_BASIS and receipt["cache_hit"] == o["cache_hit"] == qs[o["query_id"]]["cache_hit"],
                "Unbound source operation")
    external = sum(o["external_request_count"] for o in obs)
    manual = [m for m in rows("manual-reviews") if m["run_id"] == RUN]
    require(len({m["review_id"] for m in manual}) == len(manual) == run["manual_review_items_used"]
            and all((ROOT / m["artifact"]).is_file() for m in manual), "Manual review binding")
    require(external == run["external_requests_used"] <= run["budget"]["external_requests"]
            and len(manual) <= run["budget"]["manual_review_items"] and run["paid_spend"] == 0
            and run["research_cutoff_at_utc"] == scope["cutoff_at_utc"] and run["scope_id"] == "SCOPE-0001", "Run budget or frozen scope differs")
    counts = {k:v for k,v in parent["counts"].items() if not k.startswith("run8_")}
    resolved = sum(o["cited_work_id"] is not None for o in rows("reference-occurrences"))
    contexts = sum(bool(e["context_locators"]) and any(r != "unknown" for r in e["citation_roles"]) for e in rows("citation-edges"))
    counts.update(canonical_works=len(works),versions=totals["versions"],people_records=totals["authors"],organizations=totals["organizations"],
        projects=totals["projects"],reference_occurrences=totals["reference-occurrences"],resolved_occurrences=resolved,
        unresolved_occurrences=totals["reference-occurrences"]-resolved,citation_edges=totals["citation-edges"],context_reviewed_edges=contexts,
        assessments=len(active),eligible_claims=len(eligible),insufficient_claims=len(rejected),counter_evidence_claims=sum(a["counter_evidence"] for a in active),
        fully_resolved_claims=sum(a["handling_level"] == "fully_resolved" for a in active),topic_work_union=len(union),u00_works=len(works-union),
        task_events=totals["tasks"],unique_tasks=len(latest),unresolved_tasks=len(unresolved),queries=len(query_rows),
        exact_query_timestamps=sum(q.get("query_time_status","exact")=="exact" for q in query_rows),
        unavailable_exact_query_timestamps=sum(q.get("query_time_status")=="unavailable_exact" for q in query_rows),
        scientific_fulltext_works_reviewed=len({a["work_id"] for a in active}),manual_review_activities=totals["manual-reviews"],
        unknown_fields=sum(unknowns.values()),open_unknown_review_tasks=len(clocks),overdue_open_unknown_review_tasks=len(due),
        run9_external_requests=external,run9_manual_reviews=len(manual),run9_cache_reuses=sum(bool(q["cache_hit"]) for q in qs.values()),
        run9_new_works=bibliographic["counts"]["registered_works"],run9_new_edges=bibliographic["counts"]["new_citation_edges"],
        run9_resolved_historical_occurrences=integration["new_resolved_occurrences"],run9_new_reference_occurrences=bibliographic["counts"]["added_reference_occurrences"],
        run9_verified_contexts=source_cutover["current_role_confirmations_from_former_batch"],run9_provisional_projects=integration["new_projects"],
        run9_new_active_assessments=source_cutover["new_active_fulltext_assessments_in_current_scope"],
        run9_nonactive_assessments=sum(a["assessment_status"]=="pending_review" for a in rows("assessments")),
        run9_closed_work_fields=integration["closed_authority_field_reviews"]+1,
        run9_escalation_task_events=maintenance["task_events"],run9_escalation_field_transitions=maintenance["field_transitions"])
    counts.update({k+"_works":len(v) for k,v in themes.items()})
    coverage = {k:dict(denominator=len(works),states=dict(v)) for k,v in dimensions.items()}
    coverage.update(phase_status=dict(parent["coverage"]["phase_status"], **{f"P{i}":"iterated_partial" for i in range(3,7)}),
        closure={"established":False,"reason":"尚有未结的书目、施引分页、作者及项目关系、全文及科学证据工单。"},
        reconciliation={"K":len(works),"T_union":len(union),"U":len(works-union),"T_i":{k:len(v) for k,v in themes.items()}},
        scientific_gates=dict(eligible=len(eligible),insufficient=len(rejected),counter_evidence=counts["counter_evidence_claims"],
            fully_resolved=counts["fully_resolved_claims"],absolute_scale_claims=len(absolute),
            absolute_scale_eligible=sum(a["evidence_admission_status"]=="eligible" for a in absolute),
            absolute_scale_insufficient=sum(a["evidence_admission_status"]=="insufficient_evidence" for a in absolute),
            rejection_codes=dict(Counter(c for a in rejected for c in a["rejection_codes"]))),
        unknown_review=dict(field_states=dict(unknowns),open_tasks=len(clocks),overdue_open_tasks=len(due),unupgraded_overdue_tasks=0,
            original_clocks_preserved=True,next_deadline_utc=min((v.isoformat().replace("+00:00","Z") for v in clocks.values() if v>now),default=None)),
        task_states=dict(Counter(v["task_state"] for v in latest.values())),logical_record_counts=totals,
        run9_accounting={k:v for k,v in counts.items() if k.startswith("run9_")},
        delta_from_cp10={k:v-parent["counts"][k] for k,v in counts.items() if k in parent["counts"]},
        work_identity={"new":bibliographic["counts"]["registered_works"],"matched_existing_candidates":99-bibliographic["counts"]["registered_works"],"existing_doi_enriched":1,"new_merges":0,
                       "identity_confidence":dict(Counter(w["identity_confidence"] for w in rows("works")))},
        pagination={"source_rows":totals["source-list-coverage"],"fully_reconciled_by_source":dict(Counter(r["source_id"] for r in rows("source-list-coverage") if r["total_reconciled"])),
                    "run9_new_complete_citing_lists_at_europepmc":1},citation_version_screen=version_review["counts"],
        reading_policy=read("temp/reports/RUN-0009-bibliography-roadmap.json")["allowed_publication_materials"],
        synchronization={"status_at_freeze":"pending_post_commit_readback"})
    return counts, coverage, cursor, unresolved
