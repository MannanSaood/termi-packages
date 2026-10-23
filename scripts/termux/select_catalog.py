#!/usr/bin/env python3
"""Resolve the owner-approved runtime closure using isolated host APT."""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
import assemble_bootstrap as bootstrap
from catalog_policy import PROFILES, policy_for

ROOTS = ["apt", "bash", "termux-exec", "termux-tools", "hello", "git", "gh"]


def selected_versions(resolution):
    selected = {}
    for name, version in re.findall(r"^Inst ([a-z0-9+.-]+)(?::aarch64)?(?: \[[^\]]+\])? \(([^ )]+) ", resolution, re.M):
        if name in selected and selected[name] != version:
            raise ValueError("APT selected conflicting versions")
        selected[name] = version
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--packages", nargs="+", default=[], help="Additional source-built package roots")
    parser.add_argument("--profile", choices=PROFILES, default="proof")
    args = parser.parse_args()
    policy = policy_for(args.profile)
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name) for name in args.packages):
        parser.error("Invalid package name")
    roots = list(dict.fromkeys(ROOTS + args.packages))
    args.work.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=False)
    # Disposable closure-resolution authority never becomes distribution trust.
    gpg, env = bootstrap.signing_key(args.work)
    key = args.work / "resolution.gpg"
    key.write_bytes(subprocess.check_output(gpg + ["--export"], env=env))
    repo = args.work / "repository"
    packages = sorted(args.debs.glob("*.deb"))
    bootstrap.repository(repo, packages, gpg, env)
    # The older proof selector intentionally excludes Git. Keep its isolated
    # APT configuration while explicitly resolving the newly approved roots.
    apt = args.work / "apt"
    for directory in ["etc/apt.conf.d", "etc/preferences.d", "state/lists/partial", "cache/archives/partial", "log"]:
        (apt / directory).mkdir(parents=True)
    (apt / "state/status").write_text("")
    (apt / "etc/apt.conf").write_text("")
    (apt / "etc/sources.list").write_text(f"deb [arch=aarch64 signed-by={key}] file:{repo} proof main\n")
    config = apt / "isolated.conf"
    config.write_text(f'Dir::Etc "{apt / "etc"}";\n#clear APT::Architectures;\n'
                      'APT::Architecture "aarch64";\nAPT::Architectures { "aarch64"; };\n')
    env = {**env, "APT_CONFIG": str(config), "LC_ALL": "C"}
    command = ["apt-get", "-o", f"Dir::State={apt / 'state'}", "-o", f"Dir::State::status={apt / 'state/status'}",
               "-o", f"Dir::Cache={apt / 'cache'}", "-o", f"Dir::Log={apt / 'log'}",
               "-o", "APT::Sandbox::User=builder", "-o", "Acquire::Languages=none",
               "-o", "APT::Update::Error-Mode=any", "-o", "Acquire::AllowInsecureRepositories=false",
               "-o", "APT::Get::AllowUnauthenticated=false"]
    subprocess.run(command + ["update"], env=env, check=True)
    resolution = subprocess.check_output(command + ["--simulate", "--no-install-recommends", "install", *roots], env=env, text=True)
    (args.output / "runtime-resolution.txt").write_text(resolution)
    versions = selected_versions(resolution)
    names = set(versions)
    if not set(roots) <= names or not 7 <= len(names) <= policy.records:
        raise ValueError("Incomplete or excessive runtime closure")
    pool = args.output / "pool"
    pool.mkdir()
    records = []
    for package in packages:
        fields = subprocess.check_output(["dpkg-deb", "-f", str(package), "Package", "Version", "Architecture"], text=True)
        control = dict(line.split(": ", 1) for line in fields.strip().splitlines())
        if control["Package"] not in names or control["Version"] != versions[control["Package"]]:
            continue
        filename = package.name.replace(":", "%3A")
        if any(r["name"] == control["Package"] for r in records):
            raise ValueError("Multiple versions in candidate output")
        shutil.copyfile(package, pool / filename)
        records.append(dict(name=control["Package"], version=control["Version"], architecture=control["Architecture"],
                            file=filename, sha256=bootstrap.digest(package)))
    if {r["name"] for r in records} != names:
        raise ValueError("Missing selected package")
    (args.output / "approved-packages.json").write_text(json.dumps(
        dict(schema=1, publication_profile=args.profile, roots=roots, packages=sorted(records, key=lambda r: r["name"])), indent=2) + "\n")
    shutil.rmtree(args.work / "gnupg")


if __name__ == "__main__":
    main()
