"""Prove successful roots in a mixed focused batch without approving failures."""
import re


def ledger_from_progress(plan, inventory, progress, receipt, base_pins, run, run_id):
    jobs = run.get('jobs', [])
    if len(jobs) != 1 or run.get('status') not in ('in_progress', 'completed'):
        raise ValueError('Unexpected selected source run lifecycle')
    steps = {s['name']: s for s in jobs[0].get('steps', [])}
    compile_step = steps.get('Compile bounded source batch with time left for checkpoint export', {})
    export = steps.get('Publish candidate evidence to Releases, never the live APT repo', {})
    if (compile_step.get('status') != 'completed'
            or compile_step.get('conclusion') not in ('success', 'failure')
            or export.get('status') != 'completed' or export.get('conclusion') != 'success'):
        raise ValueError('Source compilation and candidate publication must have finished')
    counts = progress.get('counts', {})
    if (progress.get('schema') != 1 or progress.get('scope') != 'requested-roots'
            or progress.get('approved') is not False or progress.get('current')
            or not counts or set(counts) - {'built', 'failed'}
            or any(type(v) is not int or v < 0 for v in counts.values())
            or sum(counts.values()) != progress.get('total_recipes')):
        raise ValueError('Require a final focused-root outcome snapshot')
    completed = progress.get('completed_recipes', [])
    if not isinstance(completed, list) or len(set(completed)) != len(completed):
        raise ValueError('Invalid successful root list')
    completed = set(completed)
    if not completed or len(completed) != counts.get('built', 0):
        raise ValueError('Successful root count differs')
    failures = progress.get('failures', [])
    if (len(failures) != counts.get('failed', 0)
            or len({f['recipe'] for f in failures}) != len(failures)
            or any(f['recipe'] in completed or f['recipe'] not in plan['recipes']
                   or f.get('status') != 'failed' or type(f.get('exit_code')) is not int
                   or f['exit_code'] == 0 for f in failures)):
        raise ValueError('Incomplete or conflicting failed root history')
    if (set(base_pins) != {'inventory', 'ledger', 'plan'}
            or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in base_pins.values())
            or receipt.get('schema') != 1
            or receipt.get('status') != 'source-build-cache-not-runtime-approval'
            or receipt.get('new_graph_identity') != plan['identity']
            or any(receipt.get(field) != base_pins.get(key) for field, key in
                   [('inventory_sha256', 'inventory'), ('ledger_sha256', 'ledger'), ('graph_sha256', 'plan')])):
        raise ValueError('Seed provenance differs from the explicitly pinned base')
    seeded = set(receipt.get('recipes', []))
    built = seeded | completed
    if not built <= plan['recipes'].keys():
        raise ValueError('Unlisted completed source parent')
    records = inventory.get('packages', [])
    if {r['recipe'] for r in records} != built:
        raise ValueError('Candidate includes unproven parents or lacks completed outputs')
    # Failed roots never gain successful status merely because some archive
    # exists. Only final successful roots or byte-identical adopted outputs do.
    original = {r['file']: r for r in receipt.get('packages', [])}
    if {r['recipe'] for r in original.values()} != seeded:
        raise ValueError('Seed receipt has incomplete parent outputs')
    for record in records:
        if record['recipe'] not in completed and record != original.get(record['file']):
            raise ValueError('Adopted output changed without successful root evidence')
    result = dict(identity=[plan['identity'], 'verified-selected-roots-' + str(run_id)],
                recipes={n: dict(status='built' if n in built else r['initial_status'], attempts=0)
                         for n, r in plan['recipes'].items()},
                verified_completed_roots=sorted(completed), base_seed_pins=base_pins,
                candidate_only=True)
    for failure in failures:
        if failure['recipe'] not in built:
            result['recipes'][failure['recipe']] = dict(status='failed', attempts=1, exit_code=failure['exit_code'])
    return result
