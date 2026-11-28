"""Check the four oldest open citing-version cases in the Crossref deposit XML reference lists."""
from urllib.parse import quote
from xml.etree import ElementTree as ET

from run10_reference_records import doi
from run12_reference_search import query
from run12_version_screen import OLD
from search_run11_bibliography import OUT, read


def parse(raw):
    try:return ET.fromstring(raw)
    except ET.ParseError as exc:raise ValueError("Invalid registry XML") from exc


def tag(e):return e.tag.rsplit("}",1)[-1]


def main():
    cases=[r for r in read(OLD)["items"] if r["cohort"]=="CP11-original"]
    if len(cases)!=4:raise ValueError("Changed inherited version inventory")
    for case in cases:
        previous=read(OUT/(case["deposit_query"]+".json"))
        old,=[r for r in previous["records"] if doi(r.get("DOI"))==case["citing_doi"]]
        original=old["reference"][case["deposit_position"]-1]
        key=original["key"]
        def project(xml):
            parents=[n for n in xml.iter() if tag(n) in ("journal_article","posted_content")
                     and any(tag(d)=="doi" and doi(d.text)==case["citing_doi"] for data in n if tag(data)=="doi_data" for d in data)]
            if len(parents)!=1:raise ValueError("Cannot bind the deposit XML to the requested citing DOI")
            records=[];selected=[]
            for listing in parents[0]:
                if tag(listing)!="citation_list":continue
                for cite in listing:
                    if tag(cite)!="citation":continue
                    fields=[{"field":tag(e),"value":" ".join("".join(e.itertext()).split()),"attributes":dict(e.attrib)} for e in cite]
                    links=[v for e in cite.iter() for k,v in e.attrib.items() if k.rsplit("}",1)[-1] in ("href","uri")]
                    row=dict(source_identifier=cite.get("key") or str(len(records)+1),position=len(records)+1,fields=fields,links=links)
                    records.append(row)
                    if cite.get("key")==key:selected.append(row["position"])
            return dict(records=records,visible_total=len(records),returned_count=len(records),page_complete=True,matched_reference_key=key,
                        matched_positions=selected,previous_registry_view=case["deposit_query"],response_media_type="Crossref deposit XML (UNIXREF)")
        q=query("P4-LEGACY-XML-"+str(case["ordinal"]),"crossref","https://api.crossref.org/v1/works/"+quote(case["citing_doi"],safe="/")+"/transform",{},
              [dict(work_id=case["citing_work_id"],task_id=case["task_id"])],
              "Inspect the depositing member's bibliographic XML for a revision-specific identifier, link or earlier citing version.",project,decode=parse,accept="application/vnd.crossref.unixref+xml")
        print(case["ordinal"],q["status"],q.get("returned_count"),q.get("matched_positions"),q.get("error"),flush=True)


if __name__=="__main__":main()
