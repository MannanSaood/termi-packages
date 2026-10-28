#!/usr/bin/env python3
"""Export built Debian candidates with portable filenames and exact inventories."""
import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect(source, destination, plan=None, resume=False, link_immutable=False):
    files = sorted(source.glob("*.deb"))
    if not files:
        raise ValueError("No built packages; refusing success")
    names = set()
    planned = []
    for file in files:
        name = file.name.replace(":", "%3A")
        if (not file.is_file() or file.is_symlink() or name.casefold() in names
                or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                or ((destination / name).exists() and not resume)):
            raise ValueError("Unsafe or colliding exported artifact filename")
        names.add(name.casefold())
        fields = subprocess.check_output([
            "dpkg-deb", "-f", str(file), "Package", "Version", "Architecture", "Depends"], text=True)
        if not re.search(r"^Architecture: (aarch64|all)$", fields, re.MULTILINE):
            raise ValueError("Unexpected built package architecture")
        package_name = re.search(r"^Package: (.+)$", fields, re.MULTILINE).group(1)
        classification = None
        if plan is not None:
            classification = plan["provided_packages"].get(package_name)
            if not classification or classification["channel"] not in ("main", "root", "x11"):
                raise ValueError("No recipe/channel classification for " + package_name)
        planned.append((file, name, fields, classification))
    destination.mkdir(parents=True, exist_ok=True)
    packages = []
    for file, name, fields, classification in planned:
        target = destination / name
        if target.exists():
            if target.is_symlink() or checksum(target) != checksum(file):
                raise ValueError("Existing candidate object changed; use a new package revision")
        else:
            if link_immutable:
                try:
                    os.link(file, target)
                except OSError as error:
                    if error.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP):
                        raise
                    shutil.copyfile(file, target)
            else:
                shutil.copyfile(file, target)
        packages.append({"file": name, "original_file": file.name,
                         "sha256": checksum(target), "control": fields,
                         **(classification or {})})
    (destination / "inventory.json").write_text(json.dumps({
        "status": "candidate-not-signed-not-device-verified", "packages": packages,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--link-immutable", action="store_true",
                        help="Link completed immutable archives on the same filesystem to avoid a second copy")
    args = parser.parse_args()
    collect(args.source, args.destination, json.loads(args.plan.read_text()) if args.plan else None,
            args.resume, args.link_immutable)
