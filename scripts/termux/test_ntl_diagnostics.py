import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import NTL_GMP_DIAGNOSTICS
from catalog_repairs import apply as apply_catalog_repairs
from catalog_repairs import NTL_CXX_HEADERS
from prepare import replace_once

BASH = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')


class NtlDiagnosticsTest(unittest.TestCase):
    def test_recipe_is_patched_once_and_keeps_loader_and_diagnostics(self):
        original = ('TERMUX_PKG_VERSION="11.6.0"\nTERMUX_PKG_DEPENDS="libgf2x, libgmp"\ntermux_step_pre_configure() {\n'
                    '\ttermux_proot_run=(termux-proot-run env LD_PRELOAD= LD_LIBRARY_PATH=)\n}\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / 'build.sh'
            recipe.write_text(original)
            calls = []
            def change(name, edit, tree='packages'):
                if name == 'libntl':
                    calls.append(name)
                    # Exercise the real preparation contract: callbacks always
                    # read the immutable upstream recipe, and patch a live file.
                    replace_once(recipe, original, edit(original))
            def hook(text, name, body):
                return text.replace(name + '() {', name + '() {\n' + body)
            apply_catalog_repairs(change, hook,
                                  {'arpack-ng': 'termux_step_pre_configure() {\nfixture runtime\n}'})
            self.assertEqual(['libntl'], calls)
            prepared = recipe.read_text()
            self.assertIn('/opt/aosp:/system', prepared)
            self.assertIn('TERMI_NTL_GMP_PROBE_LOG', prepared)
            self.assertEqual(1, prepared.count("<<'TERMI_NTL_GMP_DIAGNOSTICS'"))
            self.assertIn('TERMUX_PKG_DEPENDS="libgf2x, libgmp, libc++"', prepared)
            self.assertIn('-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1', prepared)

    @unittest.skipUnless(BASH, 'Bash required')
    def test_matching_cxx_headers_keep_existing_compiler_flags(self):
        result = subprocess.run([BASH, '-c', 'TERMUX_PREFIX=/prefix; CXXFLAGS="-Oz -pthread";\n'
                                 + NTL_CXX_HEADERS + '\nprintf "%s" "$CXXFLAGS"'],
                                capture_output=True, text=True, check=True)
        self.assertEqual('-Oz -pthread -nostdinc++ -I/prefix/include/c++/v1', result.stdout)

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
