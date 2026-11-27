"""Deterministic, offline HTML view of the canonical literature snapshot.

Private execution helper. It reads logical JSONL datasets via storage.read_logical
and writes only the requested HTML. Its default output is a private preview.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import sys
# Adjacent project-local helpers are resolved by Python's script directory.

from storage import read_logical, TEMP

ROOT = Path(__file__).resolve().parents[1]
TITLES = [
    '局部空间结构与运动视差', '对比度、纹理及空间频率依赖',
    '瞬态响应与运动适应', '自然刺激、高速及复杂运动',
    'VS 细胞感受野与网络机制', '旋转、平移解耦及运动估计',
    '饱和平台与速度幅值编码', '环境距离及飞行统计先验',
    'Hx 细胞及物种层面的验证',
]
TOPIC_COLUMNS = ['BibTeX key', '题名、作者、年份、来源', '作者及机构', '摘要',
                 '来源链路', '研究问题、方法、结果', 'Assessment', '引用及作用',
                 '研究项目', '证据与处理状态']
U_COLUMNS = ['BibTeX key', '题名、作者、年份、来源', '作者及机构', '摘要',
             '来源链路', '证据与处理状态', '未分类原因', '下一步动作 / 复查条件']
TERMINAL_TASKS = {'verified_complete', 'verified_none', 'not_applicable', 'out_of_scope'}
SUBSTANTIVE = {'direct_study', 'indirect_mitigation', 'foundational_support',
               'engineering_application', 'independent_progress', 'counter_evidence'}
LABELS = {
    'biological_mechanism': '生物机制', 'mathematical_computational_model': '数学 / 计算模型',
    'engineering_implementation': '工程实现', 'direct_study': '直接研究',
    'indirect_mitigation': '间接机制 / 缓解', 'foundational_support': '基础支持',
    'engineering_application': '工程应用', 'independent_progress': '独立进展',
    'counter_evidence': '反证', 'background_only': '背景', 'candidate': '候选',
    'directly_addressed_under_conditions': '明确条件下直接处理',
    'partially_addressed': '部分处理', 'new_evidence_or_hypothesis': '新增证据 / 假说',
    'proposed_unvalidated': '提出但未验证', 'not_resolved': '未解决 / 反例',
    'insufficient_evidence': '证据不足', 'eligible': '合格证据',
    'fulltext_result': '全文推导 / 结果', 'fulltext_discussion': '全文讨论 / 假说',
    'abstract_only': '仅摘要', 'index_or_official_record': '索引 / 官方记录',
    'metadata_only': '仅书目', 'mathematical_proof': '数学推导', 'simulation': '仿真',
    'controlled_experiment': '受控实验', 'electrophysiology': '电生理', 'imaging': '成像',
    'connectomics': '连接组', 'causal_intervention': '因果干预',
    'behavioral_experiment': '行为实验', 'real_world_engineering': '真实环境工程实验',
    'dataset_measurement': '数据集测量', 'author_discussion': '作者讨论',
    'official_record': '官方记录', 'bibliographic_index': '书目索引',
    'official_confirmed': '官方证实', 'funding_acknowledgment': '资助致谢',
    'indirect_clue': '间接线索', 'inheritance': '继承', 'improvement': '改进',
    'comparison': '比较', 'replication': '复现', 'validation': '验证',
    'challenge': '质疑', 'engineering_transfer': '工程迁移', 'background': '背景文献',
    'unrelated': '主题无关', 'pending_assessment': '待评估',
    'metadata_unverified': '书目待核验', 'non_academic_resource': '非学术资源',
    'project_software_dataset_only': '仅项目 / 软件 / 数据集', 'out_of_scope': '范围外',
    'duplicate_pending_merge': '重复待合并', 'pending': '待处理', 'running': '处理中',
    'verified_complete': '已核验完成', 'partial': '部分完成', 'verified_none': '已核实确无',
    'needs_disambiguation': '待消歧', 'restricted': '访问 / 许可受限',
    'retryable_error': '可重试失败', 'paused_budget': '预算暂停',
    'unavailable_final': '已核验不可得', 'not_applicable': '不适用',
    'available_unverified': '全文已取得，完整性待核验', 'available_verified': '全文合法可读，完整性已核验',
    'not_found': '全文未找到', 'not_digitized': '未数字化', 'pending_review': '待复核',
    'original_oa': '原摘要（开放许可）', 'original_licensed': '原摘要（已获转载许可）',
    'chinese_summary_from_fulltext': '中文概括 · 依据全文',
    'chinese_summary_from_abstract': '中文概括 · 依据原摘要',
    'abstract_missing': '摘要缺失', 'abstract_restricted': '摘要受限',
    'verified': '已核验', 'source_supported': '来源支持', 'confirmed': '身份已确认',
    'unknown': '未知 / 待提取或复核', 'not_reported': '原文未披露', 'reported': '已披露',
    'author_explicit': '原作者明确主张', 'reviewer_inference': '分析者有据推断',
    'unverified_hypothesis': '未验证假说', 'negative_result': '负结果',
    'counterexample': '反例', 'replication_failure': '复现失败',
    'cross_species_conflict': '跨物种矛盾', 'cross_condition_conflict': '跨条件矛盾',
    'methodological_conflict': '方法 / 文本矛盾',
    'journal_article': '期刊论文', 'conference_paper': '会议论文', 'preprint': '预印本',
    'thesis': '学位论文', 'technical_report': '技术报告', 'book_chapter': '书章',
    'book': '书籍', 'dataset': '数据集', 'software': '软件', 'patent': '专利',
    'project_resource': '项目资源', 'other': '其他', 'published': '已发表',
    'submitted': '已投稿', 'posted': '已发布',
    'species': '物种', 'motion_type': '运动类型', 'motion_dof': '估计分量 / 自由度',
    'known_translation': '平移是否已知', 'speed_range': '速度 / 刺激范围',
    'environment': '环境类型', 'environment_details': '环境条件',
    'texture_noise': '纹理 / 噪声', 'scale': '尺度', 'scale_source_prior': '尺度来源先验',
    'scale_observability': '尺度可观测性', 'method_and_validation': '方法与验证条件',
    'rotation_only': '纯旋转', 'translation_only': '纯平移',
    'mixed_rotation_translation': '旋转 + 平移', 'direction_only': '仅方向',
    'relative': '相对尺度', 'absolute_metric': '绝对米制尺度',
    'synthetic_simulation': '合成仿真', 'laboratory': '实验室',
    'natural_environment': '自然环境', 'not_known': '未知平移',
    'none': '无', 'not_demonstrated': '未证明', 'demonstrated_under_conditions': '条件下已论证',
    'forward_citation': '施引发现', 'backward_citation': '参考文献发现',
    'author_tracking': '作者追踪', 'institution_project': '机构 / 项目追踪',
    'institution_tracking': '机构追踪', 'project_tracking': '项目追踪', 'seed': '种子',
    'project_output': '项目成果', 'funded_by': '资助关系',
    'metadata': '书目', 'fulltext': '全文', 'abstract': '摘要', 'references': '参考文献',
    'citations': '施引', 'authors': '作者', 'affiliations_projects': '机构 / 项目',
    'assessment': '证据评估', 'file_available': '全文文件已取得',
    'bibliographic_only': '仅版本书目', 'version_of_record': '正式出版版本',
    'accepted_manuscript': '录用稿', 'institutional_copy': '机构存档',
}


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def label(value):
    return LABELS.get(str(value), str(value if value is not None else '未记录'))


def link(url, text):
    if isinstance(url, str) and urlsplit(url).scheme.lower() in {'https', 'http'}:
        return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)} ↗</a>'
    return esc(text)


def tag(value, kind=''):
    return f'<span class="tag {esc(kind)}" title="{esc(value)}">{esc(label(value))}</span>'


def details(title, body, cls=''):
    return f'<details class="{esc(cls)}"><summary>{esc(title)}</summary>{body}</details>'


def uniq(values):
    return list(dict.fromkeys(values))


def read_dataset(name, base):
    # The helper resolves complete files and manifest-ordered physical partitions.
    return read_logical(name + '.jsonl', base=base)


def current_tasks(records):
    # JSONL order is the audit event order, including manifest-ordered partitions.
    latest = {}
    for record in records:
        latest[record['task_id']] = record
    return latest


def strip_provenance(value):
    if isinstance(value, list):
        return [strip_provenance(x) for x in value]
    if isinstance(value, dict):
        return {k: strip_provenance(v) for k, v in value.items()
                if k not in {'evidence_locator', 'source_locator', 'field_states',
                             'unknown_since_utc', 'review_task_id'} and v is not None}
    return value


def readable(value):
    """Render typed values without confusing unknown and not_reported."""
    if value is None:
        return '<span class="muted">未记录</span>'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, dict) and 'status' in value and 'value' in value:
        body = readable(value['value']) if value['status'] == 'reported' else tag(value['status'])
        if value.get('reason'):
            body += '<div class="muted">' + esc(value['reason']) + '</div>'
        return body
    if isinstance(value, dict):
        value = strip_provenance(value)
        return '<dl class="typed">' + ''.join(
            '<dt>' + esc(label(k)) + '</dt><dd>' + readable(v) + '</dd>'
            for k, v in value.items()) + '</dl>'
    if isinstance(value, list):
        if not value:
            return '<span class="muted">无记录</span>'
        if all(not isinstance(x, (dict, list)) for x in value):
            return '；'.join(esc(label(x)) for x in value)
        return '<ul class="compact">' + ''.join('<li>' + readable(x) + '</li>' for x in value) + '</ul>'
    return esc(label(value))


class View:
    def __init__(self, base, checkpoint=None):
        self.base = Path(base)
        self.scope = json.loads((self.base / 'snapshots/scope.json').read_text())
        names = ['works', 'versions', 'uploads', 'authors', 'organizations', 'projects',
                 'project-relations', 'assessments', 'citation-edges', 'tasks', 'queries', 'seed-manifest']
        self.data = {name: read_dataset(name, self.base) for name in names}
        self.works = sorted(self.data['works'], key=lambda x: x['work_key'])
        self.by_key = {w['work_key']: w for w in self.works}
        self.by_id = {w['work_id']: w for w in self.works}
        if len(self.by_key) != len(self.works) or len(self.by_id) != len(self.works):
            raise ValueError('Canonical Work IDs/keys are not unique; refuse an ambiguous view.')
        self.orgs = {x['org_id']: x for x in self.data['organizations']}
        self.people = {x['person_id']: x for x in self.data['authors']}
        self.versions = defaultdict(list)
        self.v_by_id = {}
        for v in self.data['versions']:
            self.versions[v['work_id']].append(v)
            self.v_by_id[v['version_id']] = v
        self.assessments = defaultdict(list)
        self.groups = defaultdict(lambda: defaultdict(list))
        self.active = []
        self.eligible = []
        for a in sorted(self.data['assessments'], key=lambda x: x['assessment_id']):
            if a.get('assessment_status') != 'active':
                continue
            if a['work_key'] not in self.by_key:
                raise ValueError('Assessment has no canonical Work: ' + a['assessment_id'])
            self.active.append(a)
            self.assessments[a['work_key']].append(a)
            if (a.get('evidence_admission_status') == 'eligible'
                    and SUBSTANTIVE.intersection(a.get('relation_type', []))):
                if a['limitation_id'] not in {f'L{i:02}' for i in range(1, 10)}:
                    raise ValueError('Invalid limitation ID: ' + a['assessment_id'])
                self.groups[a['limitation_id']][a['work_key']].append(a)
                self.eligible.append(a)
        self.topic_union = set().union(*(set(x) for x in self.groups.values())) if self.groups else set()
        self.u = set(self.by_key) - self.topic_union
        self.themes = {key: [f'L{i:02}' for i in range(1, 10) if key in self.groups[f'L{i:02}']]
                       for key in self.by_key}
        self.anchors = {key: self.row_id(key, (self.themes[key] or ['U00'])[0]) for key in self.by_key}
        self.tasks = current_tasks(self.data['tasks'])
        self.tasks_by_work = defaultdict(list)
        amap = {a['assessment_id']: a['work_id'] for a in self.data['assessments']}
        for task in self.tasks.values():
            wid = task['entity_id'] if task['entity_id'] in self.by_id else amap.get(task['entity_id'])
            if wid:
                self.tasks_by_work[wid].append(task)
        self.pending = [t for t in self.tasks.values() if t['task_state'] not in TERMINAL_TASKS]
        self.checkpoint = checkpoint or max((t.get('checkpoint_id', '') for t in self.tasks.values()), default='未记录')
        self.edges_out = defaultdict(list)
        self.edges_in = defaultdict(list)
        for edge in sorted(self.data['citation-edges'], key=lambda x: x['edge_id']):
            self.edges_out[edge['citing_key']].append(edge)
            self.edges_in[edge['cited_key']].append(edge)
        self.projects = {p['project_id']: p for p in self.data['projects']}
        self.projects_by_work = defaultdict(list)
        for p in self.projects.values():
            for wid in p.get('output_work_ids', []):
                self.projects_by_work[wid].append((p, None))
        for rel in self.data['project-relations']:
            if rel.get('from_id') in self.projects and rel.get('to_id') in self.by_id:
                self.projects_by_work[rel['to_id']].append((self.projects[rel['from_id']], rel))
            elif rel.get('to_id') in self.projects and rel.get('from_id') in self.by_id:
                self.projects_by_work[rel['from_id']].append((self.projects[rel['to_id']], rel))
        self.query_times = sorted(set(q['queried_at_utc'] for q in self.data['queries']
                                     if q.get('query_time_status') == 'exact' and q.get('queried_at_utc')))
        self.seed_records = [s for s in self.data['seed-manifest'] if s.get('record_type') == 'seed_mapping']
        self.seed_ids = sorted({s['seed_id'] for s in self.seed_records})
        self.seed_works = [self.by_id[x] for x in sorted({s['work_id'] for s in self.seed_records}) if x in self.by_id]

    @staticmethod
    def row_id(key, theme):
        return 'work-' + hashlib.sha256(key.encode()).hexdigest()[:14] + '-' + theme

    def work_link(self, key):
        return '<a href="#' + esc(self.anchors[key]) + '">' + esc(key) + '</a>' if key in self.anchors else esc(key)

    def entity_name(self, eid):
        if eid in self.by_id:
            return self.work_link(self.by_id[eid]['work_key'])
        if eid in self.people:
            return esc(self.people[eid].get('canonical_name') or self.people[eid].get('display_name') or eid)
        if eid in self.orgs:
            return esc(self.orgs[eid]['canonical_name'])
        if eid in self.projects:
            return esc(self.projects[eid]['canonical_name'])
        return esc(eid)

    def org_label(self, oid):
        seen, parts = set(), []
        while oid and oid not in seen:
            seen.add(oid)
            org = self.orgs.get(oid)
            if not org:
                parts.append(oid)
                break
            parts.append(org['canonical_name'])
            oid = org.get('parent_org_id')
        return ' → '.join(parts)

    def locators(self, locators):
        rows, seen = [], set()
        for loc in locators or []:
            sig = json.dumps(loc, ensure_ascii=False, sort_keys=True)
            if sig in seen:
                continue
            seen.add(sig)
            parts = []
            if loc.get('version_id'):
                parts.append(esc(loc['version_id']))
            for field, prefix in [('page', '页 '), ('section', '§ '), ('figure', '图 '),
                                  ('equation', '式 '), ('paragraph', '段 '), ('xpath', 'XML '),
                                  ('element_id', '节点 ')]:
                if loc.get(field) is not None:
                    parts.append(esc(prefix + str(loc[field])))
            url = loc.get('url') or self.v_by_id.get(loc.get('version_id'), {}).get('url')
            parts.append(link(url, loc.get('source_id', '原文来源')))
            if loc.get('evidence_note'):
                parts.append('<span class="muted">' + esc(loc['evidence_note']) + '</span>')
            rows.append('<li>' + ' · '.join(parts) + '</li>')
        return '<ul class="locators">' + ''.join(rows) + '</ul>' if rows else '<p class="muted">未登记定位。</p>'

    def bibliography(self, w):
        authors = '; '.join(a.get('display_name', '') for a in w.get('authors', [])) or '作者待核验'
        body = '<strong>' + esc(w['canonical_title']) + '</strong><div class="authors">' + esc(authors) + '</div>'
        body += '<div class="meta">' + esc(w.get('year') or '年份待核验') + ' · ' + esc(w.get('venue') or '来源待核验') + '</div>'
        body += '<div>' + tag(w.get('document_type')) + tag(w.get('publication_status')) + '</div>'
        body += link(w.get('url') or ('https://doi.org/' + w['doi'] if w.get('doi') else ''), w.get('doi') or '书目来源')
        available = [v for v in self.versions[w['work_id']] if v.get('version_materialization') == 'file_available']
        if available:
            body += details('全文版本 / 出处', '<ul class="compact">' + ''.join(
                '<li>' + link(v.get('url'), v['version_id']) + ' · ' + esc(label(v.get('version_type')))
                + ' · ' + esc(v.get('version_date') or '日期未记录') + '</li>' for v in available) + '</ul>')
        return body

    def authors(self, w):
        items = []
        for a in w.get('authors', []):
            orgtext = '；'.join(self.org_label(oid) for oid in a.get('organization_ids', []))
            if not orgtext:
                state = a.get('field_states', {}).get('organization_ids', {}).get('status', 'unknown')
                orgtext = '署名机构：' + label(state)
            person = self.people.get(a.get('person_id'), {})
            status = person.get('disambiguation_status', person.get('verification_status', 'unknown'))
            item = '<li><b>' + esc(a.get('display_name', '作者待核验')) + '</b><br>' + esc(orgtext)
            item += '<div class="meta">消歧 / 核验：' + esc(label(status)) + '</div>'
            history = [h for h in person.get('affiliation_history', []) if h.get('work_id') != w['work_id']]
            if history:
                # These are source observations; an undated record is not a current appointment.
                history_rows = []
                for h in history:
                    text = self.org_label(h.get('org_id')) + ' · ' + str(h.get('valid_from') or '起期未记录') + ' — ' + str(h.get('valid_to') or '止期未记录')
                    if h.get('work_id') in self.by_id:
                        text += ' · 依据 ' + self.by_id[h['work_id']]['work_key']
                    history_rows.append(text)
                item += details('其他署名 / 历史记录', '<ul class="compact">' + ''.join('<li>' + esc(x) + '</li>' for x in uniq(history_rows)) + '</ul>')
            items.append(item + '</li>')
        return details(str(len(items)) + ' 位作者 · 署名与消歧', '<ul class="bylines">' + ''.join(items) + '</ul><p class="muted">署名和历史记录不自动代表现任机构。</p>')

    def abstracts(self, w):
        status = w.get('abstract_status', 'abstract_missing')
        items = [a for a in w.get('abstract_items', []) if a.get('text')]
        if not items:
            return tag(status, 'warning') + '<p class="muted">尚无可公开展示的摘要或中文概括；未根据题名补写。</p>'
        body = []
        for a in items:
            content = '<p>' + esc(a['text']).replace('\n', '<br>') + '</p>'
            content += '<div class="meta">版本：' + esc(a.get('version_id') or '未记录')
            content += '<br>概括 / 署名：' + esc(a.get('summarizer') or '原作者') + ' · ' + esc(a.get('date') or '日期未记录')
            content += '<br>许可：' + esc(a.get('license') or '见来源许可记录') + '</div>'
            source = a.get('source') or {}
            content += link(source.get('url'), '摘要依据来源')
            content += self.locators(source.get('evidence_locator', []))
            body.append(details(label(a.get('status', status)), content, 'abstract'))
        return ''.join(body)

    def sources(self, w):
        body = ''.join('<code class="tag">' + esc(s) + '</code>' for s in w.get('seed_ids', []))
        steps = w.get('discovery_path') or []
        if steps:
            body += details('发现链路 · ' + str(len(steps)) + ' 步', '<ol class="compact">' + ''.join(
                '<li>' + self.entity_name(s.get('from_entity_id')) + ' → ' + self.entity_name(s.get('to_entity_id'))
                + '<br>' + tag(s.get('discovery_route')) + tag(s.get('verification_status'))
                + self.locators(s.get('evidence_locator', [])) + '</li>' for s in steps) + '</ol>')
        elif w.get('seed_ids'):
            body += '<p class="muted">§2.2 固定种子映射。</p>'
        else:
            body += '<p class="muted">发现路径见规范记录。</p>'
        sources, seen = [], set()
        for s in w.get('discovery_sources', []):
            sig = (s.get('source_id'), s.get('url'), s.get('accessed_at'))
            if sig in seen:
                continue
            seen.add(sig)
            sources.append('<li>' + link(s.get('url'), s.get('source_id') or '来源') + '<br><span class="meta">'
                           + esc(s.get('accessed_at') or '时点未记录') + ' · ' + esc(label(s.get('verification_status'))) + '</span></li>')
        body += details('书目来源 · ' + str(len(sources)), '<ul class="compact">' + ''.join(sources) + '</ul>')
        return body

    def findings(self, assessments):
        return ''.join(details(a['assessment_id'], '<p><b>方法：</b>' + esc(a.get('method') or '见原文定位')
                       + '</p><p><b>结果：</b>' + esc(a.get('results') or a.get('effect') or '未记录')
                       + '</p><p><b>基线：</b>' + esc(a.get('baseline') or '见条件 / 对照记录')
                       + '</p><p><b>效果：</b>' + esc(a.get('effect') or '未记录') + '</p>', 'evidence')
                       for a in assessments)

    def assessment(self, a):
        state = a.get('evidence_admission_status')
        body = '<div>' + tag(a.get('evidence_route')) + tag(a.get('handling_level')) + tag(state, 'good' if state == 'eligible' else 'warning') + '</div>'
        body += '<p class="meta">' + '；'.join(esc(label(x)) for x in a.get('relation_type', []))
        body += ' · ' + esc(label(a.get('evidence_level'))) + ' · ' + esc(label(a.get('statement_basis'))) + '</p>'
        if a.get('counter_evidence'):
            body += '<p class="counter"><b>反证 / 矛盾：</b>' + '；'.join(esc(label(x)) for x in a.get('counter_evidence_types', [])) + '</p>'
        if a.get('rejection_codes'):
            body += '<p class="counter"><b>拒收代码：</b>' + '；'.join('<code>' + esc(x) + '</code>' for x in a['rejection_codes']) + '</p>'
        body += details('实验条件与尺度门禁', readable(a.get('conditions', {}))
                        + '<p><b>绝对尺度主张：</b>' + readable(a.get('claims_absolute_scale')) + '</p>'
                        + '<p><b>尺度来源：</b>' + readable(a.get('scale_prior_details', [])) + '</p>'
                        + '<p><b>测量模型：</b>' + esc(a.get('measurement_model') or '未记录 / 不适用') + '</p>'
                        + '<p><b>剩余自由度：</b>' + readable(a.get('gauge_freedoms', [])) + '</p>'
                        + self.locators(a.get('observability_argument_locator', [])), 'evidence')
        metrics = a.get('metric_records') or []
        metric_body = ''.join('<li><strong>' + esc(m.get('value')) + ' ' + esc(m.get('unit') or '')
                              + '</strong> · ' + esc(m.get('definition') or m.get('metric_name'))
                              + '<div class="meta">' + esc(m.get('metric_id')) + ' · ' + esc(m.get('statistic'))
                              + ' · 数据 ' + esc(m.get('dataset_id') or '不适用')
                              + ' · n=' + esc(m.get('sample_count') if m.get('sample_count') is not None else label(m.get('field_states', {}).get('sample_count', {}).get('status', 'unknown')))
                              + ' · 对齐 ' + esc(m.get('alignment', '未记录')) + '</div>'
                              + self.locators(m.get('evidence_locator', [])) + '</li>' for m in metrics)
        body += details('量化指标 / 推导 · ' + str(len(metrics)) + ' 项', '<ul class="compact">' + metric_body + '</ul>'
                        + (readable(a['proof_record']) if a.get('proof_record') else '<p class="muted">未另登记数学证明；按本条证据类型评价。</p>'), 'evidence')
        body += details('数据集、对照与条件层级', readable(a.get('dataset_records', [])) + readable(a.get('baseline_records', []))
                        + readable(a.get('condition_levels', [])), 'evidence')
        body += '<p><b>剩余问题：</b>' + esc(a.get('remaining_limitations') or '未记录') + '</p>'
        body += details('生物与工程启示', '<p><b>生物：</b>' + esc(a.get('biological_implications') or '无相关证据')
                        + '</p><p><b>工程：</b>' + esc(a.get('engineering_implications') or '无相关证据') + '</p>', 'evidence')
        return details(a['assessment_id'] + ' · ' + a['limitation_id'], body, 'evidence assessment-detail')

    def citations(self, w):
        key = w['work_key']
        body = '<p class="meta">引用关系本身不证明改进；引用作用须以语境核验。</p>'
        for heading, edges, other in [('引用前作', self.edges_out[key], 'cited_key'), ('被文献引用', self.edges_in[key], 'citing_key')]:
            groups = defaultdict(list)
            context_rows = []
            for edge in edges:
                signature = (edge.get('verification_status', 'unknown'), tuple(sorted(edge.get('citation_roles') or ['unknown'])))
                groups[signature].append(edge[other])
                if edge.get('context_locators'):
                    context_rows.append('<li>' + self.work_link(edge[other]) + self.locators(edge['context_locators']) + '</li>')
            content = ''
            for (status, roles), keys in sorted(groups.items()):
                content += '<p class="meta">关系：' + esc(label(status)) + '；作用：' + ' / '.join('待核验' if r == 'unknown' else esc(label(r)) for r in roles) + '</p>'
                content += '<p class="keylist">' + ' · '.join(self.work_link(k) for k in sorted(set(keys))) + '</p>'
            if context_rows:
                content += details('引用语境与定位', '<ul class="compact">' + ''.join(context_rows) + '</ul>', 'evidence')
            body += details(heading + ' · ' + str(len({e[other] for e in edges})) + ' 篇', content or '<p class="muted">当前快照未登记；不表示不存在。</p>')
        return body

    def project_details(self, w):
        groups = defaultdict(list)
        for p, relation in self.projects_by_work[w['work_id']]:
            groups[p['project_id']].append(relation)
        if not groups:
            return '<p class="muted">当前未登记经核验项目关系；不据同机构推断同项目。</p>'
        body = ''
        for pid in sorted(groups):
            p = self.projects[pid]
            relations = [r for r in groups[pid] if r]
            content = '<p>' + link(p.get('url'), p['canonical_name']) + '</p><p>编号：' + esc(p.get('grant_id') or '未报告')
            content += '<br>时间：' + esc(p.get('start_date') or '未报告') + ' — ' + esc(p.get('end_date') or '未报告') + '</p>'
            content += '<p>' + '；'.join(esc(self.org_label(x)) for x in p.get('org_ids', [])) + '</p>'
            content += '<p>' + tag(p.get('project_relation')) + ' '.join(tag(r.get('relation_type')) for r in relations) + '</p>'
            content += self.locators([loc for r in relations for loc in r.get('evidence_locator', [])] or p.get('evidence_locator', []))
            body += details(p['canonical_name'], content)
        return body

    def states(self, w, theme):
        ft = w.get('fulltext_status', 'pending')
        ab = w.get('abstract_status', 'abstract_missing')
        ft_display = '全文待获取' if ft == 'pending' else label(ft)
        body = '<span class="tag ' + ('good' if ft == 'available_verified' else 'warning') + '" title="' + esc(ft) + '">' + esc(ft_display) + '</span>'
        body += tag(ab, 'warning' if ab in {'abstract_missing', 'abstract_restricted'} else '')
        dims = '<dl class="typed">' + ''.join('<dt>' + esc(label(k)) + '</dt><dd>' + tag(v) + '</dd>' for k, v in w.get('dimension_status', {}).items()) + '</dl>'
        dims += '<p class="muted">全文可读与全部科学主张已验证分别计数。</p>'
        body += details('分维度处理状态', dims)
        assessments = self.assessments[w['work_key']]
        shown = assessments if theme == 'U00' else [a for a in assessments if a['limitation_id'] == theme]
        if shown:
            body += details('原文定位与核验记录', ''.join('<h3>' + esc(a['assessment_id']) + '</h3>'
                            + '<p class="meta">' + esc(a.get('reviewer')) + ' · ' + esc(a.get('date')) + ' · ' + esc(label(a.get('verification_status'))) + '</p>'
                            + self.locators(a.get('evidence_locator', [])) for a in shown), 'evidence')
        other = assessments if theme == 'U00' else [a for a in assessments if a['limitation_id'] != theme]
        if other:
            body += details('其他 / 不足证据主张 · ' + str(len(other)), ''.join(self.findings([a]) + self.assessment(a) for a in other), 'evidence')
        versions = sorted(self.versions[w['work_id']], key=lambda x: x['version_id'])
        version_body = '<ul class="compact">' + ''.join('<li><code>' + esc(v['version_id']) + '</code> · ' + esc(label(v.get('version_type')))
                        + ' · ' + esc(label(v.get('version_materialization'))) + ' · ' + esc(v.get('version_date') or '日期未记录') + '</li>' for v in versions) + '</ul>'
        if w.get('notes'):
            version_body += '<p>' + esc(w['notes']).replace('\n', '<br>') + '</p>'
        body += details('版本与书目说明', version_body)
        if theme == 'U00':
            body += details('引用与项目记录', self.citations(w) + self.project_details(w))
        return body

    def next_actions(self, w):
        tasks = sorted((t for t in self.tasks_by_work[w['work_id']] if t['task_state'] not in TERMINAL_TASKS), key=lambda x: x['task_id'])
        text = '<p>' + esc(w.get('review_condition') or '按原文、身份及主题门禁复核；不得仅凭摘要形成覆盖结论。') + '</p>'
        if tasks:
            # Group repeated review conditions while retaining every current task ID.
            # Rendering tens of thousands of identical reason paragraphs obscures
            # the actual gaps and needlessly inflates the offline document.
            groups = defaultdict(list)
            for task in tasks:
                groups[(task['task_state'], task.get('failure_reason') or task.get('review_condition') or '')].append(task)
            body = '<ul class="compact">'
            for (state, reason), group in sorted(groups.items()):
                types = Counter(label(t['task_type']) for t in group)
                body += '<li>' + tag(state) + ' · ' + esc('；'.join(f'{k} {v}' for k, v in sorted(types.items())))
                body += '<p class="muted">' + esc(reason) + '</p><code>' + esc(' · '.join(t['task_id'] for t in group)) + '</code></li>'
            body += '</ul>'
            text += details('当前未解决任务 · ' + str(len(tasks)), body)
        return text

    def row(self, w, theme):
        key = w['work_key']
        all_a = self.assessments[key]
        a_for_theme = [a for a in all_a if a['limitation_id'] == theme]
        statuses = set(w.get('u00_reasons', []))
        if theme != 'U00':
            statuses.add('eligible')
        if any(a.get('counter_evidence') for a in a_for_theme):
            statuses.add('counter_evidence')
        if any(a.get('evidence_admission_status') == 'insufficient_evidence' for a in all_a):
            statuses.add('insufficient_evidence')
        if w.get('dimension_status', {}).get('assessment') != 'verified_complete':
            statuses.add('pending_assessment')
        statuses.add('fulltext_available' if w.get('fulltext_status') == 'available_verified' else 'fulltext_pending')
        statuses.add(w.get('abstract_status', 'abstract_missing'))
        orgs = ' '.join(self.org_label(oid) for a in w.get('authors', []) for oid in a.get('organization_ids', []))
        search = ' '.join(str(x) for x in [key, w['canonical_title'], w.get('year') or '', w.get('doi') or '', orgs, theme,
                      ' '.join(w.get('seed_ids', [])), ' '.join(a.get('display_name', '') for a in w.get('authors', [])),
                      ' '.join(w.get('title_variants', [])), ' '.join(x.get('text') or '' for x in w.get('abstract_items', [])),
                      ' '.join(a.get('method', '') + ' ' + a.get('effect', '') for a in all_a)])
        cells = ['<th scope="row"><code>' + esc(key) + '</code>' + ''.join('<span class="seed">' + esc(s) + '</span>' for s in w.get('seed_ids', [])) + '</th>']
        common = [self.bibliography(w), self.authors(w), self.abstracts(w), self.sources(w)]
        if theme != 'U00':
            rest = [self.findings(a_for_theme), ''.join(self.assessment(a) for a in a_for_theme), self.citations(w),
                    self.project_details(w), self.states(w, theme)]
        else:
            reasons = w.get('u00_reasons') or ['pending_assessment']
            rest = [self.states(w, theme), ''.join(tag(r, 'warning' if r == 'insufficient_evidence' else '') for r in reasons), self.next_actions(w)]
        cells += ['<td>' + x + '</td>' for x in common + rest]
        return '<tr id="' + self.row_id(key, theme) + '" data-key="' + esc(key) + '" data-theme="' + theme + '" data-status="' + esc(' '.join(sorted(statuses))) + '" data-year="' + esc(w.get('year') or '') + '" data-search="' + esc(search.casefold()) + '">' + ''.join(cells) + '</tr>'

    def section(self, theme, title):
        keys = sorted(self.u if theme == 'U00' else self.groups[theme])
        columns = U_COLUMNS if theme == 'U00' else TOPIC_COLUMNS
        table_id = 'literature-U00' if theme == 'U00' else 'limitation-' + theme
        head = ''.join('<th scope="col">' + (f'<button class="sort" data-sort="{"key" if i == 0 else "year"}" aria-label="按{"索引" if i == 0 else "年份"}排序">{esc(c)} ↕</button>' if i in {0, 1} else esc(c)) + '</th>' for i, c in enumerate(columns))
        rows = ''.join(self.row(self.by_key[key], theme) for key in keys)
        if not rows:
            rows = '<tr class="empty"><td colspan="' + str(len(columns)) + '">当前快照无合格主题证据；这不证明该方向不存在研究。</td></tr>'
        if theme == 'U00':
            note = '本表为 K 中尚未进入任何 L 表的文献，含背景、待评估、证据不足及独立可引用资源；与九张主题表互斥。'
        else:
            n = sum(len(x) for x in self.groups[theme].values())
            negative = sum(a.get('counter_evidence', False) for values in self.groups[theme].values() for a in values)
            note = f'{n} 条合格主题主张，其中 {negative} 条明确标注反证 / 矛盾。基础支持、条件性进展和反证均可入表；入表不等于局限性已解决。'
        return '<section id="section-' + theme + '" class="topic-section" data-theme="' + theme + '"><header class="section-title"><div><span class="eyebrow">' + ('LITERATURE REGISTER' if theme == 'U00' else 'LIMITATION ' + theme[1:]) + '</span><h2>' + theme + ' · ' + esc(title) + '</h2></div><span class="count">' + str(len(keys)) + ' 篇</span></header><p class="muted">' + esc(note) + '</p><div class="table-scroll"><table id="' + table_id + '"><caption>' + theme + ' · ' + esc(title) + '</caption><thead><tr>' + head + '</tr></thead><tbody>' + rows + '</tbody></table></div><p class="section-empty muted" hidden>本表没有符合当前筛选的记录。</p></section>'

    def completion(self, works):
        n = len(works)
        ft = sum(w.get('fulltext_status') == 'available_verified' for w in works)
        ab = sum(any(a.get('text') for a in w.get('abstract_items', [])) and w.get('abstract_status') not in {'abstract_missing', 'abstract_restricted'} for w in works)
        zh = sum(any(a.get('text') and a.get('status') in {'chinese_summary_from_fulltext', 'chinese_summary_from_abstract'} for a in w.get('abstract_items', [])) for w in works)
        dims = {d: Counter(w.get('dimension_status', {}).get(d, 'pending') for w in works) for d in ['metadata', 'references', 'citations', 'assessment']}
        ratio = lambda x: f'{x}/{n}（{100*x/n:.1f}%）' if n else '0/0（无分母）'
        text = '全文可用且完整性已核验 ' + ratio(ft) + '；可展示摘要 ' + ratio(ab) + '；中文概括 ' + ratio(zh) + '。'
        text += ' '.join(label(d) + '：完成 ' + str(c['verified_complete']) + '，确无 ' + str(c['verified_none']) + '，不适用 ' + str(c['not_applicable']) + '，部分完成 ' + str(c['partial']) + ' / 总数 ' + str(n) + '。' for d, c in dims.items())
        return text

    def summary(self):
        hashes = {u['sha256'] for u in self.data['uploads'] if u.get('sha256')}
        hashes.update(f['sha256'] for v in self.data['versions'] for f in v.get('file_records', []) if f.get('sha256'))
        return {
            'scope_id': self.scope['scope_id'], 'checkpoint_id': self.checkpoint,
            'cutoff_at_utc': self.scope.get('cutoff_at_utc'),
            'query_range_utc': [self.query_times[0], self.query_times[-1]] if self.query_times else [],
            'K': len(self.by_key), 'U': len(self.u),
            'T': {f'L{i:02}': len(self.groups[f'L{i:02}']) for i in range(1, 10)},
            'topic_union': len(self.topic_union), 'table_rows': len(self.u) + sum(len(x) for x in self.groups.values()),
            'seed_records': len(self.seed_ids), 'seed_works': len(self.seed_works),
            'uploads': len(self.data['uploads']), 'distinct_file_hashes': len(hashes),
            'versions': len(self.data['versions']), 'active_assessments': len(self.active),
            'eligible_assessments': len(self.eligible),
            'insufficient_assessments': sum(a.get('evidence_admission_status') == 'insufficient_evidence' for a in self.active),
            'latest_tasks': len(self.tasks), 'task_events': len(self.data['tasks']),
            'unresolved_tasks': len(self.pending), 'citation_edges': len(self.data['citation-edges']),
            'closure_claim': False,
        }

    def document(self):
        stats = self.summary()
        # Reuse the established index style; additions support genuine populated tables.
        css = (Path(__file__).resolve().parent / 'index-base.css').read_text()
        css += '\n' + EXTRA_CSS
        cards = [('规范 Work', stats['K']), ('主题文献（去重）', stats['topic_union']), ('U00 文献', stats['U']),
                 ('合格主张', stats['eligible_assessments']), ('不足证据主张', stats['insufficient_assessments']), ('未解决任务', stats['unresolved_tasks'])]
        card_html = ''.join('<div class="stat"><span>' + esc(k) + '</span><strong>' + esc(f'{v:,}') + '</strong></div>' for k, v in cards)
        topics = '；'.join(f'{k} = {v}' for k, v in stats['T'].items())
        date_text = (' — '.join(self.query_times[::max(1, len(self.query_times)-1)]) if self.query_times else '尚无精确时点查询记录')
        source_names = sorted({q.get('source_id') or '未记录来源' for q in self.data['queries']})
        coverage = '<div class="coverage"><p><strong>集合对账：</strong>K = ' + str(stats['K']) + '；U = ' + str(stats['U']) + '；主题并集 = ' + str(stats['topic_union']) + '。K = U ∪ T₁ ∪ … ∪ T₉；U 与主题表互斥。<br>' + esc(topics) + '。跨主题行数相加不等于独立 Work 数。</p>'
        coverage += '<p><strong>种子口径：</strong>按 §2.2 / seed-manifest，共 ' + str(stats['seed_records']) + ' 条种子记录，映射 ' + str(stats['seed_works']) + ' 个规范 Work。' + esc(self.completion(self.seed_works)) + '</p>'
        coverage += '<p><strong>全库口径：</strong>' + esc(self.completion(self.works)) + '</p>'
        coverage += '<p><strong>实体与主张：</strong>Upload ' + str(stats['uploads']) + '；不同文件哈希 ' + str(stats['distinct_file_hashes']) + '；Version ' + str(stats['versions']) + '；Person ' + str(len(self.people)) + '；机构及下级单位 ' + str(len(self.orgs)) + '；Project ' + str(len(self.projects)) + '；有效 Assessment ' + str(len(self.active)) + '；引文边 ' + str(stats['citation_edges']) + '。</p>'
        coverage += '<p><strong>任务：</strong>从 ' + str(stats['task_events']) + ' 个事件归并为 ' + str(stats['latest_tasks']) + ' 个当前任务，未解决 ' + str(len(self.pending)) + '。完成、确无、不适用和有依据的范围外任务从未解决数中排除；受限及不可得仍保留为缺口。</p>'
        coverage += '<p><strong>范围与来源：</strong>仅声称冻结快照与已披露来源内的覆盖；当前不声称递归闭包或全部文献穷尽。查询来源：' + esc('、'.join(source_names)) + '。索引关系、全文可用性和科学结论分别核验。<a href="temp/snapshots/scope.json">来源准入与冻结范围</a> · <a href="temp/progress.md">阶段进度与缺口</a></p></div>'
        nav = ''.join('<a href="#section-L' + f'{i:02}' + '">L' + f'{i:02}' + ' <span>' + str(stats['T'][f'L{i:02}']) + '</span></a>' for i in range(1, 10)) + '<a href="#section-U00">U00 <span>' + str(stats['U']) + '</span></a>'
        theme_options = ''.join(f'<option value="L{i:02}">L{i:02} · {esc(title)}</option>' for i, title in enumerate(TITLES, 1)) + '<option value="U00">U00 · 其他与待分类</option>'
        state_options = [('eligible', '合格主题证据'), ('counter_evidence', '反证 / 矛盾'), ('insufficient_evidence', '含不足证据主张'),
                         ('pending_assessment', '证据评估未完成'), ('fulltext_available', '全文可用已核验'), ('fulltext_pending', '全文待获取 / 待核验'),
                         ('abstract_missing', '摘要缺失'), ('abstract_restricted', '摘要受限')]
        toolbar = '<div class="toolbar"><div class="controls"><label class="control">搜索文献<input id="search" type="search" placeholder="索引、题名、作者、年份、机构或关键词" autocomplete="off"></label><label class="control">主题<select id="theme"><option value="all">全部主题与 U00</option>' + theme_options + '</select></label><label class="control">处理状态<select id="status"><option value="all">全部状态</option>' + ''.join('<option value="' + value + '">' + text + '</option>' for value, text in state_options) + '</select></label><button id="clear">清除筛选</button><button id="toggle-abstracts" aria-pressed="false">展开全部摘要</button><button id="toggle-evidence" aria-pressed="false">展开证据详情</button></div><nav class="theme-nav" aria-label="主题目录">' + nav + '</nav><div class="statusline"><span id="search-status" role="status" aria-live="polite">显示全部 ' + str(stats['K']) + ' 个独立 Work，共 ' + str(stats['table_rows']) + ' 个主题 / U00 行。</span><span><a href="ref.bib" download>下载 BibTeX</a> · <a href="temp/exports/evidence_matrix.csv">证据矩阵</a> · <a href="temp/exports/citation_graph.json">引文网络</a> · <a href="temp/progress.md">进度</a></span></div><p class="meta">同一 Work 可有多个状态；例如某主题证据合格，同时另一个主张证据不足。摘要与证据展开可独立控制。</p><noscript><p class="no-js">JavaScript 未启用：十张表、全部条目和原生详情仍可阅读，筛选与排序不可用。</p></noscript></div>'
        sections = ''.join(self.section(f'L{i:02}', title) for i, title in enumerate(TITLES, 1)) + self.section('U00', '其他、背景与待分类文献')
        summary_json = json.dumps(stats, ensure_ascii=False, sort_keys=True).replace('<', '\\u003c')
        return '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Insect-Inspired · 文献与证据索引</title><style>' + css + '</style></head><body id="top"><header class="hero"><span class="eyebrow">INSECT-INSPIRED / RESEARCH REGISTER</span><h1>昆虫启发的视觉自运动估计</h1><p class="lead">九项局限性的证据、反证与研究链路。按 Work 阅读，按主张核验；结果保留适用条件与未解决问题。</p><div class="snapshot"><span>作用域 <code>' + esc(self.scope['scope_id']) + '</code></span><span>检查点 <code>' + esc(self.checkpoint) + '</code></span><span>文献截止 ' + esc(self.scope.get('cutoff_at_utc', '未记录')) + '</span><span>已记录精确查询时段 ' + esc(date_text) + '</span></div><div class="stats">' + card_html + '</div>' + coverage + '</header>' + toolbar + '<main>' + sections + '<p id="empty-search" hidden>没有符合当前搜索条件的记录。</p></main><footer>由 temp/ 规范结构化数据确定性生成；分片数据按 manifest 顺序读取。所有书目 key 与 ref.bib 对账；全文文件未包含在此索引中。可读全文、摘要、引用关系和科学证据分别记录，未取得证据不等于不存在。</footer><a class="back" href="#top">↑ 返回顶部</a><script id="database-summary" type="application/json">' + summary_json + '</script><script>' + SCRIPT + '</script></body></html>\n'


EXTRA_CSS = r'''
.stat strong{font-size:clamp(21px,2.3vw,28px)}h3{font-size:12px;margin:12px 0 6px}.seed{display:block;font-size:10px;font-weight:normal;color:var(--muted);margin-top:5px}.typed{margin:10px 0}.typed dt{font-size:11px;font-weight:650;color:#3c565a;margin-top:7px}.typed dd{margin:1px 0 8px;padding-left:9px;border-left:2px solid #e1ebe7;overflow-wrap:anywhere}.locators,.compact{padding-left:18px;margin:8px 0}.locators li,.compact li{margin:8px 0;overflow-wrap:anywhere}.locators{font-size:11px;color:var(--muted)}.counter{background:#fff3dd;border-left:3px solid #ad7220;padding:8px 10px}.keylist{font-size:11px;line-height:1.9;overflow-wrap:anywhere}.assessment-detail{border-top:1px solid var(--line);padding-top:8px;margin-top:9px}.theme-nav span{font-variant-numeric:tabular-nums;opacity:.7;margin-left:4px}.topic-section table{min-width:1600px}.topic-section td{min-width:145px;max-width:430px}.topic-section td:nth-child(2){min-width:285px}.topic-section td:nth-child(4){min-width:260px}.topic-section td:nth-child(6){min-width:255px}.topic-section td:nth-child(7){min-width:305px}.topic-section td:nth-child(8){min-width:180px}.topic-section td:nth-child(10){min-width:230px}#literature-U00 td:nth-child(7){min-width:120px}.section-title .count{font-variant-numeric:tabular-nums}.tag{white-space:normal;overflow-wrap:anywhere}details p{overflow-wrap:anywhere}.coverage{max-width:1450px}.coverage p{line-height:1.8}tr:target{outline:3px solid #c69636;outline-offset:-3px}.table-scroll{max-height:76vh;overscroll-behavior:contain}.sort{min-height:25px}.section-empty{margin:10px 0 0}tbody tr{content-visibility:auto;contain-intrinsic-size:auto 220px}@media(max-width:850px){.toolbar{padding-left:18px;padding-right:18px}.table-scroll{max-height:72vh}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat strong{font-size:25px}.topic-section{padding:14px}.snapshot{gap:5px 16px}.coverage{padding:14px}.control:first-child{min-width:100%}}@media print{.table-scroll{max-height:none}.topic-section table{min-width:0}tbody tr{content-visibility:visible}.topic-section td{min-width:0!important}details>summary{font-weight:bold}.topic-section{break-inside:auto}}
'''

SCRIPT = r'''
(()=>{'use strict';
const q=document.querySelector('#search'),theme=document.querySelector('#theme'),state=document.querySelector('#status'),rows=[...document.querySelectorAll('tr[data-key]')],sections=[...document.querySelectorAll('.topic-section')];
const totalKeys=new Set(rows.map(r=>r.dataset.key)).size;
function apply(){const terms=q.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);let n=0;const keys=new Set();
 for(const row of rows){const yes=terms.every(t=>row.dataset.search.includes(t))&&(theme.value==='all'||row.dataset.theme===theme.value)&&(state.value==='all'||row.dataset.status.split(' ').includes(state.value));row.hidden=!yes;if(yes){n++;keys.add(row.dataset.key);}}
 for(const sec of sections){sec.hidden=theme.value!=='all'&&sec.dataset.theme!==theme.value;const local=[...sec.querySelectorAll('tr[data-key]')],visible=local.filter(r=>!r.hidden).length;sec.querySelector('.count').textContent=(visible===local.length?String(local.length):`${visible} / ${local.length}`)+' 篇';sec.querySelector('.section-empty').hidden=visible>0||local.length===0;}
 document.querySelector('#search-status').textContent=`当前显示 ${keys.size} / ${totalKeys} 个独立 Work，${n} / ${rows.length} 个主题或 U00 行。筛选不改变集合对账。`;document.querySelector('#empty-search').hidden=n>0;}
 [q,theme,state].forEach(el=>el.addEventListener(el===q?'input':'change',apply));
 document.querySelector('#clear').addEventListener('click',()=>{q.value='';theme.value='all';state.value='all';apply();q.focus();});
 function toggle(buttonId,selector,openText,closedText){const button=document.querySelector(buttonId);button.addEventListener('click',()=>{const open=button.getAttribute('aria-pressed')!=='true';document.querySelectorAll(selector).forEach(d=>d.open=open);button.setAttribute('aria-pressed',String(open));button.textContent=open?openText:closedText;});}
 toggle('#toggle-abstracts','details.abstract','收起全部摘要','展开全部摘要');toggle('#toggle-evidence','details.evidence','收起证据详情','展开证据详情');
 document.querySelectorAll('.sort').forEach(button=>button.addEventListener('click',()=>{const table=button.closest('table'),tbody=table.tBodies[0],sort=button.dataset.sort,asc=button.dataset.order!=='asc';table.querySelectorAll('th[aria-sort]').forEach(th=>th.removeAttribute('aria-sort'));table.querySelectorAll('.sort').forEach(b=>{if(b!==button)delete b.dataset.order;});button.dataset.order=asc?'asc':'desc';button.closest('th').setAttribute('aria-sort',asc?'ascending':'descending');[...tbody.querySelectorAll('tr[data-key]')].sort((a,b)=>{const x=a.dataset[sort],y=b.dataset[sort];if(sort==='year'&&(!x||!y))return !x&&!y?a.dataset.key.localeCompare(b.dataset.key,'en'):!x?1:-1;const value=sort==='year'?Number(x)-Number(y):x.localeCompare(y,'en');return (value||a.dataset.key.localeCompare(b.dataset.key,'en'))*(asc?1:-1);}).forEach(r=>tbody.appendChild(r));}));
 function revealTarget(){const hash=decodeURIComponent(location.hash.slice(1)),target=hash?document.getElementById(hash):null;if(target&&target.matches('tr[data-key]')){if(target.hidden||target.closest('section').hidden){q.value='';theme.value='all';state.value='all';apply();}target.scrollIntoView({block:'center'});}}
 window.addEventListener('hashchange',revealTarget);revealTarget();
})();
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=ROOT / 'insect-project/temp')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('preview.html'))
    parser.add_argument('--checkpoint')
    parser.add_argument('--summary-output', type=Path)
    args = parser.parse_args()
    view = View(args.base, args.checkpoint)
    output = view.document()
    args.output.write_text(output, encoding='utf-8')
    summary = view.summary()
    if args.summary_output:
        args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'bytes': len(output.encode()), 'sha256': hashlib.sha256(output.encode()).hexdigest(), **summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
