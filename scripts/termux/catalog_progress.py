#!/usr/bin/env python3
"""Bounded, truthful build progress from the isolated builder; no credentials."""
import argparse
from collections import Counter
import datetime
import json
import os
from pathlib import Path
import subprocess


def tail(path, limit=8192):
    if not path.is_file() or path.is_symlink():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - limit))
        return stream.read(limit).decode("utf-8", errors="replace")


def snapshot(root, state):
    ledger = state / "ledger.json"
    if not ledger.exists():
        ledger = state / "selected-ledger.json"
    value = json.loads(ledger.read_text()) if ledger.exists() else {"recipes": {}}
    recipes = value["recipes"]
    counts = dict(Counter(entry["status"] for entry in recipes.values()))
    current = [name for name, entry in recipes.items() if entry["status"] == "running"]
    failures = []
    for name, entry in recipes.items():
        if entry["status"] not in ("failed", "interrupted"):
            continue
        log = state / "logs" / f"{name}-{entry.get('attempts', 1)}.log"
        failures.append(dict(recipe=name, status=entry["status"], exit_code=entry.get("exit_code"),
                             log=log.name, tail=tail(log)))
    # Count binary outputs with readable Debian control archives. This is a
    # candidate-file count, distinct from completed parent recipes or approval.
    cache_path = state / "deb-count-cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    verified = {}
    debs = []
    for path in sorted((root / "output").glob("*.deb")):
        if path.is_symlink():
            continue
        try:
            stamp = [path.stat().st_size, path.stat().st_mtime_ns]
        except FileNotFoundError:
            continue
        valid = cache.get(path.name) == stamp
        if not valid:
            result = subprocess.run(["dpkg-deb", "-f", str(path), "Package"], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=10)
            valid = result.returncode == 0
        if valid:
            debs.append(path.name)
            verified[path.name] = stamp
    # The CLI is also called by a read-only Docker exec heartbeat. It does not
    # change the ledger/compile process; this derived cache only avoids reparsing
    # thousands of unchanged control archives every minute.
    if state.exists():
        temporary = state / ("deb-count-cache-" + str(os.getpid()) + ".tmp")
        temporary.write_text(json.dumps(verified))
        temporary.replace(cache_path)
    selected_log = state / "current.log"
    active_log = state / "logs" / f"{current[0]}-{recipes[current[0]].get('attempts', 1)}.log" if current else selected_log
    return dict(schema=1, updated=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                total_recipes=len(recipes), counts=counts, current=current,
                completed_recipes=sorted(name for name,entry in recipes.items() if entry["status"] == "built"),
                lane=value.get("lane"), owned_roots=value.get("owned_roots", []),
                reused_recipes=sum(e.get("origin") == "verified-termi-source-build" for e in recipes.values()),
                current_log_tail=tail(active_log), deb_files=len(debs),
                failures=failures[-100:], omitted_failure_logs=max(0, len(failures) - 100),
                halt=value.get("halt"), scope="requested-roots" if ledger.name == "selected-ledger.json" else "catalog-recipes",
                status="building" if current else "idle", approved=False)


def selected_event(state, names, recipe, status, code=None):
    state.mkdir(parents=True, exist_ok=True)
    path = state / "selected-ledger.json"
    ledger = json.loads(path.read_text()) if path.exists() else dict(recipes={name: dict(status="pending", attempts=0) for name in names})
    if recipe:
        entry = ledger["recipes"][recipe]
        entry["status"] = status
        if status == "running":
            entry["attempts"] += 1
        if code is not None:
            entry["exit_code"] = code
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--selected", nargs="+")
    parser.add_argument("--recipe")
    parser.add_argument("--status", choices=["pending", "running", "built", "failed"])
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.selected:
        selected_event(args.state, args.selected, args.recipe, args.status, args.exit_code)
    value = snapshot(args.root, args.state)
    data = json.dumps(value)
    if args.output:
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(data + "\n")
        temporary.replace(args.output)
    print(data, flush=True)


if __name__ == "__main__":
    main()
