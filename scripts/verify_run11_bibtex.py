"""Check the published bibliography with the independent Biber parser and native Git."""
import argparse
from collections import Counter, defaultdict
import ctypes
import hashlib
import json
import os
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


def whole_file_parse(parser, source, expected):
    """Use the documented Text::BibTeX 0.88 ABI supplied by this Windows Biber build."""
    cache = Path(subprocess.check_output([str(parser), "--cache"], encoding="utf-8").strip())
    library = cache / "libbtparse.dll"
    module = cache / "inc/lib/Text/BibTeX.pm"
    if not library.is_file() or not module.is_file() or not re.search(
            r"""our\s+\$VERSION\s*=\s*['"]0\.88['"]""", module.read_text(encoding="utf-8")):
        return None
    pointer = ctypes.c_void_p
    api = {
        "bt_initialize": ([], None), "bt_cleanup": ([], None),
        "bt_parse_file": ([ctypes.c_char_p, ctypes.c_ushort, ctypes.POINTER(ctypes.c_int)], pointer),
        "bt_next_entry": ([pointer, pointer], pointer), "bt_entry_key": ([pointer], ctypes.c_char_p),
        "bt_free_ast": ([pointer], None),
    }
    keys = Counter()
    with os.add_dll_directory(str(cache)):
        lib = ctypes.CDLL(str(library))
        for name, (args, result) in api.items():
            call = getattr(lib, name)
            call.argtypes, call.restype = args, result
        prior = Path.cwd()
        root = None
        lib.bt_initialize()
        try:
            os.chdir(source.parent)
            status = ctypes.c_int()
            root = lib.bt_parse_file(source.name.encode("ascii"), 0, ctypes.byref(status))
            if not root or not status.value:
                raise ValueError("The complete file failed native BibTeX parsing")
            item = None
            while True:
                item = lib.bt_next_entry(root, item)
                if not item:
                    break
                key = lib.bt_entry_key(item)
                if not key:
                    raise ValueError("A native bibliography entry has no key")
                keys[key.decode("ascii")] += 1
        finally:
            if root:
                lib.bt_free_ast(root)
            lib.bt_cleanup()
            os.chdir(prior)
    if keys != expected:
        raise ValueError("The complete native parse differs from the frozen Work keys")
    return dict(tool="Biber bundled Text::BibTeX 0.88", library_sha256=sha(library.read_bytes()),
                input_sha256=sha(source.read_bytes()), parsed_entries=sum(keys.values()), distinct_keys=len(keys))


def parse_part(parser, folder, raw):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.bib").write_bytes(raw)
    args = [str(parser), "--tool", "--output-format=bibtex", "--output-file=roundtrip.bib", "source.bib"]
    with (folder / "biber-console.log").open("wb") as log:
        parsed = subprocess.run(args, cwd=folder, stdout=log, stderr=subprocess.STDOUT)
    path = folder / "source.bib.blg"
    log_bytes = (path if path.is_file() else folder / "biber-console.log").read_bytes()
    diagnostics = [s[s.index(level):] for s in log_bytes.decode("utf-8", "replace").splitlines()
                   for level in ("WARN -", "ERROR -", "FATAL -") if level in s]
    produced = folder / "roundtrip.bib"
    return parsed.returncode, produced.read_bytes() if produced.is_file() else b"", log_bytes, diagnostics


def run(parser, repo, revision, source, out, checkpoint, entries_per_part=1600):
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
    expected = Counter(source_keys)
    del titles
    out.mkdir(parents=True)
    original = out / "source.bib"
    original.write_bytes(source_bytes)
    environment_version = subprocess.check_output([str(parser), "--version"], encoding="utf-8").strip()
    whole = None
    if os.name == "nt" and len(starts) > entries_per_part:
        whole = whole_file_parse(parser, original, expected)
    step = entries_per_part if whole is not None else len(starts)
    if not step or starts[0].start() != 0 or (whole and source_bytes != text.encode("utf-8")):
        raise ValueError("Expected a non-empty bibliography and canonical LF bytes for bounded round trips")
    inputs, outputs, logs = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    parts, diagnostics, keys, returncode = [], [], [], 0
    for at in range(0, len(starts), step):
        end = min(at + step, len(starts))
        limit = starts[end].start() if end < len(starts) else len(text)
        raw = text[starts[at].start():limit].encode("utf-8") if whole else source_bytes
        folder = out / f"part-{len(parts)+1:04}" if whole else out
        code, produced, log_bytes, messages = parse_part(parser, folder, raw)
        observed = ENTRY.findall(produced.decode("utf-8-sig"))
        if code or Counter(observed) != Counter(source_keys[at:end]):
            returncode = code or 1
        diagnostics.extend(messages)
        keys.extend(observed)
        inputs.update(raw)
        outputs.update(produced)
        logs.update(log_bytes)
        parts.append(dict(first_key=source_keys[at], last_key=source_keys[end-1], entries=end-at,
                          bytes=len(raw), input_sha256=sha(raw), output_sha256=sha(produced), log_sha256=sha(log_bytes),
                          returned_keys=len(observed), exit_code=code))
        if whole:
            print("Biber entries checked", end, "of", len(starts), flush=True)
    if inputs.hexdigest() != sha(source_bytes):
        raise ValueError("The native round trips did not cover every original input byte")
    warnings = [s for s in diagnostics if s.startswith("WARN -")]
    case_groups = defaultdict(list)
    for key in source_keys:
        case_groups[key.casefold()].append(key)
    variants = [sorted(v) for _,v in sorted(case_groups.items()) if len(v)>1]
    missing, extra = sorted(set(source_keys)-set(keys)), sorted(set(keys)-set(source_keys))
    warning_types = Counter("case_sensitive_key_pairs" if "case mismatch" in s else
                            "literal_page_fields" if "field 'pages'" in s and "falling back to literal" in s
                            else "other" for s in warnings)
    passed = returncode == 0 and not any(s.startswith(("ERROR -", "FATAL -")) for s in diagnostics) and Counter(keys) == Counter(source_keys)
    report = dict(status="passed" if passed else "failed", checkpoint_id=checkpoint, checked_at_utc=stamp(),
                  tool=environment_version, canonical_commit=commit, input_sha256=sha(source_bytes),
                  checked_original_titles=len(source_keys), bibtex_entries=len(source_keys), roundtripped_distinct_keys=len(set(keys)),
                  missing_keys=len(missing), extra_keys=len(extra), missing_key_list=missing, extra_key_list=extra,
                  parser_exit_code=returncode, warning_count=len(warnings), warning_counts=dict(warning_types),
                  warnings=warnings, errors=[s for s in diagnostics if not s.startswith("WARN -")],
                  roundtrip_sha256=outputs.hexdigest(), parser_log_sha256=logs.hexdigest(),
                  whole_file_parse=whole, roundtrip_parts=parts, roundtrip_input_sha256=inputs.hexdigest(),
                  case_variant_groups=variants)
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
    p.add_argument("--entries-per-part", type=int, default=1600)
    args = p.parse_args()
    if args.entries_per_part < 1:
        p.error("--entries-per-part must be positive")
    run(args.biber.resolve(), args.repo, args.revision, args.source, args.output, args.checkpoint, args.entries_per_part)
