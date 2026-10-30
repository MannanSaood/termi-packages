#!/usr/bin/env python3
"""Sequential source-build ledger over the pinned upstream dependency order.

Persistent builder only. Never downloads stock dependencies, signs or publishes.
"""
import argparse
from collections import Counter
import json
import hashlib
import re
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from catalog_graph import create_plan, digest

# These currently dominate shared dependency rebuilds. Focused source jobs may
# also produce them; other lanes wait for hash-verified outputs in the next seed.
SHARED_BUILD_OWNERS = {
    "qt6-qtdeclarative": 3, "ldc": 7, "swift": 5, "flang": 7,
    # Newly unblocked common libraries must be built once, then shared through
    # the next verified seed, rather than rebuilt in every dependent prefix.
    "libkdcraw": 0, "imagemagick": 1, "libpangomm-2.48": 1,
    "kf6-kimageformats": 2, "libzim": 2, "openimageio": 3, "recoll": 3,
    "libatkmm-1.6": 4, "libxml++-2.6": 5, "libpangomm-1.4": 6, "gegl": 7,
    "gtkmm4": 1, "gtkmm3": 6, "gtkmm2": 7, "libvips": 4, "eom": 6, "libkiwix": 6,
    "kdegraphics-thumbnailers": 2,
    "openjdk-21": 1, "openjdk-25": 3, "openjdk-17": 5, "gimp": 2,
    "inkscape": 6, "kscreen": 3, "pavucontrol": 1, "gwenview": 4, "mate-utils": 6,
}


def shared_build_wait(name, lane, owned):
    if not lane or not lane.endswith('-of-8'):
        return None
    # Lane4 already owns the active SuiteSparse dependency build. Route future
    # prefixes to that shared result, including its hash-root owner in lane1.
    # Lane4 selects SuiteSparse through its own dependent roots.
    if name == 'suitesparse' and lane != 'lane-4-of-8':
        return 'lane-4-of-8'
    # Focused repairs run in isolated jobs; lanes can still build independent
    # roots while waiting for their candidates to enter the shared seed.
    if name in ('swift', 'alsa-plugins', 'kf6-kimageformats', 'gegl', 'tcc', 'sftpgo'):
        return 'focused-' + name
    if name in SHARED_BUILD_OWNERS and name not in owned:
        return f'lane-{SHARED_BUILD_OWNERS[name]}-of-8'
    return None


class DiskPressure(Exception):
    """Stop before a single large recipe can fill the shared runner filesystem."""

    def __init__(self, message, free_bytes=None):
        super().__init__(message)
        self.free_bytes = free_bytes


def guarded_wait(process, root, timeout, minimum_free_gib):
    if not minimum_free_gib:
        return process.wait(timeout=timeout)
    deadline = time.monotonic() + timeout
    floor = minimum_free_gib * 1024**3
    while True:
        free_bytes = shutil.disk_usage(root).free
        if free_bytes < floor:
            raise DiskPressure("Insufficient disk during recipe compilation", free_bytes=free_bytes)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(1, remaining))
        except subprocess.TimeoutExpired:
            continue


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


def announce(ledger, event, recipe=None):
    print("TERMI_PROGRESS " + json.dumps(dict(event=event, recipe=recipe,
          counts=dict(Counter(e["status"] for e in ledger["recipes"].values())),
          total_recipes=len(ledger["recipes"]), halt=ledger.get("halt"))), flush=True)


def lane_scope(recipes, lane):
    if not lane:
        return set(recipes), set(recipes)
    match = re.fullmatch(r"lane-([0-9]+)-of-([2-8])", lane)
    if not match or int(match[1]) >= int(match[2]):
        raise ValueError("Require lane-INDEX-of-COUNT with COUNT2–8")
    index, count = map(int, match.groups())
    # Keep older lane assignments stable; spread known heavy roots in the new eight-way round.
    heavy = {name: i for i, name in enumerate(("zig", "mono", "dotnet9.0", "dotnet10.0", "llvm", "rust", "webkit2gtk-4.1", "qt6-qtwebengine"))} if count == 8 else {}
    if count == 8:
        heavy.update(SHARED_BUILD_OWNERS)
    def owner(name):
        return heavy.get(name, int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % count)
    owned = {name for name in recipes if owner(name) == index}
    selected = set(owned)
    pending = list(owned)
    while pending:
        for dependency in recipes[pending.pop()]["dependencies"]:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return owned, selected


def build(root, metadata, state_dir, jobs=2, minimum_free_gib=80, timeout=86400, retry_failed=False, resume_compile=None,
          budget_seconds=None, lane=None):
    import fcntl
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "builder.lock").open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def load(name):
            return json.loads((metadata / name).read_text())
        plan = create_plan(root, load("upstream.lock.json"), load("source.json"), load("patches.json"))
        owned, selected = lane_scope(plan["recipes"], lane)
        plan["configuration"]["runner_sha256"] = digest(Path(__file__))
        identity = (plan["identity"], plan["configuration"]["runner_sha256"])
        ledger_path = state_dir / "ledger.json"
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text())
            if ledger.get("lane") != lane:
                raise ValueError("Checkpoint lane differs; never mix installed prefixes")
            if tuple(ledger["identity"]) != identity:
                raise ValueError("Build inputs changed; use a new cache/state directory")
        else:
            ledger = dict(schema=1, identity=identity, recipes={name: dict(status=r["initial_status"], attempts=0)
                          for name, r in plan["recipes"].items()})
            receipt = state_dir.parent / "artifacts/seed-provenance.json"
            if receipt.exists():
                seed = json.loads(receipt.read_text())
                if seed["new_graph_identity"] != plan["identity"]:
                    raise ValueError("Source-build seed does not match this graph")
                for name in seed["recipes"]:
                    ledger["recipes"][name].update(status="built", origin="verified-termi-source-build", seed_inventory=seed["inventory_sha256"])
                for name, failure in seed.get("failures", {}).items():
                    if name in ledger["recipes"] and ledger["recipes"][name]["status"] != "built":
                        ledger["recipes"][name].update(failure)
            ledger.update(lane=lane, owned_roots=sorted(owned), selected_recipes=sorted(selected))
            for name, entry in ledger["recipes"].items():
                if name not in selected and entry["status"] == "pending":
                    entry["status"] = "deferred-shard"
        for entry in ledger["recipes"].values():
            if entry["status"] == "running":
                entry.update(status="interrupted", reason="Previous process ended without a completion record")
        ledger.pop("halt", None)
        if resume_compile and (not retry_failed or resume_compile not in ledger["recipes"]
                or ledger["recipes"][resume_compile]["status"] not in ("failed", "running", "interrupted")
                or ledger["recipes"][resume_compile].get("compile_resume_available") is False):
            raise ValueError("Explicit compile resume requires one previously failed/interrupted recipe and --retry-failed")
        save(state_dir / "plan.json", plan)
        save(ledger_path, ledger)
        announce(ledger, "batch-start")
        (state_dir / "logs").mkdir(exist_ok=True)
        deadline = time.monotonic() + budget_seconds if budget_seconds is not None else None
        for name, recipe in sorted(plan["recipes"].items(), key=lambda item: (item[1]["rank"] is None, item[1]["rank"] or 0)):
            if name not in selected:
                continue
            entry = ledger["recipes"][name]
            shared_wait = shared_build_wait(name, lane, owned)
            if shared_wait and entry['status'] != 'built':
                if entry['status'] not in ('failed', 'interrupted'):
                    entry.update(status='deferred-shared-build', shared_build_lane=shared_wait)
                continue
            status = next_status({**recipe, "name": name}, ledger["recipes"], retry_failed)
            if status != "ready":
                if status == "blocked-dependency":
                    entry.update(status=status, blockers=[n for n in recipe["dependencies"] if ledger["recipes"][n]["status"] != "built"])
                continue
            remaining = deadline - time.monotonic() if deadline is not None else timeout
            if remaining < 1:
                ledger["halt"] = "batch-time-budget"
                save(ledger_path, ledger)
                announce(ledger, "halt")
                return 75
            if shutil.disk_usage(root).free < minimum_free_gib * 1024**3:
                ledger["halt"] = "insufficient-builder-disk"
                save(ledger_path, ledger)
                announce(ledger, "halt")
                return 75
            entry.update(status="running", started=time.time(), attempts=entry["attempts"] + 1)
            entry.pop("blockers", None)
            save(ledger_path, ledger)
            announce(ledger, "recipe-start", name)
            command = ["bash", "./build-package.sh", "-a", "aarch64", "-s", "-j", str(jobs), "-o", str(root / "output")]
            if name == resume_compile:
                command.append("-c")
            command.append(recipe["path"])
            environment = {**os.environ, "TERMUX_INSTALL_DEPS": "false", "TERMUX_PKG_API_LEVEL": "26"}
            with (state_dir / "logs" / f"{name}-{entry['attempts']}.log").open("wb") as log:
                process = subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = guarded_wait(process, root, min(timeout, remaining), minimum_free_gib)
                except (subprocess.TimeoutExpired, KeyboardInterrupt, DiskPressure) as error:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    entry.update(status="interrupted", exit_code=124, ended=time.time())
                    if isinstance(error, DiskPressure):
                        from build_scratch import clean
                        from catalog_progress import tail
                        entry.update(reason=str(error), compile_resume_available=False, exit_code=75,
                                     disk_free_bytes_at_stop=error.free_bytes,
                                     log_tail_at_stop=tail(state_dir / "logs" / f"{name}-{entry['attempts']}.log"))
                        print("TERMI_RESOURCE_STOP " + json.dumps(dict(recipe=name,
                              free_bytes=entry["disk_free_bytes_at_stop"],
                              tail=entry["log_tail_at_stop"])), flush=True)
                        try:
                            entry["discarded_scratch"] = clean(Path.home() / ".termux-build", name,
                                discard_sources=os.environ.get("TERMI_RECLAIM_RECIPE_CACHE") == "1")
                        except OSError as cleanup_error:
                            entry["scratch_warning"] = str(cleanup_error)
                        ledger.setdefault("resource_interruptions", []).append(name)
                    save(ledger_path, ledger)
                    announce(ledger, "recipe-interrupted", name)
                    if isinstance(error, DiskPressure):
                        if shutil.disk_usage(root).free < minimum_free_gib * 1024**3:
                            ledger["halt"] = "insufficient-builder-disk-during-recipe"
                            save(ledger_path, ledger)
                            return 75
                        # A large recipe must not starve independent roots.
                        # It stays interrupted and is retried on a fresh runner.
                        continue
                    if isinstance(error, KeyboardInterrupt):
                        raise
                    if deadline is not None and time.monotonic() >= deadline:
                        ledger["halt"] = "batch-time-budget"
                        save(ledger_path, ledger)
                        announce(ledger, "halt")
                        return 75
                    continue
            if code:
                from build_scratch import configure_diagnostics
                try:
                    configure_diagnostics(Path.home() / '.termux-build', name,
                        state_dir.parent / 'artifacts' / f'configure-{name}.log')
                except (OSError, ValueError) as error:
                    print('TERMI_DIAGNOSTIC_WARNING ' + str(error), flush=True)
            entry.update(status="built" if code == 0 else "failed", exit_code=code, ended=time.time())
            save(ledger_path, ledger)
            announce(ledger, "recipe-complete", name)
            if code:
                from catalog_progress import failure_excerpt
                print("TERMI_FAILURE " + json.dumps(dict(recipe=name, exit_code=code,
                      tail=failure_excerpt(state_dir / "logs" / f"{name}-{entry['attempts']}.log"))), flush=True)
            from build_scratch import clean
            try:
                cleaned = clean(Path.home() / ".termux-build", name,
                    discard_sources=os.environ.get("TERMI_RECLAIM_RECIPE_CACHE") == "1")
            except OSError as error:
                entry["scratch_warning"] = str(error)
                print("TERMI_SCRATCH_WARNING " + str(error), flush=True)
                cleaned = []
                save(ledger_path, ledger)
            if cleaned:
                entry["discarded_scratch"] = cleaned
                entry["compile_resume_available"] = False
                save(ledger_path, ledger)
        save(ledger_path, ledger)
        summary = dict(Counter(entry["status"] for entry in ledger["recipes"].values()))
        save(state_dir / "summary.json", summary)
        announce(ledger, "batch-complete")
        return 0 if all(ledger["recipes"][name]["status"] in ("built", "excluded-architecture") for name in selected) else 1


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Container requested catalog finalization')
    signal.signal(signal.SIGTERM, interrupted)
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
    parser.add_argument("--lane")
    args = parser.parse_args()
    if args.minimum_free_gib < 8 or args.recipe_timeout < 60 or (args.budget_seconds is not None and args.budget_seconds < 60):
        parser.error("Keep at least8GiB builder headroom and a60second recipe deadline")
    raise SystemExit(build(args.root.resolve(), args.metadata.resolve(), args.state.resolve(), args.jobs,
                           args.minimum_free_gib, args.recipe_timeout, args.retry_failed, args.resume_compile, args.budget_seconds, args.lane))


if __name__ == "__main__":
    main()
