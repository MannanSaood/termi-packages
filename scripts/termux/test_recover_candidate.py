import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from recover_candidate import VerifiedParts, extract_artifacts


class RecoveryTests(unittest.TestCase):
    def test_split_stream_recovers_only_flat_artifacts(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name in ['home/builder/artifacts/inventory.json', 'etc/secret.json', 'home/builder/artifacts/../escape.json']:
                member = tarfile.TarInfo(name)
                member.size = 2
                archive.addfile(member, io.BytesIO(b'{}'))
        raw = data.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = []
            for index, chunk in enumerate([raw[:70], raw[70:]]):
                name = f'checkpoint-{index:04d}.gz.part'
                (root/name).write_bytes(chunk)
                records.append(dict(file=name, bytes=len(chunk), sha256=hashlib.sha256(chunk).hexdigest()))
            stream = VerifiedParts(records, lambda name: root/name)
            extract_artifacts(stream, root/'out')
            self.assertEqual([p.name for p in (root/'out').iterdir()], ['inventory.json'])
            self.assertEqual(stream.index, 2)

    def test_bad_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'part'
            path.write_bytes(b'bad')
            stream = VerifiedParts([dict(file='checkpoint-0000.gz.part', bytes=3, sha256='0'*64)], lambda name: path)
            with self.assertRaises(ValueError):
                stream.read(1)

    def test_artifact_symlink_rejected(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            member = tarfile.TarInfo('home/builder/artifacts/inventory.json')
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/passwd'
            archive.addfile(member)
        data.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                extract_artifacts(data, Path(tmp)/'out')
