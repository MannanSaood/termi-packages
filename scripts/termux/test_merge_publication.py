import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from merge_releases import publish_verified


class MergePublicationTests(unittest.TestCase):
    def scenario(self, behavior, existing=None, good=True):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'packages-0000.tar'
            path.write_bytes(b'verified source package bytes')
            asset = dict(name=path.name, state='uploaded', size=path.stat().st_size,
                         digest='sha256:' + hashlib.sha256(path.read_bytes()).hexdigest())
            assets = [] if existing is None else [dict(asset, **existing)]
            uploads = []
            commands = []

            def command(args, check):
                commands.append(args)
                if args[2] == 'create':
                    self.assertNotIn(str(path), args)
                    return subprocess.CompletedProcess(args, 0)
                self.assertEqual('upload', args[2])
                uploads.append(path.name)
                rc = behavior(assets, asset, len(uploads))
                return subprocess.CompletedProcess(args, rc)

            with patch('merge_releases.subprocess.run', side_effect=command), \
                    patch('merge_releases.run', side_effect=lambda _: json.dumps(dict(assets=assets))), \
                    patch('merge_releases.time.sleep'):
                if good:
                    publish_verified([path], 'owner/repo', 'candidate-1-1-0')
                else:
                    with self.assertRaises((ValueError, RuntimeError)):
                        publish_verified([path], 'owner/repo', 'candidate-1-1-0')
            self.assertTrue(all('--clobber' not in c and 'delete' not in c for c in commands))
            return len(uploads)

    def test_serial_success_requires_server_hash(self):
        self.assertEqual(1, self.scenario(lambda rows, asset, _: (rows.append(asset), 0)[1]))

    def test_uncertain_cli_error_accepts_matching_server_asset(self):
        self.assertEqual(1, self.scenario(lambda rows, asset, _: (rows.append(asset), 1)[1]))

    def test_existing_identical_asset_is_never_uploaded_again(self):
        self.assertEqual(0, self.scenario(lambda *_: self.fail('duplicate upload'), existing={}))

    def test_conflicting_hash_is_preserved_and_rejected(self):
        self.assertEqual(0, self.scenario(lambda *_: self.fail('overwrite'), existing=dict(digest='sha256:wrong'), good=False))

    def test_incomplete_asset_is_preserved_and_rejected(self):
        self.assertEqual(0, self.scenario(lambda *_: self.fail('overwrite'), existing=dict(state='starter'), good=False))

    def test_missing_upload_retries_are_bounded(self):
        self.assertEqual(3, self.scenario(lambda *_: 1, good=False))

    def test_success_without_remote_asset_is_not_assumed(self):
        self.assertEqual(3, self.scenario(lambda *_: 0, good=False))

    def test_wrong_server_size_after_upload_is_rejected(self):
        self.assertEqual(1, self.scenario(lambda rows, asset, _: (rows.append(dict(asset, size=1)), 0)[1], good=False))


if __name__ == '__main__':
    unittest.main()
