from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import NTL_GMP_DIAGNOSTICS


class NtlDiagnosticsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('perl') and shutil.which('tail'), 'Perl and tail required')
    def test_failure_exposes_bounded_compiler_log_and_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'DoConfig'
            # Exact conditional/fatal text from upstream v11.6.0 DoConfig.
            source.write_text('sub CheckGMP { return $ARGV[0] eq "pass"; }\n'
                              '   if (!CheckGMP()) {\n'
                              '         die "Error: NTL_GMP_LIP set but GMP not available -- set DEF_PREFIX or GMP_PREFIX to point to location of GMP\\n";\n'
                              '   }\n')
            subprocess.run([sys.executable, '-c', NTL_GMP_DIAGNOSTICS, str(source)], check=True)
            (root / 'OneCompilerOutput.log').write_text('hidden-old-prefix\n' + 'x' * 70000 + '\nactual compiler failure\n')
            failed = subprocess.run(['perl', str(source), 'fail'], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(0, failed.returncode)
            self.assertIn('TERMI_NTL_GMP_PROBE_LOG', failed.stderr)
            self.assertIn('actual compiler failure', failed.stderr)
            self.assertNotIn('hidden-old-prefix', failed.stderr)
            self.assertIn('NTL_GMP_LIP set but GMP not available', failed.stderr)
            self.assertLess(len(failed.stderr), 66000)
            passed = subprocess.run(['perl', str(source), 'pass'], cwd=root, capture_output=True, text=True)
            self.assertEqual(0, passed.returncode)
            self.assertEqual('', passed.stderr)

    def test_source_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DoConfig'
            source.write_text('changed upstream code')
            result = subprocess.run([sys.executable, '-c', NTL_GMP_DIAGNOSTICS, str(source)], capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual('changed upstream code', source.read_text())
