"""One-project audit executable. Project-local inherited rules; no network crawling."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from urllib.parse import unquote,urlsplit
import json,re,hashlib,csv,io,math
from html.parser import HTMLParser
from jsonschema import Draft202012Validator,FormatChecker
ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/'temp/schema.json').read_text())
SEED_RELATIONS={'S01':('S15','contains_publication'),'S15':('S01','included_in_thesis'),'S02':('S17','preliminary_of'),'S17':('S02','expanded_from'),'S19':('S20','related_report'),'S20':('S19','related_report')}
DIMENSIONS=['metadata','fulltext','abstract','references','citations','authors','affiliations_projects','assessment']
class GateError(ValueError):pass

def dt(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def iso(d):return d.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def schema_errors(kind,data):
 v=Draft202012Validator({'$schema':SCHEMA['$schema'],'$ref':'#/$defs/'+kind,'$defs':SCHEMA['$defs']},format_checker=FormatChecker())
 return [f"{'.'.join(map(str,e.path))}: {e.message}" for e in sorted(v.iter_errors(data),key=lambda e:str(e.path))]
def validate(kind,data):
 errors=schema_errors(kind,data)
 if errors:raise GateError('; '.join(errors[:8]))
 check_values(data)
 return True

def check_values(x,path=''):
 if isinstance(x,float) and not math.isfinite(x):raise GateError('non-finite value '+path)
 if isinstance(x,dict):
  if {'quantity','min','max'}<=x.keys():
   if x['min']>x['max']:raise GateError('range reversed '+path)
   allowed={'angular_velocity':['deg/s','rad/s','degrees/s','°/s'],'linear_velocity':['m/s','mm/s','cm/s'],'angular_displacement':['deg','rad','degrees','°'],'linear_displacement':['m','mm','cm'],'sample_interval':['s','ms','us'],'fov':['deg','rad','degrees','°'],'distance':['m','mm','cm']}
   if x['quantity'] in allowed and x['unit'] not in allowed[x['quantity']]:raise GateError('incompatible unit '+path)
  if x.get('status')=='reported' and isinstance(x.get('value'),list) and 'none' in x['value'] and len(x['value'])>1:raise GateError('none prior not exclusive')
  for k,v in x.items():check_values(v,path+'.'+k)
 elif isinstance(x,list):
  for i,v in enumerate(x):check_values(v,f'{path}[{i}]')

def normalize_doi(s):
 t=s.strip();t=re.sub(r'^doi:\s*','',t,flags=re.I)
 if re.match(r'^https?://(?:dx\.)?doi\.org/',t,re.I):t=unquote(urlsplit(t).path.lstrip('/'))
 return t.lower()

def register_unknown(condition,entity_id,field_path,scope_id,tasks,now):
 """Unique open task and stable clock. Mutates only an in-memory transaction."""
 if condition['status'] not in ('unknown','unknown_review_required'):return
 sig=(entity_id,field_path,scope_id)
 found=[t for t in tasks if (t['entity_id'],t['field_path'],t['scope_id'])==sig and t['task_state'] not in ('verified_complete','not_applicable')]
 if found:
  task=found[-1];condition['unknown_since_utc']=task['unknown_since_utc'];condition['review_task_id']=task['task_id']
 else:
  start=condition.get('unknown_since_utc') or iso(now)
  task_id='TASK-REVIEW-'+hashlib.sha256('|'.join(sig).encode()).hexdigest()[:16]
  task={'task_id':task_id,'entity_id':entity_id,'field_path':field_path,'scope_id':scope_id,'task_state':'pending','unknown_since_utc':start,'deadline_at_utc':iso(dt(start)+timedelta(hours=24)),'failure_reason':condition['reason'],'priority':'normal','overdue':False,'event_sequence':1}
  tasks.append(task);condition['unknown_since_utc']=start;condition['review_task_id']=task_id
 if now>=dt(task['deadline_at_utc']):
  condition['status']='unknown_review_required'
  if not task['overdue']:
   task=deepcopy(task);task['overdue']=True;task['priority']='high';task['event_sequence']+=1;tasks.append(task)
 return task

def assert_unknowns(x,tasks,now,path=''):
 taskmap={t['task_id']:t for t in tasks}
 if isinstance(x,dict):
  if x.get('status') in ('unknown','unknown_review_required'):
   if not x.get('unknown_since_utc') or x.get('review_task_id') not in taskmap:raise GateError('unknown without task '+path)
   t=taskmap[x['review_task_id']]
   if t.get('unknown_since_utc')!=x['unknown_since_utc']:raise GateError('unknown clock changed')
   if now-dt(x['unknown_since_utc'])>=timedelta(hours=24) and x['status']!='unknown_review_required':raise GateError('un-escalated overdue unknown '+path)
  for k,v in x.items():assert_unknowns(v,tasks,now,path+'.'+k)
 elif isinstance(x,list):
  for i,v in enumerate(x):assert_unknowns(v,tasks,now,f'{path}[{i}]')

def admit(seed_id,identity_verified,path,admitted_roots,valid_entities,source_ids,scope_id,authorized=True):
 if not authorized:return False,'access_not_authorized'
 if seed_id:
  if seed_id not in {'S%02d'%i for i in range(1,21)}:return False,'seed_not_listed'
  if not identity_verified:return False,'seed_identity_mismatch'
  return True,None
 if not path:return False,'missing_discovery_path'
 if path[0]['from_entity_id'] not in admitted_roots:return False,'unverified_discovery_path'
 prev=None
 for p in path:
  if p['scope_id']!=scope_id:return False,'out_of_scope'
  if p['source_id'] not in source_ids or p['verification_status']!='verified' or not p['evidence_locator']:return False,'unverified_discovery_path'
  if p['from_entity_id'] not in valid_entities or p['to_entity_id'] not in valid_entities:return False,'unverified_discovery_path'
  if prev is not None and p['from_entity_id']!=prev:return False,'unverified_discovery_path'
  prev=p['to_entity_id']
 return True,None

def seed_topology(seeds):
 m={s['seed_id']:s for s in seeds}
 if set(m)!={'S%02d'%i for i in range(1,21)} or len(m)!=len(seeds):raise GateError('seed identity set mismatch')
 for sid,s in m.items():
  expected=SEED_RELATIONS.get(sid,(None,None))
  if (s['target_related_id'],s['seed_relation_type'])!=expected:raise GateError('locked seed relation changed '+sid)
  if expected[0] and s['work_id'] and m[expected[0]]['work_id']==s['work_id']:raise GateError('independent seed works merged')
 return True

def topology(works,versions,uploads,duplicates=()):
 w={x['work_id']:x for x in works};v={x['version_id']:x for x in versions};u={x['upload_id']:x for x in uploads};d={x['upload_id']:x for x in duplicates}
 if len(w)!=len(works) or len(v)!=len(versions) or len(u)!=len(uploads) or set(u)&set(d):raise GateError('duplicate identity')
 if any(not any(y['work_id']==wid for y in versions) for wid in w):raise GateError('work without version')
 if any(y['work_id'] not in w for y in versions):raise GateError('orphan version')
 for x in list(uploads)+list(duplicates):
  if x['version_id'] not in v or v[x['version_id']]['work_id']!=x['work_id']:raise GateError('upload owner mismatch')
  seen=set();cur=x
  while cur.get('duplicate_of_upload_id'):
   ident=cur['upload_id']
   if ident in seen:raise GateError('duplicate pointer cycle')
   seen.add(ident);target=cur['duplicate_of_upload_id']
   cur=u.get(target) or d.get(target)
   if cur is None:raise GateError('duplicate missing target')
  if x.get('duplicate_of_upload_id') and (x['work_id']!=cur['work_id'] or x['version_id']!=cur['version_id'] or x['sha256']!=cur['sha256']):raise GateError('duplicate content/identity mismatch')
 return True

def cascade(state,duplicate_id,canonical_id,fail_before_commit=False):
 """Atomic copy-on-write implementation used for controlled audit and P2 reimport."""
 new=deepcopy(state);um={x['upload_id']:x for x in new['uploads']}
 if duplicate_id==canonical_id or duplicate_id not in um or canonical_id not in um:raise GateError('bad duplicate pointer')
 dup,can=um[duplicate_id],um[canonical_id]
 if any(dup[k]!=can[k] for k in ['work_id','version_id','sha256']):raise GateError('independent/nonidentical upload')
 dup['duplicate_of_upload_id']=canonical_id;dup['relation_type']='duplicate_upload'
 affected=[];merged={};discarded=[]
 for a in new['assessments']:
  if duplicate_id in a.get('provenance_upload_ids',[]):
   affected.append(a['assessment_id']);a['provenance_upload_ids']=sorted({canonical_id if u==duplicate_id else u for u in a['provenance_upload_ids']})
   # Locators with invalid positions remain invalid: no invention of positions.
   for loc in a['evidence_locator']:
    if loc.get('upload_id')==duplicate_id:loc['upload_id']=canonical_id
   valid=[l for l in a['evidence_locator'] if any(l.get(k) for k in ['page','section','figure','equation','table','paragraph','url'])]
   if not valid:
    a['assessment_status']='discarded';a['discard_reason']='No valid locator after duplicate-source reconciliation';discarded.append(a['assessment_id'])
    new.setdefault('tasks',[]).append({'task_id':'TASK-REVIEW-'+a['assessment_id'],'entity_id':a['assessment_id'],'task_state':'pending','failure_reason':a['discard_reason']})
 sigs={}
 for a in sorted(new['assessments'],key=lambda x:x['assessment_id']):
  if a['assessment_status']!='active':continue
  # Conditions, route, conclusions and negative evidence all participate.
  signature=canonical({k:a.get(k) for k in ['work_id','limitation_id','evidence_route','claim_id','conditions','results','counter_evidence','counter_evidence_types','evidence_locator']})
  if signature in sigs:
   can_a=sigs[signature];can_a['provenance_upload_ids']=sorted(set(can_a['provenance_upload_ids'])|set(a['provenance_upload_ids']))
   a['assessment_status']='merged';a['superseded_by_assessment_id']=can_a['assessment_id'];merged[a['assessment_id']]=can_a['assessment_id']
  else:sigs[signature]=a
 for collection in ['reference_occurrences','citation_edges','tasks','aliases']:
  def remap(x):
   if isinstance(x,dict):return {k:canonical_id if k=='upload_id' and v==duplicate_id else remap(v) for k,v in x.items()}
   if isinstance(x,list):return [remap(v) for v in x]
   return x
  if collection in new:new[collection]=remap(new[collection])
 new['uploads']=[x for x in new['uploads'] if x['upload_id']!=duplicate_id]
 dup.update(record_type='duplicate_upload',seed_id=None);new.setdefault('duplicates',[]).append(dup)
 topology(new['works'],new['versions'],new['uploads'],new['duplicates'])
 # Audit failure occurs before returned transaction state is installable.
 if fail_before_commit:raise GateError('injected validation failure: rolled back')
 new.setdefault('cascade_events',[]).append({'trigger_upload_id':duplicate_id,'canonical_upload_id':canonical_id,'affected_assessment_ids':affected,'merged_assessment_map':merged,'discarded_assessment_ids':discarded,'transaction_status':'committed'})
 return new

def evidence_gate(a):
 codes=[]
 if a.get('evidence_level')!='fulltext_result' or not a.get('evidence_locator'):codes.append('missing_fulltext_evidence')
 proof=a.get('proof_record');theory=a.get('claim_type')=='theoretical'
 if theory:
  if not proof or proof.get('verification_status')!='verified' or not all(proof.get(k) for k in ['assumption_locators','derivation_locators','conclusion_locator']):codes.append('missing_rigorous_derivation')
 else:
  ms=a.get('metric_records',[]);ds=a.get('dataset_records',[])
  if not ms or not any(m.get('value') is not None and math.isfinite(m['value']) for m in ms):codes.append('missing_quantitative_result')
  if any(not m.get('unit') or not m.get('definition') for m in ms):codes.append('missing_metric_definition_or_unit')
  if not ds or any(not d.get('source_locator') for d in ds):codes.append('missing_dataset_provenance')
  dataset_ids={d['dataset_id'] for d in ds}
  if any(m.get('dataset_id') not in dataset_ids for m in ms):codes.append('missing_dataset_provenance')
  if a.get('claim_type')=='engineering_trajectory':
   names={m['metric_name'] for m in ms if m.get('value') is not None}
   if 'ATE' not in names or not ({'RPE_translation','RPE_rotation'}&names):codes.append('missing_trajectory_metrics')
   if not any(d.get('sequence_ids') and d.get('ground_truth_source') for d in ds):codes.append('missing_dataset_provenance')
   if any(m['metric_name'].startswith('RPE') and not m.get('interval') for m in ms):codes.append('missing_trajectory_metrics')
  factors={}
  for c in a.get('condition_levels',[]):factors.setdefault(c['factor'],set()).add(c['level_id'])
  if a.get('limitation_id')=='L02' and not any(len(factors.get(f,set()))>=2 for f in ['contrast','spatial_frequency','texture']):codes.append('threshold_not_met')
  if a.get('limitation_id')=='L03' and a.get('claim_subtype')=='adaptation' and len(factors.get('adaptation_state',set()))<2:codes.append('threshold_not_met')
  if a.get('limitation_id')=='L07' and len(factors.get('speed',set()))<2:codes.append('threshold_not_met')
 conds=a.get('conditions',{})
 for k,c in conds.items():
  if k in ['motion_type','scale','environment','method_and_validation'] and c.get('status') in ('unknown','unknown_review_required'):codes.append('missing_critical_conditions')
 if a.get('claims_absolute_scale',{}).get('value') is True and a.get('limitation_id') in ['L06','L08']:
  prior=conds.get('scale_source_prior',{});obs=conds.get('scale_observability',{})
  if prior.get('status')!='reported' or not prior.get('value') or 'none' in prior['value'] or not a.get('scale_prior_details'):codes.append('missing_metric_scale_prior')
  if obs.get('status')!='reported' or obs.get('value') not in ['proven_under_assumptions','empirically_validated_under_assumptions'] or not a.get('observability_argument_locator') or not a.get('measurement_model') or not a.get('observability_assumptions'):codes.append('scale_observability_not_demonstrated')
  if not theory:
   metrics=a.get('metric_records',[])
   if not any(m.get('value') is not None and m.get('alignment') in ['none','SE3'] and m.get('alignment_source')!='ground_truth_fit' and m.get('unit') in ['m','mm','cm','m/s','mm/s','cm/s'] for m in metrics):codes.append('invalid_metric_alignment')
 codes=sorted(set(codes));out=deepcopy(a);out['rejection_codes']=codes;out['evidence_admission_status']='insufficient_evidence' if codes else 'eligible'
 if codes:out['handling_level']='insufficient_evidence'
 return out

class Tables(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.keys={};self.current=None
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=='table':self.current=d.get('id');self.ids.append(self.current);self.keys.setdefault(self.current,[])
  if tag=='tr' and d.get('data-key') and self.current:self.keys[self.current].append(d['data-key'])
 def handle_endtag(self,tag):
  if tag=='table':self.current=None

def reconcile(works,assessments,bib,html,exports):
 K={w['work_key'] for w in works}
 bibkeys=re.findall(r'@\w+\s*\{\s*([^,\s]+)\s*,',bib)
 if len(bibkeys)!=len(set(bibkeys)) or set(bibkeys)!=K:raise GateError('BibTeX Work mismatch')
 t=Tables();t.feed(html);expected=['limitation-L%02d'%i for i in range(1,10)]+['literature-U00']
 if sorted(t.ids)!=sorted(expected):raise GateError('HTML table set mismatch')
 for k,keys in t.keys.items():
  if len(keys)!=len(set(keys)):raise GateError('duplicate table key')
 T=set().union(*(set(t.keys.get(i,[])) for i in expected[:-1]));U=set(t.keys.get('literature-U00',[]))
 if T|U!=K or U!=K-T:raise GateError('K/T/U mismatch')
 active={a['assessment_id'] for a in assessments if a['assessment_status']=='active'}
 for name in ['evidence_matrix.csv','research_implications.csv']:
  rows=list(csv.DictReader(io.StringIO(exports[name])));ids=[x['assessment_id'] for x in rows]
  if set(ids)!=active or len(ids)!=len(set(ids)):raise GateError('Assessment export mismatch '+name)
 graph=exports['citation_graph.json']
 if {w['work_id'] for w in works}!={n['work_id'] for n in graph['nodes']}:raise GateError('graph nodes mismatch')
 wm={w['work_id']:w['work_key'] for w in works}
 for e in graph['edges']:
  if wm.get(e['citing_work_id'])!=e['citing_key'] or wm.get(e['cited_work_id'])!=e['cited_key']:raise GateError('graph FK mismatch')
 if {w['work_id'] for w in exports['research_entities.json']['work_refs']}!=set(wm):raise GateError('entities Work mismatch')
 for p in exports['research_paths.json']['paths']:
  if p['assessment_id'] not in active or p['work_id'] not in wm:raise GateError('path FK mismatch')
 return {'K':len(K),'T_union':len(T),'U':len(U),'tables':len(t.ids),'active_assessments':len(active)}

def validate_formal(root=ROOT,now=None):
 errs=[];counts={};records={}
 for filename,kind in SCHEMA['x-entity-files'].items():
  p=root/'temp'/filename
  if not p.exists():errs.append(filename+': missing');continue
  rows=[]
  for line_no,line in enumerate(p.read_text().splitlines(),1):
   if not line.strip():continue
   try:row=json.loads(line);validate(kind,row);rows.append(row)
   except Exception as e:errs.append(f'{filename}:{line_no}: {e}')
  records[filename]=rows;counts[filename]=len(rows)
 try:
  seed_topology([s for s in records.get('seed-manifest.jsonl',[]) if s['record_type']=='seed_mapping'])
  topology(records.get('works.jsonl',[]),records.get('versions.jsonl',[]),records.get('uploads.jsonl',[]),[s for s in records.get('seed-manifest.jsonl',[]) if s['record_type']=='duplicate_upload'])
 except Exception as e:errs.append('relations: '+str(e))
 if now:
  for name,rows in records.items():
   try:assert_unknowns(rows,records.get('tasks.jsonl',[]),now)
   except Exception as e:errs.append(name+': '+str(e))
 return {'passed':not errs,'counts':counts,'errors':errs}
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--formal',action='store_true');args=p.parse_args()
 if args.formal:
  out=validate_formal(now=datetime.now(timezone.utc));print(json.dumps(out,ensure_ascii=False,indent=2));raise SystemExit(0 if out['passed'] else 1)

def resolve_condition(previous,replacement,*,complete_fulltext_checked=False,applicability_checked=False):
 """Reviewer resolution requires actual recorded examination, not error erasure."""
 if replacement['status']=='not_reported' and (not complete_fulltext_checked or not replacement.get('evidence_locator')):raise GateError('not_reported requires completed relevant fulltext review')
 if replacement['status']=='not_applicable' and not applicability_checked:raise GateError('not_applicable requires verified applicability decision')
 if replacement['status']=='reported' and (replacement.get('value') is None or not replacement.get('evidence_locator')):raise GateError('reported requires value and evidence')
 if replacement['status'] in ['unknown','unknown_review_required'] and previous.get('unknown_since_utc')!=replacement.get('unknown_since_utc'):raise GateError('unknown clock reset')
 return deepcopy(replacement)

def cache_key(entity_id,task_type,source_id,api_version,parameters,scope_id,snapshot):
 return digest([entity_id,task_type,source_id,api_version,parameters,scope_id,snapshot])

def checkpoint_write(path,state,valid=True):
 if not valid:raise GateError('invalid checkpoint rejected')
 payload=canonical(state);record={'state':state,'state_sha256':hashlib.sha256(payload.encode()).hexdigest(),'status':'valid'}
 p=Path(path);tmp=p.with_suffix('.partial');tmp.write_text(canonical(record)+'\n');tmp.replace(p)
 return record

def checkpoint_resume(path):
 c=json.loads(Path(path).read_text())
 if c['status']!='valid' or digest(c['state'])!=c['state_sha256']:raise GateError('checkpoint integrity mismatch')
 return c['state']
