"""Stage signed flat APT shards on GitHub Releases, separate from the live feed."""

import gzip
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

from seed import digest
from stage_apt_pilot import REPOSITORY, download, gh, stage


CONFIG = Path("packages/termux/apt-catalog-staging.json")
KEYRING = Path("packages/termux/repository/repository-keyring.gpg").resolve()
SIGNED = ("Packages.gz", "Release", "Release.gpg", "InRelease")


def release(tag):
    return json.loads(gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}"))


def release_assets(release_id):
    pages = json.loads(gh("api", "--paginate", "--slurp",
                          f"repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100"))
    return {a["name"]: a for page in pages for a in page}


def check_asset(asset, path):
    expected = (path.name, "uploaded", path.stat().st_size, "sha256:" + digest(path))
    actual = (asset["name"], asset["state"], asset["size"], asset.get("digest"))
    if actual != expected:
        raise ValueError(f"Conflicting release asset: {path.name}")


class Uploads:
    def __init__(self, release_id):
        self.release_id = release_id
        self.assets = release_assets(release_id)
        self.next_request = 0

    def put(self, path):
        if path.name in self.assets:
            check_asset(self.assets[path.name], path)
            return
        for attempt in range(4):
            # Upload jobs run serially. Reserve room below GitHub's general
            # 500 content-generating requests per hour.
            time.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + 8.5
            conn = http.client.HTTPSConnection("uploads.github.com", timeout=180)
            try:
                url = f"/repos/{REPOSITORY}/releases/{self.release_id}/assets?"
                with path.open("rb") as data:
                    conn.request("POST", url + urlencode({"name": path.name}), data, {
                        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "termi-apt-catalog-staging",
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(path.stat().st_size),
                    })
                    response = conn.getresponse()
                    body = response.read()
                if response.status == 201:
                    asset = json.loads(body)
                    check_asset(asset, path)
                    self.assets[path.name] = asset
                    return
                if response.status not in (403, 429, 500, 502, 503, 504):
                    raise RuntimeError(f"Asset upload {path.name} failed with HTTP {response.status}")
                delay = max(60 * 2**attempt, int(response.getheader("Retry-After", "0")))
                if response.getheader("X-RateLimit-Remaining") == "0":
                    delay = max(delay, int(response.getheader("X-RateLimit-Reset", "0")) - time.time() + 2)
            except (OSError, http.client.HTTPException):
                delay = 60 * 2**attempt
            finally:
                conn.close()
            print(f"Upload of {path.name} unconfirmed; checking after {delay:.0f}s", flush=True)
            time.sleep(delay)
            self.assets = release_assets(self.release_id)
            if path.name in self.assets:
                check_asset(self.assets[path.name], path)
                return
        raise RuntimeError(f"Asset upload could not be confirmed: {path.name}")


def prepare_config(work, shard):
    config = json.loads(CONFIG.read_text())
    match = re.fullmatch(r"(main|x11|root)-([0-3])", shard)
    if not match:
        raise ValueError("Unknown staging shard")
    channel, batch = match.groups()
    start = int(batch) * config["batch_size"]
    source = release(config["source_tag"])
    asset, = (a for a in source["assets"] if a["name"] == "inventory.json")
    directory = work / "selection"
    directory.mkdir()
    inventory = download(config["source_tag"], asset, directory)
    if digest(inventory) != config["pins"]["inventory.json"]:
        raise ValueError("Inventory pin mismatch")
    all_files = sorted(r["file"] for r in json.loads(inventory.read_text())["packages"] if r["channel"] == channel)
    files = all_files[start:start + config["batch_size"]]
    if not files or len(all_files) != config["counts"][channel]:
        raise ValueError("Unexpected channel inventory")
    tag = f"{config['tag_prefix']}-{shard}"
    replacement = config.pop("replacement")
    if replacement["base_file"] in files:
        config["replacement"] = replacement
    return tag, dict(config, files=files, channels=[channel], canonical_index=True, roots={})


def staging_release(tag):
    result = subprocess.run(["gh", "release", "view", tag, "-R", REPOSITORY, "--json", "tagName"],
                            capture_output=True, text=True)
    if result.returncode:
        if "release not found" not in result.stderr.lower():
            raise RuntimeError("Unable to check staging release")
        gh("release", "create", tag, "-R", REPOSITORY, "--prerelease", "--latest=false",
           "--title", f"Termi catalog staging {tag}",
           "--notes", "Staging only. The production APT feed remains separate.")
    value = release(tag)
    if not value["prerelease"] or value["draft"]:
        raise ValueError("Refusing to modify a non-staging release")
    return value


def checked_signatures(tag, remote, output, work):
    for name in ("Packages", "catalog-manifest.json"):
        path = output / name
        check_asset(remote[path.name], path)
    hold = work / "signed"
    hold.mkdir()
    for name in SIGNED:
        path = download(tag, remote[name + ".staged"], hold)
        path.rename(hold / name)
    extracted = hold / "clear"
    subprocess.run(["gpgv", "--keyring", KEYRING, "--output", extracted, hold / "InRelease"], check=True)
    subprocess.run(["gpgv", "--keyring", KEYRING, hold / "Release.gpg", hold / "Release"], check=True)
    text = (hold / "Release").read_bytes()
    if extracted.read_bytes() != text or gzip.decompress((hold / "Packages.gz").read_bytes()) != (output / "Packages").read_bytes():
        raise ValueError("Staged signatures and index differ")
    for name in ("Packages", "Packages.gz"):
        path = (output if name == "Packages" else hold) / name
        if f" {digest(path)} {path.stat().st_size} {name}\n".encode() not in text:
            raise ValueError("Signed index pin differs")
    manifest_pin = f"X-Termi-Staging-Manifest-SHA256: {digest(output / 'catalog-manifest.json')}\n"
    if manifest_pin.encode() not in text:
        raise ValueError("Signed manifest pin differs")
    return hold


def main(phase, shard):
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise SystemExit("Run catalog staging on the project's hosted runner")
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        tag, config = prepare_config(work, shard)
        output = stage(work, config)
        (output / "pilot-manifest.json").rename(output / "catalog-manifest.json")
        staged_release = staging_release(tag)
        uploads = Uploads(staged_release["id"])
        if phase == "prepare":
            for name in ("Packages", "catalog-manifest.json"):
                uploads.put(output / name)
        elif phase == "upload":
            hold = checked_signatures(tag, uploads.assets, output, work)
            packages = sorted(output.glob("*.deb"))
            for index, path in enumerate(packages, 1):
                uploads.put(path)
                if index % 50 == 0:
                    print(f"{tag}: verified {index}/{len(packages)} individual .deb assets", flush=True)
            # Publish the signatures at APT paths only after all bytes are confirmed.
            for name in SIGNED:
                uploads.put(hold / name)
            assets = release_assets(staged_release["id"])
            for path in packages + [hold / name for name in SIGNED]:
                check_asset(assets[path.name], path)
        else:
            raise ValueError("Unknown staging phase")
        print(f"{tag}: {phase} verified {len(config['files'])} packages", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
