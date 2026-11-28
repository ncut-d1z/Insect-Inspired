"""Install a verified CP13 candidate or export in restartable, path-scoped groups."""
import argparse
import json
from pathlib import Path
import re

from escalate_unknown_run7 import git
from export_checkpoint_windows import EXPORTS
from partitioned_research_json import bound_path, put, sha

CP = "temp/snapshots/checkpoints/CP-0013"
VIEWS = ("temp/exports/research_entities", "temp/exports/citation_graph")
CHUNK = re.compile(r"/\d{4,}-[0-9a-f]{64}\.json$")


def groups(source, kind):
    if kind == "candidate":
        inventory = json.loads((source / "candidate-files.json").read_bytes())
        fixed = {CP + ".json", "temp/validation/cp13-inputs.json", "temp/validation/cp13-history.json"}
        if not fixed <= inventory.keys() or not all(k in fixed or k.startswith(CP + "/") for k in inventory):
            raise ValueError("Unexpected checkpoint inventory")
    else:
        first_only = kind == "export-parts"
        proof = "first-files.json" if first_only else "determinism.json"
        expected = "first_generation" if first_only else "passed"
        det = json.loads((source.parent / proof).read_bytes())
        if det["status"] != expected or det["checkpoint_id"] != "CP-0013":
            raise ValueError("Unverified export")
        inventory = det["artifacts"]
        if not set(EXPORTS) <= inventory.keys() or not all(k in EXPORTS or k.startswith(tuple(v+"/" for v in VIEWS)) for k in inventory):
            raise ValueError("Unexpected export inventory")
    parts = sorted(k for k in inventory if CHUNK.search(k))
    blocks, batch, mass = [], [], 0
    for k in parts:
        n = inventory[k]["bytes"]
        if not 0 < n <= 2*1024*1024 or not k.endswith("-" + inventory[k]["sha256"] + ".json"):
            raise ValueError("Invalid JSON part size or content-addressed filename " + k)
        if batch and mass + n > 12*1024*1024:
            blocks.append(batch)
            batch, mass = [], 0
        batch.append(k)
        mass += n
    if batch:
        blocks.append(batch)
    if kind == "export-parts":
        # These files have no public effect until the independently reproduced indices are activated.
        return {k: inventory[k] for k in parts}, blocks
    remaining = sorted(inventory.keys()-set(parts))
    if kind == "candidate":
        blocks.append(remaining)
    else:
        for stem in VIEWS:
            active = [k for k in remaining if k == stem+".json" or k.startswith(stem+"/")]
            if len(active) != 3:
                raise ValueError("Each JSON view needs an entry and two identical indices")
            blocks.append(active)
            remaining = [k for k in remaining if k not in active]
        # Each browser bundle is activated together; its native bibliography is independently bound.
        blocks.append(["ref.bib"])
        blocks.append([k for k in remaining if k != "ref.bib"])
    if len([k for block in blocks for k in block]) != len(inventory):
        raise ValueError("Incomplete physical delivery inventory")
    return inventory, blocks


def install(repo, source, inventory, group):
    if git(repo, "rev-parse", "--show-toplevel").decode().strip().replace("\\","/").casefold() != repo.as_posix().casefold():
        raise ValueError("Destination is not a native Git working tree")
    pending = []
    for name in group:
        src, dst = bound_path(source, name), bound_path(repo, name)
        raw = src.read_bytes()
        if {"bytes":len(raw), "sha256":sha(raw)} != inventory[name]:
            raise ValueError("Generated artifact changed " + name)
        if dst.is_file() and sha(dst.read_bytes()) == inventory[name]["sha256"]:
            continue
        if dst.exists() and (CHUNK.search(name) or git(repo, "status", "--porcelain", "--", name).strip()):
            raise ValueError("Destination has a conflicting artifact " + name)
        pending.append((dst, raw))
    for target, raw in pending:
        put(target, raw)
    return len(pending)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("plan","install","stage"))
    p.add_argument("--kind", choices=("candidate","export-parts","exports"), required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--group", type=int)
    a = p.parse_args()
    src, root = a.source.resolve(), a.repo.resolve()
    if src.is_relative_to(root):
        p.error("Use independent generated output")
    inventory, plan = groups(src, a.kind)
    if a.action == "plan":
        print(json.dumps([{"paths":g, "bytes":sum(inventory[k]["bytes"] for k in g)} for g in plan]))
    elif a.action == "stage":
        if git(root, "branch", "--show-current").strip():
            p.error("Bulk offline QA needs a detached working tree")
        print("Installed for offline QA:", sum(install(root, src, inventory, g) for g in plan))
    elif a.group is None or not 0 <= a.group < len(plan):
        p.error("Specify a valid group index")
    else:
        print("Installed in group", a.group + 1, ":", install(root, src, inventory, plan[a.group]))
