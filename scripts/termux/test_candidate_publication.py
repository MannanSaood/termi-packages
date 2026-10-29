import subprocess
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from publish_candidates import publish


class PublicationTest(unittest.TestCase):
    def test_metadata_first_and_only_one_bundle_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp)/'build';artifacts=build/'candidate/artifacts';artifacts.mkdir(parents=True)
            for name in ['rust','seed','third']:
                (artifacts/(name+'.deb')).write_bytes(name.encode())
            (artifacts/'inventory.json').write_text('{}')
            (artifacts/'build.log').write_text('original diagnostic')
            collected={};calls=[]
            def upload(command,**kwargs):
                calls.append(command)
                if command[2]=='create':
                    self.assertFalse(any(str(p).endswith('.deb') or str(p).endswith('.tar') for p in command))
                    self.assertTrue(any(str(p).endswith('build.log') for p in command))
                else:
                    self.assertEqual(1,len(list(build.glob('packages-*.tar'))))
                    archive_path=next(Path(p) for p in command if str(p).endswith('.tar'))
                    with tarfile.open(archive_path) as archive:
                        for member in archive:
                            collected[member.name]=archive.extractfile(member).read()
            with patch('publish_candidates.subprocess.run',side_effect=upload):
                publish(build,'MannanSaood/termi-packages','1','1',bundle_limit=5)
            self.assertEqual({'rust.deb':b'rust','seed.deb':b'seed','third.deb':b'third'},collected)
            self.assertEqual(4,len(calls))
            self.assertEqual([],list(build.glob('packages-*.tar')))
            self.assertEqual([],list((build/'release-upload').glob('*.tar')))
            self.assertEqual(b'rust',(artifacts/'rust.deb').read_bytes())
            self.assertEqual('original diagnostic',(artifacts/'build.log').read_text())

    def test_failed_upload_keeps_bundle_and_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp);artifacts=build/'candidate/artifacts';artifacts.mkdir(parents=True)
            (artifacts/'one.deb').write_bytes(b'package')
            (artifacts/'inventory.json').write_text('{}')
            def upload(command,**kwargs):
                if command[2]=='upload':
                    raise subprocess.CalledProcessError(1,command)
            with patch('publish_candidates.subprocess.run',side_effect=upload):
                with self.assertRaises(subprocess.CalledProcessError):
                    publish(build,'MannanSaood/termi-packages','1','1')
            self.assertEqual(1,len(list(build.glob('packages-*.tar'))))
            self.assertEqual(1,len(list((build/'release-upload').glob('*.tar'))))
            self.assertEqual(b'package',(artifacts/'one.deb').read_bytes())
            self.assertTrue(any((build/'release-upload').glob('*inventory.json')))

    def test_low_disk_keeps_metadata_and_does_not_fill_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp);artifacts=build/'candidate/artifacts';artifacts.mkdir(parents=True)
            (artifacts/'one.deb').write_bytes(b'package')
            (artifacts/'inventory.json').write_text('{}')
            from collections import namedtuple
            Usage=namedtuple('Usage','total used free')
            with patch('publish_candidates.subprocess.run') as upload, patch('publish_candidates.shutil.disk_usage',return_value=Usage(10,9,1)):
                with self.assertRaises(ValueError):
                    publish(build,'MannanSaood/termi-packages','1','1')
            self.assertEqual('create',upload.call_args.args[0][2])
            self.assertEqual(b'package',(artifacts/'one.deb').read_bytes())
