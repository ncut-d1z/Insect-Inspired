"""Resolve RUN10 backward-list identities using bibliographic fields and the CP11 Work registry."""
import argparse
from collections import defaultdict
import hashlib
import html
import re
import time
import unicodedata

from search_run10_references import CR, EPMC, FRONTIER, OUT, TEMP, fetch, read
from search_run9_bibliography import facts
from storage import iter_logical


def token(*parts):
    return hashlib.sha256("\n".join(map(str,parts)).encode()).hexdigest()[:20]


def clean(text):
    return " ".join(re.sub(r"<[^>]*>", "", html.unescape(str(text or ""))).split()).strip()


def norm(text):
    return re.sub(r"[\W_]+","",unicodedata.normalize("NFKC",clean(text)).casefold())


def doi(value):
    value=str(value or "").strip().lower()
    value=re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)","",value)
    return value if re.fullmatch(r"10\.\d{4,9}/\S+",value) else ""


def identifiers(obj):
    ids=set()
    for k,v in {**obj.get("identifiers",{}),"work_doi":obj.get("doi"),"raw":obj.get("raw_identifier"),
                "normalized":obj.get("normalized_identifier")}.items():
        if k=="doi_as_indexed_at_cp11":
            continue
        for val in v if isinstance(v,list) else [v]:
            if not isinstance(val,(str,int)) or not val:
                continue
            text=str(val).strip()
            if x:=doi(text):
                ids.add(x)
            elif str(k).lower() in {"pmid","pubmed","pubmed_id"} and text.isdigit():
                ids.add("MED:"+text)
            elif re.fullmatch(r"(?:MED:[0-9]+|PPR:PPR[0-9]+)",text,re.I):
                ids.add(text.upper())
            elif re.fullmatch(r"(?:https?://openalex\.org/)?W[0-9]+",text,re.I):
                ids.add(text.rsplit("/",1)[-1].upper())
    return ids


def existing():
    works={w["work_id"]:w for w in iter_logical("works.jsonl",TEMP)}
    idmap=defaultdict(set)
    names=defaultdict(set)
    for wid,w in works.items():
        for name in (w["canonical_title"],*w.get("title_variants",[])):
            if isinstance(name,str) and norm(name):
                names[(norm(name),str(w.get("year")))].add(wid)
        for ident in identifiers(w):
            idmap[ident].add(wid)
    for filename in ("versions.jsonl","aliases.jsonl"):
        for r in iter_logical(filename,TEMP):
            if r.get("verification_status") in {"conflicting","rejected"}:
                continue
            wid=r.get("work_id") or (r.get("target_id") if r.get("entity_type")=="work" else None)
            if wid in works:
                for ident in identifiers(r):
                    idmap[ident].add(wid)
    return works,idmap,names


def source_lists(queue, folder=OUT):
    """Yield one source-specific list page per parent, retaining all positions in receipt order."""
    by_doi={o["doi"].lower():o for o in queue if o.get("doi")}
    by_epmc={o["epmc"]:o for o in queue if o.get("epmc")}
    by_work={o["work_id"]:o for o in queue}
    for p in sorted(folder.glob("Q-RUN10-*.json")):
        if not p.name.startswith(("Q-RUN10-VCR-","Q-RUN10-BCR-","Q-RUN10-VEP-","Q-RUN10-BEP-","Q-RUN10-RCR-","Q-RUN10-REP-","Q-RUN10-ROA-","Q-RUN10-F-OA-","Q-RUN10-F-DOI-")):
            continue
        q=read(p)
        if q["status"]!="success":
            continue
        if q["source_id"]=="crossref":
            for paper in q["records"]:
                parent=by_doi.get(paper["DOI"].lower())
                if q.get("corrected_identifier")==paper["DOI"].lower():
                    parent=by_epmc.get(q["owners"][0]["epmc"])
                if parent:
                    yield parent,q,paper.get("reference",[]),paper.get("reference-count"),"reference" in paper
        elif parent:=by_work.get(q["owners"][0]["work_id"]):
            yield parent,q,q["records"],q["visible_total"],True


def fields(raw, source):
    if source=="openalex":
        return "","","","",""
    if source=="crossref":
        d=doi(raw.get("DOI"))
        if not d and raw.get("unstructured"):
            candidates=set()
            for value in re.findall(r"(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>\"\]]+)",raw["unstructured"],re.I):
                value=value.rstrip(".,;")
                while value.endswith(")") and value.count(")")>value.count("("):value=value[:-1]
                if doi(value):candidates.add(doi(value))
            if len(candidates)==1:d=candidates.pop()
        return (d,"",clean(raw.get("article-title") or raw.get("chapter-title") or raw.get("volume-title")
                or raw.get("series-title")),str(raw.get("year") or ""),clean(raw.get("author")))
    ident=str(raw.get("id") or "")
    src=raw.get("source","")
    epmc=src+":"+ident if src in {"MED","PPR"} and ident else ""
    return doi(raw.get("doi")),epmc,clean(raw.get("title")),str(raw.get("pubYear") or ""),clean(raw.get("authorString"))


def metadata(folder=OUT):
    for path in sorted(folder.glob("Q-RUN10-ID-*.json")):
        q=read(path)
        if q["status"]=="success":
            for record in q["records"]:
                yield record,q


def cross_metadata(item):
    date=item.get("published") or item.get("issued") or {}
    parts=(date.get("date-parts") or [[]])[0]
    names=[]
    for a in item.get("author",[]):
        name={k:v for k,v in {"firstName":a.get("given"),"lastName":a.get("family"),"collectiveName":a.get("name")}.items() if v}
        if a.get("ORCID"):
            name["authorId"]={"type":"ORCID","value":a["ORCID"]}
        if name:names.append(name)
    return dict(doi=doi(item["DOI"]),title=clean(next(iter(item.get("title") or []),"")),authors=names,
                year=parts[0] if parts else None,date="-".join([str(parts[0]),*(f"{n:02}" for n in parts[1:])]) if parts else None,
                venue=next(iter(item.get("container-title") or []),None),volume=item.get("volume"),number=item.get("issue"),
                pages=item.get("page"),eid=item.get("article-number"),publisher=item.get("publisher"),
                language=item.get("language"),document_type=item.get("type"),source_identifier=doi(item["DOI"]))


def ep_metadata(item):
    r=facts(item)
    return dict(doi=doi(r.get("doi")),epmc=r["source"]+":"+str(r["id"]),pmcid=r.get("pmcid"),title=clean(r.get("title")),
                authors=r.get("authors",[]),year=int(r["pubYear"]) if str(r.get("pubYear","")).isdigit() else None,
                date=r.get("firstPublicationDate"),venue=r.get("journal",{}).get("title") or r.get("journalTitle"),
                volume=r.get("issue_details",{}).get("volume"),number=r.get("issue_details",{}).get("issue"),
                pages=r.get("pageInfo"),language=item.get("language"),publication_types=r.get("pubTypeList",{}).get("pubType",[]),
                document_type="posted-content" if r["source"]=="PPR" else None,abstract_available=r.get("abstract_available",False),
                abstract_sha256=r.get("abstract_sha256"),source_identifier=r["source"]+":"+str(r["id"]))


def request_identities(group, provider, owners, requester=fetch):
    key="ID-"+{"crossref":"CR","openalex":"OA","europepmc":"EP"}[provider]+"-"+token(*group)
    if provider=="crossref":
        params={"filter":",".join("doi:"+d for d in group),"rows":len(group)}
        endpoint=CR
        def project(data):
            m=data["message"]
            return [cross_metadata(r) for r in m["items"]],m["total-results"]
    elif provider=="openalex":
        endpoint="https://api.openalex.org/works"
        params={"filter":"openalex_id:"+"|".join(group),"per_page":len(group),
                "select":"id,doi,display_name,publication_year,publication_date,ids,type,primary_location,authorships"}
        def project(data):
            output=[]
            for item in data["results"]:
                key=item["id"].rsplit("/",1)[-1];pmid=(item.get("ids",{}).get("pmid") or "").rsplit("/",1)[-1]
                loc=item.get("primary_location") or {};venue=loc.get("source") or {};authors=[]
                for authorship in item.get("authorships",[]):
                    a=authorship.get("author") or {};name=authorship.get("raw_author_name") or a.get("display_name")
                    if not name:continue
                    author={"fullName":name}
                    if a.get("orcid"):author["authorId"]={"type":"ORCID","value":a["orcid"]}
                    authors.append(author)
                typ=item.get("type")
                if typ=="article" and venue.get("type")=="journal":typ="journal-article"
                if typ=="preprint":typ="posted-content"
                output.append(dict(openalex=key,source_identifier=key,doi=doi(item.get("doi")),epmc="MED:"+pmid if pmid.isdigit() else None,
                        title=clean(item.get("display_name")),year=item.get("publication_year"),date=item.get("publication_date"),
                        venue=venue.get("display_name"),authors=authors,document_type=typ,location_version=loc.get("version")))
            return output,data["meta"]["count"]
    else:
        grouped=defaultdict(list)
        for x in group:
            src,ident=x.split(":",1)
            grouped[src].append(ident)
        query=" OR ".join("(SRC:"+src+" AND ("+" OR ".join('EXT_ID:"'+i+'"' for i in ids)+"))" for src,ids in grouped.items())
        params={"query":query,"resultType":"core","format":"json","pageSize":len(group)}
        endpoint=EPMC+"search"
        def project(data):
            return [ep_metadata(r) for r in data["resultList"]["result"]],data["hitCount"]
    def verified(data):
        rows,n=project(data)
        returned=[r["source_identifier"] for r in rows]
        if len(rows)!=n or len(set(returned))!=len(rows) or set(returned)-set(group):
            raise ValueError("Identifier lookup did not reconcile")
        return dict(records=rows,visible_total=n,returned_count=len(rows),page_complete=True,
                    requested_identifiers=group,missing_identifiers=sorted(set(group)-set(returned)))
    return requester(key,provider,endpoint,params,owners,"Resolve a reference-list identifier and recover its bibliographic fields.",verified)


def hydrate(queue,provider,folder=OUT,limit=None):
    import search_run10_references as service
    service.OUT=folder
    _,known,_=existing()
    represented=set(known)
    for r,_ in metadata(folder):
        represented.update(k for k in (r.get("doi"),r.get("epmc"),r.get("openalex")) if k)
    looked=set()
    for p in sorted(folder.glob("Q-RUN10-ID-*.json")):
        q=read(p)
        if q["source_id"]!=provider:continue
        looked.update(q.get("requested_identifiers",[]))
        if q["status"]!="success" and (q["attempt"]==4 or not q["retryable"]):
            if provider=="crossref":
                looked.update(s[4:] for s in q["parameters"]["filter"].split(",doi:")[:1])
                looked.update(q["parameters"]["filter"].split(",doi:")[1:])
            elif provider=="europepmc":
                for src,part in re.findall(r"\(SRC:(\w+) AND \(([^()]*)\)\)",q["parameters"]["query"]):
                    looked.update(src+":"+i for i in re.findall(r'EXT_ID:"([A-Za-z0-9]+)"',part))
            elif provider=="openalex":
                looked.update(q["parameters"].get("filter","").removeprefix("openalex_id:").split("|"))
    needed={}
    for owner,q,refs,_,_ in source_lists(queue,folder):
        for raw in refs:
            d,e,*_=fields(raw,q["source_id"])
            k={"crossref":d,"europepmc":e,"openalex":raw.get("openalex")}.get(provider)
            if k and k not in represented and k not in looked:needed.setdefault(k,owner)
    keys=sorted(needed)
    # Use small explicit-ID queries. Long DOI values can exceed a GET URL even in a modest batch.
    batch=[];length=0;requests=0;submitted=0
    for k in [*keys,None]:
        if batch and (k is None or len(batch)>=35 or length+len(k)>1900):
            owners={needed[x]["work_id"]:needed[x] for x in batch}
            request_identities(batch,provider,list(owners.values()))
            requests+=1;submitted+=len(batch)
            if limit and requests>=limit:break
            time.sleep(1)
            batch=[];length=0
        if k is not None:
            batch.append(k);length+=len(k)
    print("identifier queue",provider,"pending at start",len(keys),"submitted",submitted,"groups",requests,flush=True)
    return requests


if __name__=="__main__":
    from pathlib import Path
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("provider",choices=["europepmc","crossref","openalex"])
    p.add_argument("--folder",type=Path,default=OUT)
    p.add_argument("--frontier",type=Path,default=FRONTIER)
    p.add_argument("--groups",type=int,help="Number of small query groups before publishing the next Git batch")
    args=p.parse_args()
    hydrate(read(args.frontier)["worklist"],args.provider,args.folder,args.groups)
