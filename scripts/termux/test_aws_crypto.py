import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from catalog_repairs import AWS_PRIVATE_CRYPTO

class AwsCryptoTest(unittest.TestCase):
    def test_only_private_crypto_archive_bypasses_prefix_search(self):
        bash='C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else shutil.which('bash')
        if not bash:self.skipTest('Bash unavailable')
        script=AWS_PRIVATE_CRYPTO.split("<<'TERMI_AWS_CRYPTO_CC'\n")[1].split('\nTERMI_AWS_CRYPTO_CC')[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);compiler=root/'compiler';wrapper=root/'wrapper'
            compiler.write_text('#!/bin/bash\nprintf \'%s\\n\' "$@"\n');compiler.chmod(0o755)
            subprocess.run([sys.executable,'-c',script,compiler.as_posix(),wrapper.as_posix()],check=True)
            ordinary=['-c','source.c','-o','source.o']
            self.assertEqual(ordinary,subprocess.check_output([bash,str(wrapper),*ordinary],text=True).splitlines())
            bundle=root/'deps/install/lib';bundle.mkdir(parents=True);(bundle/'libcrypto.a').write_bytes(b'fixture')
            args=['-L/prefix/lib','-L'+bundle.as_posix(),'-l:libcrypto.a','-lpython3.14','-Wl,--as-needed']
            out=subprocess.check_output([bash,str(wrapper),*args],text=True).splitlines()
            self.assertEqual(args[:2],out[:2]);self.assertEqual(args[3:],out[3:])
            self.assertTrue(out[2].endswith('/deps/install/lib/libcrypto.a'));self.assertNotIn('-l:libcrypto.a',out)
            failed=subprocess.run([bash,str(wrapper),'-l:libcrypto.a'],capture_output=True,text=True)
            self.assertEqual(2,failed.returncode);self.assertIn('Cannot identify private AWS-LC archive',failed.stderr)
