"""Bind large checkpoint task cursors and unresolved task IDs to ordinary JSON files."""
import hashlib
import json
from pathlib import Path
from partitioned_research_json import bound_path, encode, metadata, put, records, sha, view_files, write_view

FORMAT = "partitioned-research-checkpoint-v1"
COLLECTIONS = {"task_cursor_state": "task_id", "unresolved_tasks": "task_id"}


def logical_chunks(checkpoint):
    yield b"{"
    for i, key in enumerate(sorted(checkpoint)):
        if i:
            yield b","
        yield encode(key) + b":"
        if key == "task_cursor_state":
            yield b"{"
            for j, (tid, cursor) in enumerate(sorted(checkpoint[key].items())):
                if j:
                    yield b","
                yield encode(tid) + b":" + encode(cursor)
            yield b"}"
        elif key == "unresolved_tasks":
            yield b"["
            for j, tid in enumerate(checkpoint[key]):
                if j:
                    yield b","
                yield encode(tid)
            yield b"]"
        else:
            yield encode(checkpoint[key])
    yield b"}\n"


def logical_binding(checkpoint):
    digest = hashlib.sha256()
    size = 0
    for chunk in logical_chunks(checkpoint):
        digest.update(chunk)
        size += len(chunk)
    return dict(logical_sha256=digest.hexdigest(), logical_bytes=size)


def write_checkpoint(path, checkpoint):
    path = Path(path)
    public = {k: v for k, v in checkpoint.items() if k not in COLLECTIONS}
    meta = {k: public[k] for k in ("scope_id", "checkpoint_id", "schema_version")}
    if public["checkpoint_id"] != path.stem or not set(checkpoint["unresolved_tasks"]) <= checkpoint["task_cursor_state"].keys():
        raise ValueError("Checkpoint path or task membership differs")
    queues = {
        **meta,
        "task_cursor_state": ({"task_id": k, "cursor_state": v} for k, v in sorted(checkpoint["task_cursor_state"].items())),
        "unresolved_tasks": ({"task_id": tid} for tid in checkpoint["unresolved_tasks"]),
    }
    # Bind each checkpoint state to an immutable index before changing its public entry.
    queue_entry = path.with_suffix("") / "queues.json"
    index = write_view(queue_entry, queues, COLLECTIONS)
    pointer = json.loads(queue_entry.read_bytes())
    # Historical checkpoint entries can still find their named index after a newer candidate moves queues.json.
    immutable = queue_entry.with_name("queues-" + pointer["index_sha256"] + ".json")
    put(immutable, queue_entry.read_bytes(), immutable=True)
    public.update(format=FORMAT, task_collections=immutable.relative_to(path.parent).as_posix(),
                  task_collections_sha256=sha(immutable.read_bytes()), **logical_binding(checkpoint))
    put(path, encode(public) + b"\n")
    return index


def load_checkpoint(path, public=None):
    path = Path(path)
    if public is None:
        public = json.loads(path.read_bytes())
    if public.get("format") != FORMAT:
        return public
    entry = bound_path(path.parent, public["task_collections"])
    if sha(entry.read_bytes()) != public["task_collections_sha256"]:
        raise ValueError("Checkpoint queue entry digest differs")
    index, folder = metadata(entry)
    if folder is None or set(index["collections"]) != set(COLLECTIONS) or any(public[k] != index["metadata"][k] for k in ("scope_id", "checkpoint_id", "schema_version")):
        raise ValueError("Checkpoint collections or scope differs")
    checkpoint = {k: v for k, v in public.items() if k not in ("format", "task_collections", "task_collections_sha256", "logical_bytes", "logical_sha256")}
    checkpoint["task_cursor_state"] = {r["task_id"]: r["cursor_state"] for r in records(index, folder, "task_cursor_state")}
    checkpoint["unresolved_tasks"] = [r["task_id"] for r in records(index, folder, "unresolved_tasks")]
    if not set(checkpoint["unresolved_tasks"]) <= checkpoint["task_cursor_state"].keys() or logical_binding(checkpoint) != {k: public[k] for k in ("logical_bytes", "logical_sha256")}:
        raise ValueError("Checkpoint data differ from the public binding")
    return checkpoint


def checkpoint_files(path, public=None):
    path = Path(path)
    if public is None:
        public = json.loads(path.read_bytes())
    if public.get("format") != FORMAT:
        return [path]
    immutable = bound_path(path.parent, public["task_collections"])
    active = immutable.with_name("queues.json")
    if active.read_bytes() != immutable.read_bytes():
        raise ValueError("Checkpoint entry and active task collections differ")
    return [path, immutable, *view_files(active)]
