import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import subprocess
import threading
import shutil
import sys
from unittest.mock import patch

from checkpoint import Parts, gh, compress_export


class CheckpointCompression(unittest.TestCase):
    def stream(self, pigz, exporter_status=0, compressor_status=0):
        payload = bytes(range(256)) * 8193
        processes, commands, uploaded = [], [], []
        original = subprocess.Popen
        def launch(command, **kwargs):
            commands.append(command)
            if command[0] == 'docker':
                command = [sys.executable, '-c',
                    'import sys; sys.stdout.buffer.write(bytes(range(256))*8193); sys.exit(' + str(exporter_status) + ')']
            elif compressor_status:
                command = [sys.executable, '-c', 'import sys; sys.exit(' + str(compressor_status) + ')']
            process = original(command, **kwargs)
            processes.append(process)
            return process
        with tempfile.TemporaryDirectory() as tmp:
            sink = Parts(Path(tmp), lambda path: uploaded.append(path.read_bytes()), limit=257)
            try:
                with patch('checkpoint.shutil.which', return_value=pigz), patch('checkpoint.subprocess.Popen', side_effect=launch):
                    if exporter_status or compressor_status:
                        with self.assertRaisesRegex(ValueError, 'failed'):
                            compress_export('stopped-builder', sink)
                        self.assertFalse((Path(tmp) / 'checkpoint.json').exists())
                    else:
                        compress_export('stopped-builder', sink)
                        sink.finish()
                        self.assertEqual(payload, gzip.decompress(b''.join(uploaded)))
                        for record, data in zip(sink.records, uploaded):
                            self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
                            self.assertLessEqual(len(data), 257)
            finally:
                sink.shutdown()
            self.assertTrue(all(p.poll() is not None for p in processes))
        if pigz:
            self.assertEqual([pigz, '-1', '-n', '-p', '2'], commands[1])

    def test_python_fallback_is_lossless(self):
        self.stream(None)

    def test_export_failure_rejects_even_a_valid_gzip_stream(self):
        self.stream(None, exporter_status=7)

    @unittest.skipUnless(shutil.which('pigz'), 'pigz executable unavailable')
    def test_real_parallel_gzip_is_lossless_and_uses_existing_parts_format(self):
        self.stream(shutil.which('pigz'))

    def test_compressor_failure_rejects_checkpoint_and_reaps_both_processes(self):
        self.stream('pigz-test', compressor_status=9)


class CheckpointParts(unittest.TestCase):
    def test_compression_continues_during_one_serial_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);started=threading.Event();release=threading.Event();uploaded=[]
            def upload(path):
                started.set()
                if not release.wait(5):raise RuntimeError('Test upload was not released')
                uploaded.append(path.read_bytes())
            sink=Parts(root,upload,limit=4,background=True)
            try:
                sink.write(b'abcd')
                self.assertTrue(started.wait(5))
                # The next part can be compressed while upload is blocked.
                sink.write(b'ef');sink.flush()
                self.assertEqual(2,len(list(root.iterdir())))
                self.assertEqual([],uploaded)
                release.set();sink.write(b'gh');sink.finish();sink.wait_uploads()
                self.assertEqual([b'abcd',b'efgh'],uploaded)
                self.assertEqual([],list(root.iterdir()))
            finally:
                release.set();sink.shutdown()

    def test_background_upload_failure_prevents_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def failed(path):raise subprocess.TimeoutExpired('gh',600)
            sink=Parts(root,failed,limit=4,background=True)
            try:
                sink.write(b'data')
                with self.assertRaises(subprocess.TimeoutExpired):sink.wait_uploads()
                self.assertEqual(b'data',(root/'checkpoint-0000.gz.part').read_bytes())
                self.assertFalse((root/'checkpoint.json').exists())
            finally:sink.shutdown()

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
        self.roundtrip(background=False)

    def test_background_gzip_parts_are_hashed_and_lossless(self):
        self.roundtrip(background=True)

    def roundtrip(self,background):
        payload = bytes(range(256)) * 257
        uploaded = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sink = Parts(root, lambda path: uploaded.append((path.name, path.read_bytes())), limit=37,background=background)
            with gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as stream:
                for start in range(0, len(payload), 123):
                    stream.write(payload[start:start+123])
            sink.finish()
            try:sink.wait_uploads()
            finally:sink.shutdown()
            self.assertGreater(len(uploaded), 2)
            self.assertEqual(payload, gzip.decompress(b"".join(blob for _, blob in uploaded)))
            for record, (name, blob) in zip(sink.records, uploaded):
                self.assertEqual(name, record["file"])
                self.assertLessEqual(len(blob), 37)
                self.assertEqual(hashlib.sha256(blob).hexdigest(), record["sha256"])
            self.assertEqual([], list(root.iterdir()))
