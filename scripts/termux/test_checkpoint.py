import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from checkpoint import Parts, gh


class CheckpointParts(unittest.TestCase):
    def test_stalled_upload_is_bounded_and_keeps_failed_part(self):
        with patch('checkpoint.subprocess.run',side_effect=subprocess.TimeoutExpired('gh',600)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                gh('owner/public','upload','checkpoint-1','part')
            self.assertEqual(600,run.call_args.kwargs['timeout'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def stalled(path):
                raise subprocess.TimeoutExpired('gh',600)
            sink=Parts(root,stalled,limit=4)
            with self.assertRaises(subprocess.TimeoutExpired):
                sink.write(b'data')
            self.assertEqual(b'data',(root/'checkpoint-0000.gz.part').read_bytes())
            self.assertFalse((root/'checkpoint.json').exists())

    def test_streamed_parts_are_bounded_hashed_and_lossless(self):
        payload = bytes(range(256)) * 257
        uploaded = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sink = Parts(root, lambda path: uploaded.append((path.name, path.read_bytes())), limit=37)
            with gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as stream:
                for start in range(0, len(payload), 123):
                    stream.write(payload[start:start+123])
            sink.finish()
            self.assertGreater(len(uploaded), 2)
            self.assertEqual(payload, gzip.decompress(b"".join(blob for _, blob in uploaded)))
            for record, (name, blob) in zip(sink.records, uploaded):
                self.assertEqual(name, record["file"])
                self.assertLessEqual(len(blob), 37)
                self.assertEqual(hashlib.sha256(blob).hexdigest(), record["sha256"])
            self.assertEqual([], list(root.iterdir()))
