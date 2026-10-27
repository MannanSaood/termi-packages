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
