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
    def test_mixed_focused_candidate_requires_pinned_final_root_proofs(self):
        self.mixed_candidate()

    def test_mixed_dependency_outputs_require_pinned_native_log(self):
        self.mixed_candidate(dependencies=True)

    def test_mixed_dependency_log_hash_mismatch_is_rejected(self):
        self.mixed_candidate(dependencies=True,corrupt_log=True)

    def mixed_candidate(self,dependencies=False,corrupt_log=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            value=test_parallel_catalog.MergeTests().candidate(root/'source','ab')
            directory=root/'source'
            plan=json.loads((directory/'catalog-plan.json').read_text())
            inventory=json.loads((directory/'inventory.json').read_text())
            base=dict(inventory='1'*64,ledger='2'*64,plan='3'*64)
            receipt=dict(schema=1,status='source-build-cache-not-runtime-approval',new_graph_identity=plan['identity'],
                         inventory_sha256=base['inventory'],ledger_sha256=base['ledger'],graph_sha256=base['plan'],
                         recipes=['a'],packages=[r for r in inventory['packages'] if r['recipe']=='a'])
            if dependencies:
                plan['recipes']['b']['dependencies']=['a']
                (directory/'catalog-plan.json').write_text(json.dumps(plan))
                value[3]=digest(directory/'catalog-plan.json')
                receipt.update(recipes=[],packages=[])
            progress=dict(schema=1,scope='requested-roots',approved=False,current=[],total_recipes=2,
                          counts=dict(built=1,failed=1),completed_recipes=['b'],
                          failures=[dict(recipe='c',status='failed',exit_code=1)])
            for name,content in [('progress.json',progress),('seed-provenance.json',receipt)]:
                (directory/name).write_text(json.dumps(content))
            entry=dict(tag='candidate-1-1-0',inventory_sha256=value[1],plan_sha256=value[3],
                       selected_progress=dict(progress_sha256=digest(directory/'progress.json'),
                           seed_provenance_sha256=digest(directory/'seed-provenance.json'),base_seed=base))
            if dependencies:
                (directory/'build.log').write_text("termux - build of 'a' done\ntermux - build of 'b' done\n")
                entry['selected_progress']['build_log_sha256']=digest(directory/'build.log')
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps(dict(repository='MannanSaood/termi-packages',candidates=[entry],required_completed_recipes=['a','b'])))
            state=dict(status='in_progress',jobs=[dict(steps=[
                dict(name='Compile bounded source batch with time left for checkpoint export',status='completed',conclusion='failure'),
                dict(name='Publish candidate evidence to Releases, never the live APT repo',status='completed',conclusion='success')])])
            def read(command):
                return json.dumps(state if command[1:3]==['run','view'] else dict(visibility='PUBLIC'))
            def command(args,**kwargs):
                if args[1:3]==['release','download']:
                    if dependencies:self.assertIn('*build.log',args)
                    target=Path(args[args.index('--dir')+1])
                    for source in directory.iterdir():shutil.copyfile(source,target/source.name)
                    if corrupt_log:(target/'build.log').write_text('tampered log')
            previous=Path.cwd()
            try:
                os.chdir(root)
                with patch.object(sys,'argv',['merge','--manifest',str(manifest),'--output','build/merged','--tag','candidate-99-1-0']),patch.object(merge_releases,'run',side_effect=read),patch.object(merge_releases.subprocess,'run',side_effect=command):
                    if corrupt_log:
                        with self.assertRaisesRegex(ValueError,'hash-pinned'):merge_releases.main()
                        return
                    merge_releases.main()
                ledger=json.loads(Path('build/merged/catalog-ledger.json').read_text())
                self.assertEqual({'a','b'},{n for n,r in ledger['recipes'].items() if r['status']=='built'})
                self.assertEqual('failed',ledger['recipes']['c']['status'])
            finally:os.chdir(previous)

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
