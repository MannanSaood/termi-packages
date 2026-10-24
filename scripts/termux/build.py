#!/usr/bin/env python3
"""Build a candidate with the pinned upstream backend; never installs or publishes."""
import argparse
import json
import subprocess
import sys
import uuid
import re
import hashlib
import os
from pathlib import Path

from prepare import ROOT, prepare, read_lock


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def input_identity(context):
    identity = hashlib.sha256()
    for path in sorted(p for p in context.rglob("*") if p.is_file()):
        identity.update(path.relative_to(context).as_posix().encode())
        with path.open("rb") as stream:
            identity.update(hashlib.file_digest(stream, "sha256").digest())
    return identity.hexdigest()


def reclaim_workflow_archives(workspace, context, seed_dir):
    """Drop only duplicated input archives after Docker has copied them.

    Explicit disposable-runner option; never applied to arbitrary local seeds.
    Keep metadata and SHA pins. The image and output pool retain actual packages.
    """
    boundary = workspace.resolve() / "build"
    targets = [context / "seed/pool"] + ([seed_dir] if seed_dir else [])
    archives = []
    for target in targets:
        if not target.resolve().is_relative_to(boundary) or target.resolve() == boundary:
            raise ValueError("Input cleanup escaped disposable workflow build directory")
        for path in [target, *target.parents]:
            if path == boundary:
                break
            if path.is_symlink():
                raise ValueError("Input cleanup refuses symbolic directories")
        for path in target.rglob("*"):
            if path.is_symlink():
                raise ValueError("Input cleanup refuses symbolic files")
            if path.is_file() and path.suffix in (".deb", ".tar"):
                archives.append(path)
    reclaimed = sum(path.stat().st_size for path in archives)
    for path in archives:
        path.unlink()
    print(f"TERMI_RECLAIMED_INPUT_BYTES {reclaimed}", flush=True)
    return reclaimed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["proof", "bootstrap", "catalog", "packages", "full-catalog"], default="proof")
    parser.add_argument("--packages", nargs="+", help="Pinned upstream recipes to source-build for Termi")
    parser.add_argument("--jobs", type=int, choices=range(1, 9), default=2, help="Bounded compiler workers / container CPU limit")
    parser.add_argument("--memory-gib", type=int, choices=range(2, 17), default=4)
    parser.add_argument("--timeout-seconds", type=int, default=7200, help="Build deadline; a full repository needs a persistent long-running builder")
    parser.add_argument("--cache-image", help="Explicit locally restored, manifest-pinned Termi checkpoint image")
    parser.add_argument("--continue-recipe", help="Explicitly resume a recipe already stopped during make or later")
    parser.add_argument("--full-recipes", action="store_true", help="Retain all recipe features for an individual catalog batch")
    parser.add_argument("--catalog-budget-seconds", type=int, default=12600)
    parser.add_argument("--catalog-minimum-free-gib", type=int, default=16)
    parser.add_argument("--catalog-retry-failed", action="store_true", help="Explicitly retry failed/interrupted catalog recipes")
    parser.add_argument("--catalog-lane")
    parser.add_argument("--seed-dir", type=Path, help="Prior Termi source-build candidate assets, never stock binaries")
    parser.add_argument("--seed-graph", type=Path)
    parser.add_argument("--seed-inventory-sha256")
    parser.add_argument("--seed-ledger-sha256")
    parser.add_argument("--seed-plan-sha256")
    parser.add_argument("--reclaim-workflow-inputs", action="store_true")
    args = parser.parse_args()
    if args.reclaim_workflow_inputs and (os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or not os.environ.get("GITHUB_WORKSPACE")):
        parser.error("Input cleanup is restricted to explicit disposable GitHub-hosted builds")
    if args.catalog_lane:
        from catalog_build import lane_scope
        lane_scope({}, args.catalog_lane)
        if args.mode != "full-catalog":
            parser.error("Lanes require full-catalog mode")
    if not 60 <= args.timeout_seconds <= 604800:
        parser.error("Build deadline must be between one minute and seven days")
    if args.seed_dir and (not args.seed_graph or any(not re.fullmatch(r"[0-9a-f]{64}", pin or "") for pin in
            [args.seed_inventory_sha256, args.seed_ledger_sha256, args.seed_plan_sha256])):
        parser.error("Seed adoption requires the new graph and explicit inventory/ledger/plan hashes")
    if not 60 <= args.catalog_budget_seconds <= 604800 or args.catalog_minimum_free_gib < 8:
        parser.error("Catalog batches require at least60seconds and8GiB disk headroom")
    if args.mode == "full-catalog" and args.catalog_budget_seconds + 600 > args.timeout_seconds:
        parser.error("Reserve at least600seconds after the catalog batch for artifact export")
    if args.mode == "packages":
        if not args.packages or len(args.packages) > 128 or any(not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name) for name in args.packages):
            parser.error("packages mode requires 1–128 valid recipe names per build batch")
    elif args.packages:
        parser.error("--packages requires --mode packages")
    if args.cache_image and not re.fullmatch(r"termi-checkpoint:[a-z0-9_.-]+", args.cache_image):
        parser.error("Only an explicitly restored local Termi checkpoint image is accepted")
    if args.catalog_retry_failed and args.mode != "full-catalog":
        parser.error("Catalog retries require full-catalog mode")
    if args.continue_recipe and (not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", args.continue_recipe)
            or not args.cache_image
            or not ((args.mode == "packages" and args.continue_recipe in args.packages)
                    or (args.mode == "full-catalog" and args.catalog_retry_failed))):
        parser.error("Compile continuation requires a restored cache and an explicit requested recipe or catalog retry")
    # Report unavailable engine before creating build state or downloading images.
    run(["docker", "info", "--format", "{{.OSType}}"])
    lock = read_lock(ROOT / "packages/termux/upstream.lock.json")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("Output already exists; use a new build directory")
    prepare(args.upstream.resolve(), output / "context", lock, full_catalog=args.mode == "full-catalog" or args.full_recipes)
    if args.seed_dir:
        from seed import prepare as prepare_seed
        prepare_seed(args.seed_dir.resolve(), output / "context", args.seed_graph.resolve(), output / "context/seed",
                     args.seed_inventory_sha256, args.seed_ledger_sha256, args.seed_plan_sha256)
    identity = input_identity(output / "context")
    (output / "build-input-identity.txt").write_text(identity + "\n")
    if args.cache_image:
        image_info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.cache_image]))[0]
        if (image_info["Config"].get("Labels") or {}).get("org.termi.build-input-identity") != identity:
            raise ValueError("Restored cache does not match the complete build-input identity")
        cache_check = subprocess.check_output(["docker", "create", "--entrypoint", "/bin/true", args.cache_image], text=True).strip()
        try:
            for name in ["upstream.lock.json", "source.json", "patches.json"]:
                target = output / ("cache-" + name)
                run(["docker", "cp", cache_check + ":/home/builder/" + name, str(target)])
                if target.is_symlink() or target.read_bytes() != (output / "context" / name).read_bytes():
                    raise ValueError("Cached prefix/source/patch identity differs from this build")
        finally:
            run(["docker", "rm", cache_check])
        dockerfile = output / "context/Dockerfile"
        original = dockerfile.read_text()
        dockerfile.write_text("FROM " + args.cache_image + "\n" + original.split("\n", 1)[1])
    artifacts = output / "artifacts"
    artifacts.mkdir()
    tag = "termi-termux-candidate:" + uuid.uuid4().hex
    run(["docker", "build", "--tag", tag, str(output / "context")])
    if args.reclaim_workflow_inputs:
        reclaim_workflow_archives(Path(os.environ["GITHUB_WORKSPACE"]), output / "context", args.seed_dir)
    container = subprocess.check_output([
        "docker", "create", "--cpus", str(args.jobs), "--memory", f"{args.memory_gib}g", "--pids-limit", "2048",
        "--env", f"TERMI_BUILD_JOBS={args.jobs}",
        "--env", f"TERMI_CONTINUE_RECIPE={args.continue_recipe or ''}",
        "--env", f"TERMI_CATALOG_BUDGET={args.catalog_budget_seconds}",
        "--env", f"TERMI_CATALOG_MINIMUM_FREE_GIB={args.catalog_minimum_free_gib}",
        "--env", f"TERMI_CATALOG_RETRY_FAILED={int(args.catalog_retry_failed)}",
        "--env", f"TERMI_CATALOG_LANE={args.catalog_lane or ''}",
        "--security-opt", "no-new-privileges", tag, args.mode, *(args.packages or [])], text=True).strip()
    (output / "container-id.txt").write_text(container + "\n")
    result = None
    try:
        # No host filesystem, Docker socket, secrets or devices are mounted.
        result = subprocess.run(["docker", "start", "--attach", container], timeout=args.timeout_seconds).returncode
    finally:
        # Docker CLI interrupt need not terminate the attached process itself.
        run(["docker", "stop", "--time", "10", container])
        state = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]["State"]
        (output / "container-state.json").write_text(json.dumps(state, indent=2) + "\n")
        copied = subprocess.run(["docker", "cp", container + ":/home/builder/artifacts/.", str(artifacts)]).returncode
        # Preserve a failed container for diagnosis; remove only after evidence copy.
        if copied == 0 and result == 0 and state["ExitCode"] == 0 and args.mode != "full-catalog":
            run(["docker", "rm", container])
    if result != 0 or state["ExitCode"] != 0 or copied != 0:
        raise SystemExit("Candidate build failed; inspect retained log/container-state.json")
    if not (artifacts / "inventory.json").is_file():
        raise SystemExit("Missing package inventory; no successful candidate")
    if args.mode == "proof":
        run([sys.executable, str(ROOT / "scripts/termux/proof_sbom.py"), "--build", str(output)])
    print(f"Candidate artifacts: {artifacts}. Not signed, installed or device verified.")


if __name__ == "__main__":
    main()
