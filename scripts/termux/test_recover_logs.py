import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from recover_logs import extract_logs

class LogRecoveryTests(unittest.TestCase):
    def archive(self, symbolic=False):
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode="w:gz") as tar:
            member=tarfile.TarInfo("home/builder/catalog-state/logs/swift-1.log")
            if symbolic:
                member.type=tarfile.SYMTYPE;member.linkname="/etc/passwd";tar.addfile(member)
            else:
                data=b"compiler failure\n";member.size=len(data);tar.addfile(member,io.BytesIO(data))
            member=tarfile.TarInfo("etc/unrelated");member.size=6;tar.addfile(member,io.BytesIO(b"ignore"))
        buf.seek(0);return buf
    def test_only_explicit_regular_log(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"logs";extract_logs(self.archive(),out,["swift-1.log"])
            self.assertEqual([p.name for p in out.iterdir()],["swift-1.log"])
            self.assertEqual((out/"swift-1.log").read_bytes(),b"compiler failure\n")
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            extract_logs(self.archive(True),Path(d)/"logs",["swift-1.log"])
    def test_missing_and_path_escape_rejected(self):
        for name in ["missing-1.log","../swift-1.log"]:
            with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
                extract_logs(self.archive(),Path(d)/"logs",[name])

    def test_cmake_path_scope(self):
        from recover_logs import diagnostic_cmake_path
        self.assertTrue(diagnostic_cmake_path("home/builder/.termux-build/swift/build/swift-android-aarch64/CMakeFiles/CMakeConfigureLog.yaml"))
        for path in ["etc/CMakeFiles/CMakeError.log", "home/builder/.termux-build/swift/build/../CMakeFiles/CMakeError.log", "home/builder/.termux-build/swift/build/x/CMakeFiles/program.sh"]:
            self.assertFalse(diagnostic_cmake_path(path))
    def test_cmake_extraction(self):
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode="w:gz") as tar:
            m=tarfile.TarInfo("home/builder/.termux-build/swift/build/swift-android-aarch64/CMakeFiles/CMakeConfigureLog.yaml")
            m.size=4;tar.addfile(m,io.BytesIO(b"log!"))
        buf.seek(0)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"out";extract_logs(buf,out,["swift-cmake"])
            self.assertEqual([p.read_bytes() for p in out.iterdir()],[b"log!"])

    def test_native_archive_scope_and_regular_file_only(self):
        from recover_logs import diagnostic_foundry_native_path
        base = 'home/builder/.termux-build/foundry/src/target/aarch64-linux-android/release/'
        name = base+'build/secp256k1-sys-012abc/out/libsecp256k1.a'
        self.assertTrue(diagnostic_foundry_native_path(name))
        self.assertTrue(diagnostic_foundry_native_path(base+'deps/libsecp256k1_sys-012abc.rlib'))
        for suffix in ['../output', 'deps/program', 'build/other-012abc/out/libsecp256k1.a']:
            self.assertFalse(diagnostic_foundry_native_path(base+suffix))
        for symbolic in [False, True]:
            buf=io.BytesIO()
            with tarfile.open(fileobj=buf, mode='w:gz') as tar:
                m=tarfile.TarInfo(name)
                if symbolic:
                    m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd';tar.addfile(m)
                else:
                    m.size=8;tar.addfile(m,io.BytesIO(b'!<arch>\n'))
            buf.seek(0)
            with tempfile.TemporaryDirectory() as d:
                if symbolic:
                    with self.assertRaises(ValueError):extract_logs(buf,Path(d)/'out',['foundry-native'])
                else:
                    out=Path(d)/'out';extract_logs(buf,out,['foundry-native'])
                    self.assertEqual([p.read_bytes() for p in out.iterdir()],[b'!<arch>\n'])
