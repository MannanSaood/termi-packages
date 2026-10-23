#!/usr/bin/env python3
"""Assign new immutable release batches before inventory review/signing.

No network operations. Reuses old asset locations only for identical approved
bytes. The modified inventory must receive fresh dependency/runtime approval.
"""
import argparse
import hashlib
import json
from pathlib import Path

from publish_repository import validate


def assign(root, profile="full-catalog", previous=None, batch_size=900):
    if not 1 <= batch_size <= 900:
        raise ValueError("Reserve release asset capacity below GitHub's1000asset limit")
    manifest = validate(root, profile)
    if (root / "dists").exists():
        raise ValueError("Plan assets before generating signed metadata")
    old, tags = {}, {}
    channel = manifest.get("channel", "main")
    if previous:
        prior = validate(previous, profile)
        if prior.get("channel", "main") != channel:
            raise ValueError("Cannot reuse asset locations across channels")
        old = {record["file"]: record for record in prior["packages"]}
        tags = prior.get("asset_tags", {})
    assigned, pending = {}, []
    for record in sorted(manifest["packages"], key=lambda r: r["file"]):
        if old.get(record["file"]) == record and record["file"] in tags:
            assigned[record["file"]] = tags[record["file"]]
        else:
            if (root / "pool" / record["file"]).stat().st_size >= 2 * 1024**3:
                raise ValueError("GitHub release assets must be under2GiB")
            pending.append(record)
    batches = []
    for start in range(0, len(pending), batch_size):
        records = pending[start:start + batch_size]
        identity = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:24]
        tag = "termi-" + channel + "-" + identity
        batches.append(dict(tag=tag, files=[r["file"] for r in records]))
        assigned.update({record["file"]: tag for record in records})
    manifest["asset_tags"] = assigned
    path = root / "approved-packages.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    validate(root, profile)
    return dict(schema=1, channel=channel, new_batches=batches, reused_assets=len(assigned) - len(pending),
                inventory_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                status="upload-plan-only-awaiting-review-signing-and-runtime-checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", choices=["proof", "full-catalog"], default="full-catalog")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = assign(args.root, args.profile, args.previous)
    with args.output.open("x") as stream:
        json.dump(plan, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
