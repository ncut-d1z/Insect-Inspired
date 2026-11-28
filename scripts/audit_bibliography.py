"""Check the published offline bundle against canonical records, including every paginated key."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess

from render_html import (ASSET_DIR, COLUMNS, MISC_COLUMNS, DATA_PREFIX, REASONS, ROOT, SUBSTANTIVE,
                         TITLES, WEB_FILES, bibliographic_fields, compact, legacy_anchor, page, source_actions)
from storage import iter_logical

RECEIPT = "temp/validation/bibliography-view.json"
# These are the only frozen CP11 files that a presentation-only release can supersede.
PRESENTATION_PATHS = {"README.md", "ref.html", "scripts/README.md", "scripts/render_html.py",
                      "scripts/storage.py", "scripts/audit_run.py", "scripts/export_checkpoint_windows.py",
                      "scripts/html-smoke-checkpoint.mjs"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__()
        self.tables, self.headers, self.resources, self.ids = [], [], [], set()
        self.body, self.links = {}, []
        self.column = False
        self.in_script = False
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        require(not any(k.startswith("on") for k in a), "Unexpected inline event")
        if "id" in a:
            require(a["id"] not in self.ids, "Duplicate element ID")
            self.ids.add(a["id"])
        if tag == "body":
            self.body = a
        if tag == "table":
            self.tables.append(a.get("id"))
            self.headers.append([])
        if tag == "script":
            self.resources.append(a.get("src"))
            self.in_script = True
        if tag == "link":
            self.resources.append(a.get("href"))
        if tag == "a":
            self.links.append(a.get("href"))
        if tag == "button" and "data-column" in a:
            self.column = True
        require(tag not in {"details","iframe","object","embed"}, "Unexpected embedded details")

    def handle_data(self, data):
        if self.column:
            self.headers[-1].append(data)
        if self.in_script:
            require(not data.strip(), "Inline payload in HTML shell")

    def handle_endtag(self, tag):
        if tag == "button":
            self.column = False
        if tag == "script":
            self.in_script = False


def audit_package(directory, works, assessments, actions, checkpoint, scope_id, by_key=None):
    if by_key is None:
        by_key = {w["work_key"]:w for w in works}
    groups = {t:set() for t in TITLES}
    for a in assessments:
        if a["assessment_status"] == "active" and a["evidence_admission_status"] == "eligible" and SUBSTANTIVE.intersection(a["relation_type"]):
            groups[a["limitation_id"]].add(a["work_key"])
    union = set().union(*groups.values())
    u00 = set(by_key) - union
    require(len(by_key)==len(works), "Duplicate canonical key")
    expected_files = {f for f in WEB_FILES if f.startswith(ASSET_DIR + "/")}
    require({p.relative_to(directory).as_posix() for p in (directory/ASSET_DIR).rglob("*") if p.is_file()} == expected_files,
            "Package contains missing or undeclared assets")
    artifacts = {name:dict(bytes=(directory/name).stat().st_size, sha256=file_hash(directory/name)) for name in WEB_FILES}
    for is_misc, stem in ((False,"topics"),(True,"misc")):
        name = "misc.html" if is_misc else "ref.html"
        html = (directory/name).read_text(encoding="utf8")
        shell = Page(html)
        table_ids = ["literature-U00"] if is_misc else ["limitation-"+k for k in TITLES]
        columns = list(MISC_COLUMNS if is_misc else COLUMNS)
        require(shell.tables == table_ids and shell.headers == [columns]*len(table_ids), "Table order or columns differ: "+name)
        require(shell.resources == [f"{ASSET_DIR}/index.css",f"{ASSET_DIR}/{stem}.js",f"{ASSET_DIR}/index.js"], "Cross-page resource load: "+name)
        require(shell.links == [("ref.html" if is_misc else "misc.html"),"#top"], "Unexpected shell link")
        ids = {"search","clear","search-status"} | ({"previous","next","page-number"} if is_misc else {"theme"})
        require(ids <= shell.ids, "Missing navigation control")
        script=(directory/ASSET_DIR/(stem+".js")).read_text(encoding="utf8")
        require(script.startswith(DATA_PREFIX) and script.endswith(";\n"), "Invalid local data script")
        d=json.loads(script[len(DATA_PREFIX):-2])
        allowed={"edition","checkpoint","rows","anchors","venues"} | ({"actions","reasons"} if is_misc else {"groups"})
        require(set(d)==allowed, "Unexpected fields in web data: "+stem)
        edition = hashlib.sha256(compact({k:v for k,v in d.items() if k!="edition"}).encode()).hexdigest()[:16]
        require(d["edition"]==edition==shell.body["data-edition"] and d["checkpoint"]==checkpoint==shell.body["data-checkpoint"], "Mixed snapshot or resources")
        require(html==page(is_misc,"ref.html",scope_id,d), "Unexpected text or hidden content in HTML shell")
        keys=[r[0] for r in d["rows"]]
        require(keys==sorted(u00 if is_misc else union), "Membership, uniqueness or key order differs: "+stem)
        require(d["anchors"]==[legacy_anchor(k) for k in keys] and len(set(d["anchors"]))==len(keys), "Legacy anchor mismatch")
        bibrows=[bibliographic_fields(by_key[k]) for k in keys]
        require(d["venues"]==sorted({r[4] for r in bibrows}), "Unused or invalid venue")
        actual_reasons, actual_actions=set(),set()
        for row,bib in zip(d["rows"],bibrows):
            require(len(row)==len(columns), "Unexpected per-Work payload width")
            require(type(row[4]) is int and 0<=row[4]<len(d["venues"]), "Invalid venue pointer")
            require(row[:4]+[d["venues"][row[4]],row[5]]==bib, "Bibliographic field differs for "+row[0])
            if is_misc:
                w=by_key[row[0]]
                require(all(type(i) is int and 0<=i<len(d["reasons"]) for i in row[6]), "Invalid reason pointer")
                require(type(row[7]) is int and 0<=row[7]<len(d["actions"]), "Invalid action pointer")
                reasons=[d["reasons"][i] for i in row[6]]
                action=d["actions"][row[7]]
                require(reasons==list(dict.fromkeys(REASONS.get(r,r) for r in w.get("u00_reasons") or [])), "U00 reasons differ")
                require(action==actions.get(w["work_id"],"暂无已登记动作"), "Unbound action for "+row[0])
                actual_reasons.update(reasons);actual_actions.add(action)
        if is_misc:
            require(d["reasons"]==sorted(actual_reasons) and d["actions"]==sorted(actual_actions), "Unused detail in U00 dictionaries")
        else:
            require(list(d["groups"])==list(TITLES), "Unexpected theme index")
            for theme,positions in d["groups"].items():
                require(all(type(i) is int and 0<=i<len(keys) for i in positions), "Invalid theme membership pointer")
                require([keys[i] for i in positions]==sorted(groups[theme]), "Incorrect theme membership: "+theme)
    total=sum(v["bytes"] for v in artifacts.values())
    topic_bytes=sum(artifacts[k]["bytes"] for k in ("ref.html","ref-data/index.css","ref-data/index.js","ref-data/topics.js"))
    if checkpoint=="CP-0011":
        require(max(artifacts[p]["bytes"] for p in ("ref.html","misc.html"))<=32768 and topic_bytes<=131072 and total<=2097152, "CP11 byte budget exceeded")
    return dict(checkpoint_id=checkpoint, status="passed", K=len(by_key), U=len(u00), T_union=len(union),
                T_i={k:len(v) for k,v in groups.items()}, topic_load_bytes=topic_bytes, total_bytes=total, artifacts=artifacts)


def presentation_revisions(repo, checkpoint, frozen):
    """Bind a later HTML release to the original Git snapshot without exempting research files."""
    receipt_path=repo/RECEIPT
    if not receipt_path.is_file():
        return {}
    receipt=json.loads(receipt_path.read_bytes())
    if receipt["checkpoint_id"]!=checkpoint:
        return {}
    info=receipt["frozen_source"]
    commit=info["commit"]
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "Invalid source commit")
    cp_path="temp/snapshots/checkpoints/"+checkpoint+".json"
    def original(name):
        raw=subprocess.check_output(["git","--no-replace-objects","-C",str(repo),"show",commit+":"+name])
        return hashlib.sha256(raw).hexdigest()
    subprocess.run(["git","--no-replace-objects","-C",str(repo),"merge-base","--is-ancestor",commit,"HEAD"],check=True)
    require(original(cp_path)==info["checkpoint_sha256"]==file_hash(repo/cp_path), "Frozen checkpoint changed")
    require(set(receipt["artifacts"])==set(WEB_FILES), "Incomplete web release inventory")
    for name,v in receipt["artifacts"].items():
        require(file_hash(repo/name)==v["sha256"] and (repo/name).stat().st_size==v["bytes"], "Published web file differs: "+name)
    revisions={}
    require(receipt["status"]=="passed", "Uncertified bibliography revision")
    for name,pair in receipt["revisions"].items():
        require(name in PRESENTATION_PATHS and name in frozen, "Unexpected historical override: "+name)
        require(original(name)==pair["frozen_sha256"]==frozen[name], "Source commit differs: "+name)
        revisions[name]=pair["view_sha256"]
    return revisions


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",type=Path,default=ROOT/"temp")
    parser.add_argument("--dir",type=Path,default=ROOT)
    parser.add_argument("--checkpoint",required=True)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    works=list(iter_logical("works.jsonl",args.base))
    assessments=list(iter_logical("assessments.jsonl",args.base))
    tasks={t["task_id"]:t for t in iter_logical("tasks.jsonl",args.base)}
    actions=source_actions(args.base,works,assessments,iter_logical("versions.jsonl",args.base),tasks,args.checkpoint)
    scope_id=json.loads((args.base/"snapshots/scope.json").read_bytes())["scope_id"]
    result=audit_package(args.dir,works,assessments,actions,args.checkpoint,scope_id)
    if args.out:
        args.out.write_bytes((json.dumps(result,indent=2,ensure_ascii=False)+"\n").encode())
    print(compact(result))
