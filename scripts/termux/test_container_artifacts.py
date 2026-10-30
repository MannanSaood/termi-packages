import io
import json
import hashlib
from contextlib import contextmanager
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import container_artifacts as ca
from publish_candidates import publish


@contextmanager
def fixture_stream(entries):
    body=io.BytesIO()
    with tarfile.open(fileobj=body,mode='w') as archive:
        for name,value in entries:
            member=tarfile.TarInfo(name);member.size=len(value)
            archive.addfile(member,io.BytesIO(value))
    body.seek(0)
    with tarfile.open(fileobj=body,mode='r|') as archive:
        yield archive


class ContainerArtifactsTest(unittest.TestCase):
    def test_metadata_does_not_copy_package_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries=[('./one.deb',b'large package fixture'),('./inventory.json',b'{}'),('./build.log',b'log')]
            with patch.object(ca,'stream',side_effect=lambda _:fixture_stream(entries)):
                ca.metadata('a'*64,Path(tmp))
            self.assertEqual(['build.log','inventory.json'],sorted(p.name for p in Path(tmp).iterdir()))

    def test_unsafe_aliases_paths_and_duplicate_metadata_are_rejected(self):
        for name in ['../escape.deb','/absolute.deb','nested/x.deb','back\\slash.deb']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                ca.member_name(tarfile.TarInfo(name))
        member=tarfile.TarInfo('alias.deb');member.type=tarfile.LNKTYPE;member.linkname='target'
        with self.assertRaises(ValueError):ca.member_name(member)
        with tempfile.TemporaryDirectory() as tmp,patch.object(ca,'stream',side_effect=lambda _:fixture_stream([('same.json',b'{}'),('same.json',b'{}')])):
            with self.assertRaises(ValueError):ca.metadata('a'*64,Path(tmp))

    def publish_fixture(self,entries,expected,upload):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp);artifacts=build/'candidate/artifacts';artifacts.mkdir(parents=True)
            (build/'candidate/stream-artifacts.json').write_text(json.dumps(dict(container='a'*64)))
            (artifacts/'inventory.json').write_text(json.dumps(dict(packages=[dict(file=n,sha256=hashlib.sha256(v).hexdigest()) for n,v in expected])))
            with patch('publish_candidates.stream',side_effect=lambda _:fixture_stream(entries)),patch('publish_candidates.subprocess.run',side_effect=upload):
                publish(build,'MannanSaood/termi-packages','1','1',bundle_limit=5)
            self.assertEqual([],list(artifacts.glob('*.deb')))
            self.assertEqual([],list(build.glob('packages-*.tar')))

    def test_streamed_bundles_match_inventory_and_stay_bounded(self):
        entries=[('one.deb',b'one'),('two.deb',b'two'),('three.deb',b'three')];collected={}
        def upload(command,**kw):
            if command[2]=='upload':
                path=next(Path(x) for x in command if str(x).endswith('.tar'))
                self.assertEqual(1,len(list(path.parent.parent.glob('packages-*.tar'))))
                with tarfile.open(path) as archive:
                    for member in archive:collected[member.name]=archive.extractfile(member).read()
        self.publish_fixture([('inventory.json',b'{}'),*entries],entries,upload)
        self.assertEqual(dict(entries),collected)

    def test_corrupt_missing_extra_duplicate_packages_never_finish_publication(self):
        expected=[('one.deb',b'one')]
        for entries in [[('one.deb',b'bad')],[],[('other.deb',b'one')],[*expected,*expected]]:
            uploads=[]
            def upload(command,**kw):
                if command[2]=='upload':uploads.append(command)
            with self.subTest(entries=entries),self.assertRaises(ValueError):
                self.publish_fixture(entries,expected,upload)
            self.assertEqual([],uploads)

    def test_docker_failure_is_not_silently_accepted(self):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w'):pass
        data.seek(0)
        class Process:
            stdout=data;args=['docker','cp']
            def wait(self,**kw):return 7
            def poll(self):return 7
        with patch.object(ca.subprocess,'Popen',return_value=Process()):
            with self.assertRaises(subprocess.CalledProcessError):
                with ca.stream('a'*64) as archive:list(archive)

    def test_invalid_container_never_executes_docker(self):
        with patch.object(ca.subprocess,'Popen') as process:
            with self.assertRaises(ValueError):
                with ca.stream('untrusted --option'):pass
            process.assert_not_called()

    def test_failed_upload_retains_bundle_inventory_and_container_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp);artifacts=build/'candidate/artifacts';artifacts.mkdir(parents=True)
            marker=build/'candidate/stream-artifacts.json';marker.write_text(json.dumps(dict(container='a'*64)))
            payload=b'package';(artifacts/'inventory.json').write_text(json.dumps(dict(packages=[dict(file='one.deb',sha256=hashlib.sha256(payload).hexdigest())])))
            def fail_upload(command,**kwargs):
                if command[2]=='upload':raise subprocess.CalledProcessError(1,command)
            with patch('publish_candidates.stream',side_effect=lambda _:fixture_stream([('one.deb',payload)])),patch('publish_candidates.subprocess.run',side_effect=fail_upload):
                with self.assertRaises(subprocess.CalledProcessError):publish(build,'repo','1','1')
            self.assertTrue(marker.is_file())
            self.assertTrue((artifacts/'inventory.json').is_file())
            self.assertEqual(1,len(list(build.glob('packages-*.tar'))))
            self.assertEqual(1,len(list((build/'release-upload').glob('*.tar'))))

    def test_streamed_low_disk_reserve_and_truncation_fail_closed(self):
        from collections import namedtuple
        usage=namedtuple('Usage','total used free')
        with patch('publish_candidates.shutil.disk_usage',return_value=usage(10,9,1)):
            with self.assertRaises(ValueError):
                self.publish_fixture([('one.deb',b'one')],[('one.deb',b'one')],lambda *a,**k:None)
        @contextmanager
        def truncated(_):
            with fixture_stream([('one.deb',b'one')]) as archive:yield archive
            raise tarfile.ReadError('truncated Docker transport')
        # The final bundle is not uploaded before transport completion succeeds.
        with patch('publish_candidates.stream',side_effect=truncated):
            # publish_fixture supplies its own stream; use direct setup here.
            with tempfile.TemporaryDirectory() as tmp:
                build=Path(tmp);a=build/'candidate/artifacts';a.mkdir(parents=True)
                (build/'candidate/stream-artifacts.json').write_text(json.dumps(dict(container='a'*64)))
                (a/'inventory.json').write_text(json.dumps(dict(packages=[dict(file='one.deb',sha256=hashlib.sha256(b'one').hexdigest())])))
                with patch('publish_candidates.subprocess.run') as upload:
                    with self.assertRaises(tarfile.ReadError):publish(build,'repo','1','1')
                    self.assertEqual(['create'],[c.args[0][2] for c in upload.call_args_list])
