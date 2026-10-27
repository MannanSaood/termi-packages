import unittest
from resume_merged_lanes import eligible
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
