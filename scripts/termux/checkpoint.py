#!/usr/bin/env python3
"""Stream a stopped, mount-free build container to versioned GitHub Releases.

No runtime signing authority. Checkpoints are untrusted until their manifest and
build-input identities match explicit restore pins. Never extract on the host.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


class Parts:
    def __init__(self, directory, upload, limit=1024**3):
        self.directory, self.upload, self.limit = directory, upload, limit
        self.records, self.stream, self.size = [], None, 0

    def write(self, data):
        count = len(data)
        while data:
            if self.stream is None:
                if len(self.records) >= 256:
                    raise ValueError("Checkpoint exceeds256GiB compressed bound")
                self.path = self.directory / f"checkpoint-{len(self.records):04d}.gz.part"
                self.stream = self.path.open("xb")
                self.hash = hashlib.sha256()
            take = min(len(data), self.limit - self.size)
            self.stream.write(data[:take]); self.hash.update(data[:take])
            self.size += take
            data = data[take:]
            if self.size == self.limit:
                self.finish()
        return count

    def flush(self):
        if self.stream:
            self.stream.flush()

    def finish(self):
        if self.stream:
            self.stream.close()
            self.records.append(dict(file=self.path.name, bytes=self.size, sha256=self.hash.hexdigest()))
            self.upload(self.path)
            self.path.unlink()
            self.stream, self.size = None, 0


def gh(repository, *arguments):
    # A stalled transport must not consume the entire checkpoint allowance.
    # Fail without deleting remote parts; manifest-last keeps them unusable
    # until every part is known to have uploaded successfully.
    return subprocess.run(["gh", "release", *arguments, "--repo", repository], check=True, timeout=600)


def save(container, repository, tag, identity):
    visibility = json.loads(subprocess.check_output(["gh", "repo", "view", repository, "--json", "visibility"]))["visibility"]
    if visibility != "PUBLIC":
        raise ValueError("The zero-cost pipeline requires a public repository")
    info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    if info["State"]["Running"] or info["Mounts"] or info["HostConfig"].get("Privileged"):
        raise ValueError("Only stopped mount-free unprivileged package builders can be checkpointed")
    if info["Config"].get("User") != "builder":
        raise ValueError("Checkpoint requires the dedicated package-builder identity")
    if any(re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL", entry.split("=", 1)[0], re.I) for entry in (info["Config"].get("Env") or [])):
        raise ValueError("Do not publish a builder containing secret environment variables")
    gh(repository, "create", tag, "--title", "Build checkpoint " + tag, "--notes", "Build cache only; not installable packages or an approved release.", "--prerelease", "--latest=false")
    with tempfile.TemporaryDirectory(prefix="termi-checkpoint-") as directory:
        directory = Path(directory)
        if shutil.disk_usage(directory).free < 2 * 1024**3:
            raise ValueError("Checkpoint streaming needs2GiB free scratch space")
        parts = Parts(directory, lambda path: gh(repository, "upload", tag, str(path)))
        process = subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE)
        try:
            with gzip.GzipFile(fileobj=parts, mode="wb", compresslevel=1, mtime=0) as compressed:
                shutil.copyfileobj(process.stdout, compressed, 1024**2)
            if process.wait() != 0:
                raise ValueError("Container export failed; incomplete checkpoint is unusable")
            parts.finish()
        finally:
            if process.poll() is None:
                process.terminate(); process.wait()
        manifest = directory / "checkpoint.json"
        manifest.write_text(json.dumps(dict(schema=1, input_identity=identity, parts=parts.records, environment=info["Config"].get("Env") or [],
                                            user="builder", workdir="/home/builder/termux-packages"), indent=2) + "\n")
        # Manifest last: incomplete uploads never have a usable checkpoint.
        gh(repository, "upload", tag, str(manifest))
        print("CHECKPOINT_MANIFEST_SHA256=" + hashlib.sha256(manifest.read_bytes()).hexdigest())


def restore(repository, tag, identity, manifest_sha256, image):
    with tempfile.TemporaryDirectory(prefix="termi-restore-") as directory:
        directory = Path(directory)
        gh(repository, "download", tag, "--pattern", "checkpoint.json", "--dir", str(directory))
        path = directory / "checkpoint.json"
        if path.stat().st_size > 128 * 1024 or hashlib.sha256(path.read_bytes()).hexdigest() != manifest_sha256:
            raise ValueError("Checkpoint manifest differs from explicit pin")
        manifest = json.loads(path.read_text())
        if manifest.get("schema") != 1 or manifest.get("input_identity") != identity or not 1 <= len(manifest["parts"]) <= 256:
            raise ValueError("Checkpoint build identity differs")
        changes = []
        for entry in manifest.get("environment", []):
            key, value = entry.split("=", 1)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or any(c in value for c in "\r\n\0") or re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL", key, re.I):
                raise ValueError("Invalid checkpoint environment")
            changes += ["--change", "ENV " + key + "=" + json.dumps(value)]
        process = subprocess.Popen(["docker", "import", *changes, "--change", "LABEL org.termi.build-input-identity=" + identity,
                                    "--change", "USER builder", "--change", "WORKDIR /home/builder/termux-packages", "-", image], stdin=subprocess.PIPE)
        decoder = __import__("zlib").decompressobj(31)
        expanded = 0
        try:
            for index, record in enumerate(manifest["parts"]):
                if record["file"] != f"checkpoint-{index:04d}.gz.part" or not 0 < record["bytes"] <= 1024**3:
                    raise ValueError("Invalid checkpoint part")
                gh(repository, "download", tag, "--pattern", record["file"], "--dir", str(directory))
                part = directory / record["file"]
                with part.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if part.stat().st_size != record["bytes"] or checksum != record["sha256"]:
                    raise ValueError("Checkpoint part differs from manifest")
                with part.open("rb") as stream:
                    while block := stream.read(1024**2):
                        while block:
                            decoded = decoder.decompress(block, 1024**2)
                            expanded += len(decoded)
                            if expanded > 512 * 1024**3 or shutil.disk_usage(directory).free < 2 * 1024**3:
                                raise ValueError("Checkpoint exceeds expanded-size or free-disk budget")
                            process.stdin.write(decoded)
                            block = decoder.unconsumed_tail
                part.unlink()
            process.stdin.write(decoder.flush())
            if not decoder.eof or decoder.unused_data:
                raise ValueError("Truncated or trailing compressed checkpoint")
            process.stdin.close()
            if process.wait() != 0:
                raise ValueError("Isolated Docker restore failed")
        finally:
            if process.poll() is None:
                process.terminate(); process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["save", "restore"])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--input-identity", required=True)
    parser.add_argument("--container")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--image", default="termi-checkpoint:restored")
    args = parser.parse_args()
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository)
            or not re.fullmatch(r"checkpoint-[a-zA-Z0-9_.-]+", args.tag)
            or not re.fullmatch(r"[0-9a-f]{64}", args.input_identity)):
        parser.error("Require a fixed repository, checkpoint tag and explicit SHA256 input identity")
    if args.mode == "save":
        if not args.container: parser.error("--container required")
        save(args.container, args.repository, args.tag, args.input_identity)
    else:
        if not args.manifest_sha256 or not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256) or not re.fullmatch(r"termi-checkpoint:[a-z0-9_.-]+", args.image):
            parser.error("Require an explicit manifest SHA256 and local checkpoint image tag")
        restore(args.repository, args.tag, args.input_identity, args.manifest_sha256, args.image)


if __name__ == "__main__":
    main()
