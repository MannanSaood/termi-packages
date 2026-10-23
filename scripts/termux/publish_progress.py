#!/usr/bin/env python3
"""Run the host builder and publish bounded live status using the outer GH token.

The isolated compiler never receives credentials or a host filesystem mount.
Progress is a prerelease, never signed packages or a release approval.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time


def markdown(value):
    counts = value.get("counts", {})
    current = ", ".join(value.get("current", [])) or "none"
    known = value.get("total_recipes") is not None
    completion = f"**{counts.get('built', 0)} / {value['total_recipes']}**" if known else "awaiting builder"
    binaries = str(value["deb_files"]) if value.get("deb_files") is not None else "unknown during preparation"
    result = ("## Termi source-build progress\n\nUnsigned candidates; not a production catalog.\n\n"
              f"Last observation: {value['updated']}\n\nStatus: **{value.get('status', 'preparing')}**\n\n"
              f"Current: `{current}`\n\n"
              f"Completed {value.get('scope', 'recipes')}: {completion}\n\n"
              f"Readable candidate Debian files: **{binaries}**\n\n"
              "| State | Count |\n|---|---:|\n" +
              "".join(f"| {name} | {counts.get(name, 0) if known else 'unknown'} |\n" for name in
                      ["running", "failed", "interrupted", "blocked-dependency", "blocked-cycle", "pending", "excluded-architecture"]))
    if value.get("halt"):
        result += "\nBatch halt: `" + str(value["halt"]) + "`\n"
    if value.get("failures"):
        result += "\n### Failures\n\nFull bounded tails are in `failures.log` and `progress.json`.\n\n"
        for failure in value["failures"][-20:]:
            result += f"- `{failure['recipe']}`: {failure['status']}, exit {failure.get('exit_code')}\n"
        for failure in value["failures"][-3:]:
            result += "\nCompiler tail for `" + failure["recipe"] + "`:\n\n```text\n" + failure.get("tail", "")[-1500:].replace("```", "~~~") + "\n```\n"
    if value.get("current_log_tail"):
        result += "\n### Current compiler tail\n\n```text\n" + value["current_log_tail"][-2000:].replace("```", "~~~") + "\n```\n"
    result += "\nPage updates approximately every60seconds. Downloadable JSON/log snapshots update every5minutes and at completion to conserve GitHub API limits.\n"
    return result


class RateLimited(RuntimeError):
    def __init__(self, retry_seconds):
        self.retry_seconds = retry_seconds


def gh(repository, *arguments):
    result = subprocess.run(["gh", "release", *arguments, "--repo", repository],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        if b"rate limit" in result.stderr.lower() or b"429" in result.stderr:
            # Never hammer a shared free-repo budget. Use the authenticated reset
            # if available; otherwise back off a full hour while compilation runs.
            wait = 3600
            try:
                reset = subprocess.check_output(["gh", "api", "rate_limit", "--jq", ".resources.core.reset"], timeout=15)
                wait = max(60, int(reset) - int(time.time()) + 5)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            raise RateLimited(wait)
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result


def publish(repository, tag, directory, value, assets=True):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "progress.json").write_text(json.dumps(value, indent=2) + "\n")
    (directory / "progress.md").write_text(markdown(value))
    failures = "\n\n".join(f"RECIPE {f['recipe']} STATUS {f['status']} EXIT {f.get('exit_code')}\n{f.get('tail','')}" for f in value.get("failures", []))
    (directory / "failures.log").write_text(failures or "No failed/interrupted recipes recorded at this update.\n")
    (directory / "current.log").write_text(value.get("current_log_tail", "") or "No current compiler log available.\n")
    if assets:
        gh(repository, "upload", tag, *[str(directory / name) for name in ["progress.json", "progress.md", "failures.log", "current.log"]], "--clobber")
    gh(repository, "edit", tag, "--notes-file", str(directory / "progress.md"))


def capture(build_dir):
    marker = build_dir / "container-id.txt"
    if marker.exists():
        container = marker.read_text().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            raise ValueError("Invalid builder container identity")
        result = subprocess.run(["docker", "exec", container, "python3", "/home/builder/catalog_progress.py",
                                 "--root", "/home/builder/termux-packages", "--state", "/home/builder/catalog-state"],
                                capture_output=True, timeout=50)
        if result.returncode == 0:
            if len(result.stdout) > 2 * 1024**2:
                raise ValueError("Progress exceeds bounded report size")
            return json.loads(result.stdout)
    final = build_dir / "artifacts/progress.json"
    return json.loads(final.read_text()) if final.exists() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository)
            or not re.fullmatch(r"progress-[0-9]+-[0-9]+", args.tag) or args.interval < 60 or not command):
        parser.error("Require a fixed repository/run tag, build command and at least60second publication interval")
    visibility = json.loads(subprocess.check_output(["gh", "repo", "view", args.repository, "--json", "visibility"]))["visibility"]
    if visibility != "PUBLIC":
        raise ValueError("Live progress requires the free public package repository")
    gh(args.repository, "create", args.tag, "--title", "Live build " + args.tag, "--notes", "Preparing source build; counts follow.", "--prerelease", "--latest=false")
    print("Live progress: https://github.com/" + args.repository + "/releases/tag/" + args.tag, flush=True)
    value = dict(schema=1, updated=datetime.datetime.now(datetime.timezone.utc).isoformat(), status="preparing",
                 counts={}, total_recipes=None, deb_files=None, current=[], failures=[], approved=False)
    directory = args.build_dir.parent / "live-progress"
    process = subprocess.Popen(command)
    next_update, next_assets, failures = 0, 0, 0
    try:
        while True:
            if time.monotonic() >= next_update or process.poll() is not None:
                retry_delay = args.interval
                try:
                    current = capture(args.build_dir)
                    if current:
                        value = current
                    value["published_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    if process.poll() is not None:
                        value["status"] = "completed" if process.returncode == 0 else "stopped-with-errors-or-pending-work"
                        value["build_exit_code"] = process.returncode
                    asset_due = time.monotonic() >= next_assets or process.poll() is not None
                    publish(args.repository, args.tag, directory, value, assets=asset_due)
                    if asset_due:
                        next_assets = time.monotonic() + 300
                    print("TERMI_LIVE " + json.dumps({k: v for k, v in value.items() if k not in ("failures", "current_log_tail")}), flush=True)
                except (OSError, ValueError, subprocess.SubprocessError, RateLimited) as error:
                    failures += 1
                    retry_delay = error.retry_seconds if isinstance(error, RateLimited) else min(900, args.interval * 2 ** min(failures - 1, 4))
                    print("::warning::Live progress update failed: " + type(error).__name__ + f"; next retry in{retry_delay}s", flush=True)
                next_update = time.monotonic() + retry_delay
            if process.poll() is not None:
                break
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
    raise SystemExit(process.returncode or (1 if failures else 0))


if __name__ == "__main__":
    main()
