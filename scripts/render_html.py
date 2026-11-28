"""Generate the two offline bibliography pages from the manifest-ordered research data."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
import hashlib
from html import escape
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile, gettempdir
import os

from storage import TEMP, iter_logical

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = "ref-data"
STATIC_FILES = ("index.css", "index.js")
WEB_FILES = ("ref.html", "misc.html", *(f"{ASSET_DIR}/{n}" for n in (*STATIC_FILES, "topics.js", "misc.js")))
DATA_PREFIX = "window.LITERATURE_INDEX="
COLUMNS = ("BibTeX key", "题名", "作者", "年份", "发表来源", "DOI")
MISC_COLUMNS = COLUMNS + ("未分类原因", "下一步动作")
TITLES = {
    "L01": "局部空间结构与运动视差", "L02": "对比度、纹理及空间频率依赖",
    "L03": "瞬态响应与运动适应", "L04": "自然刺激、高速及复杂运动",
    "L05": "VS 细胞感受野与网络机制", "L06": "旋转、平移解耦及运动估计",
    "L07": "饱和平台与速度幅值编码", "L08": "环境距离及飞行统计先验",
    "L09": "Hx 细胞及物种层面的验证",
}
MISC_TITLE = "其他、背景与待分类文献"
SUBSTANTIVE = {"direct_study", "indirect_mitigation", "foundational_support",
               "engineering_application", "independent_progress", "counter_evidence"}
TERMINAL = {"verified_complete", "verified_none", "not_applicable", "out_of_scope"}
REASONS = {
    "background": "背景文献", "unrelated": "主题无关", "pending_assessment": "待评估",
    "insufficient_evidence": "证据不足", "metadata_unverified": "书目待核验",
    "non_academic_resource": "非学术资源", "project_software_dataset_only": "仅项目、软件或数据集",
    "out_of_scope": "范围外", "duplicate_pending_merge": "疑似重复，待核对",
}
# Only these operations have a bibliography/abstract/reference-list route.
ACTIONS = {
    "metadata": "核对书目信息", "abstract": "核对公开摘要", "authors": "核对论文署名",
    "author_disambiguation": "用署名与书目标识核对作者身份",
    "references": "核对参考文献列表", "citations": "核对施引书目索引",
    "reference_identity": "核对参考文献条目的书目身份",
    "reference_identity_mapping_review": "核对参考文献条目的书目身份",
    "cited_version_review": "核对所引版本 DOI 和首发日期", "version_relation_review": "核对出版版本关系",
    "version_gap_review": "核对缺失版本的书目记录", "citation_index_expansion": "核对施引书目索引",
    "citation_source": "核对引文书目来源", "bibliographic_conflict": "核对有冲突的书目字段",
    "affiliations_projects": "核对署名机构及登记资助信息", "affiliation_projects": "核对署名机构及登记资助信息",
    "project_identity_and_output_review": "核对书目登记的项目与成果关联",
    "project_output_bibliography": "核对项目成果书目", "author_publications": "核对作者的其他出版记录",
    "bibliography_boundary_identity_completion": "核对参考文献列表的书目边界",
}
BIB_FIELDS = {
    "doi": "DOI", "eid": "电子文章编号", "number": "期号", "volume": "卷号", "pages": "页码",
    "language": "出版语言", "publisher": "出版者", "venue": "发表来源", "year": "出版年份",
    "publication_date": "出版日期", "canonical_title": "题名", "identifiers": "书目标识",
    "authors": "作者署名", "abstract_items": "摘要书目来源",
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def legacy_anchor(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:14]


def bibliographic_fields(work):
    authors = "、".join(a["display_name"] for a in work.get("authors", []) if a.get("display_name"))
    source = work.get("venue") or work.get("school") or work.get("publisher") or ""
    return [work["work_key"], work["canonical_title"], authors, work.get("year"), source, work.get("doi") or ""]


def task_action(task):
    kind = task["task_type"]
    if kind != "field_review":
        return ACTIONS.get(kind)
    field = task.get("field_path") or ""
    if re.fullmatch(r"authors\.\d+\.organization_ids", field):
        return "核对作者发表时的署名机构"
    if field in BIB_FIELDS:
        return "核对" + BIB_FIELDS[field]
    if re.fullmatch(r"authors\.\d+\.(display_name|person_id|orcid)", field):
        return "核对作者署名和身份"
    return None


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def next_actions(tasks, owners, cutoff):
    """Pick one eligible open task using its persisted priority, deadline and ID."""
    choices, open_works, bibliographic = {}, set(), set()
    ranks = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    for tid, task in tasks.items():
        wid = owners.get(task["entity_id"])
        state = task["task_state"]
        if wid is None or state in TERMINAL:
            continue
        open_works.add(wid)
        action = task_action(task)
        if action is None:
            continue
        bibliographic.add(wid)
        if state not in {"pending", "partial", "needs_disambiguation", "retryable_error"}:
            continue
        retry = instant(task.get("retry_at"))
        if retry and (not cutoff or retry > cutoff):
            continue
        if any(dep not in tasks or tasks[dep]["task_state"] not in TERMINAL for dep in task.get("dependency_ids", [])):
            continue
        due = instant(task.get("deadline_at_utc"))
        rank = (ranks.get(task.get("priority") or "normal", 2), due is None, due, tid)
        if wid not in choices or rank < choices[wid][0]:
            choices[wid] = (rank, action)
    result = dict.fromkeys(open_works, "待核实")
    result.update(dict.fromkeys(bibliographic, "等待现有工单的复查条件"))
    result.update({wid: item[1] for wid, item in choices.items()})
    return result


def source_actions(base, works, assessments, versions, tasks, checkpoint):
    owners = {w["work_id"]: w["work_id"] for w in works}
    selected = set(owners)
    for records, field in ((assessments, "assessment_id"), (versions, "version_id")):
        owners.update({r[field]: r["work_id"] for r in records if r["work_id"] in selected})
    stamp = max((t.get("updated_at_utc") or "" for t in tasks.values()), default="")
    cp_file = base / "snapshots/checkpoints" / (checkpoint + ".json")
    if re.fullmatch(r"CP-\d{4,}", checkpoint) and cp_file.is_file():
        stamp = json.loads(cp_file.read_bytes()).get("created_at_utc") or stamp
    return next_actions(tasks, owners, instant(stamp))


def topic_groups(assessments, known):
    groups = {theme: set() for theme in TITLES}
    for a in assessments:
        if a.get("assessment_status") != "active" or a.get("evidence_admission_status") != "eligible":
            continue
        if SUBSTANTIVE.intersection(a.get("relation_type", [])):
            if a["work_key"] not in known:
                raise ValueError("Unknown Work in theme membership: " + a["assessment_id"])
            groups[a["limitation_id"]].add(a["work_key"])
    return groups


def make_payload(works, checkpoint, groups=None, actions=None):
    rows = [bibliographic_fields(w) for w in works]
    venues = sorted({r[4] for r in rows})
    venue_ids = {s: i for i, s in enumerate(venues)}
    anchors = [legacy_anchor(r[0]) for r in rows]
    if len(set(anchors)) != len(anchors):
        raise ValueError("Duplicate legacy row anchor")
    for row in rows:
        row[4] = venue_ids[row[4]]
    data = dict(checkpoint=checkpoint, rows=rows, anchors=anchors, venues=venues)
    if groups is not None:
        positions = {r[0]: i for i, r in enumerate(rows)}
        data["groups"] = {theme: [positions[k] for k in sorted(keys)] for theme, keys in groups.items()}
    else:
        reason_sets = [list(dict.fromkeys(REASONS.get(r, r) for r in (w.get("u00_reasons") or []))) for w in works]
        labels = [actions.get(w["work_id"], "暂无已登记动作") for w in works]
        data["reasons"] = sorted({s for reasons in reason_sets for s in reasons})
        data["actions"] = sorted(set(labels))
        reason_ids = {s: i for i, s in enumerate(data["reasons"])}
        action_ids = {s: i for i, s in enumerate(data["actions"])}
        for row, reasons, label in zip(rows, reason_sets, labels):
            row.extend(([reason_ids[s] for s in reasons], action_ids[label]))
    data["edition"] = hashlib.sha256(compact(data).encode()).hexdigest()[:16]
    return data


def table(theme, title, columns):
    label = escape(f"{theme} · {title}")
    identifier = "literature-U00" if theme == "U00" else "limitation-" + theme
    headings = "".join(f'<th scope="col"><button type="button" data-column="{i}" aria-label="按{c}排序">{c}</button></th>' for i, c in enumerate(columns))
    return f'''<section id="section-{theme}" data-theme="{theme}">
<h2>{label} <small class="count"></small></h2>
<div class="table-scroll" role="region" aria-label="{label}" tabindex="0"><table id="{identifier}">
<caption class="visually-hidden">{label}</caption><thead><tr>{headings}</tr></thead><tbody></tbody></table></div></section>'''


def page(misc, topic_filename, scope, payload):
    theme_titles = {"U00": MISC_TITLE} if misc else TITLES
    title = MISC_TITLE if misc else "主题文献"
    other, other_title = (topic_filename, "主题文献") if misc else ("misc.html", MISC_TITLE)
    data_name = "misc" if misc else "topics"
    options = "".join(f'<option value="{k}">{k} · {t}</option>' for k,t in TITLES.items())
    selector = "" if misc else f'<label>主题<select id="theme"><option value="">全部主题</option>{options}</select></label>'
    tables = "\n".join(table(k,t,MISC_COLUMNS if misc else COLUMNS) for k,t in theme_titles.items())
    pager = ('''<nav class="pager" aria-label="文献分页"><button id="previous" type="button">上一页</button>
<span id="page-number" aria-live="polite"></span><button id="next" type="button">下一页</button></nav>''' if misc else "")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="bibliography-format" content="2"><title>{title} · 昆虫启发的视觉自运动估计</title>
<link rel="stylesheet" href="ref-data/index.css"><script defer src="ref-data/{data_name}.js"></script><script defer src="ref-data/index.js"></script></head>
<body id="top" data-page="{data_name}" data-checkpoint="{escape(payload["checkpoint"])}" data-edition="{payload["edition"]}">
<header><p>昆虫启发的视觉自运动估计</p><h1>{title}</h1>
<div class="snapshot">{escape(scope)} · {escape(payload["checkpoint"])}</div><a class="switch" href="{escape(other, quote=True)}">{other_title} →</a></header>
<main><div class="controls"><label>搜索文献<input id="search" type="search" autocomplete="off"></label>{selector}
<button id="clear" type="button">清除筛选</button></div>
<p id="search-status" role="status">正在载入书目。若列表为空，请检查相邻的 ref-data 文件夹。</p><noscript>请启用 JavaScript 以浏览离线索引。</noscript>
{tables}{pager}</main><footer><a href="#top">返回顶部 ↑</a></footer></body></html>
'''


def write_file(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == raw:
        return
    with NamedTemporaryFile(dir=path.parent, prefix=".index-", delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(raw)
        except BaseException:
            f.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def writer_lock(directory):
    # The OS releases the lock even if a generator stops unexpectedly.
    identity = os.path.normcase(str(directory.resolve())).encode()
    name = "insect-index-" + hashlib.sha256(identity).hexdigest() + ".lock"
    with (Path(gettempdir()) / name).open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def publish(directory, files):
    with writer_lock(directory):
        previous = {}
        try:
            for path, raw in files.items():
                before = path.read_bytes() if path.exists() else None
                if before != raw:
                    write_file(path, raw)
                    previous[path] = before
        except BaseException:
            for path, before in reversed(previous.items()):
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    write_file(path, before)
            raise


def generate(base, output, checkpoint=None):
    base, output = Path(base), Path(output)
    if output.name.casefold() == "misc.html":
        raise ValueError("Topic and U00 output paths must differ")
    scope = json.loads((base/"snapshots/scope.json").read_bytes())
    works = sorted(iter_logical("works.jsonl", base), key=lambda w: w["work_key"])
    keys = {w["work_key"] for w in works}
    ids = {w["work_id"] for w in works}
    if len(keys) != len(works) or len(ids) != len(works):
        raise ValueError("Duplicate canonical Work key or ID")
    assessment_rows = list(iter_logical("assessments.jsonl", base))
    groups = topic_groups(assessment_rows, keys)
    union = set().union(*groups.values())
    misc_works = [w for w in works if w["work_key"] not in union]
    tasks = {t["task_id"]: t for t in iter_logical("tasks.jsonl", base)}
    if not checkpoint:
        checkpoint = max((t["checkpoint_id"] for t in tasks.values() if t.get("checkpoint_id")), default="未记录")
    actions = source_actions(base, misc_works, assessment_rows, iter_logical("versions.jsonl", base), tasks, checkpoint)
    del tasks
    topics = make_payload([w for w in works if w["work_key"] in union], checkpoint, groups=groups)
    misc = make_payload(misc_works, checkpoint, actions=actions)
    dest = output.parent
    files = {}
    for name in STATIC_FILES:
        files[dest/ASSET_DIR/name] = (ROOT/ASSET_DIR/name).read_bytes()
    for is_misc, data, stem in ((False, topics, "topics"), (True, misc, "misc")):
        raw = compact(data).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        files[dest/ASSET_DIR/(stem+".js")] = (DATA_PREFIX + raw + ";\n").encode()
        path = dest/"misc.html" if is_misc else output
        files[path] = page(is_misc, output.name, scope["scope_id"], data).encode()
    publish(dest, files)
    return dict(checkpoint_id=checkpoint, K=len(keys), U=len(misc_works), topic_union=len(union),
                table_rows=sum(map(len, groups.values()))+len(misc_works), T={k:len(v) for k,v in groups.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=TEMP)
    parser.add_argument("--output", type=Path, default=ROOT/"ref.html")
    parser.add_argument("--checkpoint")
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    result = generate(args.base, args.output, args.checkpoint)
    if args.summary_output:
        write_file(args.summary_output, (compact(result)+"\n").encode())
    print(compact(result))
