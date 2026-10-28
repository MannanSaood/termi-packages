import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from recipe_repairs import swift_target_cxx_headers

class SwiftHeadersTest(unittest.TestCase):
    def test_android_cpp_only(self):
        recipe = swift_target_cxx_headers("termux_step_make() {\n\t--install-swift-driver --install-sourcekit-lsp\n}")
        script = recipe.split("<<'TERMI_SWIFT'\n")[1].split("\nTERMI_SWIFT")[0]
        bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'impl'
            p.write_text('function swift_c_flags() { printf "common-%s" "$1"; }\n' +
                         'flags=(-DCMAKE_C_FLAGS="$(swift_c_flags ${host})" -DCMAKE_CXX_FLAGS="$(swift_c_flags ${host}) ${cross_c_flags}")\n')
            launcher=Path(tmp)/'launcher'
            subprocess.run([sys.executable,'-c',script,str(p),'/prefix',launcher.as_posix()],check=True)
            s=p.read_text()
            self.assertIn('-DCMAKE_CXX_FLAGS="$(termi_swift_cxx_flags ${host}) ${cross_c_flags}"',s)
            self.assertIn('-DCMAKE_C_FLAGS="$(swift_c_flags ${host})"',s)
            s=s.split('flags=')[0]
            p.write_text(s+'\nunset TERMUX_PREFIX\ntermi_swift_cxx_flags android-aarch64\nprintf "\\n"\ntermi_swift_cxx_flags linux-x86_64\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),['-nostdinc++ -I/prefix/include/c++/v1 -Wno-error=variadic-macro-arguments-omitted common-android-aarch64','common-linux-x86_64'])
            fake=Path(tmp)/'compiler';fake.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n');fake.chmod(0o755)
            out=subprocess.check_output([bash,str(launcher),fake.as_posix(),'-I/prefix/include','-Werror=gnu'],text=True)
            self.assertEqual(out.splitlines(),['-nostdinc++','-I/prefix/include/c++/v1','-I/prefix/include','-Werror=gnu','-Wno-error=variadic-macro-arguments-omitted','-Wno-error=gnu-include-next'])
            self.assertIn('termi_swift_cxx_launcher_option',s)
    def test_source_drift(self):
        with self.assertRaises(ValueError): swift_target_cxx_headers('changed')
