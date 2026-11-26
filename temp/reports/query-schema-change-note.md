# Query null-count compatibility

The four query count fields returned_count, count_before_dedup, count_after_dedup and new_work_count permit null. query.field_states follows the existing field_states schema. Unknown counts point to a source-level query audit task with a 24-hour deadline; non-applicable counts are explicit. Known zero list results remain numeric zero. No query entity type was added.

## Checkpoint and retry-time audit correction

All 548 newly created query audit/review tasks belong to CP-0003, including tasks that reconcile historical queries. Historical query checkpoint IDs are preserved.

Query Q-RUN01-00465 returned the actual HTTP header `Retry-After: 118`. An exact retry deadline is not stored in that response event. Its query and sanitized receipt therefore retain `retry_at: null`; the receipt stores `retry_after_seconds: 118`. An earlier computed deadline based on request start was removed. The corresponding task `T-AUDIT-Q-RUN01-00465` must retain `retry_at: null` when merged into the formal task ledger.

This correction was recorded at 2026-11-26T08:31:39Z. No HTTP request was made, no original query timestamp was changed, and no core Work, Version, Assessment, or formal Task was edited by this export. The 603 query rows and 548 additions passed schema validation before export; the corrected query and additions were revalidated locally.
