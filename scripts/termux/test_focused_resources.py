import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import seed
import selected_guard
from catalog_build import DiskPressure
from catalog_progress import selected_event


class FocusedResources(unittest.TestCase):
    def test_subset_receipt_keeps_pins_and_cannot_be_imported_as_full_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, context = root / 'raw', root / 'context'
            raw.mkdir(); context.mkdir()
            config = dict(lock={}, source={}, patches=[])
            plan = dict(identity='source', configuration=config, recipes={
                'swift': dict(path='packages/swift', dependencies=['cxx']),
                'cxx': dict(path='packages/cxx', dependencies=[]),
                'other': dict(path='packages/other', dependencies=[])})
            ledger = dict(identity=['source', 'runner'], recipes={
                'swift': dict(status='pending'), 'cxx': dict(status='built'), 'other': dict(status='built')})
            records = []
            for name in ['cxx', 'other']:
                archive = raw / (name + '.deb'); archive.write_bytes(name.encode())
                records.append(dict(recipe=name, file=archive.name, sha256=seed.digest(archive)))
            inventory = dict(packages=records)
            for filename, value in [('inventory.json', inventory), ('catalog-plan.json', plan), ('catalog-ledger.json', ledger)]:
                (raw / filename).write_text(json.dumps(value))
            for filename, key in [('upstream.lock.json', 'lock'), ('source.json', 'source'), ('patches.json', 'patches')]:
                (context / filename).write_text(json.dumps(config[key]))
            pins = [seed.digest(raw / n) for n in ['inventory.json', 'catalog-ledger.json', 'catalog-plan.json']]
            output = context / 'seed'
            with patch.object(seed, 'expand_bundles'):
                seed.prepare(raw, context, raw / 'catalog-plan.json', output, *pins, ['swift'])
            receipt = json.loads((output / 'seed.json').read_text())
            self.assertEqual(['cxx'], receipt['recipes'])
            self.assertEqual(['swift'], receipt['dependency_roots'])
            self.assertEqual(records[:1], receipt['packages'])
            self.assertEqual(inventory, json.loads((output / 'old-inventory.json').read_text()))
            self.assertTrue((raw / 'other.deb').is_file())
            with patch('catalog_graph.create_plan', return_value=plan), self.assertRaisesRegex(ValueError, 'roots differ'):
                seed.install(output, root, context, root / 'artifacts')
            receipt['packages'].append(records[1])
            (output / 'seed.json').write_text(json.dumps(receipt))
            with patch('catalog_graph.create_plan', return_value=plan), self.assertRaisesRegex(ValueError, 'receipt changed'):
                seed.install(output, root, context, root / 'artifacts', ['swift'])

    def test_dependency_selection_requires_complete_compatible_transitive_closure(self):
        plan = dict(recipes={
            'swift': dict(dependencies=['compiler', 'cxx']),
            'compiler': dict(dependencies=['cxx']),
            'cxx': dict(dependencies=[]), 'unrelated': dict(dependencies=[])})
        allowed = {'compiler', 'cxx', 'unrelated'}
        original = copy.deepcopy(plan)
        self.assertEqual({'compiler', 'cxx'}, seed.selected_recipes(plan, allowed, ['swift']))
        self.assertEqual(allowed, seed.selected_recipes(plan, allowed, []))
        with self.assertRaisesRegex(ValueError, 'every compatible completed dependency'):
            seed.selected_recipes(plan, {'compiler'}, ['swift'])
        with self.assertRaisesRegex(ValueError, 'Unknown dependency seed root'):
            seed.selected_recipes(plan, allowed, ['unknown'])
        self.assertEqual(original, plan)
        self.assertEqual(['swift'], seed.dependency_roots('packages', ['swift']))
        self.assertEqual([], seed.dependency_roots('full-catalog', ['swift']))
        self.assertEqual(['other', 'swift'], seed.dependency_roots('packages', ['swift', 'other', 'swift']))
        self.assertEqual(['other'], seed.dependency_roots('packages', ['other']))

    def test_focused_multi_root_seed_omits_unrelated_packages_but_keeps_shared_dependencies(self):
        plan = dict(recipes={
            'apache2': dict(dependencies=['apr', 'semaphore']),
            'tool': dict(dependencies=['apr']),
            'apr': dict(dependencies=['uuid']),
            'semaphore': dict(dependencies=[]), 'uuid': dict(dependencies=[]),
            'unrelated': dict(dependencies=[])})
        allowed = {'apr', 'uuid', 'semaphore', 'unrelated'}
        roots = seed.dependency_roots('packages', ['tool', 'apache2'])
        self.assertEqual({'apr', 'uuid', 'semaphore'}, seed.selected_recipes(plan, allowed, roots))
        with self.assertRaisesRegex(ValueError, 'every compatible completed dependency'):
            seed.selected_recipes(plan, allowed - {'uuid'}, roots)

    @unittest.skipUnless(os.name == 'posix', 'Linux process groups')
    def test_disk_interruption_kills_compiler_and_retains_truthful_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            selected_event(state, ['swift'], 'swift', 'running')
            processes = []
            def disk_stop(process, *args):
                processes.append(process)
                raise DiskPressure('Insufficient disk during recipe compilation', 15 * 1024**3)
            with patch.object(selected_guard, 'guarded_wait', side_effect=disk_stop):
                result = selected_guard.supervise([sys.executable, '-c', 'import time; time.sleep(60)'],
                    state, state / 'selected-interruption.json', 60, 16)
            self.assertEqual(75, result)
            self.assertIsNotNone(processes[0].poll())
            selected_event(state, ['swift'], 'swift', 'interrupted', result)
            ledger = json.loads((state / 'selected-ledger.json').read_text())
            self.assertEqual('interrupted', ledger['recipes']['swift']['status'])
            self.assertEqual(15 * 1024**3, ledger['recipes']['swift']['disk_free_bytes_at_stop'])
            self.assertTrue(ledger['recipes']['swift']['compile_resume_available'])

    @unittest.skipUnless(os.name == 'posix', 'Linux process groups')
    def test_budget_expiration_stops_before_next_root_and_success_is_not_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / 'selected-interruption.json'
            with patch.object(selected_guard.subprocess, 'Popen') as start:
                self.assertEqual(124, selected_guard.supervise(['never-run'], root, evidence, 0, 16))
                start.assert_not_called()
            self.assertEqual(124, json.loads(evidence.read_text())['exit_code'])
            # Successful continuation must not inherit the old halt marker.
            with patch('catalog_build.shutil.disk_usage', return_value=SimpleNamespace(free=20*1024**3)):
                self.assertEqual(0, selected_guard.supervise([sys.executable, '-c', 'pass'], root, evidence, 10, 16))
            self.assertFalse(evidence.exists())
