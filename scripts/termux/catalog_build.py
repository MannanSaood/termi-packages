#!/usr/bin/env python3
"""Sequential source-build ledger over the pinned upstream dependency order.

Persistent builder only. Never downloads stock dependencies, signs or publishes.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from catalog_graph import create_plan, digest


def save(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def next_status(recipe, states, retry_failed):
    status = states[recipe["name"]]["status"]
    if status in ("built", "excluded-architecture", "blocked-cycle"):
        return status
    if status in ("failed", "interrupted", "running") and not retry_failed:
        return status
    missing = [name for name in recipe["dependencies"] if states[name]["status"] != "built"]
    return "blocked-dependency" if missing else "ready"


def build(root, metadata, state_dir, jobs=2, minimum_free_gib=80, timeout=86400, retry_failed=False, resume_compile=None,
          budget_seconds=None):
    import fcntl
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "builder.lock").open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def load(name):
            return json.loads((metadata / name).read_text())
        plan = create_plan(root, load("upstream.lock.json"), load("source.json"), load("patches.json"))
        plan["configuration"]["runner_sha256"] = digest(Path(__file__))
        identity = (plan["identity"], plan["configuration"]["runner_sha256"])
        ledger_path = state_dir / "ledger.json"
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text())
            if tuple(ledger["identity"]) != identity:
                raise ValueError("Build inputs changed; use a new cache/state directory")
        else:
            ledger = dict(schema=1, identity=identity, recipes={name: dict(status=r["initial_status"], attempts=0)
                          for name, r in plan["recipes"].items()})
        for entry in ledger["recipes"].values():
            if entry["status"] == "running":
                entry.update(status="interrupted", reason="Previous process ended without a completion record")
        ledger.pop("halt", None)
        if resume_compile and (not retry_failed or resume_compile not in ledger["recipes"]
                or ledger["recipes"][resume_compile]["status"] not in ("failed", "running", "interrupted")):
            raise ValueError("Explicit compile resume requires one previously failed/interrupted recipe and --retry-failed")
        save(state_dir / "plan.json", plan)
        save(ledger_path, ledger)
        (state_dir / "logs").mkdir(exist_ok=True)
        deadline = time.monotonic() + budget_seconds if budget_seconds is not None else None
        for name, recipe in sorted(plan["recipes"].items(), key=lambda item: (item[1]["rank"] is None, item[1]["rank"] or 0)):
            entry = ledger["recipes"][name]
            status = next_status({**recipe, "name": name}, ledger["recipes"], retry_failed)
            if status != "ready":
                if status == "blocked-dependency":
                    entry.update(status=status, blockers=[n for n in recipe["dependencies"] if ledger["recipes"][n]["status"] != "built"])
                continue
            remaining = deadline - time.monotonic() if deadline is not None else timeout
            if remaining < 1:
                ledger["halt"] = "batch-time-budget"
                save(ledger_path, ledger)
                return 75
            if shutil.disk_usage(root).free < minimum_free_gib * 1024**3:
                ledger["halt"] = "insufficient-builder-disk"
                save(ledger_path, ledger)
                return 75
            entry.update(status="running", started=time.time(), attempts=entry["attempts"] + 1)
            entry.pop("blockers", None)
            save(ledger_path, ledger)
            command = ["bash", "./build-package.sh", "-a", "aarch64", "-s", "-j", str(jobs), "-o", str(root / "output")]
            if name == resume_compile:
                command.append("-c")
            command.append(recipe["path"])
            environment = {**os.environ, "TERMUX_INSTALL_DEPS": "false", "TERMUX_PKG_API_LEVEL": "26"}
            with (state_dir / "logs" / f"{name}-{entry['attempts']}.log").open("wb") as log:
                process = subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=min(timeout, remaining))
                except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    entry.update(status="interrupted", exit_code=124, ended=time.time())
                    save(ledger_path, ledger)
                    if isinstance(error, KeyboardInterrupt):
                        raise
                    if deadline is not None and time.monotonic() >= deadline:
                        ledger["halt"] = "batch-time-budget"
                        save(ledger_path, ledger)
                        return 75
                    continue
            entry.update(status="built" if code == 0 else "failed", exit_code=code, ended=time.time())
            save(ledger_path, ledger)
        save(ledger_path, ledger)
        summary = dict(Counter(entry["status"] for entry in ledger["recipes"].values()))
        save(state_dir / "summary.json", summary)
        print(json.dumps(summary))
        return 0 if all(e["status"] in ("built", "excluded-architecture") for e in ledger["recipes"].values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--jobs", type=int, choices=range(1, 33), default=2)
    parser.add_argument("--minimum-free-gib", type=int, default=80)
    parser.add_argument("--recipe-timeout", type=int, default=86400)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--resume-compile")
    parser.add_argument("--budget-seconds", type=int, help="Stop and checkpoint within a hosted-job time budget")
    args = parser.parse_args()
    if args.minimum_free_gib < 8 or args.recipe_timeout < 60 or (args.budget_seconds is not None and args.budget_seconds < 60):
        parser.error("Keep at least8GiB builder headroom and a60second recipe deadline")
    raise SystemExit(build(args.root.resolve(), args.metadata.resolve(), args.state.resolve(), args.jobs,
                           args.minimum_free_gib, args.recipe_timeout, args.retry_failed, args.resume_compile, args.budget_seconds))


if __name__ == "__main__":
    main()
