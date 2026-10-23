import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from checkpoint import Parts


class CheckpointParts(unittest.TestCase):
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
