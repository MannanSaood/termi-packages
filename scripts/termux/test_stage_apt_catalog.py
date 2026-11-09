"""Recovery checks for a stopped staging job and an uncertain GitHub upload."""

import http.client
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from seed import digest
from stage_apt_catalog import Uploads


class UploadRecoveryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.package = Path(directory.name) / "fixture_1_aarch64.deb"
        self.package.write_bytes(b"fixture package")
        self.asset = dict(name=self.package.name, state="uploaded", size=self.package.stat().st_size,
                          digest="sha256:" + digest(self.package))

    @patch("stage_apt_catalog.http.client.HTTPSConnection")
    @patch("stage_apt_catalog.release_assets")
    def test_resumed_job_skips_an_already_verified_asset(self, assets, connect):
        assets.return_value = {self.package.name: self.asset}
        Uploads(123).put(self.package)
        connect.assert_not_called()

    @patch("stage_apt_catalog.http.client.HTTPSConnection")
    @patch("stage_apt_catalog.release_assets")
    def test_resumed_job_rejects_conflicting_existing_asset(self, assets, connect):
        assets.return_value = {self.package.name: dict(self.asset, digest="sha256:" + "0" * 64)}
        with self.assertRaisesRegex(ValueError, "Conflicting release asset"):
            Uploads(123).put(self.package)
        connect.assert_not_called()

    @patch.dict("os.environ", GH_TOKEN="fixture-token")
    @patch("stage_apt_catalog.time.sleep")
    @patch("stage_apt_catalog.http.client.HTTPSConnection")
    @patch("stage_apt_catalog.release_assets")
    def test_lost_response_reconciles_an_accepted_upload(self, assets, connect, sleep):
        assets.side_effect = [{}, {self.package.name: self.asset}]
        connection = connect.return_value
        connection.getresponse.side_effect = http.client.RemoteDisconnected("response lost")
        uploader = Uploads(123)
        uploader.put(self.package)
        uploader.put(self.package)
        self.assertEqual(2, assets.call_count)
        self.assertEqual(1, connection.request.call_count)
        sleep.assert_any_call(60)

    @patch.dict("os.environ", GH_TOKEN="fixture-token")
    @patch("stage_apt_catalog.time.sleep")
    @patch("stage_apt_catalog.http.client.HTTPSConnection")
    @patch("stage_apt_catalog.release_assets")
    def test_missing_asset_retries_after_server_rate_limit(self, assets, connect, sleep):
        import json

        assets.return_value = {}
        throttled = Mock(status=429)
        throttled.getheader.side_effect = lambda name, default=None: "75" if name == "Retry-After" else default
        accepted = Mock(status=201)
        accepted.read.return_value = json.dumps(self.asset).encode()
        connect.return_value.getresponse.side_effect = [throttled, accepted]
        Uploads(123).put(self.package)
        self.assertEqual(2, connect.return_value.request.call_count)
        sleep.assert_any_call(75)


if __name__ == "__main__":
    unittest.main()
