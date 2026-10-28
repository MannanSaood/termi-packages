#!/usr/bin/env python3
"""Combine explicitly pinned own-source Releases on a disposable free runner."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from parallel_catalog import merge
from seed import pinned, digest
from selected_candidate import ledger_from_progress


def run(command):
    return subprocess.check_output(command,text=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--tag",required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text())
    repository=manifest["repository"]
    if repository!="MannanSaood/termi-packages" or not re.fullmatch(r"candidate-[0-9]+-[0-9]+-0",args.tag):
        raise ValueError("Require fixed own package repository and candidate tag")
    if json.loads(run(["gh","repo","view",repository,"--json","visibility"]))["visibility"]!="PUBLIC":
        raise ValueError("Free public repository required")
    inputs=[]
    source_pins=[]
    alternates=[]
    accumulator=None
    for index,entry in enumerate(manifest["candidates"]):
        tag=entry["tag"]
        if not re.fullmatch(r"candidate-[0-9]+-[0-9]+-0",tag):
            raise ValueError("Untrusted candidate tag")
        directory=Path("build/merge-inputs")/str(index)
        directory.mkdir(parents=True)
        subprocess.run(["gh","release","download",tag,"--repo",repository,"--pattern","*.json",
                        "--pattern","*.deb","--pattern","*.tar","--dir",str(directory)],check=True)
        inventory=json.loads(pinned(directory,"inventory.json",entry["inventory_sha256"]).read_text())
        plan_path=pinned(directory,"catalog-plan.json",entry["plan_sha256"])
        plan=json.loads(plan_path.read_text())
        ledger_pin=entry.get("ledger_sha256")
        if entry.get("selected_success"):
            run_id=tag.split("-")[1]
            status=json.loads(run(["gh","run","view",run_id,"--repo",repository,"--json","status,conclusion"]))
            if status!={"status":"completed","conclusion":"success"}:
                raise ValueError("Selected candidate is not a completed successful source run")
            parents={r["recipe"] for r in inventory["packages"]}
            if not parents <= plan["recipes"].keys():
                raise ValueError("Unlisted successful source recipe")
            ledger=dict(identity=[plan["identity"],"successful-source-run-"+run_id],
                        recipes={n:dict(status="built" if n in parents else r["initial_status"],attempts=0)
                                 for n,r in plan["recipes"].items()},verified_successful_run=run_id)
            path=directory/"catalog-ledger.json";path.write_text(json.dumps(ledger,indent=2)+"\n")
            ledger_pin=digest(path)
        elif entry.get('selected_progress'):
            proof=entry['selected_progress']
            progress=json.loads(pinned(directory,'progress.json',proof['progress_sha256']).read_text())
            receipt=json.loads(pinned(directory,'seed-provenance.json',proof['seed_provenance_sha256']).read_text())
            run_id=tag.split('-')[1]
            status=json.loads(run(['gh','run','view',run_id,'--repo',repository,'--json','status,conclusion,jobs']))
            ledger=ledger_from_progress(plan,inventory,progress,receipt,proof['base_seed'],status,run_id)
            ledger['selected_proof_pins']=proof
            path=directory/'catalog-ledger.json';path.write_text(json.dumps(ledger,indent=2)+'\n')
            ledger_pin=digest(path)
        if not ledger_pin:
            raise ValueError("Explicit catalog ledger pin required")
        candidate=[str(directory),entry["inventory_sha256"],ledger_pin,entry["plan_sha256"]]
        source_pins.append(dict(inventory=candidate[1],ledger=candidate[2],plan=candidate[3]))
        inputs.append(candidate)
        # Download/expand only one new candidate at a time. Keeping all lane
        # bundles AND extracted copies exhausted the standard runner's disk.
        next_output=Path('build/merge-working')/str(index)
        _, inventory=merge(inputs,next_output,prefer_first_compatible=manifest.get("duplicate_policy")=="prefer-first-compatible-parent")
        alternates.extend(inventory.get('alternate_builds',[]))
        # Reclaim only these explicitly created disposable input directories,
        # and only AFTER every chosen output has been hash-verified/copied.
        shutil.rmtree(directory)
        if accumulator is not None:
            shutil.rmtree(accumulator)
        accumulator=next_output
        inputs=[[str(accumulator),*[digest(accumulator/name) for name in
                 ['inventory.json','catalog-ledger.json','catalog-plan.json']]]]
    if accumulator is None:
        raise ValueError('At least one candidate required')
    accumulator.rename(args.output)
    # Preserve original candidate provenance, not hashes of deleted temporary
    # accumulators, and retain alternate builds from every incremental merge.
    inventory['source_candidates']=source_pins
    inventory['alternate_builds']=alternates
    (args.output/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    ledger=json.loads((args.output/'catalog-ledger.json').read_text())
    ledger['source_candidates']=source_pins
    (args.output/'catalog-ledger.json').write_text(json.dumps(ledger,indent=2)+'\n')
    missing = set(manifest.get("required_completed_recipes", [])) - {r["recipe"] for r in inventory["packages"]}
    if missing:
        raise ValueError("Merge dropped required completed recipes: " + ", ".join(sorted(missing)))
    # Reclaim only this disposable job's known download directory after the
    # verified chosen archives and their input provenance have been preserved.
    shutil.rmtree(Path("build/merge-inputs"))
    bundles=[]; archive=None; size=0
    try:
        for record in inventory["packages"]:
            path=args.output/record["file"]
            if archive is None or size+path.stat().st_size > 512*1024**2:
                if archive:archive.close()
                bundle=args.output/f"packages-{len(bundles):04d}.tar";bundles.append(bundle)
                archive=tarfile.open(bundle,"w");size=0
            archive.add(path,arcname=path.name,recursive=False);size+=path.stat().st_size
    finally:
        if archive:archive.close()
    files=[args.output/n for n in ["inventory.json","catalog-ledger.json","catalog-plan.json"]]+bundles
    subprocess.run(["gh","release","create",args.tag,*map(str,files),"--repo",repository,"--title",args.tag,
                    "--notes","Verified compatible Termi candidate union; alternate build hashes retained. Unsigned, not runtime approved.",
                    "--prerelease","--latest=false"],check=True)
    print(json.dumps(dict(tag=args.tag,pins={n:digest(args.output/n) for n in ["inventory.json","catalog-ledger.json","catalog-plan.json"]})),flush=True)


if __name__=="__main__":
    main()
