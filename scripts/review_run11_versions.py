"""Compare the 65 inherited citing-version cases against deposited lists and dated edition records."""
from collections import defaultdict
from difflib import SequenceMatcher
import argparse
import json
import re
from urllib.parse import quote

from run10_reference_records import clean, doi, norm, token
from search_run10_references import read, write
from search_run11_bibliography import CR, OA, OUT, RUN, TEMP, chunks, digest, request

INPUT=TEMP/"reports/RUN-0011-version-input.json"
CARDS=TEMP/"reports/RUN-0011-version-source-cards.json"
PREPRINT=re.compile(r"10\.1101/(?:[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.)?[0-9]{4,8}",re.I)


def parents():
    return read(INPUT)["items"]


def owner(r):
    return dict(work_id=r["citing"]["work_id"],task_id=r["task_id"])


def source_cards():
    if CARDS.exists():return read(CARDS)
    cards=[];sources={}
    for path in sorted(OUT.glob("Q-RUN10-*.json")):
        if path.name.split("-")[2] not in ("VCR","BCR","RCR","F"):continue
        q=read(path)
        if q["source_id"]!="crossref" or q["status"]!="success":continue
        for paper in q.get("records",[]):
            if "reference" in paper:sources[doi(paper["DOI"])]=(path,paper["reference"])
    for idx,r in enumerate(parents(),1):
        citing,cited=r["citing"],r["cited"];cd=doi(cited["doi"]);wanted=norm(cited["canonical_title"])
        path,refs=sources.get(doi(citing["doi"]),(None,[]));indexed=set()
        family=re.sub(r"[0-9].*$","",cited["work_key"]).replace("_","").casefold()
        for occurrence in r["occurrences"]:
            try: cited_order=json.loads(occurrence["raw_reference"]).get("citedOrder")
            except (AttributeError,ValueError):continue
            if cited_order:indexed.add(int(cited_order))
        candidates=[]
        for pos,ref in enumerate(refs,1):
            literal=clean(ref.get("unstructured"));title=clean(ref.get("article-title") or ref.get("chapter-title") or ref.get("volume-title"))
            nt=norm(title);nl=norm(literal);raw=norm(" ".join(str(v) for v in ref.values()))
            reasons=[]
            if cd and (doi(ref.get("DOI"))==cd or cd in literal.lower()):reasons.append("target_doi")
            if wanted and ((nt and nt==wanted) or (len(wanted)>15 and wanted in nl)):reasons.append("target_title")
            if nt and wanted and SequenceMatcher(None,nt,wanted,autojunk=False).ratio()>=.68:reasons.append("similar_title")
            if family and len(family)>=3 and family in (norm(ref.get("author")) or nl[:100]):reasons.append("author_candidate")
            if pos in indexed:reasons.append("index_order_candidate")
            if reasons:candidates.append(dict(position=pos,match_hints=reasons,reference=ref))
        cards.append(dict(ordinal=idx,task_id=r["task_id"],citing=citing["work_key"],cited=cited["work_key"],
                     deposited_receipt=path.stem if path else None,deposited_receipt_sha256=digest(path) if path else None,
                     candidates=candidates))
    result=dict(run_id=RUN,input_sha256=digest(INPUT),items=cards)
    write(CARDS,result);return result


def editions():
    rows=parents();cards=source_cards()["items"];work_owners=defaultdict(list);preprints=defaultdict(list)
    for row,card in zip(rows,cards):
        for paper in (row["citing"],row["cited"]):
            if paper["doi"]:work_owners[doi(paper["doi"])].append(owner(row))
        for c in card["candidates"]:
            if c["match_hints"]==["index_order_candidate"]:continue
            for ident in PREPRINT.findall(json.dumps(c["reference"])):preprints[ident.lower()].append(owner(row))
    groups=[{"doi":k} for k in sorted(work_owners)]
    for num,group in enumerate(chunks(groups,"doi",16),1):
        expected={x["doi"] for x in group}
        def one(data):
            msg=data["message"];items=msg["items"]
            recs=[{k:r[k] for k in ("DOI","title","published","published-online","published-print","posted","issued","type","subtype","relation","alternative-id","ISBN","edition-number","container-title","event","volume","page","article-number","author") if k in r} for r in items]
            for r in recs:
                r["author"]=[{k:a[k] for k in ("family","given","name") if k in a} for a in r.get("author",[])]
            got=[doi(r["DOI"]) for r in recs]
            if len(got)!=len(set(got)) or set(got)-expected or len(got)!=msg["total-results"]:raise ValueError("Unbound registry metadata")
            return dict(records=recs,visible_total=len(recs),returned_count=len(recs),page_complete=True,missing=sorted(expected-set(got)))
        tasks={o["task_id"]:o for k in expected for o in work_owners[k]}
        q=request(f"VER-CR-{num:02}","crossref",CR,{"filter":",".join("doi:"+x["doi"] for x in group),"rows":len(group)},
                sorted(tasks.values(),key=lambda x:x["task_id"]),"Check edition identity, deposit relations and online versus print dates, independently of CP12's index dates.",one)
        for m in q.get("records",[]):
            for name,links in m.get("relation",{}).items():
                for link in links:
                    for d in PREPRINT.findall(str(link.get("id") or "")):
                        preprints[d.lower()].extend(work_owners[doi(m["DOI"])])
    # The target history was already acquired in CP12; keep its locator and avoid repeating it.
    prior=[row for path in OUT.glob("Q-RUN10-VBIO-*-A1.json") for row in read(path).get("records",[])]
    for ident in sorted(preprints):
        if ident in {r["doi"].lower() for r in prior}:continue
        selected={o["task_id"]:o for o in preprints[ident]}
        def versions(data):
            records=[{k:r.get(k) for k in ("doi","date","version","title","authors","published","server")} for r in data.get("collection",[])]
            if any(doi(r["doi"])!=ident for r in records) or len({r["version"] for r in records})!=len(records):raise ValueError("Preprint history mismatch")
            declared=int((data.get("messages") or [{}])[0].get("total") or len(records))
            if len(records)!=declared:raise ValueError("Incomplete publisher revision history")
            return dict(records=records,visible_total=declared,returned_count=len(records),page_complete=True)
        request("VER-BIO-"+token(ident),"publisher","https://api.biorxiv.org/details/biorxiv/"+ident,{},sorted(selected.values(),key=lambda x:x["task_id"]),
                "Date and title of each separately posted preprint revision; retain unknowns if the list does not identify the original citation.",versions)


def originals():
    rows=[r for r in parents() if r["cohort"]=="CP11-original"]
    for row in rows:
        ident=doi(row["citing"]["doi"])
        def project(data):
            rec={k:data.get(k) for k in ("id","doi","ids","display_name","publication_date")}
            return dict(records=[rec],visible_total=1,returned_count=1,page_complete=True)
        q=request("VER-ORIGINAL-ID-"+token(ident),"openalex",OA+"/https://doi.org/"+quote(ident,safe="/"),
                {"select":"id,doi,ids,display_name,publication_date"},[owner(row)],"Resolve each original citing DOI independently of search-engine pagination and alternative matches.",project)
        matches=[r for r in q.get("records",[]) if doi(r["doi"])==ident]
        if len(matches)!=1:continue
        wid=matches[0]["id"].rsplit("/",1)[-1]
        if not re.fullmatch(r"W\d+",wid):raise ValueError("Invalid OpenAlex ID")
        def reference_list(data):
            if isinstance(data,list):entries=data;decl=len(entries)
            elif isinstance(data.get("references"),list):entries=data["references"];decl=int((data.get("meta") or {}).get("count",len(entries)))
            else:entries=data["results"];decl=int(data["meta"]["count"])
            if len(entries)!=decl:raise ValueError("Reference-list API needs pagination")
            return dict(records=entries,visible_total=decl,returned_count=len(entries),page_complete=True)
        request("VER-ORIGINAL-"+wid,"openalex",OA+"/"+wid+"/references",{},[owner(row)],
                "Look for the source's literal references, including original version-specific identifiers.",reference_list)


def supplement():
    rows=parents()
    for ident in sorted({r["cited"]["doi"] for r in rows if r["cited"].get("doi") and r["cited"].get("year",0)>=2010}):
        group=[r for r in rows if r["cited"]["doi"]==ident]
        def publication(data):
            records=[{k:r.get(k) for k in ("preprint_doi","published_doi","preprint_title","published_title","preprint_date","published_date","preprint_authors","server")} for r in data.get("collection",[])]
            if any(doi(r["published_doi"])!=doi(ident) and doi(r["preprint_doi"])!=doi(ident) for r in records):raise ValueError("Unbound publisher crosswalk")
            return dict(records=records,visible_total=len(records),returned_count=len(records),page_complete=True)
        q=request("VER-PUB-"+token(ident),"publisher","https://api.biorxiv.org/pubs/biorxiv/"+quote(ident,safe="/"),{},[owner(r) for r in group],
               "Check the publisher's explicit preprint-to-journal DOI crosswalk for the cited work.",publication)
        for row in q.get("records",[]):
            pre=doi(row["preprint_doi"])
            if not pre:continue
            old=[*OUT.glob("Q-RUN10-VBIO-*-A1.json"),*OUT.glob("Q-RUN11-VER-BIO-*-A*.json")]
            if any(any(doi(x.get("doi"))==pre for x in read(p).get("records",[])) for p in old):continue
            def revisions(data):
                rec=[{k:r.get(k) for k in ("doi","date","version","title","authors","published","server")} for r in data.get("collection",[])]
                if len({r["version"] for r in rec})!=len(rec) or any(doi(r["doi"])!=pre for r in rec):raise ValueError("Unbound preprint revisions")
                return dict(records=rec,visible_total=len(rec),returned_count=len(rec),page_complete=True)
            request("VER-BIO-X-"+token(pre),"publisher","https://api.biorxiv.org/details/biorxiv/"+pre,{},[owner(r) for r in group],
                    "Inventory revisions for the newly established publisher crosswalk.",revisions)
    for wid in ("W3015110848","W4404754717"):
        def lookup(data):
            r={k:data.get(k) for k in ("id","doi","display_name","publication_date","type","ids")}
            return dict(records=[r],visible_total=1,returned_count=1,page_complete=True)
        request("VER-TARGET-"+wid,"openalex",OA+"/"+wid,{"select":"id,doi,display_name,publication_date,type,ids"},
                [owner(r) for r in rows[:4]],"Identify the target of the original printed versus index-matched references.",lookup)
    already={doi(r["citing"]["doi"]) for r in rows[:4]}
    grouped=defaultdict(list)
    for row in rows[4:]:
        ident=doi(row["citing"]["doi"])
        if ident and ident not in already:grouped[ident].append(row)
    for ident,group in sorted(grouped.items()):
        def lookup(data):
            r={k:data.get(k) for k in ("id","doi","display_name","publication_date","type","ids")}
            return dict(records=[r],visible_total=1,returned_count=1,page_complete=True)
        q=request("VER-PARENT-"+token(ident),"openalex",OA+"/https://doi.org/"+quote(ident,safe="/"),
                {"select":"id,doi,display_name,publication_date,type,ids"},[owner(r) for r in group],"Identify the citing Work before reading its separate reference-list endpoint.",lookup)
        if not q.get("records") or doi(q["records"][0]["doi"])!=ident:continue
        wid=q["records"][0]["id"].rsplit("/",1)[-1]
        def printed(data):
            refs=data["references"]
            if not isinstance(refs,list) or any(not isinstance(x,dict) for x in refs):raise ValueError("Invalid literal reference list")
            return dict(records=refs,visible_total=len(refs),returned_count=len(refs),page_complete=True)
        request("VER-PRINT-"+wid,"openalex",OA+"/"+wid+"/references",{},[owner(r) for r in group],
                "Compare the actual reference string and raw DOI with the index match. Merged lists alone cannot establish an original edition.",printed)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["cards","editions","originals","supplement"])
    {"cards":source_cards,"editions":editions,"originals":originals,"supplement":supplement}[parser.parse_args().mode]()
