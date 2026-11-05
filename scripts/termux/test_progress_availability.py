import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import publish_progress

class ProgressAvailability(unittest.TestCase):
    def execute(self, exit_code, remote, visibility='PUBLIC'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'compiler-ran';command=[sys.executable,'-c',"from pathlib import Path;import sys;Path(sys.argv[1]).write_text('ran');sys.exit(int(sys.argv[2]))",str(marker),str(exit_code)]
            argv=['publish_progress','--repository','MannanSaood/termi-packages','--tag','progress-123-1','--build-dir',str(root/'build'),'--',*command]
            with patch.object(sys,'argv',argv),patch.object(publish_progress.subprocess,'check_output',return_value=json.dumps(dict(visibility=visibility)).encode()),patch.object(publish_progress,'capture',return_value=None),patch.object(publish_progress,'gh',side_effect=remote),contextlib.redirect_stdout(io.StringIO()):
                if visibility!='PUBLIC':
                    with self.assertRaisesRegex(ValueError,'free public'):publish_progress.main()
                    self.assertFalse(marker.exists());return
                with self.assertRaises(SystemExit)as raised:publish_progress.main()
                self.assertEqual(exit_code,raised.exception.code)
            self.assertTrue(marker.is_file())
            self.assertTrue((root/'live-progress/progress.json').is_file())
    def unavailable(self,*args):raise subprocess.CalledProcessError(1,['gh','release'])
    def test_release_creation_outage_still_runs_successful_compiler(self):self.execute(0,self.unavailable)
    def test_compiler_failure_is_not_hidden_by_release_outage(self):self.execute(7,self.unavailable)
    def test_rate_limit_does_not_stop_compiler(self):
        def limited(*args):raise publish_progress.RateLimited(3600)
        self.execute(0,limited)
    def test_existing_run_tag_is_reused_without_create(self):
        calls=[]
        def available(*args):calls.append(args);return None
        self.execute(0,available)
        self.assertFalse(any('create'in c for c in calls))
    def test_private_repository_still_fails_before_compilation(self):self.execute(0,self.unavailable,'PRIVATE')

if __name__=='__main__':unittest.main()
