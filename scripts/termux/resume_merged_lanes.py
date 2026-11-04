"""Dispatch explicitly requested lanes only after a verified merge is published."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

from seed import digest
from verify_restart import verify

REPO = 'MannanSaood/termi-packages'


def read(command):
    """Retry read-only GitHub requests; never retry workflow mutations here."""
    for attempt in range(3):
        try:
            return json.loads(subprocess.check_output(command, text=True, timeout=120))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def fresh_recipe_eligible(name, plan, ledger, runs):
    if not re.fullmatch(r'[a-z0-9][a-z0-9+._-]*', name) or name not in plan['recipes']:
        raise ValueError('Invalid explicit source recipe')
    built = {n for n, r in ledger['recipes'].items() if r['status'] == 'built'}
    if name in built:
        return False
    if ledger['recipes'][name]['status'] != 'pending' or not set(plan['recipes'][name]['dependencies']) <= built:
        raise ValueError('Fresh recipe must be pending with all dependencies completed')
    # Any focused attempt, even a failed one, requires a new explicit audit.
    if any(r['displayTitle'] == 'Termi packages - ' + name for r in runs):
        return False
    return sum(r['status'] != 'completed' for r in runs) < 20


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
    fresh = manifest.get('start_recipes', [])
    if not requests and not fresh:
        return
    if manifest['repository'] != REPO or not re.fullmatch(r'candidate-[0-9]+-[0-9]+-0', args.tag):
        raise ValueError('Unexpected repository or merged seed')
    if len({r['lane'] for r in requests}) != len(requests):
        raise ValueError('Duplicate requested lanes')
    if len(set(fresh)) != len(fresh) or len(fresh) > 20:
        raise ValueError('Duplicate or excessive fresh source recipes')
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
    for name in fresh:
        runs = read(['gh', 'run', 'list', '--repo', REPO, '--limit', '1000',
                     '--json', 'databaseId,displayTitle,status'])
        for status in ['queued', 'in_progress']:
            active = read(['gh', 'api', f'repos/{REPO}/actions/runs?status={status}&per_page=100'])
            if active['total_count'] > 100:
                raise ValueError('Active inventory exceeds safe pagination bound')
            runs += [dict(databaseId=r['id'], displayTitle=r['display_title'], status=r['status'])
                     for r in active['workflow_runs']]
        # API snapshots overlap history; count each workflow only once.
        runs = list({r['databaseId']: r for r in runs}.values())
        if not fresh_recipe_eligible(name, plan, ledger, runs):
            print('Skip already attempted/built recipe or full capacity:', name, flush=True)
            continue
        source = os.environ.get('GITHUB_SHA', '')
        remote = read(['gh', 'api', f'repos/{REPO}/git/ref/heads/main'])['object']['sha']
        if not source or source != remote:
            raise ValueError('Source changed since verified merge; defer fresh dispatch')
        command = ['gh', 'workflow', 'run', 'termi_free_packages.yml', '--repo', REPO,
                   '--ref', 'main', '-f', 'mode=packages', '-f', 'recipes='+name,
                   '-f', 'seed_tag='+args.tag]
        for key, filename in [('inventory', 'inventory.json'), ('ledger', 'catalog-ledger.json'), ('plan', 'catalog-plan.json')]:
            command += ['-f', 'seed_'+key+'_sha256='+digest(args.output/filename)]
        audit = args.output/('start-'+name+'.json')
        if audit.exists():
            raise ValueError('Existing dispatch audit; reconcile before retry')
        audit.write_text(json.dumps(dict(source=source, command=command), indent=2)+'\n')
        print('Dispatch audit:', audit.read_text(), flush=True)
        subprocess.run(command, check=True)
        for attempt in range(18):
            latest = read(['gh', 'run', 'list', '--repo', REPO, '--limit', '1000',
                           '--json', 'databaseId,displayTitle,status,headSha'])
            found = [r for r in latest if r['displayTitle'] == 'Termi packages - '+name
                     and r['headSha'] == source]
            if found:
                if len(found) != 1:
                    raise ValueError('Multiple focused attempts; inspect before continuing')
                (args.output/('started-'+name+'.json')).write_text(json.dumps(found[0], indent=2)+'\n')
                print('Dispatched fresh source recipe:', name, 'run:', found[0]['databaseId'],
                      'seed:', args.tag, flush=True)
                break
            time.sleep(5)
        else:
            raise RuntimeError('Dispatch outcome unknown; reconcile audit without repeating')


if __name__ == '__main__':
    main()
