#!/usr/bin/env python3
"""Read-only validation of an Insect-Inspired logical snapshot.

No network requests; no mutation of canonical data.  The sole output is the
requested private JSON report.  JSONL is always read through storage.read_logical
so the same checks apply before and after transport partitioning.  Validators and
foreign-key indices are constructed once, not per record.

Usage: python p3p6_work/audit_run.py --out p3p6_work/audit-run.json
Exit codes: 0 coherent/pass; 1 findings; 2 concurrent input mutation or fatal read.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker
from storage import read_logical
from partitioned_research_json import load_view, view_files
from partitioned_checkpoint import checkpoint_files, load_checkpoint

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
SUBSTANTIVE = {'direct_study', 'indirect_mitigation', 'foundational_support',
               'engineering_application', 'independent_progress', 'counter_evidence'}
UNKNOWN = {'unknown', 'unknown_review_required'}
FIXED = {'S01': ('S15', 'contains_publication'),
         'S15': ('S01', 'included_in_thesis'),
         'S02': ('S17', 'preliminary_of'), 'S17': ('S02', 'expanded_from'),
         'S19': ('S20', 'related_report'), 'S20': ('S19', 'related_report')}
PRIMARY = {'work': 'work_id', 'version': 'version_id', 'upload': 'upload_id',
           'assessment': 'assessment_id', 'person': 'person_id',
           'organization': 'org_id', 'project': 'project_id', 'alias': 'alias_id',
           'reference_occurrence': 'occurrence_id', 'citation_edge': 'edge_id',
           'query': 'query_id', 'task': 'task_id', 'work_relation': 'relation_id',
           'rejection': 'rejection_id', 'cascade_event': 'cascade_event_id'}
MATRIX_HEADER = ('scope_id,checkpoint_id,schema_version,assessment_id,work_id,work_key,'
    'limitation_id,claim_id,claim_type,evidence_route,relation_type,handling_level,'
    'evidence_level,evidence_kind,evidence_admission_status,rejection_codes,conditions,'
    'dataset_records,baseline_records,condition_levels,metric_records,proof_record,'
    'claims_absolute_scale,scale_prior_details,observability_argument_locator,effect,'
    'remaining_limitations,counter_evidence,counter_evidence_types,evidence_locator,'
    'provenance_upload_ids,provenance_version_ids,verification_status,reviewer,date').split(',')
IMPLICATION_HEADER = ('scope_id,checkpoint_id,schema_version,assessment_id,work_key,'
    'limitation_id,evidence_route,evidence_admission_status,biological_implications,'
    'engineering_implications,conditions,remaining_limitations,statement_basis,'
    'evidence_locator').split(',')


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        out = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return out.astimezone(timezone.utc) if out.tzinfo else None
    except (ValueError, TypeError):
        return None


def normalize_doi(value):
    if not isinstance(value, str):
        return value
    value = unquote(value.strip()).lower()
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def walk(value):
    """Yield dictionaries plus paths; O(number of JSON nodes), no recursion limit."""
    stack = [('', value)]
    while stack:
        path, obj = stack.pop()
        if isinstance(obj, dict):
            yield path, obj
            stack.extend((path + '/' + str(k), v) for k, v in obj.items()
                         if isinstance(v, (dict, list)))
        elif isinstance(obj, list):
            stack.extend((path + '/' + str(i), v) for i, v in enumerate(obj)
                         if isinstance(v, (dict, list)))


class HTMLTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = defaultdict(list)
        self.table_ids = []
        self.ids = Counter()
        self.stack = []
        self.row_links = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids[a['id']] += 1
        if tag == 'table':
            self.stack.append(a.get('id'))
            self.table_ids.append(a.get('id'))
        if tag == 'tr' and a.get('data-key') and self.stack:
            self.tables[self.stack[-1]].append(a['data-key'])
        if tag == 'script':
            self.scripts += 1

    def handle_endtag(self, tag):
        if tag == 'table' and self.stack:
            self.stack.pop()


class Audit:
    def __init__(self, repo, out, now, max_examples=20):
        self.repo, self.temp, self.out = repo, repo / 'temp', out
        self.now, self.max_examples = now, max_examples
        self.started = time.monotonic()
        self.counts = Counter()
        self.findings = {'error': {}, 'warning': {}}
        self.datasets = {}
        self.indices = {}
        self.watched = {}
        self.validators = {}
        self.stats = {}
        self.entity_files = {}
        self.sources = {}
        self.active = {}
        self.schema = {}
        self.scope = {}
        self.checkpoints = {}
        self.extra_schemas = {'project-relations.jsonl': 'entity_export_relation'}

    def note(self, category, message, entity=None, path=None, severity='error'):
        f = self.findings[severity].setdefault(category, {'count': 0, 'examples': []})
        f['count'] += 1
        if len(f['examples']) < self.max_examples:
            e = {'message': str(message)[:900]}
            if entity is not None:
                e['entity'] = str(entity)
            if path:
                e['path'] = str(path)
            f['examples'].append(e)

    def require(self, condition, category, message, entity=None, path=None):
        self.counts['assertions'] += 1
        if not condition:
            self.note(category, message, entity, path)
        return bool(condition)

    def watch(self, path):
        path = Path(path)
        if path not in self.watched:
            try:
                s = path.stat()
                self.watched[path] = (s.st_size, s.st_mtime_ns)
            except FileNotFoundError:
                self.watched[path] = None

    def load_json(self, path, kind=None):
        self.watch(path)
        try:
            if kind in {'research_entities', 'citation_graph'}:
                for part in view_files(path):
                    self.watch(part)
                value = load_view(path)
            elif kind == 'checkpoint':
                public = json.loads(Path(path).read_bytes())
                for part in checkpoint_files(path, public):
                    self.watch(part)
                value = load_checkpoint(path, public)
            else:
                value = json.loads(Path(path).read_text(encoding='utf-8'))
        except Exception as e:
            self.note('read_error', f'{type(e).__name__}: {e}', path=path)
            return None
        if kind:
            self.validate(kind, value, str(path))
        return value

    def validator(self, kind):
        if kind not in self.validators:
            if kind not in self.schema.get('$defs', {}):
                self.note('missing_entity_schema', kind)
                return None
            self.validators[kind] = Draft202012Validator(
                {'$schema': self.schema['$schema'], '$ref': '#/$defs/' + kind,
                 '$defs': self.schema['$defs']}, format_checker=FormatChecker())
        return self.validators[kind]

    def validate(self, kind, value, entity):
        validator = self.validator(kind)
        if validator is None:
            return
        self.counts['schema_records'] += 1
        for e in validator.iter_errors(value):
            self.note('schema.' + kind, e.message, entity,
                      '/'.join(map(str, e.absolute_path)))

    def index(self, kind, records, field=None, permit_events=False):
        field = field or PRIMARY[kind]
        index = {}
        first_clock = {}
        last_seq = {}
        for r in records:
            key = r.get(field)
            if not key:
                self.note('missing_primary_key', field, kind)
                continue
            if key in index and not permit_events:
                self.note('duplicate_primary_key', field, key)
            if permit_events:
                seq = r.get('event_sequence', 0)
                if key in last_seq and seq <= last_seq[key]:
                    self.note('task_event_order', 'event_sequence must strictly increase', key)
                last_seq[key] = seq
                clock = r.get('unknown_since_utc')
                if clock:
                    if key in first_clock and utc(clock) != utc(first_clock[key]):
                        self.note('unknown_clock_reset', 'Task event changed original unknown clock', key)
                    first_clock.setdefault(key, clock)
                if key in index and seq < index[key].get('event_sequence', 0):
                    continue
            index[key] = r
        self.indices[kind] = index
        return index

    def fk(self, kind, key, entity, field, nullable=False):
        if key is None and nullable:
            return True
        return self.require(key in self.indices.get(kind, {}), 'foreign_key.' + kind,
                            f'{field}={key!r} has no canonical target', entity)

    def same_set(self, actual, expected, category, entity=None):
        missing, extra = set(expected) - set(actual), set(actual) - set(expected)
        if missing or extra:
            self.note(category, {'missing_count': len(missing), 'extra_count': len(extra),
                       'missing_examples': sorted(map(str, missing))[:10],
                       'extra_examples': sorted(map(str, extra))[:10]}, entity)
        self.counts['set_reconciliations'] += 1

    def check_cycles(self, mapping, category):
        done = set()
        for start in mapping:
            if start in done:
                continue
            chain, local, current = [], set(), start
            while current is not None and current in mapping and current not in done:
                if current in local:
                    self.note(category, 'Cycle in directed parent/duplicate chain', current)
                    break
                chain.append(current)
                local.add(current)
                current = mapping[current]
            done.update(chain)

    def load(self):
        self.watch(self.temp)
        self.watch(self.temp / 'snapshots/checkpoints')
        self.schema = self.load_json(self.temp / 'schema.json') or {}
        if not self.schema.get('$defs'):
            raise RuntimeError('Canonical schema missing or invalid')
        Draft202012Validator.check_schema(self.schema)
        self.scope = self.load_json(self.temp / 'snapshots/scope.json', 'scope') or {}
        self.sources = {s['source_id']: s for s in self.scope.get('sources', [])}
        # This is a reserved specification provenance ID, not an API provider.
        self.allowed_sources = set(self.sources) | {'SPEC-1.1'}
        self.entity_files = self.schema.get('x-entity-files', {})
        manifest_path = self.temp / 'partitions/manifest.json'
        self.watch(manifest_path)
        self.partition_manifest = self.load_json(manifest_path) if manifest_path.exists() else None
        physical_parts = (self.partition_manifest or {}).get('datasets', {})
        names = set(self.entity_files)
        names |= {p.name for p in self.temp.glob('*.jsonl')}
        names |= set(physical_parts)
        for name in sorted(names):
            self.watch(self.temp / name)
            for part in physical_parts.get(name, {}).get('parts', []):
                self.watch(self.temp / part['path'])
            try:
                records = read_logical(name, base=self.temp)
            except Exception as e:
                self.note('logical_read_error', f'{type(e).__name__}: {e}', name)
                records = []
            self.datasets[name] = records
            self.stats[name] = len(records)
            kind = self.entity_files.get(name) or self.extra_schemas.get(name)
            if kind:
                for i, r in enumerate(records):
                    label = r.get(PRIMARY.get(kind, ''), f'{name}:{i+1}')
                    self.validate(kind, r, label)
            elif records:
                self.note('unregistered_auxiliary_schema',
                          'Logical dataset read; no registered entity schema. Generic FK/source checks still apply.',
                          name, severity='warning')
            if kind in PRIMARY:
                self.index(kind, records, permit_events=(kind == 'task'))
            print(f'loaded {name}: {len(records)}', flush=True)
        self.indices['work_key'] = self.index('work_key', self.datasets.get('works.jsonl', []), 'work_key')
        self.active = {k: a for k, a in self.indices.get('assessment', {}).items()
                       if a.get('assessment_status') == 'active'}
        for p in sorted((self.temp / 'snapshots/checkpoints').glob('*.json')):
            cp = self.load_json(p, 'checkpoint')
            if cp:
                self.checkpoints[cp['checkpoint_id']] = cp
        self.scope_ids = {self.scope.get('scope_id')}
        for p in sorted((self.temp / 'snapshots/scopes').glob('*.json')):
            s = self.load_json(p, 'scope')
            if s:
                self.scope_ids.add(s.get('scope_id'))

    def topology(self):
        works, versions, uploads = (self.indices.get(k, {}) for k in ('work', 'version', 'upload'))
        by_work = Counter()
        file_index = {}
        for vid, v in versions.items():
            self.fk('work', v.get('work_id'), vid, 'work_id')
            by_work[v.get('work_id')] += 1
            records = v.get('file_records', [])
            file_index[vid] = {x.get('sha256'): x for x in records}
            self.require(len(file_index[vid]) == len(records), 'version_duplicate_file_hash', vid, vid)
            if v.get('version_materialization') == 'bibliographic_only':
                self.require(not records, 'bibliographic_version_has_file', 'Bibliographic-only Version has files', vid)
            for related in v.get('related_version_ids', []):
                self.fk('version', related, vid, 'related_version_ids')
            for f in records:
                self.file_semantics(f, vid)
        doi_map = defaultdict(list)
        for wid, w in works.items():
            self.require(by_work[wid] >= 1, 'work_without_version', 'Work requires at least one Version', wid)
            self.require(bool(re.fullmatch(r'[A-Za-z0-9_:.+\-]+', str(w.get('work_key', '')))),
                         'work_key_ascii', 'Work key must be stable ASCII', wid)
            doi = w.get('doi')
            if doi:
                self.require(doi == normalize_doi(doi), 'doi_normalization', doi, wid)
                doi_map[doi].append(wid)
            if w.get('identifiers', {}).get('doi'):
                self.require(w['identifiers']['doi'] == doi, 'work_doi_conflict', 'doi != identifiers.doi', wid)
            for person in w.get('authors', []) + w.get('editors', []):
                self.fk('person', person.get('person_id'), wid, 'authors/editors.person_id')
                for org in person.get('organization_ids', []):
                    self.fk('organization', org, wid, 'organization_ids')
        for doi, ids in doi_map.items():
            if len(ids) > 1:
                self.note('duplicate_canonical_doi', f'{doi}: {ids}', doi)
        manifest = self.datasets.get('seed-manifest.jsonl', [])
        seed_rows = [r for r in manifest if r.get('record_type') == 'seed_mapping']
        seeds = self.index('seed', seed_rows, 'seed_id')
        self.same_set(seeds, {f'S{i:02}' for i in range(1, 21)}, 'seed_set')
        duplicates = [r for r in manifest if r.get('record_type') == 'duplicate_upload']
        duplicate_map = self.index('duplicate_upload', duplicates, 'upload_id')
        all_uploads = dict(uploads)
        for uid, u in duplicate_map.items():
            self.require(uid not in uploads, 'duplicate_upload_in_canonical_dataset',
                         'Deduplicated Upload must stay in manifest audit layer', uid)
            all_uploads[uid] = u
            self.require(u.get('seed_id') is None, 'duplicate_has_seed_id', 'Duplicate must not occupy S index', uid)
        self.all_uploads = all_uploads
        for uid, u in all_uploads.items():
            self.fk('work', u.get('work_id'), uid, 'work_id')
            if self.fk('version', u.get('version_id'), uid, 'version_id'):
                v = versions[u['version_id']]
                self.require(v.get('work_id') == u.get('work_id'), 'upload_work_version_mismatch',
                             'Upload and Version must have the same Work', uid)
                f = file_index[u['version_id']].get(u.get('sha256'))
                self.require(f is not None, 'upload_file_missing_from_version', 'SHA-256 absent from Version.file_records', uid)
                if f:
                    self.require(f.get('pages') == u.get('pages'), 'upload_version_page_mismatch', 'Page counts differ', uid)
            self.file_semantics(u, uid)
            target = u.get('duplicate_of_upload_id')
            if target:
                self.require(target in all_uploads and target != uid, 'duplicate_upload_target', target, uid)
                if target in all_uploads:
                    for field in ('work_id', 'version_id', 'sha256'):
                        self.require(u.get(field) == all_uploads[target].get(field),
                                     'duplicate_upload_identity_mismatch', field, uid)
            if uid in uploads:
                self.require(not target, 'canonical_upload_is_duplicate', target, uid)
                if u.get('discovery_route') != 'seed':
                    self.require(bool(u.get('discovery_path')) or any(s.get('upload_id') == uid for s in seed_rows),
                                 'untraced_nonseed_upload', 'No seed mapping or discovery path', uid)
        self.check_cycles({k: v.get('duplicate_of_upload_id') for k, v in all_uploads.items()}, 'upload_cycle')
        relations = self.indices.get('work_relation', {})
        pair_set = {(r.get('from_work_id'), r.get('to_work_id'), r.get('relation_type'),
                     r.get('inverse_relation_type')) for r in relations.values()}
        for sid, s in seeds.items():
            expected = FIXED.get(sid, (None, None))
            self.require((s.get('target_related_id'), s.get('seed_relation_type')) == expected,
                         'seed_fixed_relation', f'Expected {expected}', sid)
            for kind, field in [('work', 'work_id'), ('version', 'version_id'), ('upload', 'upload_id')]:
                self.fk(kind, s.get(field), sid, field)
            if s.get('upload_id') in uploads:
                u = uploads[s['upload_id']]
                self.require(all(s.get(f) == u.get(f) for f in ['work_id', 'version_id']),
                             'seed_mapping_mismatch', 'Seed and Upload topology differs', sid)
            if s.get('work_id') in works:
                self.require(sid in works[s['work_id']].get('seed_ids', []), 'work_missing_seed_id', sid, s['work_id'])
        for a, b in [('S01', 'S15'), ('S02', 'S17'), ('S19', 'S20')]:
            if a in seeds and b in seeds:
                wa, wb = seeds[a]['work_id'], seeds[b]['work_id']
                self.require(wa != wb, 'fixed_pair_merged', f'{a}/{b} require distinct Work identities', a)
                forward = (wa, wb, FIXED[a][1], FIXED[b][1])
                reverse = (wb, wa, FIXED[b][1], FIXED[a][1])
                self.require(forward in pair_set or reverse in pair_set, 'missing_fixed_work_relation', f'{a}/{b}', a)
        for r in relations.values():
            self.fk('work', r.get('from_work_id'), r['relation_id'], 'from_work_id')
            self.fk('work', r.get('to_work_id'), r['relation_id'], 'to_work_id')
        self.stats.update({'canonical_works': len(works), 'versions': len(versions),
                           'canonical_uploads': len(uploads), 'duplicate_uploads': len(duplicates),
                           'unique_file_hashes': len({f for v in file_index.values() for f in v})})

    def file_semantics(self, f, entity):
        pages, media = f.get('pages'), f.get('media_type')
        if pages is None:
            state = f.get('field_states', {}).get('pages', {})
            self.require(media in {'application/xml', 'text/html', 'application/json', 'text/plain'},
                         'null_pages_media_type', 'Page-less record requires an explicit non-PDF media type', entity)
            self.require(state.get('status') == 'not_applicable' and bool(state.get('reason')),
                         'null_pages_semantics', 'Page-less formats require not_applicable pages with reason', entity)
        if media == 'application/xml':
            self.require(pages is None, 'xml_fake_page_count', 'XML must not receive invented PDF pages', entity)
        if media == 'application/pdf':
            self.require(isinstance(pages, int) and not isinstance(pages, bool) and pages >= 1,
                         'pdf_page_count', 'PDF requires real positive page count', entity)

    def references(self):
        refs = self.indices.get('reference_occurrence', {})
        versions = self.indices.get('version', {})
        keys = self.indices['work_key']
        for oid, r in refs.items():
            self.fk('work', r.get('citing_work_id'), oid, 'citing_work_id')
            self.fk('work', r.get('cited_work_id'), oid, 'cited_work_id', nullable=True)
            if self.fk('version', r.get('version_id'), oid, 'version_id'):
                self.require(versions[r['version_id']]['work_id'] == r.get('citing_work_id'),
                             'occurrence_version_owner', 'Reference Version must belong to citing Work', oid)
            # candidate_ids can be unresolved DOIs/provider IDs; they are not Work foreign keys.
            if r.get('cited_work_id') is None:
                self.require(bool(r.get('failure_reason')), 'unresolved_occurrence_without_reason',
                             'Unresolved endpoint requires failure_reason', oid)
        pairs = {}
        for eid, e in self.indices.get('citation_edge', {}).items():
            a, b = e.get('citing_key'), e.get('cited_key')
            self.fk('work_key', a, eid, 'citing_key')
            self.fk('work_key', b, eid, 'cited_key')
            pair = (a, b)
            if pair in pairs:
                self.note('duplicate_citation_edge_pair', f'Also {pairs[pair]}', eid)
            pairs[pair] = eid
            self.require(bool(e.get('occurrence_ids')) or bool(e.get('discovery_sources')),
                         'citation_without_evidence', 'Actual cite needs occurrence or index provenance', eid)
            for oid in e.get('occurrence_ids', []):
                if self.fk('reference_occurrence', oid, eid, 'occurrence_ids') and a in keys and b in keys:
                    r = refs[oid]
                    self.require((r.get('citing_work_id'), r.get('cited_work_id')) ==
                                 (keys[a]['work_id'], keys[b]['work_id']),
                                 'edge_occurrence_endpoints', 'Occurrence endpoints differ from citation edge', eid)
            if e.get('discovery_sources') and all(s.get('source_id') == 'SPEC-1.1' for s in e['discovery_sources']):
                self.note('spec_relation_as_citation', 'Normative seed relation is not scientific citation evidence', eid)

    def subjects(self):
        for pid, p in self.indices.get('person', {}).items():
            for affiliation in p.get('affiliation_history', []):
                self.fk('organization', affiliation.get('org_id'), pid, 'affiliation_history.org_id')
                if affiliation.get('work_id'):
                    self.fk('work', affiliation['work_id'], pid, 'affiliation_history.work_id')
        orgs = self.indices.get('organization', {})
        parent_map = {}
        for oid, o in orgs.items():
            parent = o.get('parent_org_id')
            if parent:
                self.fk('organization', parent, oid, 'parent_org_id')
            parent_map[oid] = parent
        self.check_cycles(parent_map, 'organization_parent_cycle')
        for pid, p in self.indices.get('project', {}).items():
            for field, kind in [('org_ids', 'organization'), ('person_ids', 'person'), ('output_work_ids', 'work')]:
                for key in p.get(field, []):
                    self.fk(kind, key, pid, field)
        for a in self.indices.get('alias', {}).values():
            self.fk(a.get('entity_type'), a.get('target_id'), a['alias_id'], 'target_id')
        for c in self.indices.get('cascade_event', {}).values():
            cid = c['cascade_event_id']
            self.require(c.get('trigger_upload_id') in self.all_uploads, 'cascade_trigger_missing', c.get('trigger_upload_id'), cid)
            self.fk('upload', c.get('canonical_upload_id'), cid, 'canonical_upload_id')
            for field, kind in [('affected_work_ids', 'work'), ('affected_version_ids', 'version'),
                                ('affected_assessment_ids', 'assessment'), ('discarded_assessment_ids', 'assessment'),
                                ('pending_review_ids', 'assessment'), ('affected_edges', 'citation_edge')]:
                for key in c.get(field, []):
                    self.fk(kind, key, cid, field)
            for old, new in c.get('merged_assessment_map', {}).items():
                self.fk('assessment', old, cid, 'merged_assessment_map')
                self.fk('assessment', new, cid, 'merged_assessment_map')

    def source_check(self, source_id, entity, path):
        if source_id is not None:
            self.require(source_id in self.allowed_sources, 'source_id_not_admitted',
                         f'{source_id!r} absent from scope source whitelist', entity, path)

    def locator_check(self, loc, entity, path):
        vid, uid = loc.get('version_id'), loc.get('upload_id')
        if vid:
            self.fk('version', vid, entity, path + '.version_id')
        if uid:
            self.require(uid in self.all_uploads, 'locator_upload_fk', uid, entity, path)
            if uid in self.all_uploads:
                u = self.all_uploads[uid]
                if vid:
                    self.require(u['version_id'] == vid, 'locator_upload_version_mismatch', vid, entity, path)
                if loc.get('page') is not None and u.get('media_type') == 'application/xml':
                    self.note('xml_locator_fake_page', 'XML locator must use section/paragraph/figure, not invented page', entity, path)
                # Only bound unambiguously PDF-labelled locators, never publisher page numbers.
                if isinstance(u.get('pages'), int) and loc.get('page') is not None and 'pdf' in str(loc.get('evidence_note', '')).lower():
                    page = loc['page']
                    if isinstance(page, int):
                        self.require(1 <= page <= u['pages'], 'locator_pdf_page_bounds', page, entity, path)
                    elif re.fullmatch(r'[\d\s,–—\-;]+', str(page)):
                        nums = [int(n) for n in re.findall(r'\d+', str(page))]
                        self.require(all(1 <= n <= u['pages'] for n in nums), 'locator_pdf_page_bounds', page, entity, path)
        self.require(any(loc.get(k) is not None and loc.get(k) != ''
                         for k in ['page', 'section', 'figure', 'equation', 'table', 'paragraph', 'url']),
                     'locator_without_position', 'Locator needs a page/section/figure/equation/table/paragraph/URL', entity, path)

    def unknown_check(self, state, entity, path):
        tid, since = state.get('review_task_id'), utc(state.get('unknown_since_utc'))
        task = self.indices.get('task', {}).get(tid)
        self.require(task is not None, 'unknown_missing_review_task', tid, entity, path)
        self.require(since is not None, 'unknown_missing_original_clock', state.get('unknown_since_utc'), entity, path)
        if task:
            self.require(task.get('task_state') not in TERMINAL, 'unknown_with_closed_task', tid, entity, path)
            if entity in self.indices.get('assessment', {}):
                self.require(task.get('entity_id') == entity or task.get('assessment_id') == entity,
                             'unknown_review_task_assessment_owner',
                             'Review task must identify the Assessment containing this unknown field', entity, path)
                task_path = str(task.get('field_path') or '').replace('/', '.').strip('.')
                state_path = path.replace('/', '.').strip('.')
                # Top-level species/motion/environment/scale are exact projections
                # of conditions and intentionally share their original task.
                allowed_paths = {state_path}
                if state_path in {'species', 'motion_type', 'environment', 'scale'}:
                    allowed_paths.add('conditions.' + state_path)
                self.require(task_path in allowed_paths, 'unknown_review_task_field_path',
                             f'{task_path!r} does not identify {state_path!r}', entity, path)
            if since:
                self.require(utc(task.get('unknown_since_utc')) == since, 'unknown_task_clock_mismatch', tid, entity, path)
                deadline = utc(task.get('deadline_at_utc'))
                self.require(deadline is not None and since <= deadline <= since + timedelta(hours=24),
                             'unknown_invalid_deadline', task.get('deadline_at_utc'), entity, path)
                if self.now >= since + timedelta(hours=24):
                    self.require(state.get('status') == 'unknown_review_required',
                                 'unknown_overdue_not_escalated', tid, entity, path)
                    self.require(task.get('overdue') is True and task.get('priority') in {'high', 'urgent', 'critical'},
                                 'unknown_overdue_task_not_escalated', tid, entity, path)
        self.counts['unknown_fields'] += 1

    def generic(self):
        for name, records in self.datasets.items():
            kind = self.entity_files.get(name) or self.extra_schemas.get(name)
            for i, r in enumerate(records):
                entity = r.get(PRIMARY.get(kind, ''), f'{name}:{i+1}')
                if kind == 'seed_manifest_record':
                    entity = r.get('seed_id') or r.get('upload_id') or entity
                for path, obj in walk(r):
                    if 'source_id' in obj:
                        self.source_check(obj.get('source_id'), entity, path)
                    if 'source_id' in obj and 'evidence_note' in obj:
                        self.locator_check(obj, entity, path)
                    if obj.get('status') in UNKNOWN and ('unknown_since_utc' in obj or 'review_task_id' in obj):
                        self.unknown_check(obj, entity, path)
                    if obj.get('status') in {'not_reported', 'not_applicable'} and 'unknown_since_utc' in obj:
                        self.require(bool(obj.get('reason')), 'missing_null_reason', obj.get('status'), entity, path)
                        if obj.get('status') == 'not_reported':
                            self.require(bool(obj.get('evidence_locator')), 'not_reported_without_checked_source',
                                         'not_reported must locate checked original evidence', entity, path)
                    if 'quantity' in obj and 'min' in obj and 'max' in obj:
                        low, high = obj.get('min'), obj.get('max')
                        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                            self.require(math.isfinite(low) and math.isfinite(high) and low <= high,
                                         'invalid_quantity_range', f'{low}..{high}', entity, path)
                    for k, value in obj.items():
                        if isinstance(value, float) and not math.isfinite(value):
                            self.note('nonfinite_json_number', k, entity, path)
                    if isinstance(obj.get('version'), str) and obj['version'].startswith('V-') and 'source_id' in obj:
                        self.fk('version', obj['version'], entity, path + '.version')
                if kind in {'query', 'task', 'work_relation', 'rejection', 'cascade_event'}:
                    self.require(r.get('scope_id') in self.scope_ids, 'unknown_scope', r.get('scope_id'), entity)

    def task_queries(self):
        tasks, queries = self.indices.get('task', {}), self.indices.get('query', {})
        task_types = {'seed': 'seed', 'work': 'work', 'version': 'version', 'upload': 'upload',
                      'assessment': 'assessment', 'person': 'person', 'organization': 'organization', 'project': 'project'}
        for tid, t in tasks.items():
            kind = task_types.get(t.get('entity_type'))
            if kind:
                self.fk(kind, t.get('entity_id'), tid, 'entity_id')
            elif t.get('entity_type') == 'source':
                self.source_check(t.get('entity_id'), tid, 'entity_id')
            elif t.get('entity_type') == 'scope':
                self.require(t.get('entity_id') in self.scope_ids, 'task_scope_fk', t.get('entity_id'), tid)
            elif t.get('entity_type') == 'checkpoint':
                self.require(t.get('entity_id') in self.checkpoints, 'task_entity_checkpoint_fk', t.get('entity_id'), tid)
            for dep in t.get('dependency_ids', []):
                self.fk('task', dep, tid, 'dependency_ids')
            for q in t.get('query_ids', []):
                self.fk('query', q, tid, 'query_ids')
            if t.get('assessment_id'):
                self.fk('assessment', t['assessment_id'], tid, 'assessment_id')
            if t.get('version_id'):
                self.fk('version', t['version_id'], tid, 'version_id')
            if t.get('checkpoint_id'):
                self.require(t['checkpoint_id'] in self.checkpoints, 'task_checkpoint_fk', t['checkpoint_id'], tid)
            if t.get('unknown_since_utc') and t.get('task_state') not in TERMINAL:
                since, deadline = utc(t['unknown_since_utc']), utc(t.get('deadline_at_utc'))
                self.require(since is not None and deadline is not None and since <= deadline <= since + timedelta(hours=24),
                             'unknown_task_invalid_deadline', t.get('deadline_at_utc'), tid)
        for qid, q in queries.items():
            self.fk('task', q.get('task_id'), qid, 'task_id')
            if q.get('checkpoint_id'):
                self.require(q['checkpoint_id'] in self.checkpoints, 'query_checkpoint_fk', q['checkpoint_id'], qid)
            if q.get('reused_query_id'):
                self.fk('query', q['reused_query_id'], qid, 'reused_query_id')
            new_work_ids = q.get('new_work_ids', [])
            for wid in new_work_ids:
                self.fk('work', wid, qid, 'new_work_ids')
            new_work_count = q.get('new_work_count')
            if new_work_count is not None:
                self.require(new_work_count == len(set(new_work_ids)),
                             'query_new_work_count', 'new_work_count differs from unique IDs', qid)
            else:
                count_state = q.get('field_states', {}).get('new_work_count', {})
                self.require(count_state.get('status') in
                             {'unknown', 'unknown_review_required', 'not_reported', 'not_applicable'}
                             and bool(count_state.get('reason')),
                             'query_null_new_work_count_state',
                             'Unavailable count requires an explicit non-present field state and reason; null is not zero', qid)
                # Nonempty canonical IDs already determine an exact unique count;
                # do not let nullable legacy query metadata conceal that mismatch.
                self.require(not new_work_ids, 'query_missing_derived_new_work_count',
                             'Nonempty new_work_ids require their known numeric unique count', qid)
            if q.get('page_complete') and q.get('status') not in {'success', 'cache_hit', 'verified_complete'}:
                # Exact provider status vocabulary is validated by schema; this is an audit warning only.
                self.note('query_page_complete_status', str(q.get('status')), qid, severity='warning')
        self.stats['latest_tasks'] = len(tasks)
        self.stats['task_states'] = dict(Counter(t.get('task_state') for t in tasks.values()))
        self.stats['unresolved_tasks'] = sum(t.get('task_state') not in TERMINAL for t in tasks.values())

    def manual_assessment_baselines(self):
        # A portable adapter must explicitly provide an already verified,
        # immutable published baseline. Never silently skip missing private
        # historical files and never manufacture a fresh manual decision.
        baselines = getattr(self, '_manual_assessment_baselines', None)
        if baselines is None:
            raise RuntimeError('An explicit published Assessment baseline is required; use audit_cp7.py')
        return baselines

    def assessments(self):
        path = Path(__file__).with_name('gates.py')
        self.watch(path)
        spec = importlib.util.spec_from_file_location('existing_read_only_gate', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        works, versions, uploads = (self.indices.get(k, {}) for k in ('work', 'version', 'upload'))
        for aid, a in self.indices.get('assessment', {}).items():
            wid = a.get('work_id')
            if self.fk('work', wid, aid, 'work_id'):
                self.require(works[wid]['work_key'] == a.get('work_key'), 'assessment_work_key_mismatch', a.get('work_key'), aid)
            for uid in a.get('provenance_upload_ids', []):
                if self.fk('upload', uid, aid, 'provenance_upload_ids'):
                    self.require(uploads[uid]['work_id'] == wid, 'assessment_upload_owner', uid, aid)
                    self.require(uploads[uid]['version_id'] in a.get('provenance_version_ids', []),
                                 'assessment_upload_missing_version', uid, aid)
            for vid in a.get('provenance_version_ids', []):
                if self.fk('version', vid, aid, 'provenance_version_ids'):
                    self.require(versions[vid]['work_id'] == wid, 'assessment_version_owner', vid, aid)
            for field in ['species', 'motion_type', 'environment', 'scale']:
                self.require(a.get(field) == a.get('conditions', {}).get(field),
                             'assessment_condition_projection', field, aid)
            embedded = {}
            for group, key in [('dataset_records', 'dataset_id'), ('baseline_records', 'baseline_id'),
                               ('condition_levels', 'condition_id'), ('metric_records', 'metric_id')]:
                objects = a.get(group, [])
                embedded[key] = {r.get(key) for r in objects}
                self.require(len(embedded[key]) == len(objects), 'assessment_embedded_duplicate_id', group, aid)
            for group in ['baseline_records', 'metric_records']:
                for obj in a.get(group, []):
                    for field in ['dataset_id', 'baseline_id']:
                        if field in obj and obj[field] is not None:
                            self.require(obj[field] in embedded[field], 'assessment_embedded_fk', f'{field}: {obj[field]}', aid)
                    for field, target in [('condition_ids', 'condition_id'), ('metric_ids', 'metric_id')]:
                        for key in obj.get(field, []):
                            self.require(key in embedded[target], 'assessment_embedded_fk', f'{field}: {key}', aid)
            if a.get('assessment_status') == 'active':
                self.require(not a.get('superseded_by_assessment_id'), 'active_assessment_superseded', 'Active record has successor', aid)
                self.require(bool(a.get('provenance_version_ids')), 'active_assessment_without_version', 'No inspected Version', aid)
                try:
                    module.check_values(a)
                    mechanical = module.evidence_gate(a)
                    # Read-only prediction. Never replace stricter manual rejection with its output.
                    if a.get('evidence_admission_status') == 'eligible':
                        self.require(mechanical.get('evidence_admission_status') == 'eligible',
                                     'eligible_assessment_fails_mechanical_gate', mechanical.get('rejection_codes'), aid)
                        self.require(not a.get('rejection_codes'), 'eligible_with_rejection_codes', a.get('rejection_codes'), aid)
                        self.require(a.get('handling_level') != 'insufficient_evidence',
                                     'eligible_with_insufficient_handling', 'Inconsistent handling state', aid)
                    elif a.get('evidence_admission_status') == 'insufficient_evidence':
                        self.require(bool(a.get('rejection_codes')), 'manual_rejection_without_code', 'Rejection reason required', aid)
                        if mechanical.get('evidence_admission_status') == 'eligible':
                            self.counts['manual_rejections_preserved_over_mechanical_pass'] += 1
                except Exception as e:
                    self.note('assessment_semantic_gate_exception', f'{type(e).__name__}: {e}', aid)
                for loc in a.get('evidence_locator', []):
                    if loc.get('version_id'):
                        self.require(loc['version_id'] in a.get('provenance_version_ids', []),
                                     'assessment_primary_locator_version', loc['version_id'], aid)
                    if loc.get('upload_id'):
                        self.require(loc['upload_id'] in a.get('provenance_upload_ids', []),
                                     'assessment_primary_locator_upload', loc['upload_id'], aid)
                if a.get('evidence_admission_status') == 'eligible':
                    self.require(a.get('evidence_level') == 'fulltext_result' and a.get('fulltext_status') == 'available_verified',
                                 'eligible_without_fulltext', 'Eligible evidence requires verified fulltext result', aid)
                    if a.get('limitation_id') in {'L05', 'L09'}:
                        species = a.get('conditions', {}).get('species', {})
                        values = species.get('value') or []
                        explicit = species.get('status') == 'reported' and bool(values)
                        explicit = explicit and all(
                            isinstance(s, dict) and len(str(s.get('scientific_name') or '').split()) >= 2
                            and not re.search(r'\b(?:sp|spp)\.?$', str(s.get('scientific_name')), re.I)
                            for s in values)
                        self.require(explicit, 'eligible_L05_L09_without_explicit_species',
                                     'Cell/species-specific claims require reported species; genus-only or unknown cannot qualify', aid)
            elif a.get('assessment_status') == 'merged':
                self.fk('assessment', a.get('superseded_by_assessment_id'), aid, 'superseded_by_assessment_id')
            if a.get('cascade_event_id'):
                self.fk('cascade_event', a['cascade_event_id'], aid, 'cascade_event_id')
        # Independently authored reviews are preserved as a scientific veto. The
        # private audit cannot silently turn a manual rejection into eligibility.
        checked = set()
        for path, records in self.manual_assessment_baselines():
            try:
                if not isinstance(records, list):
                    raise ValueError('Explicit manual baseline must contain a list')
                for old in records:
                    aid = old.get('assessment_id')
                    current = self.indices.get('assessment', {}).get(aid)
                    if not current:
                        continue
                    checked.add(aid)
                    if old.get('evidence_admission_status') == 'insufficient_evidence':
                        self.require(current.get('evidence_admission_status') != 'eligible',
                                     'manual_rejection_mechanically_upgraded', str(path), aid)
                    if old.get('counter_evidence'):
                        self.require(current.get('counter_evidence') is True, 'manual_counterevidence_lost', str(path), aid)
            except Exception as e:
                self.note('private_manual_baseline_unreadable', str(e), str(path), severity='warning')
        self.stats['assessments_compared_to_manual_baseline'] = len(checked)
        self.stats['active_assessments'] = len(self.active)
        self.stats['active_admission_states'] = dict(Counter(a.get('evidence_admission_status') for a in self.active.values()))

    def html_bib(self):
        keys = set(self.indices['work_key'])
        p = self.repo / 'ref.bib'
        self.watch(p)
        try:
            bib = p.read_text(encoding='utf-8')
            bibkeys = re.findall(r'(?im)^\s*@(?!comment\b|preamble\b|string\b)[a-z]+\s*\{\s*([^,\s]+)\s*,', bib)
            self.require(len(bibkeys) == len(set(bibkeys)), 'bibtex_duplicate_key', 'Duplicate entry key')
            self.same_set(bibkeys, keys, 'bibtex_work_set')
            self.require(bibkeys == sorted(bibkeys), 'bibtex_key_sort', 'Entries must be sorted by key')
        except Exception as e:
            self.note('bibtex_read_error', str(e))
        p = self.repo / 'ref.html'
        self.watch(p)
        try:
            html = p.read_text(encoding='utf-8')
            if '<meta name="bibliography-format" content="2">' in html or (self.repo / 'misc.html').exists():
                from audit_bibliography import audit_package, source_actions, WEB_FILES
                for name in WEB_FILES:
                    self.watch(self.repo / name)
                snapshot = json.loads((self.temp / 'exports/research_paths.json').read_bytes())['checkpoint_id']
                works, assessments, versions = (self.datasets[k + '.jsonl'] for k in ('works','assessments','versions'))
                tasks = {t['task_id']: t for t in self.datasets['tasks.jsonl']}
                actions = source_actions(self.temp, works, assessments, versions, tasks, snapshot)
                view = audit_package(self.repo, works, assessments, actions, snapshot, self.scope['scope_id'])
                self.stats['reconciliation'] = {k: view[k] for k in ('K','T_union','U','T_i')}
                self.stats['offline_bibliography'] = view
                return
            parser = HTMLTables()
            parser.feed(html)
        except Exception as e:
            self.note('html_read_error', str(e))
            return
        expected_ids = {f'limitation-L{i:02}' for i in range(1, 10)} | {'literature-U00'}
        self.same_set(parser.table_ids, expected_ids, 'html_ten_tables')
        self.require(len(parser.table_ids) == 10, 'html_table_count', len(parser.table_ids))
        for identifier, count in parser.ids.items():
            if count > 1:
                self.note('html_duplicate_id', count, identifier)
        expected = defaultdict(set)
        for a in self.active.values():
            if a.get('evidence_admission_status') == 'eligible' and SUBSTANTIVE.intersection(a.get('relation_type', [])):
                expected['limitation-' + a['limitation_id']].add(a['work_key'])
        union = set().union(*expected.values()) if expected else set()
        expected['literature-U00'] = keys - union
        for table in expected_ids:
            rows = parser.tables.get(table, [])
            self.require(len(rows) == len(set(rows)), 'html_duplicate_table_key', table)
            self.same_set(rows, expected[table], 'html_topic_membership', table)
        shown = set(k for rows in parser.tables.values() for k in rows)
        actual_topics = set().union(*(set(parser.tables.get(f'limitation-L{i:02}', [])) for i in range(1, 10)))
        actual_u = set(parser.tables.get('literature-U00', []))
        self.same_set(shown, keys, 'html_K_equals_U_union_T')
        self.same_set(actual_u, keys - actual_topics, 'html_U_equals_K_minus_T')
        self.require(not actual_u.intersection(actual_topics), 'html_U_topic_overlap', 'U00 must be disjoint from themes')
        for element in ['search', 'theme', 'status', 'toggle-abstracts']:
            self.require(parser.ids[element] == 1, 'html_required_control', element)
        self.require(parser.scripts > 0 and ('href="#top"' in html or 'href="#top-of-page"' in html or '返回顶部' in html),
                     'html_navigation_function', 'Search/filter script and back-to-top control required')
        self.stats['reconciliation'] = {'K': len(keys), 'T_union': len(union), 'U': len(keys - union),
            'T_i': {f'L{i:02}': len(expected[f'limitation-L{i:02}']) for i in range(1, 10)}}

    def exports(self):
        export_meta = []
        graph = self.load_json(self.temp / 'exports/citation_graph.json', 'citation_graph')
        entities = self.load_json(self.temp / 'exports/research_entities.json', 'research_entities')
        paths = self.load_json(self.temp / 'exports/research_paths.json', 'research_paths')
        works = self.indices.get('work', {})
        edges = self.indices.get('citation_edge', {})
        refs = self.indices.get('reference_occurrence', {})
        for export, obj in [('citation_graph', graph), ('research_entities', entities), ('research_paths', paths)]:
            if obj is None:
                continue
            export_meta.append((export, obj.get('scope_id'), obj.get('checkpoint_id'), obj.get('schema_version')))
        if graph:
            nodes = graph.get('nodes', [])
            node_ids = [x.get('work_id') for x in nodes]
            self.require(len(node_ids) == len(set(node_ids)), 'graph_duplicate_node', 'Duplicate Work ID')
            self.same_set(node_ids, works, 'graph_node_set')
            for n in nodes:
                if n.get('work_id') in works:
                    w = works[n['work_id']]
                    self.require(all(n.get(k) == w.get(k) for k in n), 'graph_node_value', 'Node differs from canonical Work', n['work_id'])
            export_edges = graph.get('edges', [])
            self.require(len(export_edges) == len({e.get('edge_id') for e in export_edges}), 'graph_duplicate_edge', 'Duplicate edge ID')
            self.same_set([e.get('edge_id') for e in export_edges], edges, 'graph_edge_set')
            for e in export_edges:
                eid = e.get('edge_id')
                if eid in edges:
                    self.require(all(e.get(k) == v for k, v in edges[eid].items() if k in e),
                                 'graph_edge_value', 'Exported edge differs from canonical record', eid)
                for side in ['citing', 'cited']:
                    wid, key = e.get(side + '_work_id'), e.get(side + '_key')
                    if self.fk('work', wid, eid, side + '_work_id'):
                        self.require(works[wid]['work_key'] == key, 'graph_endpoint_key', key, eid)
            unresolved = graph.get('unresolved_occurrences', [])
            self.same_set([x.get('occurrence_id') for x in unresolved],
                          {oid for oid, r in refs.items() if r.get('cited_work_id') is None}, 'graph_unresolved_pointer_set')
            self.require(len(unresolved) == len({x.get('occurrence_id') for x in unresolved}),
                         'graph_duplicate_unresolved_pointer', 'Duplicate unresolved occurrence ID')
            for p in unresolved:
                oid = p.get('occurrence_id')
                self.require(set(p) == {'occurrence_id', 'citing_work_id', 'candidate_ids', 'failure_reason', 'canonical_dataset'},
                             'graph_unresolved_pointer_shape', 'Only canonical pointer fields; no copied raw reference', oid)
                if oid in refs:
                    self.require(all(p.get(k) == refs[oid].get(k) for k in ['citing_work_id', 'candidate_ids', 'failure_reason']),
                                 'graph_unresolved_pointer_value', 'Pointer differs from source occurrence', oid)
                self.require(str(p.get('canonical_dataset', '')).removeprefix('temp/') == 'reference-occurrences.jsonl',
                             'graph_unresolved_dataset_pointer', p.get('canonical_dataset'), oid)
            independent = graph.get('independent_progress', [])
            self.same_set([x.get('assessment_id') for x in independent],
                          {aid for aid, a in self.active.items() if 'independent_progress' in a.get('relation_type', [])},
                          'graph_independent_progress_set')
            for p in independent:
                a = self.active.get(p.get('assessment_id'))
                if a:
                    self.require(all(p.get(k) == a.get(k) for k in p), 'graph_independent_progress_value', 'Assessment differs', p.get('assessment_id'))
        relation_index = {}
        if entities:
            for group, kind, key in [('people', 'person', 'person_id'), ('organizations', 'organization', 'org_id'), ('projects', 'project', 'project_id')]:
                rows = entities.get(group, [])
                self.require(len(rows) == len({x.get(key) for x in rows}), 'entities_duplicate_id', group)
                self.same_set([x.get(key) for x in rows], self.indices.get(kind, {}), 'entities_' + group + '_set')
                for row in rows:
                    if row.get(key) in self.indices.get(kind, {}):
                        self.require(row == self.indices[kind][row[key]], 'entities_canonical_value', group, row[key])
            self.same_set([x.get('work_id') for x in entities.get('work_refs', [])], works, 'entities_work_set')
            for row in entities.get('work_refs', []):
                if row.get('work_id') in works:
                    self.require(works[row['work_id']]['work_key'] == row.get('work_key'), 'entities_work_key', row.get('work_key'), row['work_id'])
            relations = entities.get('relations', [])
            relation_index = {r.get('relation_id'): r for r in relations}
            self.require(len(relation_index) == len(relations), 'entities_duplicate_relation', 'Relation IDs duplicated')
            all_entities = set(works) | set(self.indices.get('person', {})) | set(self.indices.get('organization', {})) | set(self.indices.get('project', {}))
            for r in relations:
                self.require(r.get('from_id') in all_entities and r.get('to_id') in all_entities,
                             'entities_relation_endpoint', f'{r.get("from_id")} -> {r.get("to_id")}', r.get('relation_id'))
                for loc in r.get('evidence_locator', []):
                    self.source_check(loc.get('source_id'), r.get('relation_id'), 'evidence_locator')
            expected_authors = {(wid, a.get('person_id')) for wid, w in works.items() for a in w.get('authors', [])}
            actual_authors = {(r.get('from_id'), r.get('to_id')) for r in relations if r.get('relation_type') == 'authored_by'}
            self.same_set(actual_authors, expected_authors, 'entities_authorship_relation_set')
            expected_affiliations = Counter((pid, a.get('org_id'), a.get('work_id'), a.get('role'), a.get('valid_from'), a.get('valid_to'))
                for pid, person in self.indices.get('person', {}).items() for a in person.get('affiliation_history', []))
            actual_affiliations = Counter((r.get('from_id'), r.get('to_id'), r.get('work_id'), r.get('role'), r.get('valid_from'), r.get('valid_to'))
                for r in relations if r.get('relation_type') == 'affiliated_with')
            self.require(actual_affiliations == expected_affiliations, 'entities_affiliation_relation_multiset',
                         {'missing': sum((expected_affiliations - actual_affiliations).values()),
                          'extra': sum((actual_affiliations - expected_affiliations).values())})
            canonical_projects = self.datasets.get('project-relations.jsonl', [])
            self.same_set({r.get('relation_id') for r in relations if r.get('relation_type') == 'project_output'},
                          {r.get('relation_id') for r in canonical_projects if r.get('relation_type') == 'project_output'},
                          'entities_project_output_relation_set')
            for canonical in canonical_projects:
                self.require(relation_index.get(canonical.get('relation_id')) == canonical,
                             'entities_project_relation_value', 'Canonical project relation missing or changed', canonical.get('relation_id'))
        if paths:
            rows = paths.get('paths', [])
            self.require(len(rows) == len({p.get('path_id') for p in rows}), 'paths_duplicate_id', 'Duplicate path ID')
            self.same_set([p.get('assessment_id') for p in rows], self.active, 'paths_assessment_set')
            for p in rows:
                pid, aid = p.get('path_id'), p.get('assessment_id')
                a = self.active.get(aid)
                self.fk('seed', p.get('seed_id'), pid, 'seed_id')
                self.fk('work', p.get('work_id'), pid, 'work_id')
                if a:
                    self.require(all(p.get(k) == a.get(k) for k in ['work_id', 'limitation_id', 'counter_evidence']),
                                 'path_assessment_projection', aid, pid)
                steps = p.get('ordered_steps', [])
                prior = None
                for step in steps:
                    rid = step.get('relation_id')
                    source = relation_index.get(rid)
                    if rid in edges:
                        e = edges[rid]
                        source = {'from_id': self.indices['work_key'][e['citing_key']]['work_id'],
                                  'to_id': self.indices['work_key'][e['cited_key']]['work_id'],
                                  'relation_type': 'cites'}
                    self.require(source is not None, 'path_unresolved_relation', rid, pid)
                    if source:
                        actual_pair = (step.get('from_id'), step.get('to_id'))
                        original_pair = (source.get('from_id'), source.get('to_id'))
                        # Traversal may walk citations backward; relation direction is kept explicit in the canonical edge.
                        self.require(actual_pair == original_pair or actual_pair == original_pair[::-1],
                                     'path_relation_endpoints', rid, pid)
                        self.require(step.get('relation_type') == source.get('relation_type'), 'path_relation_type', rid, pid)
                    if prior is not None:
                        self.require(step.get('from_id') == prior, 'path_disconnected_steps', rid, pid)
                    prior = step.get('to_id')
                    self.source_check(step.get('source_id'), pid, 'ordered_steps')
                    if isinstance(step.get('locator'), dict):
                        self.locator_check(step['locator'], pid, 'ordered_steps.locator')
                        self.require(step.get('source_id') == step['locator'].get('source_id'),
                                     'path_source_locator_disagreement', rid, pid)
                if steps:
                    seed = self.indices.get('seed', {}).get(p.get('seed_id'), {})
                    self.require(steps[0].get('from_id') == seed.get('work_id') and steps[-1].get('to_id') == p.get('work_id'),
                                 'path_start_end', 'Path must connect seed Work to assessed Work', pid)
                elif not p.get('gap_reason'):
                    seed = self.indices.get('seed', {}).get(p.get('seed_id'), {})
                    self.require(seed.get('work_id') == p.get('work_id'), 'empty_nonseed_path_without_gap', 'No steps and no explicit gap', pid)
        for filename, header in [('evidence_matrix.csv', MATRIX_HEADER), ('research_implications.csv', IMPLICATION_HEADER)]:
            p = self.temp / 'exports' / filename
            self.watch(p)
            try:
                with p.open(encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f)
                    self.require(reader.fieldnames == header, 'csv_header', filename)
                    rows = list(reader)
                ids = [r.get('assessment_id') for r in rows]
                self.require(len(ids) == len(set(ids)), 'csv_duplicate_assessment', filename)
                self.same_set(ids, self.active, 'csv_active_assessment_set', filename)
                metas = set()
                for r in rows:
                    aid = r.get('assessment_id')
                    metas.add((r.get('scope_id'), r.get('checkpoint_id'), r.get('schema_version')))
                    a = self.active.get(aid)
                    if a:
                        for k, value in r.items():
                            if k not in a:
                                continue
                            original = a[k]
                            if isinstance(original, (dict, list, bool)) or original is None:
                                try:
                                    actual = json.loads(value)
                                except (ValueError, TypeError):
                                    self.note('csv_json_cell', k, aid, filename)
                                    continue
                            else:
                                actual = value
                            self.require(actual == original, 'csv_canonical_value', k, aid, filename)
                if len(metas) > 1:
                    self.note('csv_mixed_snapshot_metadata', filename)
                export_meta.extend((filename, *meta) for meta in metas)
            except Exception as e:
                self.note('csv_read_error', str(e), filename)
        metadata_set = {(x[1], x[2], x[3]) for x in export_meta}
        self.require(len(metadata_set) <= 1, 'exports_mixed_snapshot_metadata', list(metadata_set))
        for name, scope, cp, version in export_meta:
            self.require(scope == self.scope.get('scope_id'), 'export_scope', scope, name)
            self.require(version == self.schema.get('schema_version'), 'export_schema_version', version, name)
            self.require(cp in self.checkpoints, 'export_checkpoint', cp, name)
        self.stats['export_metadata'] = export_meta

    def partitions_and_artifact_hashes(self):
        if self.partition_manifest:
            for name, d in self.partition_manifest.get('datasets', {}).items():
                total, h = 0, hashlib.sha256()
                for part in d.get('parts', []):
                    path = (self.temp / part['path']).resolve()
                    if not self.require(path.is_relative_to(self.temp.resolve()), 'partition_path_escape', str(path), name):
                        continue
                    if not path.exists():
                        self.note('partition_missing', str(path), name)
                        continue
                    ph, count, size = hashlib.sha256(), 0, 0
                    with path.open('rb') as f:
                        for line in f:
                            h.update(line)
                            ph.update(line)
                            size += len(line)
                            count += bool(line.strip())
                    self.require(ph.hexdigest() == part.get('sha256'), 'partition_sha256', str(path), name)
                    self.require(count == part.get('records') and size == part.get('bytes'), 'partition_counts', str(path), name)
                    total += count
                self.require(total == d.get('logical_records') == len(self.datasets.get(name, [])),
                             'partition_logical_count', total, name)
                self.require(h.hexdigest() == d.get('logical_sha256'), 'partition_logical_sha256', name)
        # Historical checkpoint hashes are intentionally not compared with the
        # latest mutable files. Only the checkpoint named by current exports is.
        export_cps = {x[2] for x in self.stats.get('export_metadata', [])}
        for cid in export_cps:
            cp = self.checkpoints.get(cid, {})
            hashes = cp.get('artifact_hashes', {})
            if not isinstance(hashes, dict):
                continue
            revisions = {}
            receipt = self.repo / 'temp/validation/bibliography-view.json'
            if receipt.is_file() and hashes:
                from audit_bibliography import presentation_revisions
                self.watch(receipt)
                revisions = presentation_revisions(self.repo, cid, hashes)
            for rel, expected in hashes.items():
                p = self.repo / rel
                if not p.is_file():
                    p = self.temp / rel
                self.watch(p)
                if not p.is_file():
                    self.note('checkpoint_artifact_missing', rel, cid)
                    continue
                if isinstance(expected, dict):
                    expected = expected.get('sha256')
                expected = revisions.get(rel, expected)
                if isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected):
                    self.require(sha(p) == expected, 'checkpoint_artifact_hash', rel, cid)

    def finish(self):
        changed = []
        for p, before in self.watched.items():
            try:
                s = p.stat()
                after = (s.st_size, s.st_mtime_ns)
            except FileNotFoundError:
                after = None
            if before != after:
                changed.append(str(p))
        error_count = sum(x['count'] for x in self.findings['error'].values())
        warning_count = sum(x['count'] for x in self.findings['warning'].values())
        result = {'audit_version': '1.0', 'read_only': True,
            'audited_at_utc': self.now.isoformat().replace('+00:00', 'Z'),
            'repository': str(self.repo), 'schema_version': self.schema.get('schema_version'),
            'scope_id': self.scope.get('scope_id'),
            'status': 'inflight_inputs_changed' if changed else ('failed' if error_count else 'passed'),
            'error_count': error_count, 'warning_count': warning_count,
            'duration_seconds': round(time.monotonic() - self.started, 3),
            'validator_count': len(self.validators), 'counters': dict(self.counts),
            'statistics': self.stats, 'findings': self.findings,
            'changed_inputs': changed,
            'limits': ['Mechanical validation does not independently confirm scientific truth or reread papers.',
                       'Known manual scientific rejections override a mechanical pass.',
                       'Unregistered auxiliary datasets receive generic checks and a schema-registration warning.',
                       'No search or new scientific manual-budget activity was performed.']}
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': result['status'], 'errors': error_count, 'warnings': warning_count,
                          'seconds': result['duration_seconds'], 'report': str(self.out)}, ensure_ascii=False), flush=True)
        return 2 if changed else (1 if error_count else 0)

    def run(self):
        for method in [self.load, self.topology, self.references, self.subjects, self.generic,
                       self.task_queries, self.assessments, self.html_bib, self.exports,
                       self.partitions_and_artifact_hashes]:
            print('audit ' + method.__name__, flush=True)
            try:
                method()
            except Exception as e:
                self.note('audit_section_exception', f'{type(e).__name__}: {e}', method.__name__)
                if method == self.load:
                    return self.finish()
        return self.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT / 'Insect-Inspired')
    parser.add_argument('--out', type=Path, default=ROOT / 'p3p6_work/audit-run.json')
    parser.add_argument('--now', help='UTC ISO date-time, for reproducible deadline checks')
    parser.add_argument('--max-examples', type=int, default=20)
    args = parser.parse_args()
    now = utc(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error('--now must be an ISO date-time with timezone')
    out = args.out.resolve()
    if out.is_relative_to(args.repo.resolve()):
        parser.error('--out must be outside the canonical repository; this audit is read-only')
    return Audit(args.repo.resolve(), out, now, args.max_examples).run()


if __name__ == '__main__':
    sys.exit(main())
