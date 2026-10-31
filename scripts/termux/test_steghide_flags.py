from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from catalog_repairs import STEGHIDE_FLAGS_PATCH

BRANCHES = ['-std=c++11 -O2 -Wall -g', '-std=c++11 -O2 -Wall', '-std=c++11 -O2 -Wall']
FIXTURE = '\n'.join('CXXFLAGS="'+flags+'"' for flags in BRANCHES)+'\n'

class SteghideFlagsTest(unittest.TestCase):
    def patch(self, root):
        return subprocess.run([sys.executable, '-c', STEGHIDE_FLAGS_PATCH, str(root)],capture_output=True,text=True)

    def test_all_files_validated_before_write_and_repeat_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'configure').write_text(FIXTURE)
            (root/'configure.in').write_text(FIXTURE.replace('-Wall -g','-Wall -changed'))
            self.assertNotEqual(0,self.patch(root).returncode)
            self.assertEqual(FIXTURE,(root/'configure').read_text())
            (root/'configure.in').write_text(FIXTURE)
            r=self.patch(root);self.assertEqual(0,r.returncode,r.stderr)
            self.assertNotEqual(0,self.patch(root).returncode)

    @unittest.skipUnless(shutil.which('sh'),'POSIX shell unavailable')
    def test_debug_nondebug_and_default_branches_retain_cross_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['configure','configure.in']:(root/name).write_text(FIXTURE)
            r=self.patch(root);self.assertEqual(0,r.returncode,r.stderr)
            incoming='-fstack-protector-strong -Oz -nostdinc++ -I/prefix/include/c++/v1'
            for name in ['configure','configure.in']:
                for original,assignment in zip(BRANCHES,(root/name).read_text().splitlines()):
                    for initial in [incoming,'']:
                        r=subprocess.run(['sh','-c',assignment+'; printf "%s" "$CXXFLAGS"'],env={'CXXFLAGS':initial},capture_output=True,text=True)
                        self.assertEqual(0,r.returncode,r.stderr)
                        self.assertEqual(initial+' '+original,r.stdout)
