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
