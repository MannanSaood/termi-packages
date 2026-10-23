import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import catalog_build as builder
from catalog_graph import order_and_cycles


class GraphTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
