import unittest
from verify_restart import verify, REQUIRED

class RestartTest(unittest.TestCase):
    def sample(self):
        return {"status":"completed", "displayTitle":"lane", "jobs":[{"steps":[{"name":n,"conclusion":"success"} for n in REQUIRED]}]}
    def test_saved_failed_compile_allowed(self):
        verify(self.sample(), "lane")
    def test_export_failure_rejected(self):
        run=self.sample();run["jobs"][0]["steps"][0]["conclusion"]="failure"
        with self.assertRaises(ValueError): verify(run,"lane")
    def test_running_rejected(self):
        run=self.sample();run["status"]="in_progress"
        with self.assertRaises(ValueError): verify(run,"lane")
    def test_other_lane_rejected(self):
        with self.assertRaises(ValueError): verify(self.sample(),"other lane")
    def test_missing_exports_rejected(self):
        run=self.sample();run["jobs"][0]["steps"]=[]
        with self.assertRaises(ValueError): verify(run,"lane")
    def test_stale_checkpoint_step_requires_real_checkpoint_and_completed_job(self):
        run = self.sample()
        job = run['jobs'][0]
        job['status'] = 'completed'
        step = next(s for s in job['steps'] if s['name'].startswith('Preserve'))
        step.update(status='in_progress', conclusion=None)
        with self.assertRaises(ValueError): verify(run, 'lane')
        verify(run, 'lane', checkpoint_verified=True)
        job['status'] = 'in_progress'
        with self.assertRaises(ValueError): verify(run, 'lane', checkpoint_verified=True)
        job['status'] = 'completed'
        for outcome in ['failure', 'skipped', 'cancelled']:
            step['conclusion'] = outcome
            with self.assertRaises(ValueError): verify(run, 'lane', checkpoint_verified=True)
        step['conclusion'] = None
        next(s for s in job['steps'] if s['name'].startswith('Publish'))['conclusion'] = None
        with self.assertRaises(ValueError): verify(run, 'lane', checkpoint_verified=True)
