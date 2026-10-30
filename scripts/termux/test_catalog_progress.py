import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import catalog_progress
import publish_progress


class ProgressTests(unittest.TestCase):

    def test_new_failure_log_survives_many_cached_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state';(state/'logs').mkdir(parents=True);(root/'output').mkdir()
            recipes={'arpack-ng':dict(status='interrupted',attempts=1,exit_code=75,ended=200)}
            recipes.update({f'cached-{i}':dict(status='failed',attempts=1,exit_code=1,ended=100) for i in range(150)})
            (state/'ledger.json').write_text(json.dumps(dict(recipes=recipes)))
            (state/'logs/arpack-ng-1.log').write_text('LLVM extraction stage reached disk guard')
            snapshot=catalog_progress.snapshot(root,state)
            self.assertEqual(100,len(snapshot['failures']))
            self.assertEqual('arpack-ng',snapshot['failures'][-1]['recipe'])
            self.assertIn('LLVM extraction stage',snapshot['failures'][-1]['tail'])
            self.assertEqual(51,snapshot['omitted_failure_logs'])

    def test_reporting_recovery_preserves_native_exit_and_final_publication_failures(self):
        class Builder:
            returncode = None
            def poll(self): return self.returncode
            def wait(self, timeout=None): self.returncode = native_exit; return native_exit

        for native_exit, reports, expected in [
            (0, [subprocess.TimeoutExpired('gh', 60), None], 0),
            (0, [None, subprocess.TimeoutExpired('gh', 60)], 1),
            (7, [subprocess.TimeoutExpired('gh', 60), None], 7),
        ]:
            with self.subTest(native_exit=native_exit, expected=expected), tempfile.TemporaryDirectory() as tmp:
                args=['publish_progress.py','--repository','owner/public','--tag','progress-1-1','--build-dir',str(Path(tmp)/'build'),'--','compiler']
                with patch.object(sys,'argv',args), \
                        patch.object(publish_progress.subprocess,'check_output',return_value=b'{"visibility":"PUBLIC"}'), \
                        patch.object(publish_progress,'gh'), \
                        patch.object(publish_progress.subprocess,'Popen',return_value=Builder()), \
                        patch.object(publish_progress,'capture',return_value=None), \
                        patch.object(publish_progress,'publish',side_effect=reports) as report, \
                        patch.object(publish_progress.time,'monotonic',return_value=1000), \
                        self.assertRaises(SystemExit) as result:
                    publish_progress.main()
                self.assertEqual(expected,result.exception.code)
                self.assertEqual(2,report.call_count)

    def test_late_compile_failure_survives_early_configure_probe_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'compile.log'
            with path.open('wb') as stream:
                stream.write(b'configure: error: optional feature probe\n'*8)
                stream.seek(33*1024**2)
                stream.write(b'\nsource.cpp:123: error: actual late failure\n')
                stream.write(b'parallel successful output\n'*1000)
                stream.write(b'make: stopped\n')
            excerpt=catalog_progress.failure_excerpt(path)
            self.assertIn('optional feature probe',excerpt)
            self.assertIn('actual late failure',excerpt)
            self.assertIn('make: stopped',excerpt)
            self.assertLessEqual(len(excerpt.encode()),8192)

    def test_cmake_multiline_error_survives_later_configuration_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'configure.log'
            path.write_text('configure: error: optional probe\n'*8+'CMake Error at cmake/check.cmake:12 (message):\n  Missing required target dependency\n\n' + 'successful configure probe\n'*2000)
            excerpt=catalog_progress.failure_excerpt(path)
            self.assertIn('CMake Error at',excerpt)
            self.assertIn('Missing required target dependency',excerpt)
            self.assertLessEqual(len(excerpt.encode()),8192)

    def test_first_error_is_retained_when_parallel_output_pushes_it_out_of_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'compile.log'
            path.write_text('source.cpp:7: error: actual cause\n'+'unrelated output\n'*10000+'make: stopped\n')
            excerpt=catalog_progress.failure_excerpt(path)
            self.assertIn('error: actual cause',excerpt)
            self.assertIn('make: stopped',excerpt)
            self.assertLess(len(excerpt),8192)

    def test_rate_limit_waits_for_reset_instead_of_retrying_each_minute(self):
        result = subprocess.CompletedProcess(["gh"], 1, stderr=b"API rate limit exceeded")
        with patch.object(publish_progress.subprocess, "run", return_value=result), \
                patch.object(publish_progress.subprocess, "check_output", return_value=b"2000\n"), \
                patch.object(publish_progress.time, "time", return_value=1000):
            with self.assertRaises(publish_progress.RateLimited) as error:
                publish_progress.gh("owner/repo", "edit", "progress-1-1")
            self.assertEqual(1005, error.exception.retry_seconds)

    def test_preparation_does_not_invent_zero_totals(self):
        page = publish_progress.markdown(dict(updated="now", total_recipes=None, deb_files=None, counts={}))
        self.assertIn("awaiting builder", page)
        self.assertIn("unknown during preparation", page)
        self.assertNotIn("0 / 0", page)

    def test_unique_count_inventory_contains_only_completed_recipe_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/"state";state.mkdir()
            ledger=dict(recipes={"finished":dict(status="built"),"failed":dict(status="failed"),
                                 "reused":dict(status="built",origin="verified-termi-source-build"),
                                 "pending":dict(status="pending"),"running":dict(status="running")})
            (state/"ledger.json").write_text(json.dumps(ledger))
            value=catalog_progress.snapshot(root,state)
            self.assertEqual(["finished","reused"],value["completed_recipes"])
            self.assertEqual(2,value["counts"]["built"])

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
            gh.reset_mock()
            publish_progress.publish("owner/public-packages", "progress-1-1", Path(folder), value, assets=False)
            self.assertEqual(1, gh.call_count)
            self.assertEqual("edit", gh.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
