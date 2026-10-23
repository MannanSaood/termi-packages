#!/usr/bin/env python3
"""Produce generation2 from the exact approved bootstrap plus original Debian bytes.

No network, new signing key or installed-device files are used. Existing proof
repositories remain byte-identical; the APK separately activates the HTTPS source.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import zipfile

ORIGINAL = {
    "archive": "a798850fc3ce91ae0b6d2c5f34ede6481b438e235ea53acf3f549f8f928443f4",
    "manifest": "efabe4ac249e754b1292ecfec23d17b2f781a6a39e492a441d94a6c348949738",
    "closure": "687f27a18698af38c3fdfa8c086e90f898270fc08b321522caa218c939e9484d",
}
PREFIX = "data/data/com.terminal.nextgen/files/usr"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checksums(payload):
    rows = []
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        for member in archive:
            name = member.name.removeprefix("./").rstrip("/")
            if name in ("", "."):
                continue
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or
                    any(c in name for c in "\\\r\n\t") or name in seen):
                raise ValueError("Unsafe or duplicate checksum member")
            seen.add(name)
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("Unsupported checksum member")
            if member.isfile():
                if not name.startswith(PREFIX + "/") or not 0 <= member.size <= 64 * 1024 * 1024:
                    raise ValueError("Checksum payload outside bounded private prefix")
                with archive.extractfile(member) as content:
                    value = hashlib.md5(content.read(), usedforsecurity=False).hexdigest()
                rows.append(f"{value}  {name}\n")
    return "".join(rows).encode()


def repair(bootstrap, debs, output):
    original = {}
    for field, filename in (("archive", "bootstrap.zip"), ("manifest", "bootstrap.manifest"),
                            ("closure", "runtime-closure.json")):
        data = (bootstrap / filename).read_bytes()
        if sha(data) != ORIGINAL[field]:
            raise ValueError(f"Unapproved original {field}")
        original[field] = data
    records = json.loads(original["closure"])["packages"]
    additions = {}
    for record in records:
        deb = debs / record["file"]
        if not deb.exists():
            deb = debs / record["file"].replace(":", "%3A")
        if sha(deb.read_bytes()) != record["sha256"]:
            raise ValueError(f"Original package hash mismatch: {record['name']}")
        payload = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(deb)])
        additions[f"var/lib/dpkg/info/{record['name']}.md5sums"] = checksums(payload)
    if len(additions) != 55:
        raise ValueError("Unexpected bootstrap closure")
    manifest = original["manifest"].decode().splitlines()
    names = {line.split("\t")[1] for line in manifest[1:]}
    if names.intersection(additions):
        raise ValueError("Checksum record already exists; refusing replacement")
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(original["archive"])) as old:
        with zipfile.ZipFile(output / "bootstrap.zip", "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as new:
            for entry in old.infolist():
                new.writestr(entry, old.read(entry))
            for name, data in sorted(additions.items()):
                entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100600 << 16
                new.writestr(entry, data)
                manifest.append(f"f\t{name}\t{len(data)}\t{sha(data)}\t-")
    (output / "bootstrap.manifest").write_text(
        manifest[0] + "\n" + "\n".join(sorted(manifest[1:], key=lambda r: r.split("\t")[1])) + "\n",
        encoding="utf-8", newline="\n")
    identity = f"1:{ORIGINAL['archive']}:{ORIGINAL['manifest']}"
    archive_hash = sha((output / "bootstrap.zip").read_bytes())
    manifest_hash = sha((output / "bootstrap.manifest").read_bytes())
    (output / "bootstrap.properties").write_text(
        f"format=1\narchitecture=aarch64\nprefix=/{PREFIX}\ngeneration=2\n"
        f"archive={archive_hash}\nmanifest={manifest_hash}\ncompatible={identity}\n",
        encoding="utf-8", newline="\n")
    (output / "repair.provenance.json").write_text(json.dumps({
        "original": ORIGINAL, "added_records": len(additions),
        "archive": archive_hash, "manifest": manifest_hash,
        "method": "dpkg-compatible MD5 records from pinned original Debian payloads; SHA256 authenticates inputs",
        "packages": [{"name": r["name"], "file": r["file"], "sha256": r["sha256"]} for r in records],
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--debs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repair(args.bootstrap, args.debs, args.output)
