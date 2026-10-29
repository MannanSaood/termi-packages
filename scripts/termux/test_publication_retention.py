import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from build_scratch import configure_diagnostics
from reclaim_bundles import reclaim
from verify_restart import verify_checkpoint_manifest


class PublicationRetentionTests(unittest.TestCase):
    def test_checkpoint_gate_requires_every_uploaded_part(self):
        manifest = dict(schema=1, input_identity='a'*64,
                        parts=[dict(file='checkpoint-0000.gz.part', bytes=4, sha256='b'*64)])
        asset = dict(name='checkpoint-0000.gz.part', size=4, state='uploaded', digest='sha256:'+'b'*64)
        verify_checkpoint_manifest(manifest, [asset])
        for assets in [[], [dict(asset, size=3)], [dict(asset, digest='sha256:'+'c'*64)]]:
            with self.assertRaises(ValueError):
                verify_checkpoint_manifest(manifest, assets)

    def test_only_uploaded_bundle_copies_are_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp) / 'build'
            upload = build / 'release-upload'
            upload.mkdir(parents=True)
            bundle = build / 'packages-0000.tar'
            bundle.write_bytes(b'bundle')
            link = upload / '0014-packages-0000.tar'
            os.link(bundle, link)
            original = build / 'package.deb'
            original.write_bytes(b'original')
            log = upload / '0006-build.log'
            log.write_bytes(b'log')
            self.assertEqual(1, reclaim(build, [bundle]))
            self.assertFalse(bundle.exists())
            self.assertFalse(link.exists())
            self.assertEqual(b'original', original.read_bytes())
            self.assertEqual(b'log', log.read_bytes())

    def test_conflicting_upload_copy_prevents_all_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            upload = build / 'release-upload'
            upload.mkdir()
            bundle = build / 'packages-0000.tar'
            bundle.write_bytes(b'original')
            link = upload / '0001-packages-0000.tar'
            link.write_bytes(b'different')
            with self.assertRaises(ValueError):
                reclaim(build, [bundle])
            self.assertEqual(b'original', bundle.read_bytes())
            with self.assertRaises(ValueError):
                reclaim(build, [upload / '..' / '..' / 'packages-0000.tar'])

    def test_checkpoint_pipeline_returns_python_failure(self):
        workflow = (Path(__file__).parents[2] / '.github/workflows/termi_free_packages.yml').read_text()
        body = workflow.split('      - name: Preserve catalog or interrupted build as streamed release checkpoint')[1]
        script = body.split('        run: |\n')[1]
        script = '\n'.join(line[10:] for line in script.splitlines())
        bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        if not bash:
            self.skipTest('Bash unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'build/candidate').mkdir(parents=True)
            (root / 'build/candidate/container-id.txt').write_text('container')
            (root / 'build/candidate/build-input-identity.txt').write_text('identity')
            # Execute the actual workflow snippet with a failed exporter.
            script = 'python3() { return 7; }\nexport GITHUB_REPOSITORY=repo GITHUB_RUN_ID=1 GITHUB_RUN_ATTEMPT=1\n' + script
            result = subprocess.run([bash, '-c', script], cwd=root, capture_output=True)
            self.assertEqual(7, result.returncode, result.stderr)

    def test_configure_failure_survives_in_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / '.termux-build'
            source = top / 'mkvtoolnix/src/config.log'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'first probe\nreal error: missing declaration\xff\n')
            output = Path(tmp) / 'artifacts/configure-mkvtoolnix.log'
            self.assertEqual(1, configure_diagnostics(top, 'mkvtoolnix', output))
            self.assertIn(source.read_bytes(), output.read_bytes())
            self.assertEqual(0, configure_diagnostics(top, 'other', output.with_name('absent.log')))
            self.assertFalse(output.with_name('absent.log').exists())
            with self.assertRaises(ValueError):
                configure_diagnostics(top, '../mkvtoolnix', output)

    def test_large_diagnostic_keeps_head_and_tail_with_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / '.termux-build'
            source = top / 'recipe/build/config.log'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'HEAD' + b'x' * (2 * 1024 * 1024) + b'TAIL')
            output = Path(tmp) / 'configure.log'
            configure_diagnostics(top, 'recipe', output)
            data = output.read_bytes()
            self.assertIn(b'HEAD', data)
            self.assertTrue(data.endswith(b'TAIL'))
            self.assertIn(b'MIDDLE OMITTED', data)
            self.assertLess(len(data), 1024 * 1024 + 200)
