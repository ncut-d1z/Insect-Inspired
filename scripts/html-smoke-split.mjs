import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {createHash} from "node:crypto";
import {pathToFileURL, fileURLToPath} from "node:url";

const columns = ["BibTeX key","题名","作者","年份","发表来源","DOI"];
const topics = Array.from({length:9}, (_, i) => "L0" + (i + 1));
const seconds = ms => Math.round(ms) / 1000;
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const median = values => [...values].sort((a,b) => a-b)[Math.floor(values.length/2)];

async function interactive(page, url) {
  await page.goto(url, {waitUntil:"load"});
  await page.locator('body[data-ready="true"]').waitFor({state:"attached",timeout:15000});
}
async function tableChecks(page, misc, root, urls, checkpoint) {
  const data = await page.evaluate(() => window.LITERATURE_INDEX);
  const ids = misc ? ["literature-U00"] : topics.map(t => "limitation-" + t);
  assert.deepEqual(await page.locator("table").evaluateAll(t => t.map(x => x.id)), ids);
  const wanted = misc ? [...columns,"未分类原因","下一步动作"] : columns;
  for (const id of ids) assert.deepEqual(await page.locator("#"+id+" thead button").allTextContents(), wanted);
  assert.equal(await page.locator("body").getAttribute("data-checkpoint"), checkpoint);
  assert.equal(await page.locator("details, [data-search], script:not([src])").count(), 0);
  const visibleRows = page.locator("tbody tr[data-key]");
  const n = data.rows.length;
  const normalCount = misc ? Math.min(50,n) : Object.values(data.groups).flat().length;
  assert.equal(await visibleRows.count(), normalCount);
  if (!n) return;
  if (!misc) {
    if (checkpoint === "CP-0011") {
      assert.equal(n,35); assert.equal(normalCount,59);
    }
    const group = topics.find(t => data.groups[t].length);
    await page.locator("#theme").selectOption(group);
    assert.equal(await visibleRows.count(), data.groups[group].length);
    await page.locator("#limitation-"+group+" button[data-column='3']").click();
    const years = await visibleRows.locator("td:nth-child(4)").allTextContents();
    const present = years.filter(x => x !== "—").map(Number);
    assert.deepEqual(present, [...present].sort((a,b) => a-b));
    await page.locator("#clear").click();
    assert.equal(await visibleRows.count(),normalCount);
    const repeated = data.rows.findIndex((_,i) => Object.values(data.groups).filter(g => g.includes(i)).length>1);
    if (repeated >= 0) {
      await page.locator("#search").fill(data.rows[repeated][0]);
      const matched = await visibleRows.evaluateAll(rs => rs.map(r => r.dataset.key));
      assert.equal(matched.filter(k => k===data.rows[repeated][0]).length,
                   Object.values(data.groups).filter(g => g.includes(repeated)).length);
    }
    await page.screenshot({path:path.join(root,"topics-desktop.png")});
  } else {
    if (checkpoint === "CP-0011") assert.equal(n,5142);
    const last = n-1;
    await page.locator("#search").fill(data.rows[last][0].toLowerCase());
    assert.ok((await visibleRows.evaluateAll(rs => rs.map(r => r.dataset.key))).includes(data.rows[last][0]));
    await page.locator("#clear").click();
    if (n>50) {
      await page.locator("#next").click();
      assert.equal(await visibleRows.first().getAttribute("data-key"),data.rows[50][0]);
      await page.locator("#previous").click();
      assert.equal(await visibleRows.first().getAttribute("data-key"),data.rows[0][0]);
    }
    await page.locator("#literature-U00 button[data-column='3']").click();
    const sorted = data.rows.map((r,i) => [r,i]).sort(([a,i],[b,j]) =>
      (a[3] == null)-(b[3] == null) || Number(a[3])-Number(b[3]) || i-j).map(([r])=>r[0]);
    assert.deepEqual(await visibleRows.evaluateAll(rs=>rs.map(r=>r.dataset.key)),sorted.slice(0,50));
    const noDoi = data.rows.find(r => !r[5]);
    if (noDoi) {
      await page.locator("#search").fill(noDoi[0]);
      const text = await visibleRows.evaluateAll((rs,key)=>rs.find(r=>r.dataset.key===key).cells[5].textContent,noDoi[0]);
      assert.equal(text,"—");
    }
    const fragment="#work-"+data.anchors[last]+"-U00";
    await page.goto(urls.topics+fragment,{waitUntil:"commit"});
    await page.waitForURL(urls.misc+fragment);
    await page.locator(fragment).waitFor({state:"visible"});
    assert.equal(await visibleRows.count(),n%50||50);
    assert.equal(await page.locator(fragment).getAttribute("data-key"), data.rows[last][0]);
    await page.locator("#clear").click();
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(root,"misc-mobile.png")});
  }
  await page.locator("#search").fill("__no_such_literature_work_9ad13c__");
  assert.equal(await visibleRows.count(),0);
  await page.locator("#clear").click();
  assert.equal(await visibleRows.count(),normalCount);
  assert.equal(await page.locator("a.switch").getAttribute("href"),misc?path.basename(fileURLToPath(urls.topics)):"misc.html");
}

export async function runSplitAudit({pw, htmlPath, root, checkpoint, executablePath}) {
  fs.mkdirSync(root,{recursive:true});
  const dir=path.dirname(htmlPath), urls={topics:pathToFileURL(htmlPath).href,misc:pathToFileURL(path.join(dir,"misc.html")).href};
  const names=[path.basename(htmlPath),"misc.html","ref-data/index.css","ref-data/index.js","ref-data/topics.js","ref-data/misc.js"];
  const inventory=()=>Object.fromEntries(names.map(n=>{
    const b=fs.readFileSync(path.join(dir,n));return [n,{bytes:b.length,sha256:digest(b)}];
  }));
  const report={checkpoint_id:checkpoint,started_at_utc:new Date().toISOString(),offline:true,
    method:"Three new browser processes and empty browser profiles per entry, disabled network, navigation through usable rows. Browser launch time recorded separately.",
    samples:{topics:[],misc:[]},checks:{},errors:[],artifacts:inventory()};
  const options={headless:true};
  if (executablePath) options.executablePath=executablePath;
  try {
    for (const kind of ["topics","misc"]) {
      for(let i=0;i<3;i++) {
        const start=performance.now();
        const browser=await pw.launch(options);
        try {
          report.browser=browser.version();
          report.executable=executablePath || "playwright chromium";
          const context=await browser.newContext({offline:true,viewport:{width:1440,height:1000},deviceScaleFactor:1});
          const page=await context.newPage();
          page.setDefaultTimeout(10000);
          const requests=[];
          page.on("pageerror",err=>report.errors.push(String(err)));
          page.on("request",req=>requests.push(req.url()));
          await context.route(/^https?:/i,route=>{report.errors.push("Unexpected network request");return route.abort();});
          const navStart=performance.now();
          await interactive(page,urls[kind]);
          const wall=seconds(performance.now()-navStart);
          const ready=await page.evaluate(()=>performance.getEntriesByName("bibliography-ready")[0].startTime);
          const expected=[urls[kind],...["index.css","index.js",kind+".js"].map(n=>pathToFileURL(path.join(dir,"ref-data",n)).href)];
          assert.deepEqual([...new Set(requests)].sort(),expected.sort());
          report.samples[kind].push({navigation_seconds:seconds(ready),navigation_observed_seconds:wall,
                                     launch_to_ready_seconds:seconds(performance.now()-start)});
          if(i===0) await tableChecks(page,kind==="misc",root,urls,checkpoint);
        } finally {await browser.close();}
      }
    }
    const a=report.artifacts;
    report.median_seconds=Object.fromEntries(Object.entries(report.samples).map(([k,v])=>[k,median(v.map(s=>s.navigation_seconds))]));
    report.total_bytes=Object.values(a).reduce((n,x)=>n+x.bytes,0);
    report.topic_load_bytes=[names[0],"ref-data/index.css","ref-data/index.js","ref-data/topics.js"].reduce((n,k)=>n+a[k].bytes,0);
    if(checkpoint==="CP-0011") {
      assert.ok(a[names[0]].bytes<=32768 && a["misc.html"].bytes<=32768);
      assert.ok(report.topic_load_bytes<=131072 && report.total_bytes<=2097152);
      assert.ok(Object.values(report.median_seconds).every(t=>t<=2));
    }
    assert.deepEqual(inventory(),report.artifacts);
    assert.deepEqual(report.errors,[]);
    report.checks={nine_and_one_tables:true,exact_columns:true,isolated_offline_resources:true,local_search_sort:true,
      pagination_and_legacy_anchor:true,missing_doi:true,clear_and_empty:true,mobile:true,stable_bytes:true};
    report.passed=true;
  } catch(error) {
    report.errors.push(String(error.stack || error));report.passed=false;throw error;
  } finally {
    report.completed_at_utc=new Date().toISOString();
    fs.writeFileSync(path.join(root,"ui-audit-final.json"),JSON.stringify(report,null,2)+"\n");
    console.log(JSON.stringify({passed:report.passed,medians:report.median_seconds,total:report.total_bytes,output:root}));
  }
}
