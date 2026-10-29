import json
import shutil
import tempfile
import unittest
from pathlib import Path

from build import input_identity, reclaim_workflow_archives
import seed


class SeedOutputLayout(unittest.TestCase):
    def context(self, root):
        context = root / 'context'
        pool = context / 'seed/pool'
        pool.mkdir(parents=True)
        records = []
        for name, content in [('a_1_all.deb', b'aaaa'), ('b_1_all.deb', b'bbbbbb')]:
            path = pool / name
            path.write_bytes(content)
            records.append(dict(file=name, original_file=name, sha256=seed.digest(path)))
        (context / 'seed/seed.json').write_text(json.dumps(dict(packages=records)))
        (context / 'Dockerfile').write_text('FROM pinned-builder\n'
            'COPY --chown=builder:builder seed/ /home/builder/seed/\n')
        return context, records

    def test_one_image_copy_and_same_workflow_builder_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context, records = self.context(root)
            other = root / 'workflow-context'
            shutil.copytree(context, other)
            receipt = (context / 'seed/seed.json').read_bytes()
            self.assertEqual(10, seed.stage_output_archives(context))
            self.assertEqual(10, seed.stage_output_archives(other))
            self.assertEqual(input_identity(context), input_identity(other))
            self.assertEqual(receipt, (context / 'seed/seed.json').read_bytes())
            self.assertFalse((context / 'seed/pool').exists())
            self.assertEqual(2, len(list(context.rglob('*.deb'))))
            self.assertIn('seed-output/ /home/builder/termux-packages/output/',
                          (context / 'Dockerfile').read_text())
            builder = root / 'builder'
            shutil.copytree(context / 'seed-output', builder / 'output')
            for record in records:
                # The exact bytes Docker preloads are the archive used by the
                # importer, without an extra seed/pool -> output copy.
                archive = seed.verified_archive(context / 'seed', builder, record)
                self.assertEqual(builder / 'output' / record['original_file'], archive)
                self.assertEqual(record['sha256'], seed.digest(archive))
            (builder / 'output' / records[0]['original_file']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                seed.verified_archive(context / 'seed', builder, records[0])

    def test_invalid_staging_never_moves_an_archive(self):
        for invalid in ['hash', 'traversal', 'duplicate', 'unlisted', 'dockerfile']:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                context, records = self.context(Path(tmp))
                if invalid == 'hash':
                    records[0]['sha256'] = '0' * 64
                elif invalid == 'traversal':
                    records[0]['original_file'] = '../outside.deb'
                elif invalid == 'duplicate':
                    records[1]['original_file'] = records[0]['original_file']
                elif invalid == 'unlisted':
                    (context / 'seed/pool/extra.deb').write_bytes(b'preserve')
                else:
                    (context / 'Dockerfile').write_text('changed source')
                (context / 'seed/seed.json').write_text(json.dumps(dict(packages=records)))
                with self.assertRaises(ValueError):
                    seed.stage_output_archives(context)
                self.assertTrue((context / 'seed/pool/a_1_all.deb').is_file())
                self.assertTrue((context / 'seed/pool/b_1_all.deb').is_file())
                self.assertFalse((context / 'seed-output').exists())

    def test_old_seed_layout_still_verifies_and_new_host_copy_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context, records = self.context(root / 'build')
            self.assertEqual(context / 'seed/pool/a_1_all.deb',
                seed.verified_archive(context / 'seed', root / 'builder', records[0]))
            seed.stage_output_archives(context)
            metadata = (context / 'seed/seed.json').read_bytes()
            self.assertEqual(10, reclaim_workflow_archives(root, context, None))
            self.assertFalse(list((context / 'seed-output').glob('*.deb')))
            self.assertEqual(metadata, (context / 'seed/seed.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
