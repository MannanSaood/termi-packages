import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import build
from select_catalog import selected_versions


class PackageRequests(unittest.TestCase):
    def test_apt_version_selection_preserves_epochs_and_ignores_retained_old_versions(self):
        text = "Inst nodejs (26.4.0-1 Termi:stable [aarch64])\nInst example:aarch64 [1.0] (1:2.0 Termi:stable [aarch64])\nConf example (1:2.0 Termi:stable [aarch64])\n"
        self.assertEqual({"nodejs": "26.4.0-1", "example": "1:2.0"}, selected_versions(text))
    def invoke(self, *arguments):
        return patch.object(sys, "argv", ["build.py", "--upstream", "unused", "--output", "unused", *arguments])

    def test_arbitrary_recipe_names_reach_isolated_builder(self):
        # Stop at the first Docker call: this test neither downloads nor builds.
        for name in ["nodejs", "npm", "python", "nano", "clang", "libc++"]:
            with self.subTest(name=name), self.invoke("--mode", "packages", "--packages", name), \
                    patch.object(build, "run", side_effect=RuntimeError("reached-builder")) as run:
                with self.assertRaisesRegex(RuntimeError, "reached-builder"):
                    build.main()
                run.assert_called_once_with(["docker", "info", "--format", "{{.OSType}}"])

    def test_invalid_requests_never_start_docker(self):
        cases = [
            ["--mode", "packages"],
            ["--mode", "packages", "--packages", "../nodejs"],
            ["--mode", "packages", "--packages", "nodejs;echo"],
            ["--mode", "catalog", "--packages", "nodejs"],
            ["--mode", "packages", "--packages", *(["nodejs"] * 129)],
            ["--mode", "full-catalog", "--packages", "nodejs"],
            ["--jobs", "0"],
            ["--memory-gib", "1"],
            ["--timeout-seconds", "0"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments[:5]), self.invoke(*arguments), \
                    patch.object(build, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    build.main()
                self.assertEqual(2, error.exception.code)
                run.assert_not_called()

    def test_full_catalog_uses_upstream_builder_without_name_selection(self):
        with self.invoke("--mode", "full-catalog", "--jobs", "4", "--memory-gib", "6", "--timeout-seconds", "86400"), \
                patch.object(build, "run", side_effect=RuntimeError("reached-builder")) as run:
            with self.assertRaisesRegex(RuntimeError, "reached-builder"):
                build.main()
            run.assert_called_once_with(["docker", "info", "--format", "{{.OSType}}"])


if __name__ == "__main__":
    unittest.main()
