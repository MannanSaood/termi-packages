from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from catalog_repairs import QT5_HOST_HEADERS


class QtHostHeadersTests(unittest.TestCase):
    def test_host_makefile_uses_qt_headers_without_android_system_root(self):
        script=QT5_HOST_HEADERS.split("<<'TERMI_QT5_HOST_HEADERS'\n")[1].split('\nTERMI_QT5_HOST_HEADERS')[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefix=root/'android-include';private=root/'host-include'
            (prefix/'QtCore').mkdir(parents=True)
            (prefix/'QtCore/qglobal.h').write_text('portable Qt header')
            (prefix/'stdlib.h').write_text('Android system header must not reach host')
            flags=f'-I{prefix} -isystem {prefix} -I{prefix}/QtCore -I/usr/include'
            make=root/'Makefile';make.write_text('INCPATH = '+flags+'\nCXX = g++\n')
            subprocess.run([sys.executable,'-c',script,str(prefix),str(private)],cwd=root,check=True)
            content=make.read_text()
            self.assertNotIn('-I'+str(prefix)+' ',content)
            self.assertNotIn('-isystem '+str(prefix)+' ',content)
            self.assertIn('-I'+str(prefix)+'/QtCore',content)
            self.assertIn('-I/usr/include',content)
            self.assertIn('-I'+str(private),content)
            self.assertEqual('portable Qt header',(private/'QtCore/qglobal.h').read_text())
            self.assertFalse((private/'stdlib.h').exists())
            self.assertEqual('Android system header must not reach host',(prefix/'stdlib.h').read_text())
