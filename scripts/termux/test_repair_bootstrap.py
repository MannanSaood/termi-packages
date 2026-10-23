import hashlib
import io
import tarfile
import unittest
from repair_bootstrap import checksums, PREFIX


class RepairChecksums(unittest.TestCase):
    def archive(self, members):
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w") as archive:
            for name, kind, data in members:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.size = len(data) if kind == tarfile.REGTYPE else 0
                if kind == tarfile.SYMTYPE:
                    entry.linkname = "file"
                archive.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
        return result.getvalue()

    def test_records_original_regular_payload_not_alias(self):
        data = self.archive([(f"./{PREFIX}/bin/file", tarfile.REGTYPE, b"original"),
                             (f"./{PREFIX}/bin/link", tarfile.SYMTYPE, b"")])
        digest = hashlib.md5(b"original", usedforsecurity=False).hexdigest()
        self.assertEqual(f"{digest}  {PREFIX}/bin/file\n".encode(), checksums(data))

    def test_hostile_members_are_rejected(self):
        for members in [
            [("../escape", tarfile.REGTYPE, b"x")],
            [("/absolute", tarfile.REGTYPE, b"x")],
            [("etc/escape", tarfile.REGTYPE, b"x")],
            [(f"{PREFIX}/bad\nname", tarfile.REGTYPE, b"x")],
            [(f"{PREFIX}/hard", tarfile.LNKTYPE, b"")],
            [(f"{PREFIX}/file", tarfile.REGTYPE, b"x")] * 2,
        ]:
            with self.assertRaises(ValueError):
                checksums(self.archive(members))
