import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import catalog_build as builder
from catalog_graph import order_and_cycles


class GraphTests(unittest.TestCase):
    def test_focused_swift_wait_does_not_take_independent_lane_work(self):
        self.assertEqual('focused-swift',builder.shared_build_wait('swift','lane-5-of-8',{'swift','app'}))
        self.assertIsNone(builder.shared_build_wait('app','lane-5-of-8',{'swift','app'}))
        self.assertIsNone(builder.shared_build_wait('swift',None,{'swift'}))
        self.assertIsNone(builder.shared_build_wait('swift','lane-1-of-4',{'swift'}))
        self.assertEqual('lane-3-of-8',builder.shared_build_wait('qt6-qtdeclarative','lane-5-of-8',set()))
        self.assertIsNone(builder.shared_build_wait('qt6-qtdeclarative','lane-3-of-8',{'qt6-qtdeclarative'}))

    def test_common_frontier_has_one_owner_across_eight_lanes(self):
        names=['libkdcraw','imagemagick','libpangomm-2.48','kf6-kimageformats',
               'libzim','openimageio','recoll','libatkmm-1.6','libxml++-2.6',
               'libpangomm-1.4','gegl']
        recipes={name:dict(dependencies=[]) for name in names}
        recipes.update({f'app{i}':dict(dependencies=names) for i in range(8)})
        counts={name:0 for name in names}
        for lane in range(8):
            label=f'lane-{lane}-of-8'
            owned,selected=builder.lane_scope(recipes,label)
            for name in names:
                if name in selected and builder.shared_build_wait(name,label,owned) is None:
                    self.assertIn(name,owned)
                    counts[name]+=1
        self.assertEqual(dict.fromkeys(names,1),counts)
        self.assertEqual('focused-alsa-plugins',builder.shared_build_wait('alsa-plugins','lane-0-of-8',{'alsa-plugins'}))
        self.assertIsNone(builder.shared_build_wait('alsa-plugins',None,{'alsa-plugins'}))

    @unittest.skipUnless(os.name == 'posix', 'Linux isolated lane runner')
    def test_shared_dependency_waits_for_seed_while_independent_work_continues(self):
        with tempfile.TemporaryDirectory() as temporary:
            names=[f'fixture-{i}' for i in range(100)]
            owned,_=builder.lane_scope({n:dict(dependencies=[]) for n in names},'lane-1-of-8')
            app,independent=sorted(owned)[:2]
            plan=dict(identity='shared-fixture',configuration={},recipes={
                'qt6-qtdeclarative':dict(path='packages/qt6-qtdeclarative',dependencies=[],rank=0,initial_status='pending'),
                app:dict(path='packages/'+app,dependencies=['qt6-qtdeclarative'],rank=1,initial_status='pending'),
                independent:dict(path='packages/'+independent,dependencies=[],rank=2,initial_status='pending')})
            for seeded in (False,True):
                root=Path(temporary)/str(seeded);root.mkdir()
                for name in ['upstream.lock.json','source.json','patches.json']:
                    (root/name).write_text('{}')
                (root/'build-package.sh').write_text('#!/bin/bash\necho "${@: -1}" >> executed\n')
                if seeded:
                    (root/'artifacts').mkdir()
                    (root/'artifacts/seed-provenance.json').write_text(json.dumps(dict(
                        new_graph_identity='shared-fixture',recipes=['qt6-qtdeclarative'],inventory_sha256='fixture')))
                with patch.object(builder,'create_plan',return_value=plan):
                    self.assertEqual(0 if seeded else 1,builder.build(root,root,root/'state',minimum_free_gib=0,lane='lane-1-of-8'))
                executed=set((root/'executed').read_text().splitlines())
                self.assertEqual({'packages/'+independent}|({'packages/'+app} if seeded else set()),executed)
                ledger=json.loads((root/'state/ledger.json').read_text())
                self.assertEqual('built' if seeded else 'deferred-shared-build',ledger['recipes']['qt6-qtdeclarative']['status'])

    def test_disk_guard_keeps_full_configured_reserve_during_compilation(self):
        process=Mock()
        with patch.object(builder.shutil,'disk_usage',return_value=Mock(free=12*1024**3)):
            with self.assertRaises(builder.DiskPressure):
                builder.guarded_wait(process,Path('.'),60,16)
        process.wait.assert_not_called()
        process.wait.return_value=0
        with patch.object(builder.shutil,'disk_usage',return_value=Mock(free=20*1024**3)):
            self.assertEqual(0,builder.guarded_wait(process,Path('.'),60,16))
        self.assertLessEqual(process.wait.call_args.kwargs['timeout'],1)

    @unittest.skipUnless(os.name == "posix", "Linux isolated lane runner")
    def test_lane_executes_only_owned_independent_roots_and_cannot_restore_another_lane(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ["upstream.lock.json","source.json","patches.json"]:
                (root/name).write_text("{}")
            (root/"build-package.sh").write_text('#!/bin/bash\nprintf "%s\\n" "${@: -1}" >> executed\n')
            plan=dict(identity="lane-fixture",configuration={},recipes={
                f"fixture-{i}":dict(path=f"packages/fixture-{i}",dependencies=[],rank=i,initial_status="pending") for i in range(20)})
            owned,_=builder.lane_scope(plan["recipes"],"lane-0-of-4")
            with patch.object(builder,"create_plan",return_value=plan):
                self.assertEqual(0,builder.build(root,root,root/"state",minimum_free_gib=0,lane="lane-0-of-4"))
                self.assertEqual({"packages/"+n for n in owned},set((root/"executed").read_text().splitlines()))
                with self.assertRaisesRegex(ValueError,"lane differs"):
                    builder.build(root,root,root/"state",minimum_free_gib=0,lane="lane-1-of-4")

    def test_parallel_lanes_own_every_root_once_and_include_all_dependencies(self):
        recipes = {str(i): dict(dependencies=[str(i-1)] if i else []) for i in range(30)}
        owners = []
        for lane in range(8):
            owned, selected = builder.lane_scope(recipes,f"lane-{lane}-of-8")
            owners.extend(owned)
            self.assertTrue(owned <= selected)
            for name in selected:
                self.assertTrue(set(recipes[name]["dependencies"]) <= selected)
            self.assertEqual((owned,selected),builder.lane_scope(recipes,f"lane-{lane}-of-8"))
        self.assertEqual(set(recipes),set(owners))
        self.assertEqual(len(recipes),len(owners))
        for invalid in ["lane-4-of-4","lane-0-of-0","lane-0-of-20","arbitrary"]:
            with self.assertRaises(ValueError):
                builder.lane_scope(recipes,invalid)

    def test_eight_lanes_spread_heavy_roots(self):
        names=["zig","mono","dotnet9.0","dotnet10.0","llvm","rust","webkit2gtk-4.1","qt6-qtwebengine"]
        recipes={name:dict(dependencies=[]) for name in names}
        for index,name in enumerate(names):
            owned,_=builder.lane_scope(recipes,f"lane-{index}-of-8")
            self.assertEqual({name},owned)

    def test_cycles_are_distinct_from_downstream_blockers(self):
        order, cycles = order_and_cycles({"a": {"b"}, "b": {"a"}, "dependent": {"a"}, "independent": set()})
        self.assertEqual([["a", "b"]], cycles)
        self.assertEqual("independent", order[0])


@unittest.skipUnless(os.name == "posix", "POSIX persistent-builder process checks")
class LedgerTests(unittest.TestCase):
    def test_failed_dependency_does_not_block_independent_build_and_retry_retains_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["upstream.lock.json", "source.json", "patches.json"]:
                (root / name).write_text("{}")
            (root / "build-package.sh").write_text(
                '#!/bin/bash\nset -eu\n'
                'printf "%s\\n" "${@: -1}" >> executed\n'
                'if [ "${@: -1}" = packages/a ]; then test -f allow; fi\n')
            plan = dict(identity="pinned-identity", configuration={}, recipes={
                "a": dict(path="packages/a", dependencies=[], rank=0, initial_status="pending"),
                "b": dict(path="packages/b", dependencies=["a"], rank=1, initial_status="pending"),
                "c": dict(path="packages/c", dependencies=[], rank=2, initial_status="pending"),
            })
            state = root / "state"
            with patch.object(builder, "create_plan", return_value=plan):
                self.assertEqual(1, builder.build(root, root, state, minimum_free_gib=0))
                first = json.loads((state / "ledger.json").read_text())["recipes"]
                self.assertEqual(["failed", "blocked-dependency", "built"], [first[k]["status"] for k in "abc"])
                (root / "allow").touch()
                self.assertEqual(1, builder.build(root, root, state, minimum_free_gib=0))
                self.assertEqual(0, builder.build(root, root, state, minimum_free_gib=0, retry_failed=True))
                final = json.loads((state / "ledger.json").read_text())["recipes"]
                self.assertEqual([2, 1, 1], [final[k]["attempts"] for k in "abc"])
                self.assertEqual(["packages/a", "packages/c", "packages/a", "packages/b"], (root / "executed").read_text().splitlines())
                plan["identity"] = "different-prefix-or-patches"
                with self.assertRaisesRegex(ValueError, "inputs changed"):
                    builder.build(root, root, state, minimum_free_gib=0)

    def test_disk_shortage_records_halt_without_spawning_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["upstream.lock.json", "source.json", "patches.json"]:
                (root / name).write_text("{}")
            plan = dict(identity="pin", configuration={}, recipes={
                "a": dict(path="packages/a", dependencies=[], rank=0, initial_status="pending")})
            with patch.object(builder, "create_plan", return_value=plan), patch.object(builder.subprocess, "Popen") as process:
                self.assertEqual(75, builder.build(root, root, root / "state", minimum_free_gib=10**9))
                process.assert_not_called()
                self.assertEqual("insufficient-builder-disk", json.loads((root / "state/ledger.json").read_text())["halt"])

    def test_hosted_budget_checkpoints_remaining_work_and_next_run_keeps_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["upstream.lock.json", "source.json", "patches.json"]:
                (root / name).write_text("{}")
            (root / "build-package.sh").write_text('#!/bin/bash\nprintf "%s\\n" "${@: -1}" >> executed\n')
            plan = dict(identity="pin", configuration={}, recipes={
                name: dict(path="packages/" + name, dependencies=[], rank=rank, initial_status="pending")
                for rank, name in enumerate(["a", "b"])})
            state = root / "state"
            with patch.object(builder, "create_plan", return_value=plan):
                with patch.object(builder.time, "monotonic", side_effect=[0, 1, 61]):
                    self.assertEqual(75, builder.build(root, root, state, minimum_free_gib=0, budget_seconds=60))
                ledger = json.loads((state / "ledger.json").read_text())
                self.assertEqual("batch-time-budget", ledger["halt"])
                self.assertEqual("built", ledger["recipes"]["a"]["status"])
                self.assertEqual("pending", ledger["recipes"]["b"]["status"])
                self.assertEqual(0, builder.build(root, root, state, minimum_free_gib=0))
                self.assertEqual(["packages/a", "packages/b"], (root / "executed").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
