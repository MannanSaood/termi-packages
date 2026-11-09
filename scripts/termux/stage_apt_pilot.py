"""Stage a pinned package subset as individual, verified GitHub release assets."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
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


def repack_carbonyl(work, output, staged, version):
    """Rebuild the launcher from source while retaining the verified browser and ICU bytes."""
    old_name, = (name for name, row in staged.items() if row["recipe"] == "carbonyl")
    old = staged.pop(old_name)
    old_path = output / old["asset"]
    tree = work / "carbonyl"
    subprocess.run(["dpkg-deb", "--raw-extract", old_path, tree], check=True)
    prefix = tree / "data/data/com.terminal.nextgen/files/usr"
    launcher = prefix / "bin/carbonyl"
    runtime = prefix / "lib/carbonyl"
    library = runtime / "libtermi-carbonyl-exe.so"
    assert launcher.is_symlink() and launcher.resolve() == runtime / "headless_shell"
    assert not library.exists() and (runtime / "icudtl.dat").is_file()
    sources = Path(__file__).resolve().parent
    ndk = Path(os.environ["ANDROID_HOME"]) / "ndk/30.0.16248370"
    clang = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang"
    subprocess.run([clang, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
                    sources / "carbonyl_launcher.c", "-o", library, "-ldl"], check=True)
    launcher.unlink()
    shutil.copyfile(sources / "carbonyl_launcher.sh", launcher)
    launcher.chmod(0o755)
    control = tree / "DEBIAN/control"
    previous = control.read_text()
    assert previous.count("\nVersion: 0.0.3-4\n") == 1 and version == "0.0.3-5"
    control.write_text(previous.replace("\nVersion: 0.0.3-4\n", f"\nVersion: {version}\n"))
    checksums = tree / "DEBIAN/md5sums"
    if checksums.exists():
        changed = {f.relative_to(tree).as_posix(): f for f in (launcher, library)}
        lines = [line for line in checksums.read_text().splitlines() if line.split(maxsplit=1)[1] not in changed]
        for name, path in changed.items():
            lines.append(f"{hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()}  {name}")
        checksums.write_text("\n".join(lines) + "\n")
    new_name = f"carbonyl_{version}_aarch64.deb"
    new_path = output / new_name
    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", tree, new_path], check=True)
    verified = work / "carbonyl-verified"
    subprocess.run(["dpkg-deb", "--raw-extract", new_path, verified], check=True)
    original = work / "carbonyl-original"
    subprocess.run(["dpkg-deb", "--raw-extract", old_path, original], check=True)

    def files(root):
        result = {}
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[name] = ("link", os.readlink(path))
            elif path.is_file():
                result[name] = (stat.S_IMODE(path.stat().st_mode), digest(path))
        return result

    before, after = files(original), files(verified)
    changed_paths = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    expected = {f.relative_to(tree).as_posix() for f in (control, launcher, library)}
    if checksums.exists():
        expected.add(checksums.relative_to(tree).as_posix())
    assert changed_paths == expected and files(tree) == after
    old_path.unlink()
    staged[new_name] = dict(old, file=new_name, original_file=new_name, asset=new_name,
                            bytes=new_path.stat().st_size, sha256=digest(new_path),
                            control=old["control"].replace("Version: 0.0.3-4\n", f"Version: {version}\n"))
    return dict(base_file=old_name, base_sha256=old["sha256"], new_file=new_name,
                new_sha256=staged[new_name]["sha256"], changed_paths=sorted(changed_paths),
                launcher_sha256=digest(launcher), source_sha256=digest(sources / "carbonyl_launcher.c"),
                compiler=subprocess.check_output([clang, "--version"], text=True).splitlines()[0])


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
    repair = None
    if config.get("repair_carbonyl"):
        repair = repack_carbonyl(work, output, staged, config["roots"]["carbonyl"])
    index = subprocess.check_output(["dpkg-scanpackages", "--multiversion", ".", "/dev/null"], cwd=output)
    index = re.sub(rb"(?m)^Filename: \./", b"Filename: ", index)
    (output / "Packages").write_bytes(index)
    manifest = dict(source=tag, pins=pins, roots=config["roots"], packages=list(staged.values()),
                    index_sha256=hashlib.sha256(index).hexdigest(), status="unsigned-test-staging")
    if repair:
        manifest["carbonyl_repair"] = repair
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
