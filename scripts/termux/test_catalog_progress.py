import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import catalog_progress
import publish_progress


class ProgressTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dpkg-deb"), "Actual Debian archive inspection")
    def test_counts_valid_outputs_and_records_failure_tails_without_claiming_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "state"
            (state / "logs").mkdir(parents=True)
            (root / "output").mkdir()
            package = root / "fixture"
            (package / "DEBIAN").mkdir(parents=True)
            (package / "DEBIAN/control").write_text("Package: progress-fixture\nVersion: 1.0\nArchitecture: aarch64\nMaintainer: Fixture\nDescription: test only\n")
            subprocess.run(["dpkg-deb", "--build", str(package), str(root / "output/valid.deb")], check=True, capture_output=True)
            (root / "output/incomplete.deb").write_bytes(b"incomplete archive")
            ledger = dict(recipes={"ok": dict(status="built", attempts=1), "bad": dict(status="failed", attempts=2, exit_code=7),
                                  "active": dict(status="running", attempts=1), "waiting": dict(status="blocked-dependency")})
            (state / "ledger.json").write_text(json.dumps(ledger))
            (state / "logs/bad-2.log").write_text("x" * 30000 + "\nactual compiler error\n")
            (state / "logs/active-1.log").write_text("currently compiling real input\n")
            value = catalog_progress.snapshot(root, state)
            self.assertEqual(1, value["deb_files"])
            self.assertEqual(1, value["counts"]["built"])
            self.assertEqual(["active"], value["current"])
            self.assertEqual(7, value["failures"][0]["exit_code"])
            self.assertLessEqual(len(value["failures"][0]["tail"].encode()), 8192)
            self.assertIn("actual compiler error", value["failures"][0]["tail"])
            self.assertFalse(value["approved"])
            self.assertIn("currently compiling", value["current_log_tail"])
            with patch.object(catalog_progress.subprocess, "run", wraps=subprocess.run) as inspected:
                catalog_progress.snapshot(root, state)
                # The verified file is cached; the incomplete file is rechecked.
                self.assertEqual(1, inspected.call_count)
            page = publish_progress.markdown(value)
            self.assertIn("**1 / 4**", page)
            self.assertIn("exit 7", page)
            self.assertIn("not a production catalog", page)

    def test_selected_roots_have_explicit_scope_and_preserve_failure_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "state"
            catalog_progress.selected_event(state, ["nodejs", "npm"], "nodejs", "running")
            catalog_progress.selected_event(state, ["nodejs", "npm"], "nodejs", "failed", 9)
            catalog_progress.selected_event(state, ["nodejs", "npm"], "nodejs", "running")
            value = catalog_progress.snapshot(Path(folder), state)
            self.assertEqual("requested-roots", value["scope"])
            self.assertEqual(2, value["total_recipes"])
            self.assertEqual(2, json.loads((state / "selected-ledger.json").read_text())["recipes"]["nodejs"]["attempts"])

    def test_live_publisher_uploads_only_bounded_reports_not_builder_credentials_or_binaries(self):
        value = dict(updated="test timestamp", counts={"built": 2}, current=[], total_recipes=3,
                     deb_files=5, failures=[dict(recipe="broken", status="failed", exit_code=1, tail="real failure tail")])
        with tempfile.TemporaryDirectory() as folder, patch.object(publish_progress, "gh") as gh:
            publish_progress.publish("owner/public-packages", "progress-1-1", Path(folder), value)
            names = {p.name for p in Path(folder).iterdir()}
            self.assertEqual({"progress.json", "progress.md", "failures.log", "current.log"}, names)
            self.assertEqual(2, gh.call_count)
            self.assertIn("real failure tail", (Path(folder) / "failures.log").read_text())
            self.assertNotIn("GH_TOKEN", (Path(folder) / "progress.json").read_text())


if __name__ == "__main__":
    unittest.main()
