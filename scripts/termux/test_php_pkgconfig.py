from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

import catalog_repairs


class PhpPkgconfigTest(unittest.TestCase):
    source = ('TERMUX_PKG_BUILD_DEPENDS="postgresql"\n'
              'TERMUX_PKG_EXTRA_CONFIGURE_ARGS="--enable-gd=shared --with-external-gd"\n')

    def transform(self, text):
        class Captured(Exception):
            pass
        result = []
        def change(name, transform, tree='packages'):
            if name == 'php':
                result.append(transform(text))
                raise Captured
        with self.assertRaises(Captured):
            catalog_repairs.apply(change, lambda *args: '', lambda path: '')
        return result[0]

    def test_only_build_prerequisites_change_and_gd_features_are_retained(self):
        self.assertEqual(self.source.replace('"postgresql"',
            '"libdeflate, libxpm, openh264, postgresql"'), self.transform(self.source))

    def test_changed_dependency_contract_or_repeat_is_rejected(self):
        for text in [self.source.replace('postgresql', 'changed'), self.transform(self.source)]:
            with self.subTest(text=text), self.assertRaises(AssertionError):
                self.transform(text)

    @unittest.skipUnless(shutil.which('pkg-config'), 'pkg-config unavailable')
    def test_real_pkgconfig_requires_private_metadata_with_shared_libraries(self):
        # Reproduce the three missing pc names and their observed parent chains.
        # These are metadata fixtures, not replacement libraries or native PHP.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def pc(name, requires=''):
                (root / (name + '.pc')).write_text(
                    f'Name: {name}\nDescription: fixture\nVersion: 2.3.3\n'
                    f'Requires.private: {requires}\nLibs: -l{name}\n')
            pc('gdlib', 'xpm libtiff-4 libheif')
            pc('libtiff-4', 'libdeflate')
            pc('libheif', 'openh264')
            env = dict(os.environ, PKG_CONFIG_LIBDIR=str(root), PKG_CONFIG_PATH='', PKG_CONFIG_SYSROOT_DIR='')
            args = ['pkg-config', '--cflags', '--libs', 'gdlib >= 2.1.0']
            before = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, before.returncode)
            for name in ['xpm', 'libdeflate', 'openh264']:
                self.assertIn(name, before.stderr)
                pc(name)
            after = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertEqual(0, after.returncode, after.stderr)
            self.assertIn('-lgdlib', after.stdout)
