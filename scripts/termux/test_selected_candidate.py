import copy
import unittest
from selected_candidate import ledger_from_progress


class SelectedCandidateTests(unittest.TestCase):
    def inputs(self):
        pins = dict(inventory='1'*64, ledger='2'*64, plan='3'*64)
        plan = dict(identity='source', recipes={n: dict(initial_status='pending') for n in ['seeded', 'good', 'bad']})
        original = dict(file='seeded.deb', recipe='seeded', sha256='4'*64, control='source control')
        inventory = dict(packages=[original, dict(file='good.deb', recipe='good', sha256='5'*64)])
        progress = dict(schema=1, scope='requested-roots', approved=False, current=[], total_recipes=2,
                        counts=dict(built=1, failed=1), completed_recipes=['good'],
                        failures=[dict(recipe='bad',status='failed',exit_code=1)])
        receipt = dict(schema=1, status='source-build-cache-not-runtime-approval', new_graph_identity='source',
                       inventory_sha256=pins['inventory'], ledger_sha256=pins['ledger'], graph_sha256=pins['plan'],
                       recipes=['seeded'], packages=[copy.deepcopy(original)])
        run = dict(status='in_progress', jobs=[dict(steps=[
            dict(name='Compile bounded source batch with time left for checkpoint export',status='completed',conclusion='failure'),
            dict(name='Publish candidate evidence to Releases, never the live APT repo',status='completed',conclusion='success')])])
        return [plan,inventory,progress,receipt,pins,run,123]

    def test_partial_success_preserves_failures_and_seeded_bytes(self):
        value=ledger_from_progress(*self.inputs())
        self.assertEqual(['good'],value['verified_completed_roots'])
        self.assertEqual('built',value['recipes']['seeded']['status'])
        self.assertEqual('failed',value['recipes']['bad']['status'])
        self.assertTrue(value['candidate_only'])

    def test_publication_and_compilation_must_be_finished(self):
        for step,field,value in [(0,'status','in_progress'),(1,'conclusion','failure')]:
            args=self.inputs();args[5]['jobs'][0]['steps'][step][field]=value
            with self.assertRaises(ValueError):ledger_from_progress(*args)

    def test_failed_root_archive_cannot_be_promoted(self):
        args=self.inputs();args[1]['packages'].append(dict(file='bad.deb',recipe='bad',sha256='6'*64))
        with self.assertRaises(ValueError):ledger_from_progress(*args)

    def test_changed_seed_archive_is_rejected(self):
        args=self.inputs();args[1]['packages'][0]['sha256']='7'*64
        with self.assertRaises(ValueError):ledger_from_progress(*args)

    def test_wrong_seed_or_graph_receipt_is_rejected(self):
        for key in ['new_graph_identity','inventory_sha256']:
            args=self.inputs();args[3][key]='wrong'
            with self.assertRaises(ValueError):ledger_from_progress(*args)

    def test_incomplete_or_ambiguous_success_snapshot_is_rejected(self):
        for field,value in [('current',['good']),('completed_recipes',['good','good']),('failures',[])]:
            args=self.inputs();args[2][field]=value
            with self.assertRaises(ValueError):ledger_from_progress(*args)
