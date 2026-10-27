"""Extract explicitly named diagnostic logs from verified own checkpoints."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from recover_candidate import VerifiedParts
from seed import digest


def extract_logs(stream, output, names):
    if not names or len(names) > 16 or any(not re.fullmatch(r"[a-z0-9+_.-]+-[0-9]+\.log", n) for n in names):
        raise ValueError("Invalid diagnostic names")
    output.mkdir(parents=True, exist_ok=False)
    found = set()
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if len(parts) != 5 or parts[:4] != ("home", "builder", "catalog-state", "logs") or parts[4] not in names:
                continue
            if not member.isfile() or not 0 <= member.size <= 64 * 1024**2 or parts[4] in found:
                raise ValueError("Unsafe or oversized diagnostic")
            with archive.extractfile(member) as src, (output / parts[4]).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024**2)
            found.add(parts[4])
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
