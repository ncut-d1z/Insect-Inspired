#!/usr/bin/env python3
"""Deterministic static BibTeX and five research views from logical JSONL.

Default output is a private preview.  The root orchestrator can publish with:
  python cp5_qa/export_run.py --repo insect-project --checkpoint CP-0005 --output-dir insect-project
This module performs no scientific search, merges, state changes or inference of
new citation/project relations.  It does not write ref.html (render_html.py does).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
# Adjacent project-local helpers are resolved by Python's script directory.

from jsonschema import Draft202012Validator, FormatChecker
from storage import read_logical
from audit_run import MATRIX_HEADER, IMPLICATION_HEADER

ROOT = Path(__file__).resolve().parents[1]
FIELD_ORDER = ('author editor title year month journal booktitle series edition volume number pages eid publisher school '
               'institution address type howpublished doi isbn issn url urldate language note abstract').split()
NODE_FIELDS = ['work_id', 'work_key', 'canonical_title', 'identity_confidence', 'publication_status']
EDGE_FIELDS = ['edge_id', 'citing_key', 'cited_key', 'verification_status', 'citation_roles',
               'context_locators', 'occurrence_ids', 'discovery_sources']
POINTER_SCHEMA = {
    'type': 'object', 'properties': {
        'occurrence_id': {'type': 'string', 'minLength': 1},
        'citing_work_id': {'type': 'string', 'minLength': 1},
        'candidate_ids': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
        'failure_reason': {'type': ['string', 'null']},
        'canonical_dataset': {'const': 'temp/reference-occurrences.jsonl'}},
    'required': ['occurrence_id', 'citing_work_id', 'candidate_ids', 'failure_reason', 'canonical_dataset'],
    'additionalProperties': False}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact records avoid amplifying repeated nested evidence indentation.
    path.write_text(json_text(obj) + '\n', encoding='utf-8')


def tex(value):
    # BibTeX counts braces when parsing a field even after a backslash.
    replacements = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
                    '#': r'\#', '_': r'\_', '{': r'\textbraceleft{}', '}': r'\textbraceright{}',
                    '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(replacements.get(c, c) for c in str(value).replace('\r', ' ').replace('\n', ' '))


def name_bib(author):
    if author.get('is_corporate'):
        return '{' + tex(author['display_name']) + '}'
    family, given = author.get('family_name'), author.get('given_name')
    if family:
        return tex(family) + (', ' + tex(given) if given else '')
    # Preserve the supplied name when structured components are unavailable;
    # never invent an anonymous author or infer family-name boundaries.
    return tex(author.get('display_name', ''))


def bibliography(works, scope):
    output = []
    for w in sorted(works.values(), key=lambda x: x['work_key']):
        dtype = w['document_type']
        typ = {'journal_article': 'article', 'conference_paper': 'inproceedings',
               'book_chapter': 'incollection', 'book': 'book',
               'technical_report': 'techreport'}.get(dtype, 'misc')
        if dtype == 'thesis':
            typ = {'phd': 'phdthesis', 'masters': 'mastersthesis'}.get(w.get('degree_type'), 'misc')
        fields, prepared = {}, set()
        if w.get('authors'):
            fields['author'] = ' and '.join(name_bib(a) for a in w['authors'])
            prepared.add('author')
        if w.get('editors'):
            fields['editor'] = ' and '.join(name_bib(a) for a in w['editors'])
            prepared.add('editor')
        fields['title'] = '{' + tex(w['canonical_title']) + '}'
        prepared.add('title')
        if w.get('year') is not None:
            fields['year'] = w['year']
        date = w.get('publication_date')
        if date and re.match(r'^\d{4}-\d{2}', date):
            fields['month'] = date[5:7]
        if typ == 'article' and w.get('venue'):
            fields['journal'] = w['venue']
        elif typ in {'inproceedings', 'incollection'} and w.get('venue'):
            fields['booktitle'] = w['venue']
        for field in ['series', 'edition', 'volume', 'number', 'pages', 'eid', 'publisher',
                      'school', 'institution', 'address', 'doi', 'isbn', 'issn', 'url', 'language']:
            if w.get(field) is not None and w.get(field) != '':
                value = w[field]
                if isinstance(value, list):
                    value = ', '.join(map(str, value))
                fields[field] = re.sub(r'(?<=\d)[\-–—]+(?=\d)', '--', str(value)) if field == 'pages' else value
        if typ == 'misc':
            fields['type'] = dtype
            fields['howpublished'] = w.get('venue') or dtype
        accessed = [s.get('accessed_at', '')[:10] for s in w.get('discovery_sources', []) if s.get('accessed_at')]
        accessed = [x for x in accessed if re.fullmatch(r'\d{4}-\d{2}-\d{2}', x)]
        if accessed:
            fields['urldate'] = max(accessed)
        notes = []
        if w.get('identity_confidence') != 'confirmed':
            notes.append('Provisional bibliographic identity; ' + str(w.get('identity_confidence')) + '.')
        if w.get('verification_status') in {'unverified', 'conflicting'}:
            notes.append('Bibliographic verification status: ' + w['verification_status'] + '.')
        if w.get('seed_ids') == ['S01']:
            notes.append('Dissertation cover dated November 2018; repository publication year 2019.')
        if w.get('seed_ids') == ['S02']:
            notes.append('Conference year and pages follow official NeurIPS metadata; alternative pagination is retained in audit data.')
        if w.get('seed_ids') == ['S17']:
            notes.append('Metadata describe the published article; the supplied file is an author-formatted manuscript.')
        if notes:
            fields['note'] = ' '.join(notes)
        # Chinese summaries are original project text; omission of a restricted
        # publisher abstract is deliberate and does not synthesize one from title.
        abstracts = [a for a in w.get('abstract_items', [])
                     if a.get('text') and a.get('status') in {'chinese_summary_from_fulltext', 'chinese_summary_from_abstract'}]
        if abstracts:
            selected = sorted(abstracts, key=lambda a: (a.get('date', ''), a.get('version_id') or '', a['text']))[-1]
            fields['abstract'] = selected['text']
        entries = []
        for field in FIELD_ORDER:
            if field in fields:
                value = fields[field] if field in prepared or field in {'doi', 'url', 'isbn', 'issn', 'urldate'} else tex(fields[field])
                entries.append('  ' + field + ' = {' + str(value) + '}')
        output.append('@' + typ + '{' + w['work_key'] + ',\n' + ',\n'.join(entries) + '\n}\n')
    return '\n'.join(output)


def source_locators(source, note):
    if not source:
        return []
    if source.get('evidence_locator'):
        return source['evidence_locator']
    if source.get('source_id') and (source.get('url') or source.get('identifier')):
        loc = {'source_id': source['source_id'], 'evidence_note': note}
        for name in ['url', 'identifier', 'accessed_at']:
            if source.get(name):
                loc[name] = source[name]
        if isinstance(source.get('version'), str) and source['version'].startswith('V-'):
            loc['version_id'] = source['version']
        # An identifier-only API observation can be located by its metadata section.
        if not loc.get('url'):
            loc['section'] = 'Author metadata in the identified source record'
        return [loc]
    return []


def weaker_status(*statuses):
    order = {'rejected': 0, 'conflicting': 1, 'unverified': 2, 'source_supported': 3, 'verified': 4}
    known = [s for s in statuses if s in order]
    return min(known, key=lambda s: order[s]) if known else 'unverified'


def entity_relations(works, people, project_relations):
    rows = []
    for w in sorted(works.values(), key=lambda x: x['work_id']):
        for i, a in enumerate(w.get('authors', []), 1):
            src = a.get('source') or next(iter(w.get('discovery_sources', [])), {})
            person = people.get(a['person_id'], {})
            status = weaker_status(src.get('verification_status'), w.get('verification_status'))
            if person.get('identity_confidence') not in {None, 'confirmed'} and status == 'verified':
                status = 'source_supported'
            rows.append({'relation_id': f'ER-{w["work_id"]}-author-{i:02}', 'relation_type': 'authored_by',
                         'from_id': w['work_id'], 'to_id': a['person_id'],
                         'valid_from': w.get('publication_date'), 'valid_to': None,
                         'verification_status': status,
                         'evidence_locator': source_locators(src, 'Authorship stated by the cited metadata/byline; person identity resolution is a separate status.'),
                         'role': 'authorship', 'work_id': w['work_id']})
    for p in sorted(people.values(), key=lambda x: x['person_id']):
        for i, affiliation in enumerate(p.get('affiliation_history', []), 1):
            relation = {'relation_id': f'ER-{p["person_id"]}-aff-{i:03}', 'relation_type': 'affiliated_with',
                        'from_id': p['person_id'], 'to_id': affiliation['org_id'],
                        'valid_from': affiliation.get('valid_from'), 'valid_to': affiliation.get('valid_to'),
                        'verification_status': affiliation.get('verification_status', 'source_supported'),
                        'evidence_locator': affiliation.get('evidence_locator', [])}
            if affiliation.get('role'):
                relation['role'] = affiliation['role']
            if affiliation.get('work_id'):
                relation['work_id'] = affiliation['work_id']
            rows.append(relation)
    rows.extend(project_relations)
    ids = [r['relation_id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate canonical/derived entity relation ID')
    return sorted(rows, key=lambda r: r['relation_id'])


def edge_locator(edge):
    if edge.get('context_locators'):
        return edge['context_locators'][0]
    for src in edge.get('discovery_sources', []):
        locs = source_locators(src, 'Actual citation index/printed-reference observation, not a version or project relation.')
        if locs:
            return locs[0]
    return None


def research_paths(assessments, works, seeds, discoveries, graph_edges, entity_rows):
    by_work = defaultdict(list)
    for d in discoveries:
        by_work[d.get('work_id')].append(d)
    edge_pairs = {(e['citing_work_id'], e['cited_work_id']): e for e in graph_edges}
    relation_pairs = defaultdict(list)
    author_edges = defaultdict(dict)
    for r in entity_rows:
        relation_pairs[(r['from_id'], r['to_id'])].append(r)
        if r['relation_type'] == 'authored_by':
            author_edges[r['from_id']][r['to_id']] = r
    seed_by_work = defaultdict(list)
    for sid, seed in seeds.items():
        seed_by_work[seed['work_id']].append(sid)
    result = []

    def step_for_relation(r, left, right):
        locs = r.get('evidence_locator', [])
        if not locs:
            return None
        loc = locs[0]
        return {'from_id': left, 'to_id': right, 'relation_id': r['relation_id'],
                'relation_type': r['relation_type'], 'source_id': loc['source_id'], 'locator': loc}

    for a in sorted(assessments, key=lambda x: x['assessment_id']):
        wid = a['work_id']
        base = {'path_id': 'PATH-' + a['assessment_id'], 'limitation_id': a['limitation_id'],
                'assessment_id': a['assessment_id'], 'work_id': wid,
                'counter_evidence': a['counter_evidence'], 'evidence_locators': a.get('evidence_locator', [])}
        if seed_by_work.get(wid):
            result.append({**base, 'seed_id': sorted(seed_by_work[wid])[0], 'ordered_steps': [],
                           'path_type': 'seed', 'verification_status': 'verified', 'gap_reason': None})
            continue
        candidates = sorted(by_work.get(wid, []), key=lambda d: (len(d.get('steps', [])), d.get('root_seed_id', ''), d.get('discovery_id', '')))
        best = None
        for d in candidates:
            sid = d.get('root_seed_id')
            if sid not in seeds:
                continue
            steps, errors, statuses = [], [], []
            current = seeds[sid]['work_id']
            route = 'backward_citation'
            for raw in d.get('steps', []):
                left, right = raw.get('from_entity_id'), raw.get('to_entity_id')
                route = raw.get('discovery_route', route)
                if left != current:
                    errors.append('Discovery steps are not continuous from the recorded seed.')
                    break
                if route in {'backward_citation', 'forward_citation'}:
                    pair = (left, right) if route == 'backward_citation' else (right, left)
                    edge = edge_pairs.get(pair)
                    loc = edge_locator(edge) if edge else None
                    if not edge or not loc:
                        errors.append('Discovery lead has no matching canonical citation edge with source evidence; no citation was synthesized.')
                        break
                    steps.append({'from_id': left, 'to_id': right, 'relation_id': edge['edge_id'],
                                  'relation_type': 'cites', 'source_id': loc['source_id'], 'locator': loc})
                    statuses.append(edge['verification_status'])
                elif route == 'author_publication':
                    shared = sorted(set(author_edges.get(left, {})) & set(author_edges.get(right, {})))
                    choices = []
                    for person in shared:
                        first, second = author_edges[left][person], author_edges[right][person]
                        s1, s2 = step_for_relation(first, left, person), step_for_relation(second, person, right)
                        if s1 and s2:
                            choices = [s1, s2]
                            statuses.extend([first['verification_status'], second['verification_status']])
                            break
                    if not choices:
                        errors.append('Author-publication lead lacks two traceable authorship relations; no authorship/project relation was synthesized.')
                        break
                    steps.extend(choices)
                else:
                    choices = relation_pairs.get((left, right), []) + relation_pairs.get((right, left), [])
                    chosen = next((r for r in sorted(choices, key=lambda r: r['relation_id']) if r.get('evidence_locator')), None)
                    if chosen is None:
                        errors.append('Institution/project lead lacks an explicit canonical entity relation; shared affiliation alone is not a project relation.')
                        break
                    steps.append(step_for_relation(chosen, left, right))
                    statuses.append(chosen['verification_status'])
                current = right
            if not errors and current != wid:
                errors.append('Discovery path does not reach the assessed Work.')
            obj = {**base, 'seed_id': sid, 'ordered_steps': steps if not errors else [],
                   'path_type': route, 'verification_status': weaker_status(*statuses) if not errors else 'unverified',
                   'gap_reason': ' '.join(errors) if errors else None}
            if best is None:
                best = obj
            if not errors:
                best = obj
                break
        if best is None:
            # Missing seed root is an input integrity error, not a license to
            # invent a seed association or emit a misleading path.
            raise ValueError(f'Assessment {a["assessment_id"]}: no seed-rooted discovery record for {wid}')
        result.append(best)
    return result


def run(args):
    temp = args.repo / 'temp'
    registry = json.loads((temp / 'schema.json').read_text())
    scope = json.loads((temp / 'snapshots/scope.json').read_text())
    data = {}
    for filename in ['works.jsonl', 'authors.jsonl', 'organizations.jsonl', 'projects.jsonl',
                     'assessments.jsonl', 'citation-edges.jsonl', 'reference-occurrences.jsonl',
                     'seed-manifest.jsonl', 'discovery-paths.jsonl', 'project-relations.jsonl']:
        data[filename] = read_logical(filename, base=temp)
    works = {w['work_id']: w for w in data['works.jsonl']}
    by_key = {w['work_key']: w for w in works.values()}
    if len(works) != len(data['works.jsonl']) or len(by_key) != len(works):
        raise ValueError('Work IDs or BibTeX keys are not unique')
    people = {p['person_id']: p for p in data['authors.jsonl']}
    seeds = {s['seed_id']: s for s in data['seed-manifest.jsonl'] if s.get('record_type') == 'seed_mapping'}
    active = sorted((a for a in data['assessments.jsonl'] if a['assessment_status'] == 'active'), key=lambda a: a['assessment_id'])
    prefix = {'scope_id': scope['scope_id'], 'checkpoint_id': args.checkpoint, 'schema_version': registry['schema_version']}
    nodes = sorted(({k: w[k] for k in NODE_FIELDS} for w in works.values()), key=lambda r: r['work_id'])
    edges = []
    for e in sorted(data['citation-edges.jsonl'], key=lambda e: e['edge_id']):
        if e['citing_key'] not in by_key or e['cited_key'] not in by_key:
            raise ValueError(f'Citation edge {e["edge_id"]} has an unresolved Work key')
        if not e.get('occurrence_ids') and not e.get('discovery_sources'):
            raise ValueError(f'Citation edge {e["edge_id"]} has no primary discovery evidence')
        edges.append({**{k: e[k] for k in EDGE_FIELDS},
                      'citing_work_id': by_key[e['citing_key']]['work_id'],
                      'cited_work_id': by_key[e['cited_key']]['work_id']})
    pointers = sorted(({'occurrence_id': r['occurrence_id'], 'citing_work_id': r['citing_work_id'],
                        'candidate_ids': r['candidate_ids'], 'failure_reason': r.get('failure_reason'),
                        'canonical_dataset': 'temp/reference-occurrences.jsonl'}
                       for r in data['reference-occurrences.jsonl'] if r.get('cited_work_id') is None), key=lambda r: r['occurrence_id'])
    graph = {**prefix, 'nodes': nodes, 'edges': edges, 'unresolved_occurrences': pointers,
             'independent_progress': [{k: a[k] for k in ['assessment_id', 'work_id', 'limitation_id', 'relation_type']}
                                      for a in active if 'independent_progress' in a['relation_type']]}
    relations = entity_relations(works, people, data['project-relations.jsonl'])
    entities = {**prefix, 'people': sorted(people.values(), key=lambda x: x['person_id']),
                'organizations': sorted(data['organizations.jsonl'], key=lambda x: x['org_id']),
                'projects': sorted(data['projects.jsonl'], key=lambda x: x['project_id']),
                'work_refs': [{'work_id': w['work_id'], 'work_key': w['work_key']} for w in sorted(works.values(), key=lambda x: x['work_id'])],
                'relations': relations}
    paths = {**prefix, 'paths': research_paths(active, works, seeds, data['discovery-paths.jsonl'], edges, relations)}
    objects = {'citation_graph': graph, 'research_entities': entities, 'research_paths': paths}
    schema_patch_needed = registry['$defs']['citation_graph']['properties']['unresolved_occurrences']['items'] != POINTER_SCHEMA
    # Private compatibility patch follows the approved README 1.1.1. The
    # canonical schema is never modified by this exporter.
    registry['$defs']['citation_graph']['properties']['unresolved_occurrences']['items'] = POINTER_SCHEMA
    errors = []
    for name, obj in objects.items():
        validator = Draft202012Validator({'$schema': registry['$schema'], '$ref': '#/$defs/' + name,
                                          '$defs': registry['$defs']}, format_checker=FormatChecker())
        for error in validator.iter_errors(obj):
            if len(errors) < 30:
                errors.append({'artifact': name, 'path': '/'.join(map(str, error.absolute_path)), 'message': error.message[:700]})
    if errors:
        raise ValueError('Export schema violations: ' + json.dumps(errors, ensure_ascii=False))
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / 'ref.bib').write_text(bibliography(works, scope), encoding='utf-8')
    for name, obj in objects.items():
        write_json(out / 'temp/exports' / (name + '.json'), obj)
    for filename, header in [('evidence_matrix.csv', MATRIX_HEADER), ('research_implications.csv', IMPLICATION_HEADER)]:
        path = out / 'temp/exports' / filename
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header, lineterminator='\n')
            writer.writeheader()
            for a in active:
                row = {}
                for k in header:
                    value = prefix[k] if k in prefix else a[k]
                    row[k] = json_text(value) if isinstance(value, (dict, list, bool)) or value is None else value
                writer.writerow(row)
    patch = [{'op': 'replace', 'path': '/$defs/citation_graph/properties/unresolved_occurrences/items', 'value': POINTER_SCHEMA}]
    patch_path = args.report.parent / 'graph-schema-patch.json'
    write_json(patch_path, patch)
    artifacts = [out / 'ref.bib'] + sorted((out / 'temp/exports').glob('*'))
    report = {'scope_id': scope['scope_id'], 'checkpoint_id': args.checkpoint,
              'schema_version': registry['schema_version'], 'output_dir': str(out),
              'canonical_schema_pointer_patch_needed': schema_patch_needed,
              'schema_patch_path': str(patch_path), 'input_record_counts': {n: len(x) for n, x in data.items()},
              'counts': {'bibtex_entries': len(works), 'graph_nodes': len(nodes), 'graph_edges': len(edges),
                         'unresolved_pointers': len(pointers), 'independent_progress': len(graph['independent_progress']),
                         'active_assessments': len(active), 'entity_relations': len(relations),
                         'paths': len(paths['paths']), 'path_gaps': sum(bool(p['gap_reason']) for p in paths['paths'])},
              'authorship_statuses': dict(Counter(r['verification_status'] for r in relations if r['relation_type'] == 'authored_by')),
              'schema_errors': errors,
              'artifact_hashes': {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}}
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT / 'insect-project')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent / 'export-preview')
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--report', type=Path, default=Path(__file__).parent / 'export-run-report.json')
    args = parser.parse_args()
    args.repo, args.output_dir, args.report = args.repo.resolve(), args.output_dir.resolve(), args.report.resolve()
    run(args)


if __name__ == '__main__':
    main()
