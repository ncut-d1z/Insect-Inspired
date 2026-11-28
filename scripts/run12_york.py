"""Resolve the two homonymous York University records by registry location."""
from run12_followups import SOURCE
from run12_reference_search import query
from search_run11_bibliography import OUT, read

def main():
    row,=[r for r in read(SOURCE)["records"] if r["id"]=="11163855"]
    if "Toronto" not in row["authors"][0]["affiliations"][0]:raise ValueError("Original byline differs")
    original=read(OUT/"Q-RUN12-P5-ROR-11163855-A1.json")
    candidates=[o for o in original["records"] if any(n["value"]=="York University" and "ror_display" in n["types"] for n in o["names"])]
    if len(candidates)!=2:raise ValueError("Homonym inventory changed")
    for o in candidates:
        rid=o["source_identifier"].rsplit("/",1)[-1]
        def project(data):
            if data["id"]!=o["source_identifier"]:raise ValueError("Wrong ROR entity")
            places=[{k:loc["geonames_details"].get(k) for k in ("name","country_code","country_name","lat","lng")}
                    for loc in data["locations"]]
            item=dict(source_identifier=data["id"],names=data["names"],status=data["status"],types=data["types"],locations=places)
            return dict(records=[item],returned_count=1,visible_total=1,page_complete=True)
        q=query("P5-YORK-"+rid,"ror","https://api.ror.org/v2/organizations/"+rid,{},[dict(work_id=row["work_id"],task_id="T-affiliations_projects-"+row["work_id"])],
             "Disambiguate the publication affiliation using independently registered city and country for both homonymous institutions.",project)
        print(rid,q["status"],[r["locations"] for r in q.get("records",[])],flush=True)

if __name__=="__main__":main()
