"""Regenerate the research exports and both pages of the offline bibliography on Windows."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from audit_cp10 import EXPORTS as ORIGINAL_EXPORTS
from checkpoint_cp10 import require
from render_html import WEB_FILES
from partitioned_research_json import view_files

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = tuple(dict.fromkeys((*ORIGINAL_EXPORTS, *WEB_FILES)))


def export_files(output):
    names = list(EXPORTS)
    for entry in ('temp/exports/research_entities.json', 'temp/exports/citation_graph.json'):
        names.extend(path.relative_to(output).as_posix() for path in view_files(output / entry))
    return list(dict.fromkeys(names))


def generate(output, checkpoint):
    output = output.resolve()
    require(not output.is_relative_to(ROOT) and not output.exists(), "Use a fresh external output directory")
    output.mkdir(parents=True)
    report = output / "export-validation.json"
    commands = [
        ["export_run.py", "--repo", ROOT, "--output-dir", output, "--checkpoint", checkpoint, "--report", report],
        ["render_html.py", "--base", ROOT / "temp", "--output", output / "ref.html",
         "--checkpoint", checkpoint, "--summary-output", output / "html-summary.json"],
    ]
    for command in commands:
        with (output / (command[0] + ".log")).open("wb") as log:
            subprocess.run([sys.executable, "-B", "-X", "utf8", ROOT / "scripts" / command[0], *command[1:]],
                           check=True, stdout=log, stderr=subprocess.STDOUT)
    validation = json.loads(report.read_bytes())
    require(not validation["schema_errors"] and not validation["canonical_schema_pointer_patch_needed"],
            "Canonical export schema differs")
    bindings = {}
    for name in export_files(output):
        path = output / name
        raw = path.read_bytes()
        normalized = raw.replace(b"\r\n", b"\n")
        if raw != normalized:
            path.write_bytes(normalized)
        bindings[name] = {"bytes": len(normalized), "sha256": hashlib.sha256(normalized).hexdigest()}
    validation["artifact_hashes"] = {name: entry["sha256"] for name, entry in bindings.items()}
    validation["bibliography"] = json.loads((output / "html-summary.json").read_bytes())
    validation["canonical_utf8_newline"] = "LF"
    validation["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report.write_bytes((json.dumps(validation, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps(dict(checkpoint=checkpoint, counts=validation["counts"], artifacts=bindings)), flush=True)
    return bindings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    args = parser.parse_args()
    generate(args.output, args.checkpoint)
