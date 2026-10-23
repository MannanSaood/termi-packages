#!/usr/bin/env python3
"""Export the pinned upstream dependency graph and recipe/channel identities."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import heapq

CHANNELS = {"packages": "main", "root-packages": "root", "x11-packages": "x11"}


def order_and_cycles(dependencies):
    """Bounded graph diagnostics; never break a source dependency silently."""
    reverse = {name: set() for name in dependencies}
    for name, required in dependencies.items():
        for dep in required:
            reverse[dep].add(name)
    remaining = {name: len(required) for name, required in dependencies.items()}
    ready = [name for name, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for dependent in sorted(reverse[name]):
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                heapq.heappush(ready, dependent)
    seen, finish = set(), []
    for start in sorted(dependencies):
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            name, done = stack.pop()
            if done:
                finish.append(name)
            elif name not in seen:
                seen.add(name)
                stack.append((name, True))
                stack.extend((dep, False) for dep in sorted(dependencies[name], reverse=True) if dep not in seen)
    seen, cycles = set(), []
    for start in reversed(finish):
        if start in seen:
            continue
        stack, group = [start], []
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            group.append(name)
            stack.extend(reverse[name] - seen)
        if len(group) > 1 or start in dependencies[start]:
            cycles.append(sorted(group))
    return order + sorted(set(dependencies) - set(order)), sorted(cycles)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_plan(root, lock, source, patches):
    if (lock["application_id"] != "com.terminal.nextgen"
            or lock["prefix"] != "/data/data/com.terminal.nextgen/files/usr"
            or lock["architecture"] != "aarch64" or source["commit"] != lock["commit"]):
        raise ValueError("Graph requires the pinned Termi ARM64 configuration")
    previous = Path.cwd()
    previous_arch = os.environ.get("TERMUX_ARCH")
    try:
        os.chdir(root)
        os.environ["TERMUX_ARCH"] = lock["architecture"]
        spec = importlib.util.spec_from_file_location("termi_pinned_buildorder", root / "scripts/buildorder.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        packages = module.read_packages_from_directories([], False, True)
        unique = {pkg.name: pkg for pkg in packages.values()}
        parent_dependencies = {}
        for name, package in unique.items():
            dependencies = set(package.deps)
            for sub in package.subpkgs:
                dependencies.update(sub.deps)
            # Upstream explicitly removes runtime-only metapackage edges from
            # source-build order. Keep them in Debian metadata for APT instead.
            dependencies.difference_update(package.antideps)
            parent_dependencies[name] = {packages[dep].name for dep in dependencies if packages[dep].name != name}
        ordered_names, cycles = order_and_cycles(parent_dependencies)
        cycle_names = {name for group in cycles for name in group}
        order = [unique[name] for name in ordered_names]
        recipes, provided = {}, {}
        for rank, package in enumerate(order):
            path = Path(package.dir)
            channel = CHANNELS[path.parts[0]]
            parents = sorted(parent_dependencies[package.name])
            recipes[package.name] = dict(path=path.as_posix(), channel=channel, dependencies=parents,
                                         rank=rank, initial_status="blocked-cycle" if package.name in cycle_names else "pending")
            for name, parent in packages.items():
                if parent is package:
                    provided[name] = dict(recipe=package.name, channel=channel)
            for sub in package.subpkgs:
                provided[sub.name] = dict(recipe=package.name, channel=channel)
        for directory, channel in CHANNELS.items():
            for script in sorted((root / directory).glob("*/build.sh")):
                name = script.parent.name
                if name in recipes:
                    continue
                excluded = module.parse_build_file_excluded_arches(str(script))
                if lock["architecture"] not in excluded:
                    raise ValueError("Recipe omitted without an architecture exclusion: " + name)
                recipes[name] = dict(path=script.relative_to(root).parent.as_posix(), channel=channel,
                                     dependencies=[], rank=None, initial_status="excluded-architecture")
        identity = dict(lock=lock, source=source, patches=patches,
                        graph_sha256=digest(Path(__file__).resolve()),
                        upstream_graph_sha256=digest(root / "scripts/buildorder.py"))
        return dict(schema=1, identity=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                    configuration=identity, recipes=recipes, provided_packages=provided, cycle_groups=cycles)
    finally:
        os.chdir(previous)
        if previous_arch is None:
            os.environ.pop("TERMUX_ARCH", None)
        else:
            os.environ["TERMUX_ARCH"] = previous_arch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def load(name):
        return json.loads((args.metadata / name).read_text())
    plan = create_plan(args.root.resolve(), load("upstream.lock.json"), load("source.json"), load("patches.json"))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(plan, stream, indent=2)
        stream.write("\n")
    print(json.dumps(dict(recipes=len(plan["recipes"]), provided_packages=len(plan["provided_packages"]),
                         excluded=sum(r["initial_status"] == "excluded-architecture" for r in plan["recipes"].values()))))


if __name__ == "__main__":
    main()
