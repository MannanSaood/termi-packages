"""Bound focused compilation before disk loss or the hosted job deadline."""
import argparse
import os
from pathlib import Path
import signal
import subprocess

from catalog_build import DiskPressure, guarded_wait, save


def supervise(command, root, evidence, seconds, minimum_free_gib):
    # A restored checkpoint may contain the previous attempt's interruption.
    # Its history stays in selected-ledger.json; this marker describes this run.
    evidence.unlink(missing_ok=True)
    process = None
    reason = None
    code = 0
    try:
        if seconds <= 0:
            raise subprocess.TimeoutExpired(command, seconds)
        process = subprocess.Popen(command, start_new_session=True)
        code = guarded_wait(process, root, seconds, minimum_free_gib)
    except DiskPressure as error:
        code, reason = 75, dict(reason=str(error), disk_free_bytes_at_stop=error.free_bytes)
    except subprocess.TimeoutExpired:
        code, reason = 124, dict(reason='Focused compilation budget exhausted')
    except KeyboardInterrupt:
        code, reason = 143, dict(reason='Focused compilation interrupted for finalization')
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
    if reason is not None:
        save(evidence, dict(status='interrupted', exit_code=code,
                            compile_resume_available=True, **reason))
        print('TERMI_FOCUSED_INTERRUPTION ' + str(reason), flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--minimum-free-gib', type=int, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.minimum_free_gib < 8 or not args.command or args.command[0] != '--':
        parser.error('Require disk reserve and an explicit compiler command')
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    raise SystemExit(supervise(args.command[1:], args.root, args.evidence,
                               args.seconds, args.minimum_free_gib))


if __name__ == '__main__':
    main()
