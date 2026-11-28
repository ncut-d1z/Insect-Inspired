"""Check the published bibliography with the independent Biber parser and native Git."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from history_run10 import blobs
from escalate_unknown_run7 import git, parts_for
from partitioned_research_json import encode, put, sha
from export_run import tex
from search_run11_bibliography import ROOT, stamp

ENTRY = re.compile(r"^@[a-zA-Z]+\{\s*([^,\s]+),", re.MULTILINE)
TITLE = re.compile(r"^  title = \{\{(.*)\}\},?$", re.MULTILINE)


def run(parser, repo, revision, source, out, checkpoint):
    out = out.resolve()
    if out.is_relative_to(ROOT) or out.exists():
        raise ValueError("Use a fresh external Biber output directory")
    commit = git(repo, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    titles = {}
    with blobs(repo) as get:
        manifest = json.loads(get(commit, "temp/partitions/manifest.json"))
        for part in parts_for("works", manifest):
            for line in get(commit, "temp/" + part["path"]).splitlines():
                work = json.loads(line)
                key = work["work_key"]
                if key in titles:
                    raise ValueError("Duplicate canonical Work key " + key)
                titles[key] = tex(work["canonical_title"])

    source_bytes = source.read_bytes()
    text = source_bytes.decode("utf-8").replace("\r\n", "\n")
    starts = list(ENTRY.finditer(text))
    source_keys = [m[1] for m in starts]
    if Counter(source_keys) != Counter(titles.keys()):
        raise ValueError("BibTeX keys differ from the frozen canonical Work keys")
    for i, start in enumerate(starts):
        end = starts[i+1].start() if i+1 < len(starts) else len(text)
        matches = TITLE.findall(text, start.end(), end)
        if matches != [titles[start[1]]]:
            raise ValueError("Original bibliographic title differs for " + start[1])
    del titles, text, starts
    out.mkdir(parents=True)
    original = out / "source.bib"
    original.write_bytes(source_bytes)
    environment_version = subprocess.check_output([str(parser), "--version"], encoding="utf-8").strip()
    args = [str(parser), "--tool", "--output-format=bibtex", "--output-file=roundtrip.bib", "source.bib"]
    with (out / "biber-console.log").open("wb") as log:
        parsed = subprocess.run(args, cwd=out, stdout=log, stderr=subprocess.STDOUT)
    log_path = out / "source.bib.blg"
    if not log_path.is_file():
        log_path = out / "biber-console.log"
    log_bytes = log_path.read_bytes()
    diagnostics = [s[s.index(level):] for s in log_bytes.decode("utf-8", "replace").splitlines()
                   for level in ("WARN -", "ERROR -", "FATAL -") if level in s]
    warnings = [s for s in diagnostics if s.startswith("WARN -")]
    roundtrip = out / "roundtrip.bib"
    actual_bytes = roundtrip.read_bytes() if roundtrip.is_file() else b""
    keys = ENTRY.findall(actual_bytes.decode("utf-8-sig"))
    missing, extra = sorted(set(source_keys)-set(keys)), sorted(set(keys)-set(source_keys))
    warning_types = Counter("case_sensitive_key_pairs" if "case mismatch" in s else
                            "literal_page_fields" if "field 'pages'" in s and "falling back to literal" in s
                            else "other" for s in warnings)
    passed = parsed.returncode == 0 and not any(s.startswith(("ERROR -", "FATAL -")) for s in diagnostics) and Counter(keys) == Counter(source_keys)
    report = dict(status="passed" if passed else "failed", checkpoint_id=checkpoint, checked_at_utc=stamp(),
                  tool=environment_version, canonical_commit=commit, input_sha256=sha(source_bytes),
                  checked_original_titles=len(source_keys), bibtex_entries=len(source_keys), roundtripped_distinct_keys=len(set(keys)),
                  missing_keys=len(missing), extra_keys=len(extra), missing_key_list=missing, extra_key_list=extra,
                  parser_exit_code=parsed.returncode, warning_count=len(warnings), warning_counts=dict(warning_types),
                  warnings=warnings, errors=[s for s in diagnostics if not s.startswith("WARN -")],
                  roundtrip_sha256=sha(actual_bytes), parser_log_sha256=sha(log_bytes))
    put(out / "bibtex-parse.json", encode(report) + b"\n")
    if not passed:
        raise ValueError("Biber failed to round-trip all canonical keys; see " + str(out / "bibtex-parse.json"))
    print("Canonical titles, round-tripped keys and warnings:", len(source_keys), len(keys), len(warnings), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--biber", type=Path, required=True)
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--revision", required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--checkpoint", required=True)
    args = p.parse_args()
    run(args.biber.resolve(), args.repo, args.revision, args.source, args.output, args.checkpoint)
