import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import merge_releases
from seed import digest
import test_parallel_catalog


class StreamingMergeTests(unittest.TestCase):
    def test_incremental_merge_reclaims_inputs_and_keeps_all_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture=test_parallel_catalog.MergeTests()
            first=fixture.candidate(root/'source0','ab')
            second=fixture.candidate(root/'source1','bc',b'alternate source build')
            third=fixture.candidate(root/'source2','a',b'third build')
            entries=[]
            for index,value in enumerate([first,second,third]):
                entries.append(dict(tag=f'candidate-{index+1}-1-0',inventory_sha256=value[1],ledger_sha256=value[2],plan_sha256=value[3]))
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps(dict(repository='MannanSaood/termi-packages',duplicate_policy='prefer-first-compatible-parent',candidates=entries,required_completed_recipes=list('abc'))))
            downloads=[]
            def fake_command(command,**kwargs):
                if command[1:3]==['release','download']:
                    index=int(command[3].split('-')[1])-1
                    directory=Path(command[command.index('--dir')+1])
                    if downloads:
                        self.assertFalse(downloads[-1].exists())
                    downloads.append(directory)
                    for source in (root/f'source{index}').iterdir():
                        shutil.copyfile(source,directory/source.name)
            previous=Path.cwd()
            try:
                os.chdir(root)
                with patch.object(sys,'argv',['merge','--manifest',str(manifest),'--output','build/merged','--tag','candidate-99-1-0']),patch.object(merge_releases,'run',return_value='{"visibility":"PUBLIC"}'),patch.object(merge_releases.subprocess,'run',side_effect=fake_command):
                    merge_releases.main()
                inventory=json.loads(Path('build/merged/inventory.json').read_text())
                ledger=json.loads(Path('build/merged/catalog-ledger.json').read_text())
                self.assertEqual(3,len(inventory['packages']))
                self.assertEqual(3,len(inventory['source_candidates']))
                self.assertEqual(inventory['source_candidates'],ledger['source_candidates'])
                self.assertEqual(2,len(inventory['alternate_builds']))
                for record in inventory['packages']:
                    self.assertEqual(record['sha256'],digest(Path('build/merged')/record['file']))
                self.assertFalse(any(Path('build/merge-working').iterdir()))
            finally:
                os.chdir(previous)
