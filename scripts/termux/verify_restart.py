"""Fail closed unless the prior same-lane run fully preserved its outputs."""
import json
import os
import re
import subprocess

REQUIRED = {
    "Publish candidate evidence to Releases, never the live APT repo",
    "Preserve catalog or interrupted build as streamed release checkpoint",
}

def verify(run, title):
    if run.get("status") != "completed" or run.get("displayTitle") != title:
        raise ValueError("Prior same-lane run is not completed")
    jobs = run.get("jobs", [])
    if len(jobs) != 1:
        raise ValueError("Unexpected prior job structure")
    steps = {s["name"]: s.get("conclusion") for s in jobs[0].get("steps", [])}
    if any(steps.get(name) != "success" for name in REQUIRED):
        raise ValueError("Prior candidate/checkpoint export did not succeed; retain outputs and investigate")

if __name__ == "__main__":
    run_id = os.environ["AFTER_RUN"]
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("Invalid predecessor run")
    data = json.loads(subprocess.check_output([
        "gh", "run", "view", run_id, "--repo", "MannanSaood/termi-packages",
        "--json", "status,displayTitle,jobs"], text=True))
    verify(data, os.environ["EXPECTED_TITLE"])
    print("Prior candidate and checkpoint exports verified")
