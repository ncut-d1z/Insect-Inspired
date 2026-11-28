"""Coordinate the frozen RUN11 source limits across native PowerShell workers."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time

from search_run10_references import OUT, ROOT


def private_directory():
    value=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","--path-format=absolute","--git-common-dir"],text=True).strip()
    directory=Path(value)/"RUN-0011-source-control"
    directory.mkdir(exist_ok=True)
    return directory


@contextmanager
def locked(path):
    with path.open("a+b") as f:
        if f.seek(0,2)==0:
            f.write(b"0");f.flush()
        if os.name=="nt":
            import msvcrt
            while True:
                f.seek(0)
                try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:time.sleep(.15)
            try:yield
            finally:
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)


@contextmanager
def source_slot(source,file,run):
    private=private_directory()
    with locked(private/(source+".lock")):
        if (private.parent/"RUN-0011-sync-halt").exists():
            raise RuntimeError("Earlier Git synchronization requires recovery")
        delay=private/(source+".next")
        if delay.exists():
            left=float(delay.read_text())-time.time()
            if left>60:raise RuntimeError(f"{source} is deferred until {datetime.fromtimestamp(float(delay.read_text()),timezone.utc).isoformat()}")
            if left>0:time.sleep(left)
        reservation=private/(file.stem+".inflight")
        with locked(private/"budget.lock"):
            saved={p.stem for p in OUT.glob("Q-RUN11-*.json")}
            inflight={p.stem for p in private.glob("*.inflight")}-saved
            if file.stem in inflight:raise RuntimeError("Interrupted source request requires reconciliation: "+file.stem)
            if len(saved|inflight)>=run["budget"]["external_requests"]:raise RuntimeError("Source request budget reached")
            if (datetime.now(timezone.utc)-datetime.fromisoformat(run["started_at_utc"])).total_seconds()>=run["budget"]["wall_clock_hours"]*3600:
                raise RuntimeError("Run clock budget reached")
            reservation.write_text(datetime.now(timezone.utc).isoformat())
        # Crossref list and lookup starts are both limited to one per second.
        if source=="crossref":delay.write_text(str(time.time()+1))
        try:yield delay
        finally:
            if file.is_file():reservation.unlink(missing_ok=True)
