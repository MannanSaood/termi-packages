#!/usr/bin/env python3
"""Dispatch isolated free lanes and merge only pinned compatible Termi outputs.

Each lane has its own GitHub run/container/prefix/checkpoint/progress page.
Merging candidates never signs them, runs package scripts, or approves them.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from seed import compatibility, digest, pinned, expand_bundles


def merge(inputs, output, prefer_first_compatible=False):
    if output.exists():
        raise ValueError("Merge destination must be new")
    sources = []
    for directory, inventory_pin, ledger_pin, plan_pin in inputs:
        directory = Path(directory)
        inventory, ledger, plan = [json.loads(pinned(directory,name,pin).read_text()) for name,pin in
            [("inventory.json",inventory_pin),("catalog-ledger.json",ledger_pin),("catalog-plan.json",plan_pin)]]
        sources.append((directory,inventory,ledger,plan,dict(inventory=inventory_pin,ledger=ledger_pin,plan=plan_pin)))
        expand_bundles(directory,inventory)
    if not sources:
        raise ValueError("At least one pinned candidate required")
    target = sources[0][3]
    records, paths, built, origins, variants = {}, {}, set(), [], []
    failures = {}
    for directory, inventory, ledger, plan, pins in sources:
        allowed, invalid = compatibility(plan,target,ledger)
        failures.update({name: entry for name, entry in ledger["recipes"].items()
                         if (entry["status"] == "failed" or
                             (entry["status"] == "interrupted" and entry.get("exit_code") == 75
                              and entry.get("compile_resume_available") is False))
                         and name in target["recipes"] and name not in invalid})
        present = set()
        for record in inventory["packages"]:
            if record["recipe"] not in allowed:
                continue
            name = record["file"]
            if not re.fullmatch(r"[A-Za-z0-9%+._~-]+\.deb",name):
                raise ValueError("Unsafe merged archive name")
            path = pinned(directory,name,record["sha256"])
            if name in records and records[name] != record:
                first = records[name]
                if not prefer_first_compatible or any(first.get(k) != record.get(k) for k in ["control","recipe","channel","original_file"]):
                    raise ValueError("Conflicting candidate outputs; review required: " + name)
                # Explicit policy chooses one entire compatible parent build,
                # never treats independently rebuilt bytes as identical.
                variants.append(dict(file=name,chosen_sha256=first["sha256"],alternate_sha256=record["sha256"],source=pins))
                present.add(record["recipe"])
                continue
            if record["recipe"] in built and name not in records:
                raise ValueError("Compatible parent output set differs across candidates")
            records[name],paths[name] = record,path
            present.add(record["recipe"])
        if allowed != present:
            raise ValueError("Completed parent missing recorded output")
        built.update(allowed)
        origins.append(pins)
    output.mkdir(parents=True)
    for name,path in paths.items():
        shutil.copyfile(path,output/name)
    merged = dict(schema=1,identity=[target["identity"],"verified-candidate-union"],
                  recipes={name:dict(status="built" if name in built else recipe["initial_status"],attempts=0)
                           for name,recipe in target["recipes"].items()}, source_candidates=origins)
    for name, entry in failures.items():
        if name not in built:
            merged["recipes"][name] = entry
    inventory = dict(status="candidate-not-signed-not-device-verified",packages=[records[n] for n in sorted(records)],
                     source_candidates=origins,alternate_builds=variants,
                     duplicate_policy="prefer-first-compatible-parent" if prefer_first_compatible else "identical-only")
    for name,value in [("catalog-plan.json",target),("catalog-ledger.json",merged),("inventory.json",inventory)]:
        (output/name).write_text(json.dumps(value,indent=2)+"\n")
    pins = {name:digest(output/name) for name in ["inventory.json","catalog-ledger.json","catalog-plan.json"]}
    print(json.dumps(dict(unique_completed_recipes=len(built),unique_archives=len(records),pins=pins,approved=False)))
    return merged, inventory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    dispatch=sub.add_parser("dispatch")
    dispatch.add_argument("--repository",default="MannanSaood/termi-packages")
    dispatch.add_argument("--lanes",type=int,choices=list(range(2,9)),default=4)
    dispatch.add_argument("--seed-tag",required=True)
    for name in ["inventory","ledger","plan"]:
        dispatch.add_argument("--"+name+"-sha256",required=True)
    combine=sub.add_parser("merge")
    combine.add_argument("--input",action="append",nargs=4,required=True,
                         metavar=("DIRECTORY","INVENTORY_SHA256","LEDGER_SHA256","PLAN_SHA256"))
    combine.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="merge":
        merge(args.input,args.output)
        return
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",args.repository) or not re.fullmatch(r"candidate-[0-9]+-[0-9]+-[0-9]+",args.seed_tag):
        parser.error("Require a fixed repository and candidate tag")
    for name in ["inventory","ledger","plan"]:
        if not re.fullmatch(r"[0-9a-f]{64}",getattr(args,name+"_sha256")):
            parser.error("Explicit candidate hashes required")
    visibility=json.loads(subprocess.check_output(["gh","repo","view",args.repository,"--json","visibility"]))
    if visibility["visibility"]!="PUBLIC":
        raise ValueError("Parallel free pipeline requires a public repository")
    for index in range(args.lanes):
        command=["gh","workflow","run","termi_free_packages.yml","--repo",args.repository,"--ref","main",
                 "-f","mode=full-catalog","-f",f"recipes=lane-{index}-of-{args.lanes}","-f","seed_tag="+args.seed_tag]
        for name in ["inventory","ledger","plan"]:
            command += ["-f",f"seed_{name}_sha256="+getattr(args,name+"_sha256")]
        subprocess.run(command,check=True)
        print(f"Dispatched lane-{index}-of-{args.lanes}",flush=True)


if __name__=="__main__":
    main()
