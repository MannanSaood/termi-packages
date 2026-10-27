import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from recipe_repairs import rust_target_cxx_headers


class RustHeadersTests(unittest.TestCase):
    def test_target_wrapper_preserves_arguments_and_host_config(self):
        bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        if not bash or not Path(bash).exists():
            self.skipTest('Bash unavailable')
        anchor = '\tunset CC CFLAGS CFLAGS_${env_host} CPP CPPFLAGS CXX CXXFLAGS LD LDFLAGS PKG_CONFIG RANLIB'
        setup = rust_target_cxx_headers(anchor).split(anchor)[0]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'bootstrap.toml').write_text('[target.aarch64-linux-android]\nprofiler = true\n[target.x86_64-unknown-linux-gnu]\ncxx = "host-cxx"\n')
            (p / 'fake-cxx').write_text('#!/bin/bash\nprintf "%s\\n" "$@" > args.txt\n')
            script = '''set -eu
export MSYS_NO_PATHCONV=1
TERMUX_PKG_TMPDIR="$PWD"
TERMUX_PREFIX='/data/data/com.terminal.nextgen/files/usr'
CARGO_TARGET_NAME=aarch64-linux-android
TERMUX_HOST_PLATFORM=aarch64-linux-android
TERMUX_PKG_API_LEVEL=26
CXX="$PWD/fake-cxx"
chmod +x "$CXX"
configure() {
''' + setup + '''
}
configure
./termi-rust-cxx '-I/data/data/com.terminal.nextgen/files/usr/include' '--target=aarch64-linux-android' 'file with spaces.cpp'
'''
            (p / 'check.sh').write_text(script)
            subprocess.run([bash, 'check.sh'], cwd=p, check=True, capture_output=True)
            self.assertEqual((p / 'args.txt').read_text().splitlines(), [
                '-nostdinc++', '-I/data/data/com.terminal.nextgen/files/usr/include/c++/v1',
                '-I/data/data/com.terminal.nextgen/files/usr/include', '--target=aarch64-linux-android', 'file with spaces.cpp', '--target=aarch64-linux-android26'])
            config = (p / 'bootstrap.toml').read_text()
            self.assertIn('[target.aarch64-linux-android]\ncxx = ', config)
            self.assertIn('[target.x86_64-unknown-linux-gnu]\ncxx = "host-cxx"', config)

    def test_changed_source_rejected(self):
        with self.assertRaises(ValueError):
            rust_target_cxx_headers('changed upstream')
