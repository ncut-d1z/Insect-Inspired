"""Check four CP12 parent abstracts in their bibliographic records and retain only provenance in Git."""
from run10_reference_records import clean, doi, norm
from run11_reference_inventory import owners_input, queue_inputs
from search_run9_bibliography import facts
from search_run11_bibliography import EPMC, request


def main():
    queue,titles=queue_inputs()
    owners=[queue[i-1] for i in (327,709,1268,1835)]
    expected={w["epmc"].split(":")[1]:w for w in owners}
    def project(data):
        records=data["resultList"]["result"]
        if len(records)!=len(expected) or {r["id"] for r in records}!=set(expected):
            raise ValueError("Incomplete metadata response")
        result=[]
        for record in records:
            w=expected[record["id"]]
            if norm(record["title"])!=norm(titles[w["work_id"]][0]) or doi(record.get("doi"))!=w["doi"]:
                raise ValueError("Paper does not match the frozen parent")
            print("PMID",record["id"],record["title"],flush=True)
            print(clean(record.get("abstractText")),flush=True)
            result.append(facts(record))
        return dict(records=result,returned_count=len(result),visible_total=len(result),page_complete=True)
    q=request("P56-VISUAL-MOTION-ABS-REST","europepmc",EPMC.rstrip("/")+"/search",
              {"query":"SRC:MED AND ("+" OR ".join("EXT_ID:"+k for k in expected)+")","resultType":"core","format":"json","pageSize":len(expected)},
              owners_input(owners),"Check only abstract, bibliographic and publication byline records at the Europe PMC REST search endpoint.",project)
    print(q["query_id"],q["status"],q.get("error"),flush=True)


if __name__=="__main__":
    main()
