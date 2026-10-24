import os
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from build import reclaim_workflow_archives
from catalog_build import DiskPressure, guarded_wait
import catalog_build


class ResourceGuards(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Linux compiler process groups')
    def test_disk_halt_kills_recipe_and_persists_recoverable_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ['upstream.lock.json','source.json','patches.json']:
                (root/name).write_text('{}')
            (root/'build-package.sh').write_text('#!/bin/bash\nsleep 60\n')
            plan=dict(identity='guard-fixture',configuration={},recipes={
                'resource-fixture':dict(path='packages/resource-fixture',dependencies=[],rank=0,initial_status='pending')})
            with patch.object(catalog_build,'create_plan',return_value=plan), patch(
                    'catalog_build.shutil.disk_usage',side_effect=[
                        SimpleNamespace(free=20*1024**3),SimpleNamespace(free=7*1024**3)]):
                self.assertEqual(75,catalog_build.build(root,root,root/'state',minimum_free_gib=16))
            ledger=json.loads((root/'state/ledger.json').read_text())
            self.assertEqual('insufficient-builder-disk-during-recipe',ledger['halt'])
            entry=ledger['recipes']['resource-fixture']
            self.assertEqual('interrupted',entry['status'])
            self.assertFalse(entry['compile_resume_available'])

    def test_single_large_recipe_is_stopped_when_free_space_drops(self):
        process = Mock(args=['compiler'])
        process.wait.side_effect = [subprocess.TimeoutExpired('compiler', 5), 0]
        with patch('catalog_build.shutil.disk_usage', side_effect=[
                SimpleNamespace(free=12*1024**3), SimpleNamespace(free=7*1024**3)]):
            with self.assertRaises(DiskPressure):
                guarded_wait(process, Path('.'), 100, 16)
        self.assertEqual(1, process.wait.call_count)

    def test_completed_recipe_returns_actual_exit_code(self):
        process = Mock(args=['compiler'])
        process.wait.return_value = 7
        with patch('catalog_build.shutil.disk_usage', return_value=SimpleNamespace(free=12*1024**3)):
            self.assertEqual(7, guarded_wait(process, Path('.'), 100, 16))

    def test_reclaim_keeps_metadata_and_rejects_paths_outside_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pool = root/'build/candidate/context/seed/pool'
            pool.mkdir(parents=True)
            (pool/'fixture.deb').write_bytes(b'candidate')
            (pool/'inventory.json').write_text('{}')
            self.assertEqual(9, reclaim_workflow_archives(root, root/'build/candidate/context', None))
            self.assertTrue((pool/'inventory.json').exists())
            outside = root/'personal'
            outside.mkdir()
            (outside/'keep.deb').write_bytes(b'keep')
            with self.assertRaises(ValueError):
                reclaim_workflow_archives(root, root/'build/candidate/context', outside)
            self.assertTrue((outside/'keep.deb').exists())

    @unittest.skipUnless(os.name == 'posix', 'Linux builder aliases')
    def test_reclaim_rejects_symlink_before_deleting_any_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            pool=root/'build/candidate/context/seed/pool'
            pool.mkdir(parents=True)
            (pool/'keep.deb').write_bytes(b'keep')
            (pool/'alias').symlink_to(root)
            with self.assertRaises(ValueError):
                reclaim_workflow_archives(root, root/'build/candidate/context', None)
            self.assertTrue((pool/'keep.deb').exists())


if __name__ == '__main__':
    unittest.main()
