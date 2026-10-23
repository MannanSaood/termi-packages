#!/usr/bin/env python3
"""Build a candidate with the pinned upstream backend; never installs or publishes."""
import argparse
import json
import subprocess
import sys
import uuid
import re
import hashlib
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
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 604800:
        parser.error("Build deadline must be between one minute and seven days")
    if args.mode == "packages":
        if not args.packages or len(args.packages) > 128 or any(not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name) for name in args.packages):
            parser.error("packages mode requires 1–128 valid recipe names per build batch")
    elif args.packages:
        parser.error("--packages requires --mode packages")
    if args.cache_image and not re.fullmatch(r"termi-checkpoint:[a-z0-9_.-]+", args.cache_image):
        parser.error("Only an explicitly restored local Termi checkpoint image is accepted")
    if args.continue_recipe and (not args.cache_image or args.mode != "packages" or args.continue_recipe not in args.packages):
        parser.error("Compile continuation requires a restored cache and one requested recipe")
    # Report unavailable engine before creating build state or downloading images.
    run(["docker", "info", "--format", "{{.OSType}}"])
    lock = read_lock(ROOT / "packages/termux/upstream.lock.json")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("Output already exists; use a new build directory")
    prepare(args.upstream.resolve(), output / "context", lock, full_catalog=args.mode == "full-catalog" or args.full_recipes)
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
    container = subprocess.check_output([
        "docker", "create", "--cpus", str(args.jobs), "--memory", f"{args.memory_gib}g", "--pids-limit", "2048",
        "--env", f"TERMI_BUILD_JOBS={args.jobs}",
        "--env", f"TERMI_CONTINUE_RECIPE={args.continue_recipe or ''}",
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
        if copied == 0 and result == 0 and state["ExitCode"] == 0:
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
