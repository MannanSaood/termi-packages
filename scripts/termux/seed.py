#!/usr/bin/env python3
"""Reuse only hash-pinned, source-compatible Termi outputs; never stock binaries.

Host: verify an explicit prior source-run inventory/ledger/graph and prepare a
small input cache. Builder: reverify, unpack data only, never run maintainer
scripts, and retain provenance for every reused archive.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import posixpath
import shutil
import subprocess
import tarfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pinned(directory, name, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Explicit seed metadata hashes are required")
    # GitHub normalizes '%' in uploaded asset names to '.', including portable
    # Debian epoch filenames. Names select candidates only; SHA256 is authority.
    aliases = {name, name.replace("%", ".")}
    paths = [p for p in directory.iterdir() if any(p.name == alias or re.fullmatch(r"[0-9]{4}-" + re.escape(alias), p.name) for alias in aliases)]
    matches = [p for p in paths if p.is_file() and not p.is_symlink() and digest(p) == expected]
    if not matches:
        raise ValueError("Missing/ambiguous hash-pinned seed metadata: " + name)
    # Workflow evidence may contain graph-only and runtime copies with exactly
    # the same bytes. Multiple SHA256-identical copies are not conflicting input.
    matches.sort(key=lambda p:p.name)
    if name.endswith(".json") and matches[0].stat().st_size > 32 * 1024**2:
        raise ValueError("Oversized seed metadata")
    return matches[0]


def compatibility(old, new, ledger):
    if old["configuration"]["lock"] != new["configuration"]["lock"] or old["configuration"]["source"] != new["configuration"]["source"]:
        raise ValueError("Seed app/prefix/toolchain/source configuration differs")
    for key in ["graph_sha256", "upstream_graph_sha256"]:
        if old["configuration"].get(key) != new["configuration"].get(key):
            raise ValueError("Seed dependency resolver changed")
    if ledger["identity"][0] != old["identity"]:
        raise ValueError("Seed ledger and source graph differ")
    paths = {r["path"]: name for plan in [old, new] for name, r in plan["recipes"].items()}
    def patches(plan):
        return {p["path"]: p["after_sha256"] for p in plan["configuration"]["patches"]}
    before, after = patches(old), patches(new)
    changed = set()
    for path in before.keys() | after.keys():
        if before.get(path) == after.get(path):
            continue
        parent = "/".join(path.split("/")[:2])
        if parent in paths:
            changed.add(paths[parent])
        elif path != "scripts/build/termux_step_finish_build.sh":
            # Sole operational exception: a reviewed post-package scratch hook.
            # Any other toolchain/prefix/build-script change invalidates seeds.
            raise ValueError("Global build patch changed; cannot adopt source outputs: " + path)
    invalid = set(changed)
    while True:
        expanded = invalid | {name for plan in [old, new] for name, r in plan["recipes"].items()
                              if set(r["dependencies"]) & invalid}
        if expanded == invalid:
            break
        invalid = expanded
    allowed = {name for name, entry in ledger["recipes"].items()
               if entry["status"] == "built" and name in new["recipes"] and name not in invalid}
    return allowed, invalid


def compatible_failures(old, new, ledger):
    """Retain failures and disk blockers until inputs change or retry is explicit."""
    _, invalid = compatibility(old, new, ledger)
    return {name: entry for name, entry in ledger["recipes"].items()
            if name in new["recipes"] and name not in invalid
            and (entry["status"] == "failed" or
                 (entry["status"] == "interrupted" and entry.get("exit_code") == 75
                  and entry.get("compile_resume_available") is False))}


def expand_bundles(raw, inventory):
    """Unpack only inventory-pinned regular Debian members; never tar.extract."""
    expected = {r["file"]:r["sha256"] for r in inventory["packages"]}
    total = 0
    for bundle in sorted(raw.glob("*.tar")):
        if bundle.is_symlink():
            raise ValueError("Aliased package bundle")
        with tarfile.open(bundle,mode="r|") as archive:
            for member in archive:
                name = member.name
                if not member.isfile() or not re.fullmatch(r"[A-Za-z0-9%+._~-]+\.deb",name) or name not in expected:
                    raise ValueError("Unlisted/unsafe package bundle member")
                total += member.size
                if member.size > 2 * 1024**3 or total > 16 * 1024**3:
                    raise ValueError("Package bundle exceeds bounded source-cache budget")
                target = raw / name
                if target.exists() or target.is_symlink():
                    if target.is_symlink() or digest(target) != expected[name]:
                        raise ValueError("Existing bundled package differs")
                    continue
                temporary = raw / (name + ".seed-partial")
                if temporary.exists() or temporary.is_symlink():
                    raise ValueError("Unexpected partial source-cache member")
                try:
                    with archive.extractfile(member) as source, temporary.open("xb") as destination:
                        shutil.copyfileobj(source,destination,1024*1024)
                    if digest(temporary) != expected[name]:
                        raise ValueError("Bundled package hash differs from pinned inventory")
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)


def dependency_roots(mode, requested):
    # Focused builds need their complete dependency closure, not thousands of
    # unrelated installed packages and duplicate archives to republish. The
    # full seed stays published; the existing host/builder checks pin the subset.
    return sorted(set(requested)) if mode == 'packages' else []


def selected_recipes(plan, allowed, roots):
    if not roots:
        return allowed
    closure = set(roots)
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name not in plan['recipes']:
            raise ValueError('Unknown dependency seed root')
        for dependency in plan['recipes'][name]['dependencies']:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    if not closure - set(roots) <= allowed:
        raise ValueError('Dependency seed requires every compatible completed dependency')
    return closure & allowed


def prepare(raw, context, new_graph, output, inventory_hash, ledger_hash, graph_hash, roots=None):
    inventory_path = pinned(raw, "inventory.json", inventory_hash)
    ledger_path = pinned(raw, "catalog-ledger.json", ledger_hash)
    graph_path = pinned(raw, "catalog-plan.json", graph_hash)
    inventory, ledger, old = [json.loads(p.read_text()) for p in [inventory_path, ledger_path, graph_path]]
    expand_bundles(raw,inventory)
    new = json.loads(new_graph.read_text())
    for name, key in [("upstream.lock.json", "lock"), ("source.json", "source"), ("patches.json", "patches")]:
        if json.loads((context / name).read_text()) != new["configuration"][key]:
            raise ValueError("New seed plan does not match the prepared source context")
    allowed, invalid = compatibility(old, new, ledger)
    allowed = selected_recipes(new, allowed, roots)
    records = [r for r in inventory["packages"] if r["recipe"] in allowed]
    present = {r["recipe"] for r in records}
    if allowed != present:
        raise ValueError("A completed seed recipe has no recorded outputs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Seed output must be new/empty")
    (output / "pool").mkdir(parents=True)
    for record in records:
        name = record["file"]
        if not re.fullmatch(r"[A-Za-z0-9%+._~-]+\.deb", name):
            raise ValueError("Unsafe seed archive name")
        path = pinned(raw, name, record["sha256"])
        shutil.copyfile(path, output / "pool" / name)
    for name, path in [("old-inventory.json", inventory_path), ("old-ledger.json", ledger_path), ("old-plan.json", graph_path)]:
        shutil.copyfile(path, output / name)
    receipt = dict(schema=1, inventory_sha256=inventory_hash, ledger_sha256=ledger_hash, graph_sha256=graph_hash,
                   new_graph_identity=new["identity"], recipes=sorted(allowed), invalidated=sorted(invalid),
                   packages=records, failures=compatible_failures(old, new, ledger), status="source-build-cache-not-runtime-approval")
    if roots:
        receipt['dependency_roots'] = sorted(roots)
    (output / "seed.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(dict(reused_recipes=len(allowed), reused_archives=len(records), invalidated_recipes=len(invalid))), flush=True)


def stage_output_archives(context):
    """Put each verified archive in its final image location only once.

    Used before hashing both workflow and builder contexts. Metadata stays in
    seed/, while Docker copies archives directly to the retained output pool.
    This avoids a second full writable-layer copy during native seed import.
    """
    context = Path(context)
    seed = context / 'seed'
    if not (seed / 'seed.json').is_file():
        return 0
    receipt = json.loads((seed / 'seed.json').read_text())
    pool, output = seed / 'pool', context / 'seed-output'
    if output.exists() or output.is_symlink() or pool.is_symlink():
        raise ValueError('Seed output staging requires a new regular directory')
    records = receipt['packages']
    files, names = set(), set()
    for record in records:
        original = record['original_file']
        if not re.fullmatch(r'[A-Za-z0-9%+:._~-]+\.deb', original) or original in names:
            raise ValueError('Unsafe or duplicate staged seed output filename')
        names.add(original)
        path = pool / record['file']
        if path.parent != pool or path.is_symlink() or digest(path) != record['sha256']:
            raise ValueError('Staged source-built seed bytes changed')
        files.add(path)
    if set(pool.iterdir()) != files:
        raise ValueError('Unlisted seed staging files')
    dockerfile = context / 'Dockerfile'
    source = dockerfile.read_text()
    anchor = 'COPY --chown=builder:builder seed/ /home/builder/seed/\n'
    if source.count(anchor) != 1:
        raise ValueError('Seed Docker copy anchor changed')
    total = sum(path.stat().st_size for path in files)
    output.mkdir()
    for record in records:
        (pool / record['file']).replace(output / record['original_file'])
    pool.rmdir()
    dockerfile.write_text(source.replace(anchor, anchor +
        'COPY --chown=builder:builder seed-output/ /home/builder/termux-packages/output/\n'),
        encoding='utf-8', newline='\n')
    print(f'TERMI_PRELOADED_SEED_ARCHIVES {len(records)} bytes={total}', flush=True)
    return total


def verified_archive(seed, root, record):
    original = record['original_file']
    if not re.fullmatch(r'[A-Za-z0-9%+:._~-]+\.deb', original):
        raise ValueError('Unsafe seed output filename')
    path = seed / 'pool' / record['file']
    if not path.exists() and not path.is_symlink():
        path = root / 'output' / original
    if path.is_symlink() or digest(path) != record['sha256']:
        raise ValueError('Source-built seed bytes changed')
    return path


def resolve_payload_alias(path, readlink=os.readlink):
    """Resolve package links without following the builder's /system shim.

    Android /system is a platform namespace. The Linux image redirects it to
    its own AOSP build tree; that host-only redirect must not affect either
    direct platform links or relative links that eventually reach /system.
    Other links are still followed and checked against the Termi prefix.
    """
    source = PurePosixPath(str(path))
    if not source.is_absolute():
        raise ValueError("Source-cache alias must be absolute")
    # POSIX preserves exactly two leading slashes as a distinct anchor, but
    # the Android/Linux package namespace uses the same root for / and //.
    pending = list(source.parts[1:])
    resolved = PurePosixPath("/")
    hops = 0
    while pending:
        part = pending.pop(0)
        if part == "..":
            resolved = resolved.parent
            continue
        candidate = resolved / part
        if candidate == PurePosixPath("/system"):
            normalized = PurePosixPath(posixpath.normpath(str(candidate.joinpath(*pending))))
            if normalized.is_relative_to(PurePosixPath("/system")):
                return normalized
            # /system/../outside is not a platform alias.
            pending = list(normalized.parts[1:])
            resolved = PurePosixPath("/")
            continue
        try:
            link = PurePosixPath(readlink(str(candidate)))
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENOTDIR, errno.EINVAL):
                raise
            resolved = candidate
            continue
        hops += 1
        if hops > 40:
            raise ValueError("Unsafe source-cache payload alias cycle")
        if link.is_absolute():
            resolved = PurePosixPath("/")
            pending = list(link.parts[1:]) + pending
        else:
            pending = list(link.parts) + pending
    return resolved


def unpack(path, prefix):
    process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(path)], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or "\\" in member.name or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError("Unsafe source-cache payload entry")
                destination = Path("/").joinpath(*name.parts)
                # Replace a leaf alias; never resolve it as the write target.
                # Alternative loaders reverse their .so/.so.1 links. Following
                # the old leaf can write through it or produce a transient loop.
                target = destination.parent.resolve() / destination.name
                if member.isdir() and (target == Path("/") or target in prefix.parents):
                    continue
                if not target.is_relative_to(prefix):
                    raise ValueError("Seed package payload is outside the Termi prefix")
                if target.is_symlink():
                    if member.isdir():
                        raise ValueError("Seed directory would traverse an existing alias")
                    target.unlink()
                if member.issym() or member.islnk():
                    link = PurePosixPath(member.linkname)
                    linked = (Path(str(link)) if link.is_absolute() else Path("/").joinpath(*link.parts)) if member.islnk() else (Path(str(link)) if link.is_absolute() else target.parent / str(link))
                    linked = resolve_payload_alias(linked)
                    platform_alias = member.issym() and linked.is_relative_to(PurePosixPath("/system"))
                    if not linked.is_relative_to(PurePosixPath(str(prefix))) and not platform_alias:
                        raise ValueError(f"Unsafe source-cache payload alias: {member.name} -> {linked}")
                # Namespace and alias destinations were checked above. The data
                # filter rejects legitimate absolute Android-prefix symlinks;
                # tar_filter retains those while still checking member paths.
                archive.extract(member, path="/", filter=tarfile.tar_filter)
        if process.wait() != 0:
            raise ValueError("Seed data archive extraction failed")
    finally:
        if process.poll() is None:
            process.terminate(); process.wait()


def validate_prefix_aliases(prefix):
    """Audit the final cache, after all alternative-package overlays settle."""
    aliases = 0
    for directory, folders, files in os.walk(prefix, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            if not path.is_symlink():
                continue
            linked = resolve_payload_alias(path)
            if not (linked.is_relative_to(PurePosixPath(str(prefix))) or
                    linked.is_relative_to(PurePosixPath("/system"))):
                raise ValueError(f"Unsafe final source-cache alias: {path} -> {linked}")
            aliases += 1
    return aliases


def install(seed, root, metadata, artifacts, roots=None):
    from catalog_graph import create_plan
    load = lambda name: json.loads((metadata / name).read_text())
    new = create_plan(root, load("upstream.lock.json"), load("source.json"), load("patches.json"))
    receipt = json.loads((seed / "seed.json").read_text())
    old = json.loads(pinned(seed, "old-plan.json", receipt["graph_sha256"]).read_text())
    ledger = json.loads(pinned(seed, "old-ledger.json", receipt["ledger_sha256"]).read_text())
    inventory = json.loads(pinned(seed, "old-inventory.json", receipt["inventory_sha256"]).read_text())
    allowed, _ = compatibility(old, new, ledger)
    if receipt.get('dependency_roots', []) != sorted(roots or []):
        raise ValueError('Dependency seed roots differ from requested build')
    allowed = selected_recipes(new, allowed, roots)
    expected = [r for r in inventory["packages"] if r["recipe"] in allowed]
    if receipt["new_graph_identity"] != new["identity"] or receipt["packages"] != expected or set(receipt["recipes"]) != allowed:
        raise ValueError("Source-cache receipt changed or source compatibility differs")
    if receipt.get("failures", {}) != compatible_failures(old, new, ledger):
        raise ValueError("Source-cache failure evidence differs")
    existing = artifacts / "seed-provenance.json"
    if existing.exists():
        if json.loads(existing.read_text()) != receipt:
            raise ValueError("Existing builder seed receipt differs")
        print("TERMI_SOURCE_SEED already present in verified checkpoint; not replayed", flush=True)
        return
    prefix = Path("/data/data/com.terminal.nextgen/files/usr")
    prefix.mkdir(parents=True, exist_ok=True)
    markers = Path("/data/data/.built-packages")
    markers.mkdir(parents=True, exist_ok=True)
    versions = {}
    preloaded = 0
    for record in expected:
        path = verified_archive(seed, root, record)
        preloaded += path == root / 'output' / record['original_file']
        fields = subprocess.check_output(["dpkg-deb", "-f", str(path), "Package", "Version", "Architecture"], text=True)
        control = dict(line.split(": ", 1) for line in fields.strip().splitlines())
        original = dict(line.split(": ", 1) for line in record["control"].strip().splitlines())
        if any(control[k] != original[k] for k in ["Package", "Version", "Architecture"]) or control["Architecture"] not in ("aarch64", "all"):
            raise ValueError("Source-built seed control identity changed")
        versions.setdefault(record["recipe"], set()).add(control["Version"])
    if any(len(v) != 1 for v in versions.values()):
        raise ValueError("Ambiguous seed parent version")
    (root / "output").mkdir(exist_ok=True)
    for record in expected:
        path = verified_archive(seed, root, record)
        try:
            unpack(path, prefix)
        except (ValueError, OSError, tarfile.TarError) as error:
            raise ValueError(f"Seed import failed in {record['file']}: {error}") from error
        original = record["original_file"]
        if Path(original).name != original or "/" in original or "\\" in original:
            raise ValueError("Unsafe seed output filename")
        destination = root / "output" / original
        if path != destination:
            shutil.copyfile(path, destination)
        control = dict(line.split(": ", 1) for line in record["control"].strip().splitlines())
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", control["Package"]):
            raise ValueError("Unsafe seed marker name")
        (markers / control["Package"]).write_text(control["Version"] + "\n")
    for name, values in versions.items():
        (markers / name).write_text(next(iter(values)) + "\n")
    artifacts.mkdir(exist_ok=True)
    aliases = validate_prefix_aliases(prefix)
    (artifacts / "seed-validation.json").write_text(json.dumps(dict(
        status="PASS", recipes=len(allowed), archives=len(expected), aliases_checked=aliases,
        new_graph_identity=new["identity"], inventory_sha256=receipt["inventory_sha256"],
        ledger_sha256=receipt["ledger_sha256"], plan_sha256=receipt["graph_sha256"],
        preloaded_archives=preloaded,
        maintainer_scripts_executed=False), indent=2) + "\n")
    (artifacts / "seed-provenance.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"TERMI_SOURCE_SEED recipes={len(allowed)} archives={len(expected)} preloaded={preloaded}; no maintainer scripts executed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument('--mode', default='full-catalog')
    parser.add_argument('--requested', nargs='*', default=[])
    args = parser.parse_args()
    install(args.seed, args.root, args.metadata, args.artifacts,
            dependency_roots(args.mode, args.requested))


if __name__ == "__main__":
    main()
