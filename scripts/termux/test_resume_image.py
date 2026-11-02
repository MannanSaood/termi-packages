import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import resume_image
import build


class RestoredInputVerification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.context = self.root / 'context'
        self.context.mkdir()
        self.cached = self.root / 'cached'
        self.cached.mkdir()
        with tarfile.open(self.context / 'source.tar', 'w') as archive:
            for name, data in [('build-package.sh', b'original-script\n'),
                               ('packages/example/build.sh', b'original-recipe\n'),
                               ('packages/lrzsz/obsolete.patch', b'obsolete\n')]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo('recipe-link')
            link.type = tarfile.SYMTYPE
            link.linkname = 'packages/example/build.sh'
            archive.addfile(link)
        for name, data in [('overlay/packages/example/build.sh', b'checked-patched-recipe\n'),
                           ('build-in-container.sh', b'checked-runtime\n'),
                           ('seed/metadata.json', b'{"verified":true}\n'),
                           ('seed-output/dep.deb', b'non-executable archive integrity fixture\n')]:
            p = self.context / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self.dockerfile = self.context / 'Dockerfile'
        self.dockerfile.write_text('FROM pinned-image\nUSER root\n'
            'ADD --chown=builder:builder source.tar /home/builder/termux-packages/\n'
            'COPY --chown=builder:builder overlay/ /home/builder/termux-packages/\n'
            'RUN rm -- /home/builder/termux-packages/packages/lrzsz/obsolete.patch\n'
            'COPY --chown=builder:builder build-in-container.sh /home/builder/\n'
            'COPY --chown=builder:builder seed/ /home/builder/seed/\n'
            'COPY --chown=builder:builder seed-output/ /home/builder/termux-packages/output/\n'
            'RUN find /home/builder/termux-packages -name "*.sh" -exec chmod u+x {} +\n'
            'USER builder\nWORKDIR /home/builder/termux-packages\n'
            'ENTRYPOINT ["/bin/bash", "/home/builder/build-in-container.sh"]\n')

    def materialize(self):
        # Independent expected Docker ADD/COPY results; no generated manifest
        # is used to construct the filesystem that the verifier checks.
        for name, data in [('termux-packages/build-package.sh', b'original-script\n'),
                           ('termux-packages/packages/example/build.sh', b'checked-patched-recipe\n'),
                           ('build-in-container.sh', b'checked-runtime\n'),
                           ('seed/metadata.json', b'{"verified":true}\n'),
                           ('termux-packages/output/dep.deb', b'non-executable archive integrity fixture\n')]:
            p = self.cached / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.cached / 'termux-packages/recipe-link').symlink_to('packages/example/build.sh')

    def verify_locally(self, manifest):
        # Execute the production verifier unchanged except for its fixed home
        # boundary, relocated to this disposable test fixture.
        data = json.loads(json.dumps(manifest).replace('/home/builder', self.cached.as_posix()))
        code = resume_image.VERIFY.replace("'/home/builder'", repr(self.cached.as_posix()))
        return subprocess.run([sys.executable, '-c', code], input=json.dumps(data),
                              capture_output=True, text=True)

    def test_full_source_overlay_runtime_seed_and_output_content_verified(self):
        self.materialize()
        manifest = resume_image.expected_inputs(self.context)
        record = manifest['files']['/home/builder/termux-packages/packages/example/build.sh']
        self.assertEqual(hashlib.sha256(b'checked-patched-recipe\n').hexdigest(), record['sha256'])
        self.assertIn('/home/builder/termux-packages/output/dep.deb', manifest['files'])
        result = self.verify_locally(manifest)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(6, json.loads(result.stdout)['verified_files'])

    def test_changed_runtime_rejected_without_modifying_compiler_cache(self):
        self.materialize()
        manifest = resume_image.expected_inputs(self.context)
        cache = self.cached / '.termux-build/compiler-object.o'
        cache.parent.mkdir()
        cache.write_bytes(b'preserved compiler cache fixture')
        (self.cached / 'build-in-container.sh').write_bytes(b'changed-runtime\n')
        result = self.verify_locally(manifest)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b'preserved compiler cache fixture', cache.read_bytes())

    def test_changed_source_symlink_missing_seed_and_reappeared_deletion_rejected(self):
        self.materialize()
        manifest = resume_image.expected_inputs(self.context)
        link = self.cached / 'termux-packages/recipe-link'
        link.unlink()
        link.symlink_to('other-recipe')
        self.assertNotEqual(0, self.verify_locally(manifest).returncode)
        link.unlink()
        link.symlink_to('packages/example/build.sh')
        seed = self.cached / 'seed/metadata.json'
        seed.unlink()
        self.assertNotEqual(0, self.verify_locally(manifest).returncode)
        seed.write_bytes(b'{"verified":true}\n')
        obsolete = self.cached / 'termux-packages/packages/lrzsz/obsolete.patch'
        obsolete.parent.mkdir()
        obsolete.write_bytes(b'obsolete\n')
        self.assertNotEqual(0, self.verify_locally(manifest).returncode)

    def test_unrecognized_docker_instruction_and_escaping_tar_rejected(self):
        original = self.dockerfile.read_text()
        self.dockerfile.write_text(original + 'RUN unexpected-input-change\n')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            resume_image.expected_inputs(self.context)
        self.dockerfile.write_text(original)
        with tarfile.open(self.context / 'source.tar', 'w') as archive:
            info = tarfile.TarInfo('../outside')
            info.size = 1
            archive.addfile(info, io.BytesIO(b'x'))
        with self.assertRaisesRegex(ValueError, 'escapes'):
            resume_image.expected_inputs(self.context)

    def test_probe_is_unprivileged_bounded_read_only_and_does_not_build_image(self):
        manifest = resume_image.expected_inputs(self.context)
        response = dict(verified_files=len(manifest['files']), verified_absent=len(manifest['absent']))
        proof = self.root / 'proof.json'
        with patch.object(resume_image.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(response).encode(), b'')) as run:
            resume_image.verify_restored_inputs('verified-restored-image', self.context, proof)
        args, kwargs = run.call_args
        command = args[0]
        self.assertEqual(['docker', 'run'], command[:2])
        for flag, value in [('--network', 'none'), ('--memory', '512m'), ('--cpus', '1'), ('--user', 'builder')]:
            self.assertEqual(value, command[command.index(flag) + 1])
        self.assertNotIn('--mount', command)
        self.assertIn('--read-only', command)
        self.assertNotIn('build', command)
        self.assertEqual(300, kwargs['timeout'])
        self.assertTrue(kwargs['check'])
        self.assertEqual(response['verified_files'], json.loads(proof.read_text())['verified_files'])

    def test_failed_probe_never_produces_success_proof(self):
        proof = self.root / 'proof.json'
        with patch.object(resume_image.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['docker'])):
            with self.assertRaises(subprocess.CalledProcessError):
                resume_image.verify_restored_inputs('verified-restored-image', self.context, proof)
        self.assertFalse(proof.exists())

    def test_driver_reuses_only_verified_image_and_does_not_fall_back_on_drift(self):
        with patch.object(resume_image, 'verify_restored_inputs') as verify, patch.object(build, 'run') as run:
            image = build.candidate_image_after_identity_check(self.context, 'restored-image', self.root / 'proof.json')
            self.assertEqual('restored-image', image)
            verify.assert_called_once_with('restored-image', self.context, self.root / 'proof.json')
            run.assert_not_called()
        with patch.object(resume_image, 'verify_restored_inputs', side_effect=ValueError('input drift')), patch.object(build, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'input drift'):
                build.candidate_image_after_identity_check(self.context, 'restored-image', self.root / 'proof.json')
            run.assert_not_called()

    def test_fresh_driver_build_still_uses_original_docker_build_path(self):
        with patch.object(resume_image, 'verify_restored_inputs') as verify, patch.object(build, 'run') as run:
            image = build.candidate_image_after_identity_check(self.context, None, self.root / 'proof.json')
            self.assertTrue(image.startswith('termi-termux-candidate:'))
            run.assert_called_once_with(['docker', 'build', '--tag', image, str(self.context)])
            verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
