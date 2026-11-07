import subprocess
import unittest
from unittest.mock import Mock
from seed_download import download


class DownloadTests(unittest.TestCase):
    def test_protocol_error_retries_and_overwrites_partial_download(self):
        runner=Mock(side_effect=[subprocess.CompletedProcess([],1,'','stream PROTOCOL_ERROR'),
                                 subprocess.CompletedProcess([],0,'','')])
        sleep=Mock();download('candidate-123-1-0','seed',runner,sleep)
        self.assertEqual(2,runner.call_count)
        self.assertIn('--clobber',runner.call_args.args[0])
        self.assertIn('http2client=0',runner.call_args.kwargs['env']['GODEBUG'])
        sleep.assert_called_once_with(5)

    def test_semantic_errors_are_not_retried(self):
        runner=Mock(return_value=subprocess.CompletedProcess([],1,'','release not found'))
        with self.assertRaises(subprocess.CalledProcessError):download('candidate-123-1-0','seed',runner,Mock())
        self.assertEqual(1,runner.call_count)

    def test_release_asset_http_500_retries(self):
        failure = subprocess.CompletedProcess([], 1, '', 'HTTP 500 (https://api.github.com/repos/MannanSaood/termi-packages/releases/assets/721217062)')
        runner = Mock(side_effect=[failure, subprocess.CompletedProcess([], 0, '', '')])
        sleep = Mock()

        download('candidate-42390022557-1-0', 'seed', runner, sleep)

        self.assertEqual(2, runner.call_count)
        self.assertIn('--clobber', runner.call_args.args[0])
        sleep.assert_called_once_with(5)

    def test_retry_budget_is_bounded(self):
        runner=Mock(return_value=subprocess.CompletedProcess([],1,'','connection reset'))
        with self.assertRaises(subprocess.CalledProcessError):download('candidate-123-1-0','seed',runner,Mock())
        self.assertEqual(3,runner.call_count)
