import unittest
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import resume_merged_lanes
from resume_merged_lanes import eligible, fresh_recipe_eligible
from verify_restart import REQUIRED


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(lane='lane-2-of-8', after_run=100)
        self.prior = dict(status='completed', displayTitle='Termi full-catalog - lane-2-of-8',
                          jobs=[dict(steps=[dict(name=n, conclusion='success') for n in REQUIRED])])

    def test_saved_lane_can_restart(self):
        self.assertTrue(eligible(self.request, self.prior, []))

    def test_any_newer_replacement_prevents_duplicate(self):
        for status in ['queued', 'in_progress', 'completed']:
            self.assertFalse(eligible(self.request, self.prior, [dict(databaseId=101,
                displayTitle=self.prior['displayTitle'], status=status)]))

    def test_incomplete_export_rejected(self):
        self.prior['jobs'][0]['steps'][0]['conclusion'] = 'failure'
        with self.assertRaises(ValueError):
            eligible(self.request, self.prior, [])


    def test_wrong_lane_rejected(self):
        self.request['lane'] = 'lane-1-of-8'
        with self.assertRaises(ValueError):
            eligible(self.request, self.prior, [])


class FreshRecipeTests(unittest.TestCase):
    def setUp(self):
        self.plan = dict(recipes=dict(app=dict(dependencies=['provider'])))
        self.ledger = dict(recipes=dict(app=dict(status='pending'), provider=dict(status='built')))

    def test_ready_recipe_can_start(self):
        self.assertTrue(fresh_recipe_eligible('app', self.plan, self.ledger, []))

    def test_completed_recipe_is_not_rebuilt(self):
        self.ledger['recipes']['app']['status'] = 'built'
        self.assertFalse(fresh_recipe_eligible('app', self.plan, self.ledger, []))

    def test_failure_cannot_be_implicitly_retried(self):
        self.ledger['recipes']['app']['status'] = 'failed'
        with self.assertRaises(ValueError):
            fresh_recipe_eligible('app', self.plan, self.ledger, [])

    def test_missing_dependency_is_rejected(self):
        self.ledger['recipes']['provider']['status'] = 'pending'
        with self.assertRaises(ValueError):
            fresh_recipe_eligible('app', self.plan, self.ledger, [])

    def test_any_prior_focused_attempt_prevents_duplicate(self):
        for status in ['completed', 'queued', 'in_progress']:
            self.assertFalse(fresh_recipe_eligible('app', self.plan, self.ledger,
                [dict(displayTitle='Termi packages - app', status=status)]))

    def test_twenty_job_bound_includes_merge_and_other_jobs(self):
        rows = [dict(displayTitle='other', status='in_progress') for _ in range(20)]
        self.assertFalse(fresh_recipe_eligible('app', self.plan, self.ledger, rows))
        self.assertTrue(fresh_recipe_eligible('app', self.plan, self.ledger, rows[:-1]))

    def full_dispatch(self, remote='source'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps(dict(repository='MannanSaood/termi-packages',
                required_completed_recipes=['provider'], start_recipes=['app'])))
            self.plan['identity'] = 'graph'
            self.ledger['identity'] = ['graph']
            (root/'catalog-plan.json').write_text(json.dumps(self.plan))
            (root/'catalog-ledger.json').write_text(json.dumps(self.ledger))
            (root/'inventory.json').write_text(json.dumps(dict(packages=[dict(recipe='provider')])))
            dispatched = []

            def read(command, **_):
                if command[1:3] == ['run', 'list']:
                    return json.dumps([dict(databaseId=123, displayTitle='Termi packages - app',
                        status='queued', headSha='source')] if dispatched else [])
                if 'git/ref/heads/main' in command[-1]:
                    return json.dumps(dict(object=dict(sha=remote)))
                return json.dumps(dict(total_count=0, workflow_runs=[]))

            def run(command, **_):
                if command[1:3] == ['workflow', 'run']:
                    dispatched.append(command)
                return subprocess.CompletedProcess(command, 0)

            with patch.object(sys, 'argv', ['resume', '--manifest', str(manifest),
                    '--output', str(root), '--tag', 'candidate-99-1-0']), \
                    patch.dict(os.environ, dict(GITHUB_SHA='source')), \
                    patch.object(resume_merged_lanes.subprocess, 'check_output', side_effect=read), \
                    patch.object(resume_merged_lanes.subprocess, 'run', side_effect=run):
                if remote != 'source':
                    with self.assertRaisesRegex(ValueError, 'Source changed'):
                        resume_merged_lanes.main()
                    self.assertEqual([], dispatched)
                    return
                resume_merged_lanes.main()
            self.assertEqual(1, len(dispatched))
            self.assertIn('seed_tag=candidate-99-1-0', dispatched[0])
            self.assertTrue(any(v.startswith('seed_inventory_sha256=') for v in dispatched[0]))
            self.assertEqual('source', json.loads((root/'start-app.json').read_text())['source'])
            self.assertEqual(123, json.loads((root/'started-app.json').read_text())['databaseId'])

    def test_verified_merge_dispatches_once_with_pins_and_run_readback(self):
        self.full_dispatch()

    def test_source_change_defers_dispatch(self):
        self.full_dispatch(remote='new-source')


class ReadRetryTests(unittest.TestCase):
    def test_transient_api_failure_recovers_without_any_mutation(self):
        failure = subprocess.CalledProcessError(1, ['gh', 'run', 'list'])
        with patch.object(resume_merged_lanes.subprocess, 'check_output',
                          side_effect=[failure, '{"runs": []}']) as query, \
                patch.object(resume_merged_lanes.subprocess, 'run') as mutation, \
                patch.object(resume_merged_lanes.time, 'sleep'):
            self.assertEqual(dict(runs=[]), resume_merged_lanes.read(['gh', 'run', 'list']))
        self.assertEqual(2, query.call_count)
        mutation.assert_not_called()

    def test_repeated_failure_is_bounded_and_fail_closed(self):
        failure = subprocess.TimeoutExpired(['gh', 'run', 'list'], 120)
        with patch.object(resume_merged_lanes.subprocess, 'check_output', side_effect=failure) as query, \
                patch.object(resume_merged_lanes.time, 'sleep'):
            with self.assertRaises(subprocess.TimeoutExpired):
                resume_merged_lanes.read(['gh', 'run', 'list'])
        self.assertEqual(3, query.call_count)

    def test_invalid_json_is_not_treated_as_an_empty_inventory(self):
        with patch.object(resume_merged_lanes.subprocess, 'check_output', return_value='bad'):
            with self.assertRaises(json.JSONDecodeError):
                resume_merged_lanes.read(['gh', 'run', 'list'])
