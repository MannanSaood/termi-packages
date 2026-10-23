#!/usr/bin/env python3
"""Merge Termi build inventories into a new review-only repository snapshot.

No stock package fetches, signing, deployment, or changes to the live repository.
Dependency verification and operator approval are separate promotion gates.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from catalog_policy import PROFILES, policy_for
from publish_repository import digest, validate

ROOTS = ["apt", "bash", "termux-exec", "termux-tools", "hello", "git", "gh"]


def stage(candidates, output, profile="proof", base=None, channel="main"):
    policy = policy_for(profile)
    if channel not in ("main", "root", "x11") or (channel != "main" and profile != "full-catalog"):
        raise ValueError("Optional channels require an explicit full-catalog profile")
    if output.exists():
        raise ValueError("Use a new staging directory; existing snapshots are immutable")
    records, files, evidence = {}, {}, {}
    metadata = {}

    def add(path, record):
        filename = record["file"]
        if not re.fullmatch(r"[A-Za-z0-9%+._~-]+\.deb", filename):
            raise ValueError("Unsafe package filename")
        identity = (record["name"], record["version"], record["architecture"])
        if (path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= policy.package_bytes
                or digest(path) != record["sha256"]):
            raise ValueError("Invalid candidate package bytes")
        if identity in records and records[identity][1]["sha256"] != record["sha256"]:
            raise ValueError("Same package identity has different bytes; bump package revision")
        if filename in files and files[filename] != record["sha256"]:
            raise ValueError("Immutable pool filename collision")
        if identity not in records:
            records[identity] = (path, record)
            files[filename] = record["sha256"]
        if len(records) > policy.records:
            raise ValueError("Snapshot exceeds selected publication profile")

    if base:
        approval = base / "approved-packages.json"
        if approval.is_symlink() or approval.stat().st_size > policy.approval_bytes:
            raise ValueError("Invalid base inventory")
        base_profile = json.loads(approval.read_text()).get("publication_profile", "proof")
        if profile == "proof" and base_profile != "proof":
            raise ValueError("Cannot implicitly import a full catalog into the proof profile")
        manifest = validate(base, base_profile)
        if manifest.get("channel", "main") != channel:
            raise ValueError("Cannot mix base repository channels")
        for record in manifest["packages"]:
            add(base / "pool" / record["file"], record)
        for name in manifest.get("evidence", {}):
            evidence[name] = base / name

    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("Invalid candidate directory")
        for name in ["inventory.json", "upstream.lock.json", "patches.json", "source.json"]:
            path = candidate / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > policy.approval_bytes:
                raise ValueError("Missing or oversized candidate provenance")
        lock = json.loads((candidate / "upstream.lock.json").read_text())
        if (lock.get("application_id") != "com.terminal.nextgen"
                or lock.get("prefix") != "/data/data/com.terminal.nextgen/files/usr"
                or lock.get("architecture") != "aarch64" or lock.get("package_api") != 26
                or not re.fullmatch(r"[0-9a-f]{40}", lock.get("commit", ""))):
            raise ValueError("Candidate is not pinned to the Termi ARM64 prefix")
        source = json.loads((candidate / "source.json").read_text())
        full_build = source.get("catalog_scope") == "full-catalog"
        plan = None
        if full_build:
            plan_file = candidate / "catalog-plan.json"
            if plan_file.is_symlink() or not plan_file.is_file() or plan_file.stat().st_size > policy.approval_bytes:
                raise ValueError("Full builds need reviewed channel classification")
            plan = json.loads(plan_file.read_text())
            if plan["configuration"]["lock"] != lock or plan["configuration"]["source"] != source:
                raise ValueError("Channel plan and candidate build identity differ")
        inventory = json.loads((candidate / "inventory.json").read_text())
        if inventory.get("status") != "candidate-not-signed-not-device-verified":
            raise ValueError("Unrecognized candidate inventory")
        build_id = digest(candidate / "inventory.json")
        for name in ["inventory.json", "upstream.lock.json", "patches.json", "source.json"]:
            evidence[f"builds/{build_id}/{name}"] = candidate / name
        if full_build:
            evidence[f"builds/{build_id}/catalog-plan.json"] = candidate / "catalog-plan.json"
        metadata[build_id] = dict(recipe_commit=lock["commit"], prefix=lock["prefix"])
        for package in inventory["packages"]:
            candidate_channel = package.get("channel", "main" if not full_build else None)
            if candidate_channel not in ("main", "root", "x11"):
                raise ValueError("Missing or invalid package channel classification")
            if candidate_channel != channel:
                continue
            filename = package["file"]
            if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9%+._~-]+\.deb", filename):
                raise ValueError("Unsafe inventory path")
            path = candidate / filename
            # Never invoke an archive parser before checking the recorded bytes.
            if (path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= policy.package_bytes
                    or digest(path) != package["sha256"]):
                raise ValueError("Candidate differs from build inventory")
            control = subprocess.check_output(["dpkg-deb", "-f", str(path), "Package", "Version", "Architecture"], text=True)
            fields = dict(line.split(": ", 1) for line in control.strip().splitlines())
            if plan is not None and plan["provided_packages"].get(fields["Package"]) != {
                    "recipe": package.get("recipe"), "channel": candidate_channel}:
                raise ValueError("Debian package differs from recipe/channel plan")
            if fields["Architecture"] not in ("aarch64", "all"):
                raise ValueError("Unsupported package ABI")
            add(path, dict(name=fields["Package"], version=fields["Version"], architecture=fields["Architecture"],
                           file=filename, sha256=package["sha256"]))

    if channel == "main" and not set(ROOTS) <= {identity[0] for identity in records}:
        raise ValueError("Missing base runtime roots; supply the reviewed Termi base snapshot")
    if not records:
        raise ValueError("No packages in requested channel")
    if len(evidence) + 1 > policy.evidence_files:
        raise ValueError("Too many provenance records")
    total = sum(path.stat().st_size for path, _ in records.values()) + sum(p.stat().st_size for p in evidence.values())
    if total > policy.repository_bytes:
        raise ValueError("Snapshot exceeds selected storage budget")
    if shutil.disk_usage(output.parent).free < total + 64 * 1024**2:
        raise ValueError("Insufficient space for a new snapshot")
    manifest = dict(schema=1, publication_profile=profile, channel=channel,
                    roots=ROOTS if channel == "main" else sorted({identity[0] for identity in records}),
                    packages=[r for _, r in sorted(records.values(), key=lambda item: (item[1]["name"], item[1]["version"]))])
    approval = json.dumps(manifest, indent=2)
    if len(approval.encode()) > policy.approval_bytes:
        raise ValueError("Oversized candidate inventory")
    (output / "pool").mkdir(parents=True)
    for path, record in records.values():
        shutil.copyfile(path, output / "pool" / record["file"])
    for name, path in evidence.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    status = output / "staging.json"
    status.write_text(json.dumps(dict(status="candidate-awaiting-dependency-source-license-runtime-review", builds=metadata,
                                     complete_catalog=False), indent=2) + "\n")
    manifest["evidence"] = {name: digest(output / name) for name in evidence}
    manifest["evidence"]["staging.json"] = digest(status)
    approval = json.dumps(manifest, indent=2) + "\n"
    if len(approval.encode()) > policy.approval_bytes:
        raise ValueError("Oversized final candidate inventory")
    (output / "approved-packages.json").write_text(approval)
    validate(output, profile)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, nargs="+", required=True)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, default="proof")
    parser.add_argument("--channel", choices=["main", "root", "x11"], default="main")
    args = parser.parse_args()
    result = stage(args.candidate, args.output, args.profile, args.base, args.channel)
    print(f"Staged {len(result['packages'])} records; dependency verification, approval and signing still required")


if __name__ == "__main__":
    main()
