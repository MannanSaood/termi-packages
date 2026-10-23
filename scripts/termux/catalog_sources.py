#!/usr/bin/env python3
"""Export available exact source inputs for the approved runtime packages."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from catalog_policy import PROFILES, policy_for


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, default="proof")
    args = parser.parse_args()
    policy = policy_for(args.profile)
    source_limit = 96 * 1024**2 if args.profile == "proof" else 8 * 1024**3
    names = {r["name"] for r in json.loads((args.repository / "approved-packages.json").read_text())["packages"]}
    parents = {}
    for tree in ["packages", "root-packages", "x11-packages"]:
        for recipe in (args.recipes / tree).glob("*/build.sh"):
            parents[recipe.parent.name] = recipe.parent.name
            for sub in recipe.parent.glob("*.subpackage.sh"):
                parents[sub.name.removesuffix(".subpackage.sh")] = recipe.parent.name
    destination = args.repository / "sources"
    destination.mkdir()
    records = []
    for parent in sorted({parents[name] for name in names}):
        inputs = []
        cache = args.cache / parent / "cache"
        for source in sorted(cache.iterdir()) if cache.is_dir() else []:
            if not source.is_file() or source.is_symlink():
                continue
            if source.stat().st_size > source_limit:
                raise ValueError(f"Oversized source input: {source}")
            checksum = digest(source)
            name = checksum[:16 if args.profile == "proof" else 64] + "-" + source.name.replace(":", "%3A")
            target = destination / name
            if not target.exists():
                shutil.copyfile(source, target)
            inputs.append(dict(file="sources/" + name, sha256=checksum))
        source_tree = args.cache / parent / "src"
        if (source_tree / ".git").exists():
            name = parent + "-git-source.tar"
            subprocess.run(["git", "-C", str(source_tree), "archive", "--format=tar",
                            "--output", str(destination / name), "HEAD"], check=True)
            inputs.append(dict(file="sources/" + name, sha256=digest(destination / name)))
        records.append(dict(recipe_package=parent, packages=sorted(n for n in names if parents[n] == parent),
                            inputs=inputs, note="Recipe, patches and source references are in build-context/source.tar.gz; platform/toolchain inputs are pinned by upstream.lock.json"))
    if sum(p.stat().st_size for p in destination.iterdir()) > policy.repository_bytes:
        raise ValueError("Source archive exceeds selected publication budget")
    (args.repository / "sources.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"parents": len(records), "without_cached_sources": [r["recipe_package"] for r in records if not r["inputs"]],
                      "source_bytes": sum(p.stat().st_size for p in destination.iterdir())}))


if __name__ == "__main__":
    main()
