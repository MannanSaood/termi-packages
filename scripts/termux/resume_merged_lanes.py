"""Dispatch explicitly requested lanes only after a verified merge is published."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from seed import digest
from verify_restart import verify

REPO = 'MannanSaood/termi-packages'


def eligible(request, prior, runs):
    lane = request['lane']
    predecessor = str(request['after_run'])
    if not re.fullmatch(r'lane-[0-7]-of-8', lane) or not predecessor.isdigit():
        raise ValueError('Invalid explicit lane restart')
    title = 'Termi full-catalog - ' + lane
    verify(prior, title)
    return not any(r['displayTitle'] == title and int(r['databaseId']) > int(predecessor)
                   for r in runs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    requests = manifest.get('restart_lanes', [])
    if not requests:
        return
    if manifest['repository'] != REPO or not re.fullmatch(r'candidate-[0-9]+-[0-9]+-0', args.tag):
        raise ValueError('Unexpected repository or merged seed')
    if len({r['lane'] for r in requests}) != len(requests):
        raise ValueError('Duplicate requested lanes')
    inventory = json.loads((args.output/'inventory.json').read_text())
    ledger = json.loads((args.output/'catalog-ledger.json').read_text())
    plan = json.loads((args.output/'catalog-plan.json').read_text())
    built = {n for n, v in ledger['recipes'].items() if v['status'] == 'built'}
    if ledger['identity'][0] != plan['identity'] or built != {v['recipe'] for v in inventory['packages']}:
        raise ValueError('Merged identity or completed inventory differs')
    if not set(manifest['required_completed_recipes']) <= built:
        raise ValueError('Required preserved completions absent')
    # Publication must have succeeded, not merely local merge creation.
    subprocess.run(['gh', 'release', 'view', args.tag, '--repo', REPO], check=True, stdout=subprocess.DEVNULL)
    def read(command):
        return json.loads(subprocess.check_output(command, text=True))
    for request in requests:
        prior = read(['gh', 'run', 'view', str(request['after_run']), '--repo', REPO,
                      '--json', 'status,displayTitle,jobs'])
        runs = read(['gh', 'run', 'list', '--repo', REPO, '--workflow', 'termi_free_packages.yml',
                     '--limit', '1000', '--json', 'databaseId,displayTitle,status'])
        if not eligible(request, prior, runs):
            print('Skip already replaced lane:', request['lane'], flush=True)
            continue
        command = ['gh', 'workflow', 'run', 'termi_free_packages.yml', '--repo', REPO, '--ref', 'main',
                   '-f', 'mode=full-catalog', '-f', 'recipes='+request['lane'],
                   '-f', 'after_run='+str(request['after_run']), '-f', 'seed_tag='+args.tag]
        for key, name in [('inventory', 'inventory.json'), ('ledger', 'catalog-ledger.json'), ('plan', 'catalog-plan.json')]:
            command += ['-f', 'seed_'+key+'_sha256='+digest(args.output/name)]
        subprocess.run(command, check=True)
        print('Dispatched preserved lane:', request['lane'], 'seed:', args.tag, flush=True)


if __name__ == '__main__':
    main()
