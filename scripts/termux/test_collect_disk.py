import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collect_artifacts import collect, checksum


class ImmutableCandidateExport(unittest.TestCase):
    fields = 'Package: fixture\nVersion: 1:2\nArchitecture: aarch64\n'

    def test_link_preserves_archive_after_source_unlink_and_rejects_changed_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'output';source.mkdir()
            original=source/'fixture_1%3A2_aarch64.deb';original.write_bytes(b'completed immutable archive')
            destination=root/'artifacts'
            with patch('collect_artifacts.subprocess.check_output',return_value=self.fields):
                collect(source,destination,link_immutable=True)
                exported=destination/'fixture_1%3A2_aarch64.deb'
                self.assertTrue(original.samefile(exported))
                inventory=json.loads((destination/'inventory.json').read_text())
                self.assertEqual(checksum(original),inventory['packages'][0]['sha256'])
                original.unlink()
                self.assertEqual(b'completed immutable archive',exported.read_bytes())
                original.write_bytes(b'changed revision without new filename')
                with self.assertRaisesRegex(ValueError,'Existing candidate object changed'):
                    collect(source,destination,resume=True,link_immutable=True)
                self.assertEqual(b'completed immutable archive',exported.read_bytes())

    def test_cross_filesystem_export_falls_back_to_lossless_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'output';source.mkdir()
            original=source/'fixture_1_aarch64.deb';original.write_bytes(b'archive bytes')
            destination=root/'artifacts'
            with patch('collect_artifacts.subprocess.check_output',return_value=self.fields), \
                    patch('collect_artifacts.os.link',side_effect=OSError(errno.EXDEV,'different filesystem')):
                collect(source,destination,link_immutable=True)
            exported=destination/original.name
            self.assertFalse(original.samefile(exported))
            self.assertEqual(checksum(original),checksum(exported))
