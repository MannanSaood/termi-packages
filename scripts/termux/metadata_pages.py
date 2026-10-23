#!/usr/bin/env python3
"""Verify/copy already signed APT metadata for Pages; never sign or approve packages."""
import argparse
import datetime
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote

LIMIT = 64 * 1024**2
CHANNELS = ("main", "root", "x11")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fields(text):
    result, previous = {}, None
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and previous:
            result[previous] += "\n" + line
        else:
            key, value = line.split(":", 1)
            if key in result:
                raise ValueError("Duplicate metadata field")
            result[key], previous = value.strip(), key
    return result


def verify(root, keyring, channel, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    signed = root / "dists/stable/InRelease"
    for name in ["approved-packages.json", "repository-keyring.gpg", "dists/stable/InRelease", "dists/stable/Release", "dists/stable/Release.gpg"]:
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
            raise ValueError("Missing, aliased or oversized metadata")
    if (root / "repository-keyring.gpg").read_bytes() != keyring.read_bytes():
        raise ValueError("Snapshot uses a different trust root")
    release = root / "dists/stable/Release"
    verified = subprocess.check_output(["gpgv", "--keyring", str(keyring.resolve()), "--output", "-", str(signed)])
    if verified != release.read_bytes():
        raise ValueError("Clear-signed metadata and Release differ")
    subprocess.run(["gpgv", "--keyring", str(keyring.resolve()), str(release.with_name("Release.gpg")), str(release)], check=True)
    header = fields(verified.decode())
    created, expiry = [parsedate_to_datetime(header[key]) for key in ["Date", "Valid-Until"]]
    if (created.tzinfo is None or expiry.tzinfo is None or expiry <= now
            or created > now + datetime.timedelta(minutes=10) or not datetime.timedelta(0) < expiry - created <= datetime.timedelta(days=46)):
        raise ValueError("Expired or invalid metadata lifetime")
    if (header.get("Origin") != "Termi" or header.get("Suite") != "stable"
            or header.get("Architectures") != "aarch64" or header.get("Components") != "main"
            or header.get("X-Termi-Inventory-SHA256") != digest(root / "approved-packages.json")):
        raise ValueError("Unapproved identity or inventory")
    expected_paths = {"main/binary-aarch64/Packages", "main/binary-aarch64/Packages.gz"}
    entries = [line.split() for line in header["SHA256"].splitlines() if line.strip()]
    if len(entries) != 2 or {e[2] for e in entries if len(e) == 3} != expected_paths:
        raise ValueError("Unexpected signed index paths")
    for checksum, size, name in entries:
        path = release.parent / name
        if (path.is_symlink() or not path.is_file() or not 0 < int(size) <= LIMIT
                or path.stat().st_size != int(size) or digest(path) != checksum):
            raise ValueError("Signed index checksum differs")
        immutable = path.parent / "by-hash/SHA256" / checksum
        if immutable.is_symlink() or not immutable.is_file() or digest(immutable) != checksum:
            raise ValueError("Missing or changed Acquire-By-Hash object")
    index = release.parent / "main/binary-aarch64/Packages"
    with gzip.GzipFile(fileobj=io.BytesIO(index.with_name("Packages.gz").read_bytes())) as compressed:
        if compressed.read(LIMIT + 1) != index.read_bytes():
            raise ValueError("Compressed index differs")
    manifest = json.loads((root / "approved-packages.json").read_text())
    records = manifest["packages"]
    tags = manifest.get("asset_tags", {})
    if (manifest.get("schema") != 1 or manifest.get("channel", "main") != channel or not 1 <= len(records) <= 20000
            or set(tags) != {r["file"] for r in records}
            or any(not re.fullmatch("termi-" + channel + "-[0-9a-f]{24}", tag) for tag in tags.values())):
        raise ValueError("Missing approved release asset mapping")
    approved = {(r["name"], r["version"], r["architecture"]): r for r in records}
    actual = {}
    for paragraph in index.read_text().strip().split("\n\n"):
        record = fields(paragraph)
        identity = (record["Package"], record["Version"], record["Architecture"])
        item = approved.get(identity)
        if item is None or identity in actual or record["SHA256"] != item["sha256"]:
            raise ValueError("Index differs from signed inventory")
        if (not re.fullmatch(r"[A-Za-z0-9%+._~-]+\.deb", item["file"])
                or record["Filename"] != "pool/" + tags[item["file"]] + "/" + quote(item["file"], safe="+._~-")
                or not 0 < int(record["Size"]) < 2 * 1024**3):
            raise ValueError("Unsafe release asset path or size")
        actual[identity] = True
    if set(actual) != set(approved) or len(approved) != len(records):
        raise ValueError("Incomplete or duplicate index")
    return len(records)


def verify_pages(public, keyring):
    if public.is_symlink() or not public.is_dir():
        raise ValueError("Missing metadata site")
    total = 0
    for path in public.rglob("*"):
        relative = path.relative_to(public).as_posix()
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Aliased metadata site")
        if path.is_file():
            total += path.stat().st_size
            if total > 512 * 1024**2 or not re.fullmatch(
                r"apt/(main|root|x11)/(?:approved-packages\.json|repository-keyring\.gpg|dists/stable/(?:InRelease|Release|Release\.gpg|main/binary-aarch64/(?:Packages|Packages\.gz|by-hash/SHA256/[0-9a-f]{64})))", relative):
                raise ValueError("Metadata site contains non-metadata files or exceeds512MiB")
            if "/by-hash/" in relative and digest(path) != path.name:
                raise ValueError("Changed immutable metadata object")
    if not (public / "apt/main").is_dir():
        raise ValueError("Main channel required")
    return {channel: verify(public / "apt" / channel, keyring, channel)
            for channel in CHANNELS if (public / "apt" / channel).exists()}


def export(root, output, keyring, channel="main"):
    verify(root, keyring, channel)
    output.mkdir(parents=True, exist_ok=False)
    for name in ["approved-packages.json", "repository-keyring.gpg"]:
        shutil.copyfile(root / name, output / name)
    shutil.copytree(root / "dists", output / "dists", symlinks=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--repository", type=Path, help="Export one already signed local snapshot into a new site")
    parser.add_argument("--channel", choices=CHANNELS, default="main")
    args = parser.parse_args()
    if args.repository:
        export(args.repository, args.public / "apt" / args.channel, args.keyring, args.channel)
    print(json.dumps(verify_pages(args.public, args.keyring)))


if __name__ == "__main__":
    main()
