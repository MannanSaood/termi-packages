"""Extract explicitly named diagnostic logs from verified own checkpoints."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from recover_candidate import VerifiedParts
from seed import digest


def diagnostic_cmake_path(name):
    parts = PurePosixPath(name).parts
    return (".." not in parts and bool(re.fullmatch(
        r"home/builder/\.termux-build/swift/build/(?:[A-Za-z0-9_.+-]+/){0,5}CMakeFiles/(?:CMakeConfigureLog\.yaml|CMakeError\.log|CMakeOutput\.log)", name)))


def diagnostic_foundry_native_path(name):
    return bool(re.fullmatch(
        r"home/builder/\.termux-build/foundry/src/target/aarch64-linux-android/release/"
        r"(?:build/secp256k1-sys-[0-9a-f]+/(?:out/libsecp256k1\.a|output)|deps/libsecp256k1_sys-[0-9a-f]+\.rlib)", name))


def extract_logs(stream, output, names):
    if not names or len(names) > 16 or any(n not in ("swift-cmake", "foundry-native") and not re.fullmatch(r"[a-z0-9+_.-]+-[0-9]+\.log", n) for n in names):
        raise ValueError("Invalid diagnostic names")
    output.mkdir(parents=True, exist_ok=False)
    found = set()
    written = set()
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            key = None
            filename = None
            if len(parts) == 5 and parts[:4] == ("home", "builder", "catalog-state", "logs") and parts[4] in names:
                key = filename = parts[4]
            elif "swift-cmake" in names and diagnostic_cmake_path(member.name):
                key = "swift-cmake"
                filename = hashlib.sha256(member.name.encode()).hexdigest()[:16] + "-" + parts[-1]
            elif "foundry-native" in names and diagnostic_foundry_native_path(member.name):
                key = "foundry-native"
                filename = hashlib.sha256(member.name.encode()).hexdigest()[:16] + "-" + parts[-1]
            if key is None:
                continue
            if not member.isfile() or not 0 <= member.size <= 64 * 1024**2 or filename in written or len(written) >= 64:
                raise ValueError("Unsafe or oversized diagnostic")
            with archive.extractfile(member) as src, (output / filename).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024**2)
            written.add(filename)
            found.add(key)
    while stream.read(1024**2):
        pass
    if found != set(names):
        raise ValueError("Requested diagnostics missing")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    repo = "MannanSaood/termi-packages"
    if not re.fullmatch(r"checkpoint-[0-9]+-[0-9]+", spec["tag"]) or not re.fullmatch(r"diagnostics-[0-9]+-[0-9]+", args.tag):
        raise ValueError("Invalid release tag")
    output = Path("build/diagnostics")
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        def fetch(name):
            subprocess.run(["gh","release","download",spec["tag"],"--repo",repo,"--pattern",name,"--dir",str(tmp)],check=True)
            return tmp / name
        manifest = fetch("checkpoint.json")
        if digest(manifest) != spec["manifest_sha256"]:
            raise ValueError("Manifest hash mismatch")
        data = json.loads(manifest.read_text())
        if data["schema"] != 1 or data["input_identity"] != spec["input_identity"]:
            raise ValueError("Checkpoint identity mismatch")
        extract_logs(VerifiedParts(data["parts"],fetch),output,spec["logs"])
    receipt = dict(checkpoint=spec, logs={p.name:digest(p) for p in output.iterdir()})
    (output/"provenance.json").write_text(json.dumps(receipt,indent=2))
    subprocess.run(["gh","release","create",args.tag,*map(str,sorted(output.iterdir())),"--repo",repo,"--title",args.tag,"--notes","Hash-verified build diagnostics only. No executable packages.","--prerelease","--latest=false"],check=True)
    print(json.dumps(receipt),flush=True)

if __name__ == "__main__":
    main()
