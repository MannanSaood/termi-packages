import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from recipe_repairs import mesa_bindgen_headers


class MesaHeadersTests(unittest.TestCase):
    def test_only_cpp_bindings_receive_headers_before_dependency_includes(self):
        bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        if not bash or not Path(bash).exists():
            self.skipTest('Bash unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'bindgen').write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
            script = '''set -eu
export MSYS_NO_PATHCONV=1
export PATH="$PWD:$PATH"
chmod +x bindgen
TERMUX_PREFIX=/data/data/com.terminal.nextgen/files/usr
_WRAPPER_BIN="$PWD/wrapper"
setup() {
''' + mesa_bindgen_headers('\tmkdir -p $_WRAPPER_BIN') + '''
}
setup
wrapper/bindgen rusticl_llvm_bindings.hpp -- -Iroot 'header with spaces' > cpp.txt
wrapper/bindgen rusticl_mesa_bindings.h -- -Iroot > c.txt
'''
            (p/'check.sh').write_text(script)
            subprocess.run([bash, 'check.sh'], cwd=p, check=True, capture_output=True)
            self.assertEqual((p/'cpp.txt').read_text().splitlines(), ['rusticl_llvm_bindings.hpp', '--', '-nostdinc++', '-I/data/data/com.terminal.nextgen/files/usr/include/c++/v1', '-Iroot', 'header with spaces'])
            self.assertEqual((p/'c.txt').read_text().splitlines(), ['rusticl_mesa_bindings.h', '--', '-Iroot'])

    def test_changed_source_rejected(self):
        with self.assertRaises(ValueError):
            mesa_bindgen_headers('changed source')
