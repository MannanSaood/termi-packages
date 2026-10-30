import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from catalog_repairs import octave_fortran_recipe, OCTAVE_CONFIG_DIAGNOSTICS


RUNTIME = '''\tlocal work="$TERMUX_PKG_TMPDIR/termi-fortran"
\texport FC="$work/termi-flang"
\t( TERMUX_PKG_EXTRA_CONFIGURE_ARGS="-DLLVM_ENABLE_RUNTIMES=flang-rt" )
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_Fortran_COMPILER=$wrapper -DCMAKE_Fortran_FLAGS=-fPIC"
'''
RECIPE = '''TERMUX_PKG_LICENSE="GPL-3.0"
TERMUX_PKG_DEPENDS="arpack-ng, libc++, suitesparse, sundials"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="--with-x --with-qt=6 --enable-fortran-calling-convention=f2c"
termux_step_pre_configure() {
\ttermux_setup_flang
\tlocal flang_libs_dir="old-runtime"
\texport F77="$FC"
\tln -sf $flang_libs_dir/libFortranRuntime.a $TERMUX_PKG_TMPDIR/_deps/
\tln -sf $flang_libs_dir/libFortranDecimal.a $TERMUX_PKG_TMPDIR/_deps/
\texport ac_cv_f77_libs="-L$TERMUX_PKG_TMPDIR/_deps -l:libFortranRuntime.a -l:libFortranDecimal.a"
\tLDFLAGS+=" -Wl,-rpath,$TERMUX_PREFIX/lib/octave/$TERMUX_PKG_VERSION"
\texport LIBS="-landroid-complex-math -L$_libgcc_path -l:$_libgcc_name"
\texport PATH="$TERMUX_PREFIX/opt/qt6/cross/bin:$PATH"
}
'''
BASH = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')


class OctaveFortranTest(unittest.TestCase):
    def test_source_runtime_replaces_legacy_archives_without_changing_features(self):
        text = octave_fortran_recipe(RECIPE, RUNTIME)
        self.assertNotIn('libFortranRuntime.a', text)
        self.assertNotIn('libFortranDecimal.a', text)
        self.assertNotIn('CMAKE_Fortran_COMPILER', text)
        self.assertIn('-DLLVM_ENABLE_RUNTIMES=flang-rt', text)
        self.assertIn('export F77="$FC"', text)
        self.assertIn('$work/runtime-build/flang-rt/lib/libflang_rt.runtime.a', text)
        self.assertIn('-lc++ -landroid-execinfo', text)
        self.assertEqual(1, text.split('TERMUX_PKG_DEPENDS=')[1].splitlines()[0].count('libc++'))
        for line in RECIPE.splitlines():
            if line.startswith(('TERMUX_PKG_EXTRA_CONFIGURE_ARGS=', '\tLDFLAGS+=', '\texport LIBS=', '\texport PATH=')):
                self.assertIn(line, text)
        self.assertIn('Apache-2.0', text)

    def test_upstream_setup_drift_fails_closed(self):
        with self.assertRaises(AssertionError):
            octave_fortran_recipe(RECIPE.replace('libFortranRuntime.a', 'different.a'), RUNTIME)
        with self.assertRaises(AssertionError):
            octave_fortran_recipe(RECIPE, 'different runtime setup')

    @unittest.skipUnless(BASH, 'Bash required')
    def test_configure_failure_exposes_bounded_log_and_remains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config.log').write_text('old-hidden-prefix\n' + 'x' * 70000 + '\nactual linker error\n')
            script = root / 'probe.sh'
            script.write_text(OCTAVE_CONFIG_DIAGNOSTICS + '\nTERMUX_PKG_SRCDIR="$1"\ntermux_step_configure_autotools_failure_hook\n')
            failed = subprocess.run([BASH, script.as_posix(), root.as_posix()], capture_output=True, text=True)
            self.assertNotEqual(0, failed.returncode)
            self.assertIn('TERMI_OCTAVE_CONFIG_LOG', failed.stderr)
            self.assertIn('actual linker error', failed.stderr)
            self.assertNotIn('old-hidden-prefix', failed.stderr)
            self.assertLess(len(failed.stderr), 66000)
