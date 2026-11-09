"""Stage a pinned package subset as individual, verified GitHub release assets."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from seed import digest


REPOSITORY = "MannanSaood/termi-packages"


def gh(*args):
    return subprocess.check_output(["gh", *args])


def download(tag, asset, directory):
    name = asset["name"]
    gh("release", "download", tag, "-R", REPOSITORY, "-p", name, "-D", str(directory))
    path = directory / name
    if path.stat().st_size != asset["size"] or "sha256:" + digest(path) != asset["digest"]:
        raise ValueError(f"Release asset does not match published digest: {name}")
    return path


def stage(work, config):
    tag = config["source_tag"]
    release = json.loads(gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}"))
    assets = {a["name"]: a for a in release["assets"]}
    pins = config["pins"]
    for name, pin in pins.items():
        if digest(download(tag, assets[name], work)) != pin:
            raise ValueError(f"Candidate pin mismatch: {name}")
    inventory = json.loads((work / "inventory.json").read_text())
    records = {r["file"]: r for r in inventory["packages"]}
    selected = set(config["files"])
    if len(selected) != len(config["files"]) or not selected <= records.keys():
        raise ValueError("Invalid selection")
    output = work / "assets"
    output.mkdir()
    staged = {}
    for name, asset in sorted(assets.items()):
        if not re.fullmatch(r"packages-[0-9]+\.tar", name):
            continue
        bundle = download(tag, asset, work)
        with tarfile.open(bundle, "r|") as archive:
            for member in archive:
                if member.name not in selected:
                    continue
                record = records[member.name]
                filename = re.sub(r"[^A-Za-z0-9_.-]", "_", member.name)
                if not member.isfile() or member.name in staged or record["channel"] not in ("main", "x11"):
                    raise ValueError("Unexpected selected archive")
                path = output / filename
                with archive.extractfile(member) as source, path.open("xb") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
                if digest(path) != record["sha256"]:
                    raise ValueError(f"Package digest mismatch: {member.name}")
                staged[member.name] = dict(asset=filename, bytes=path.stat().st_size, **record)
        bundle.unlink()
        if staged.keys() == selected:
            break
    if staged.keys() != selected:
        raise ValueError("Candidate did not contain the complete selection")
    index = subprocess.check_output(["dpkg-scanpackages", "--multiversion", ".", "/dev/null"], cwd=output)
    index = re.sub(rb"(?m)^Filename: \./", b"Filename: ", index)
    (output / "Packages").write_bytes(index)
    manifest = dict(source=tag, pins=pins, roots=config["roots"], packages=list(staged.values()),
                    index_sha256=hashlib.sha256(index).hexdigest(), status="unsigned-test-staging")
    (output / "pilot-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return output


def main():
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SystemExit("This stage runs only on the project's hosted runner")
    config = json.loads(Path("packages/termux/apt-pilot.json").read_text())
    tag = "apt-pilot-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
    with tempfile.TemporaryDirectory() as directory:
        output = stage(Path(directory), config)
        gh("release", "create", tag, "-R", REPOSITORY, "--prerelease",
           "--latest=false", "--title", "Termi ARM64 APT pilot", "--notes",
           "Isolated Git Annex and Carbonyl test snapshot. Await signed metadata and phone validation.")
        paths = sorted(output.iterdir())
        gh("release", "upload", tag, "-R", REPOSITORY, *map(str, paths))
        release = json.loads(gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}"))
        pages = json.loads(gh("api", "--paginate", "--slurp",
                              f"repos/{REPOSITORY}/releases/{release['id']}/assets?per_page=100"))
        actual = {a["name"]: (a["state"], a["size"], a["digest"]) for page in pages for a in page}
        expected = {p.name: ("uploaded", p.stat().st_size, "sha256:" + digest(p)) for p in paths}
        if actual != expected:
            raise ValueError("Staged GitHub assets did not match the verified snapshot")
        print(f"{tag}: verified {len(config['files'])} individual package assets", flush=True)


if __name__ == "__main__":
    main()
