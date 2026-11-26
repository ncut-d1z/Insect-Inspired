"""Snapshot JSONL partition transport. Records and IDs do not change."""
from pathlib import Path
import json,hashlib
REPO=Path('/workspace/scratch/2e518600ca4c/insect-project');TEMP=REPO/'temp'
def read_logical(name,base=TEMP):
 path=Path(base)/name
 manifest=Path(base)/'partitions/manifest.json'
 parts=[path]
 if manifest.exists():
  d=json.loads(manifest.read_text())
  if name in d['datasets']:parts=[Path(base)/x['path'] for x in d['datasets'][name]['parts']]
 out=[]
 for p in parts:
  with p.open() as f:
   for line in f:
    if line.strip():out.append(json.loads(line))
 return out

def replace_logical(name,rows,base=TEMP):
 """Replace one unpublished logical dataset and update its content-addressed parts."""
 base=Path(base);p=base/name;mp=base/'partitions/manifest.json';m=json.loads(mp.read_text()) if mp.exists() else None
 raw=''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n' for x in rows).encode();old=m['datasets'].get(name) if m else None
 if not old:
  p.write_bytes(raw);return
 cap=m['partition_target_bytes'];parts=[];buf=[];size=0;chunks=[]
 for line in raw.splitlines(keepends=True):
  if buf and size+len(line)>cap:chunks.append(b''.join(buf));buf=[];size=0
  buf.append(line);size+=len(line)
 if buf:chunks.append(b''.join(buf))
 for i,b in enumerate(chunks):
  h=hashlib.sha256(b).hexdigest();q=p if i==0 else base/'partitions'/p.stem/(h+'.jsonl');q.parent.mkdir(exist_ok=True,parents=True);q.write_bytes(b);parts.append(dict(path=str(q.relative_to(base)),sha256=h,records=len(b.splitlines()),bytes=len(b)))
 m['datasets'][name]=dict(logical_records=len(rows),logical_sha256=hashlib.sha256(raw).hexdigest(),parts=parts);mp.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
 live={v['path'] for d in m['datasets'].values() for v in d['parts']}
 for oldpart in old['parts']:
  if oldpart['path'] not in live:(base/oldpart['path']).unlink()

def partition_snapshot(max_bytes=4*1024*1024):
 manifest={'schema_version':'1.1.1','encoding':'UTF-8','record_format':'JSONL','transport_only':True,'partition_target_bytes':max_bytes,'datasets':{}}
 dest=TEMP/'partitions';dest.mkdir(exist_ok=True)
 for p in sorted(TEMP.glob('*.jsonl')):
  if p.stat().st_size<=max_bytes:continue
  raw=p.read_bytes();lines=raw.splitlines(keepends=True);chunks=[];buf=[];size=0
  for line in lines:
   if buf and size+len(line)>max_bytes:chunks.append(b''.join(buf));buf=[];size=0
   buf.append(line);size+=len(line)
  if buf:chunks.append(b''.join(buf))
  parts=[]
  for i,b in enumerate(chunks):
   h=hashlib.sha256(b).hexdigest();q=p if i==0 else dest/p.stem/(h+'.jsonl');q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
   parts.append({'path':str(q.relative_to(TEMP)),'sha256':h,'records':len(b.splitlines()),'bytes':len(b)})
  manifest['datasets'][p.name]={'logical_records':len(lines),'logical_sha256':hashlib.sha256(raw).hexdigest(),'parts':parts}
 (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 return manifest
if __name__=='__main__':print(json.dumps(partition_snapshot(),ensure_ascii=False)[:1000])
