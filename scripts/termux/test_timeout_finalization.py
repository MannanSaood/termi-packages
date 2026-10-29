import subprocess
import unittest
from unittest.mock import patch

from build import attach_builder


class TimeoutFinalizationTests(unittest.TestCase):
    def test_normal_failure_does_not_send_a_stop_signal(self):
        with patch('build.subprocess.run',return_value=subprocess.CompletedProcess([],1)) as run:
            self.assertEqual(1,attach_builder('builder-id',18600))
        self.assertEqual(1,run.call_count)

    def test_timeout_allows_export_but_never_reports_success(self):
        with patch('build.subprocess.run',side_effect=[
                subprocess.TimeoutExpired('docker start',18600),
                subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],0)]) as run:
            self.assertEqual(124,attach_builder('builder-id',18600))
        self.assertEqual(['docker','kill','--signal=SIGTERM','builder-id'],run.call_args_list[1].args[0])
        self.assertEqual(['docker','wait','builder-id'],run.call_args_list[2].args[0])
        self.assertEqual(300,run.call_args_list[2].kwargs['timeout'])

    def test_hung_finalization_is_bounded_and_still_unsuccessful(self):
        with patch('build.subprocess.run',side_effect=[
                subprocess.TimeoutExpired('docker start',18600),
                subprocess.CompletedProcess([],0),subprocess.TimeoutExpired('docker wait',300)]):
            self.assertEqual(124,attach_builder('builder-id',18600))
