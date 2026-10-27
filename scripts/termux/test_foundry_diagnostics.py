import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from recipe_repairs import foundry_link_diagnostics


class FoundryDiagnosticsTest(unittest.TestCase):
    def test_captures_native_symbols_and_preserves_cargo_exit(self):
        bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        recipe=foundry_link_diagnostics('termux_step_make() {\n\tcargo build \\\n\t\t--features="cli"\n}\n')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'target/aarch64-linux-android/release/build/secp256k1-sys-abc/out'
            out.mkdir(parents=True);(out/'libsecp256k1.a').write_bytes(b'fixture')
            nm=root/'nm.py';nm.write_text('print("0000 T rustsecp256k1_v0_10_0_test")\n')
            script=root/'build.sh';script.write_text(recipe+'\npython3() { "$TERMI_TEST_PYTHON" "$@"; }\n'
                +'cargo() { return "$FAKE_CARGO_STATUS"; }\ntermux_step_make\n')
            env={**os.environ,'TERMUX_PKG_SRCDIR':root.as_posix(),'CARGO_TARGET_NAME':'aarch64-linux-android',
                 'NM':shlex.join([sys.executable,nm.as_posix()]),'TERMI_TEST_PYTHON':Path(sys.executable).as_posix()}
            for status in [0,19]:
                result=subprocess.run([bash,str(script)],env={**env,'FAKE_CARGO_STATUS':str(status)},capture_output=True,text=True)
                self.assertEqual(status,result.returncode,result.stderr)
                self.assertEqual(status!=0,'TERMI FOUNDRY NATIVE:' in result.stdout)
                if status:self.assertIn("'v0_10_0': 1",result.stdout)
