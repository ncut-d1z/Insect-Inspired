import fs from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';

const argv=process.argv.slice(2);
if (argv.includes('--help')) {
 console.log('Usage: node scripts/html-smoke-checkpoint.mjs --html FILE --out-dir NEW_EXTERNAL_DIR --checkpoint CP-NNNN [--executable-path CHROMIUM]');
 process.exit(0);
}
const options={};
for (let i=0;i<argv.length;i+=2) {
 if (!['--html','--out-dir','--checkpoint','--executable-path'].includes(argv[i]) || !argv[i+1] || argv[i+1].startsWith('--')) throw new Error('Unknown or incomplete argument');
 if (options[argv[i]]) throw new Error('Duplicate argument');
 options[argv[i]]=argv[i+1];
}
if (!options['--html'] || !options['--out-dir'] || !/^CP-[0-9]{4}$/.test(options['--checkpoint'] || '')) throw new Error('Explicit HTML, new external output directory and CP-NNNN are required');
const root=path.resolve(options['--out-dir']);
const htmlPath=path.resolve(options['--html']);
const repo=path.dirname(htmlPath);
if (!fs.existsSync(htmlPath) || fs.existsSync(root)) throw new Error('HTML must exist and output directory must be new');
if (root===repo || root.startsWith(repo+path.sep)) throw new Error('UI output must be outside the repository');
const require=createRequire(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES ? path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES,'_checkpoint_resolution.cjs') : import.meta.url);
const {chromium: pw}=require('playwright');
fs.mkdirSync(root,{recursive:true});
const htmlBefore=fs.readFileSync(htmlPath);
const htmlSha=createHash('sha256').update(htmlBefore).digest('hex');
const report={checkpoint_id:options['--checkpoint'],started_at_utc:new Date().toISOString(),errors:[],checks:{},html_path:htmlPath,html_bytes:htmlBefore.length,html_sha256:htmlSha,screenshots:['html-desktop.png','html-topic.png','html-mobile.png','html-mobile-controls.png']};
const assert=(ok,message)=>{if(!ok)throw new Error(message);};
const launchOptions={headless:true};
if (options['--executable-path']) launchOptions.executablePath=options['--executable-path'];
const browser=await pw.launch(launchOptions);
try {
 const page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});
 page.setDefaultTimeout(60000);
 page.on('pageerror',e=>report.errors.push(String(e)));
 const started=Date.now();
 await page.goto(pathToFileURL(htmlPath).href,{waitUntil:'domcontentloaded',timeout:60000});
 report.load_seconds=(Date.now()-started)/1000;
 console.log('Loaded',report.load_seconds,'seconds');
 const ids=await page.locator('table').evaluateAll(t=>t.map(x=>x.id));
 assert(JSON.stringify(ids)===JSON.stringify([...Array(9)].map((_,i)=>`limitation-L${String(i+1).padStart(2,'0')}`).concat(['literature-U00'])),'Ten table IDs/order mismatch');
 report.checks.ten_fixed_tables=true;
 const summary=await page.locator('#database-summary').textContent();report.summary=JSON.parse(summary);
 assert(report.summary.checkpoint_id===options['--checkpoint'],'HTML checkpoint differs from requested CP-NNNN');
 await page.screenshot({path:path.join(root,'html-desktop.png')});
 await page.locator('#search').fill('Strubbe2019');
 await page.locator('#theme').selectOption('L06');
 let visible=await page.locator('tr[data-key]:not([hidden])').evaluateAll(rows=>rows.map(r=>({key:r.dataset.key,theme:r.dataset.theme})));
 assert(visible.length===1&&visible[0].key==='Strubbe2019'&&visible[0].theme==='L06','Search and theme filter failed');
 report.checks.search_and_theme=true;
 await page.locator('#toggle-abstracts').click();
 assert(await page.locator('details.abstract[open]').count()>0,'Abstract expansion failed');
 assert(await page.locator('#toggle-abstracts').getAttribute('aria-pressed')==='true','Abstract button aria state failed');
 await page.locator('#toggle-abstracts').click();
 assert(await page.locator('details.abstract[open]').count()===0,'Abstract collapse failed');
 report.checks.abstract_expand_collapse=true;
 await page.locator('#toggle-evidence').click();
 assert(await page.locator('details.evidence[open]').count()>0,'Evidence expansion failed');
 await page.locator('#toggle-evidence').click();
 assert(await page.locator('details.evidence[open]').count()===0,'Evidence collapse failed');
 report.checks.evidence_expand_collapse=true;
 await page.locator('#section-L06').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(root,'html-topic.png')});
 await page.locator('.back').click();
 await page.waitForFunction(()=>window.scrollY<10,{},{timeout:10000});
 report.checks.back_to_top=true;
 await page.locator('#clear').click();
 assert(await page.locator('#search').inputValue()===''&&await page.locator('#theme').inputValue()==='all','Clear failed');
 assert(await page.locator('tr[data-key]:not([hidden])').count()===report.summary.table_rows,'Clear did not restore all rows');
 report.checks.clear=true;
 await page.locator('#status').selectOption('counter_evidence');
 visible=await page.locator('tr[data-key]:not([hidden])').evaluateAll(rows=>rows.map(r=>r.dataset.status));
 assert(visible.length>0&&visible.every(x=>x.split(' ').includes('counter_evidence')),'State filter failed');
 report.checks.counter_evidence_filter=true;
 await page.locator('#clear').click();
 await page.locator('#theme').selectOption('L01');
 await page.locator('#limitation-L01 .sort[data-sort="year"]').click();
 const years=await page.locator('#limitation-L01 tr[data-key]').evaluateAll(rows=>rows.map(r=>Number(r.dataset.year)));
 assert(years.every((n,i)=>i===0||years[i-1]<=n),'Year sort failed');
 report.checks.year_sort=true;
 await page.locator('#clear').click();
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
 await page.screenshot({path:path.join(root,'html-mobile.png')});
 const dimensions=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));
 assert(dimensions.scrollWidth<=dimensions.width,'Mobile document overflows viewport');
 report.checks.mobile_no_document_overflow=true;
 report.mobile_dimensions=dimensions;
 await page.locator('#search').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(root,'html-mobile-controls.png')});
 assert(report.errors.length===0,'Browser JS errors observed');
 report.checks.no_javascript_errors=true;
 report.completed_at_utc=new Date().toISOString();
 report.passed=true;
} catch(error) {
 report.passed=false;report.failure=String(error);console.error(error);
} finally {
 await browser.close();
 report.html_sha256_after=createHash('sha256').update(fs.readFileSync(htmlPath)).digest('hex');
 report.input_changed=report.html_sha256_after!==htmlSha;
 if(report.input_changed){report.passed=false;report.failure='Input HTML changed during UI validation';}
 if(Object.keys(report.checks).length!==10){report.passed=false;report.failure=report.failure||'Expected ten UI checks';}
 fs.writeFileSync(path.join(root,'html-browser-check.json'),JSON.stringify(report,null,2)+'\n');
 fs.writeFileSync(path.join(root,'ui-audit-final.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(report));
}
if(!report.passed)process.exitCode=1;
