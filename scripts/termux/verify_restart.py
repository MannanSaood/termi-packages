"""Fail closed unless the prior same-lane run fully preserved its outputs."""
import json
import os
import re
import subprocess
import hashlib

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


def verify_checkpoint_manifest(manifest, assets):
    if (manifest.get('schema') != 1 or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('input_identity', ''))
            or not isinstance(manifest.get('parts'), list) or not 1 <= len(manifest['parts']) <= 256):
        raise ValueError('Prior checkpoint has no complete manifest')
    by_name = {asset['name']: asset for asset in assets}
    for index, record in enumerate(manifest['parts']):
        name = f'checkpoint-{index:04d}.gz.part'
        if (record.get('file') != name or type(record.get('bytes')) is not int
                or not 0 < record['bytes'] <= 1024**3
                or not re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', ''))):
            raise ValueError('Invalid prior checkpoint part record')
        asset = by_name.get(name, {})
        if (asset.get('size') != record['bytes'] or asset.get('state') != 'uploaded'
                or asset.get('digest') not in (None, 'sha256:' + record['sha256'])):
            raise ValueError('Prior checkpoint part missing or differs from manifest')


def verify_remote_checkpoint(run_id):
    repository = 'MannanSaood/termi-packages'
    prior = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/runs/{run_id}']))
    attempt = prior['run_attempt']
    if type(attempt) is not int or attempt < 1:
        raise ValueError('Invalid prior checkpoint attempt')
    tag = f'checkpoint-{run_id}-{attempt}'
    release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/releases/tags/{tag}']))
    assets = release['assets']
    header = next((a for a in assets if a['name'] == 'checkpoint.json'), {})
    if not 0 < header.get('size', 0) <= 128 * 1024 or header.get('state') != 'uploaded':
        raise ValueError('Prior checkpoint manifest is absent; step success alone is insufficient')
    raw = subprocess.check_output(['gh', 'release', 'download', tag, '--repo', repository,
                                   '--pattern', 'checkpoint.json', '--output', '-'])
    if len(raw) != header['size'] or header.get('digest') not in (None, 'sha256:' + hashlib.sha256(raw).hexdigest()):
        raise ValueError('Prior checkpoint manifest differs from uploaded asset')
    verify_checkpoint_manifest(json.loads(raw), assets)

if __name__ == "__main__":
    run_id = os.environ["AFTER_RUN"]
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("Invalid predecessor run")
    data = json.loads(subprocess.check_output([
        "gh", "run", "view", run_id, "--repo", "MannanSaood/termi-packages",
        "--json", "status,displayTitle,jobs"], text=True))
    verify(data, os.environ["EXPECTED_TITLE"])
    verify_remote_checkpoint(run_id)
    print("Prior candidate and checkpoint exports verified")
