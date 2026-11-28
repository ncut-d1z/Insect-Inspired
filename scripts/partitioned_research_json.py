"""Store an ordered JSON research view as readable entity collections with SHA-256 bindings."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

FORMAT="partitioned-research-json-v1"
LIMIT=2*1024*1024
ENTITY_KEYS={"people":"person_id","organizations":"org_id","projects":"project_id","work_refs":"work_id","relations":"relation_id"}
GRAPH_KEYS={"nodes":"work_id","edges":"edge_id","unresolved_occurrences":"occurrence_id","independent_progress":"assessment_id"}


def encode(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bound_path(folder,relative):
    p=PurePosixPath(relative)
    if p.is_absolute() or not p.parts or any(s in (".","..") or ":" in s or "\\" in s for s in p.parts):
        raise ValueError("Invalid relative view path")
    path=folder.joinpath(*p.parts)
    if not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink():raise ValueError("Path escapes view directory")
    return path


def put(path,data,immutable=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        prior=path.read_bytes()
        if prior==data:return
        if immutable:raise ValueError("Mutable content-addressed JSON part: "+str(path))
    with NamedTemporaryFile(dir=path.parent, prefix=path.name+".", suffix=".part", delete=False) as out:
        tmp=Path(out.name)
        try:
            out.write(data)
        except BaseException:
            out.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def write_view(entry,view,keys):
    """Write chunks first. An existing active index remains usable until the final pointer is replaced."""
    entry=Path(entry);folder=entry.with_suffix("")
    if not set(keys)<=set(view):raise ValueError("Missing research collection")
    meta={k:v for k,v in view.items() if k not in keys}
    real=hashlib.sha256();real.update(b"{");first=True
    collections={}
    for name in sorted(view):
        if not first:real.update(b",")
        first=False;real.update(encode(name)+b":")
        if name not in keys:real.update(encode(view[name]));continue
        key=keys[name];real.update(b"[");parts=[];count=0;last=None;buf=[];mass=0;first_id=None;kinds=Counter()
        header={"checkpoint_id":meta["checkpoint_id"],"collection":name,"scope_id":meta["scope_id"],"schema_version":meta["schema_version"]}
        prefix=encode(header)[:-1]+b',"records":[';suffix=b"]}\n"
        def flush():
            nonlocal buf,mass,first_id
            if not buf:return
            raw=prefix+b",".join(buf)+suffix
            if len(raw)>LIMIT:raise ValueError("A JSON record exceeds the configured shard size")
            h=sha(raw);p=f"{name}/{len(parts)+1:04}-{h}.json"
            put(bound_path(folder,p),raw,immutable=True)
            parts.append(dict(path=p,records=len(buf),bytes=len(raw),sha256=h,first_id=first_id,last_id=last))
            buf=[];mass=0;first_id=None
        for row in view[name]:
            ident=row[key]
            if not isinstance(ident,str) or (last is not None and ident<=last):raise ValueError("Unsorted or duplicate "+name+" identity "+str(ident))
            raw=encode(row)
            if buf and mass+len(raw)+1+len(prefix)+len(suffix)>LIMIT:flush()
            if not buf:first_id=ident
            if count:real.update(b",")
            real.update(raw);mass+=len(raw)+(1 if buf else 0);buf.append(raw);last=ident;count+=1
            if name=="relations":kinds[row["relation_type"]]+=1
        flush();real.update(b"]")
        collections[name]=dict(id_field=key,records=count,parts=parts)
        if kinds:collections[name]["relation_types"]=dict(kinds)
    real.update(b"}\n")
    idx=dict(format=FORMAT,kind=entry.stem,metadata=meta,logical_sha256=real.hexdigest(),collections=collections)
    payload=encode(idx)+b"\n"
    # Include the index hash in its name so every published prior entry remains usable.
    h=sha(payload);unique="index-"+h+".json"
    put(folder/unique,payload,immutable=True)
    put(folder/"index.json",payload)
    pointer=dict(format=FORMAT,kind=entry.stem,scope_id=meta["scope_id"],checkpoint_id=meta["checkpoint_id"],
                 index=folder.name+"/"+unique,index_sha256=h)
    put(entry,encode(pointer)+b"\n")
    return idx


def metadata(entry):
    entry=Path(entry);top=json.loads(entry.read_bytes())
    if top.get("format")!=FORMAT:return top,None
    path=bound_path(entry.parent,top["index"]);raw=path.read_bytes()
    if sha(raw)!=top["index_sha256"]:raise ValueError("Research index digest mismatch")
    idx=json.loads(raw)
    if idx["format"]!=FORMAT or idx["kind"]!=top["kind"] or idx["metadata"]["scope_id"]!=top["scope_id"] or idx["metadata"]["checkpoint_id"]!=top["checkpoint_id"]:
        raise ValueError("Research pointer or scope differs")
    return idx,path.parent


def records(idx,folder,name):
    desc=idx["collections"][name];last=None;total=0
    for part in desc["parts"]:
        data=bound_path(folder,part["path"]).read_bytes()
        if len(data)!=part["bytes"] or sha(data)!=part["sha256"]:raise ValueError("Invalid research part "+part["path"])
        block=json.loads(data);rows=block["records"]
        if block["collection"]!=name or any(block[k]!=idx["metadata"][k] for k in ("scope_id","checkpoint_id","schema_version")) or len(rows)!=part["records"] or not rows:
            raise ValueError("Invalid collection header")
        key=desc["id_field"]
        if rows[0][key]!=part["first_id"] or rows[-1][key]!=part["last_id"]:raise ValueError("Part boundaries differ")
        for row in rows:
            ident=row[key]
            if last is not None and ident<=last:raise ValueError("Identity duplicated or out of order")
            total+=1;last=ident;yield row
    if total!=desc["records"]:raise ValueError("Collection total differs")


def load_view(entry):
    idx,folder=metadata(entry)
    if folder is None:return idx
    obj=dict(idx["metadata"]);digest=hashlib.sha256();digest.update(b"{")
    for n,key in enumerate(sorted(obj.keys()|idx["collections"].keys())):
        if n:digest.update(b",")
        digest.update(encode(key)+b":")
        if key in idx["metadata"]:
            digest.update(encode(obj[key]))
            continue
        rows=[];digest.update(b"[")
        for i,row in enumerate(records(idx,folder,key)):
            if i:digest.update(b",")
            digest.update(encode(row));rows.append(row)
        obj[key]=rows;digest.update(b"]")
    digest.update(b"}\n")
    if digest.hexdigest()!=idx["logical_sha256"]:raise ValueError("Logical view SHA-256 differs")
    return obj


def view_files(entry):
    entry=Path(entry);idx,folder=metadata(entry)
    if folder is None:return [entry]
    top=json.loads(entry.read_bytes());active=[entry,bound_path(entry.parent,top["index"]),folder/"index.json"]
    if (folder/"index.json").read_bytes()!=active[1].read_bytes():raise ValueError("Directory index and active entry differ")
    return [*active,*(bound_path(folder,p["path"]) for c in idx["collections"].values() for p in c["parts"])]


def reconstruction_info(entry, output=None):
    """Verify the complete logical byte stream and optionally write it to a new file."""
    index, folder = metadata(entry)
    if folder is None:
        data = encode(index) + b"\n"
        if output is not None:
            with output.open("xb") as dest:
                dest.write(data)
        return {"logical_sha256":sha(data),"logical_bytes":len(data)}
    view_files(entry)
    def chunks():
        yield b"{"
        for n, key in enumerate(sorted(index["metadata"].keys() | index["collections"].keys())):
            if n:
                yield b","
            yield encode(key) + b":"
            if key in index["metadata"]:
                yield encode(index["metadata"][key])
            else:
                yield b"["
                for i, row in enumerate(records(index, folder, key)):
                    if i:
                        yield b","
                    yield encode(row)
                yield b"]"
        yield b"}\n"
    digest = hashlib.sha256()
    length = 0
    dest = output.open("xb") if output is not None else None
    try:
        for chunk in chunks():
            length += len(chunk)
            digest.update(chunk)
            if dest is not None:
                dest.write(chunk)
        if digest.hexdigest() != index["logical_sha256"]:
            raise ValueError("Reconstructed JSON digest differs from the manifest")
    except BaseException:
        if dest is not None:
            dest.close()
            output.unlink(missing_ok=True)
        raise
    finally:
        if dest is not None:
            dest.close()
    return {"logical_sha256":digest.hexdigest(),"logical_bytes":length}


def reconstruct(entry, output=None):
    return reconstruction_info(entry, output)["logical_sha256"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry", type=Path)
    parser.add_argument("--output", type=Path, help="Create the original logical JSON at a new path after verification")
    args = parser.parse_args()
    print(reconstruct(args.entry, args.output))
