import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch


class PublicationTest(unittest.TestCase):
    def test_focused_seeded_build_bundles_archives(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/termi_free_packages.yml"
        text = workflow.read_text().split("- name: Publish candidate evidence", 1)[1]
        script = text.split("python3 - <<'PY'\n", 1)[1].split("          PY", 1)[0]
        script = textwrap.dedent(script)
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                artifacts = Path("build/candidate/artifacts")
                artifacts.mkdir(parents=True)
                (artifacts / "rust.deb").write_bytes(b"own-source-rust")
                (artifacts / "seed.deb").write_bytes(b"own-source-seed")
                (artifacts / "inventory.json").write_text("{}")
                with patch.dict(os.environ, {"LANE_LABEL": "rust", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "test/test"}), patch("subprocess.run") as run:
                    exec(compile(script, "publication", "exec"), {})
                command = run.call_args.args[0]
                self.assertTrue(any(str(p).endswith(".tar") for p in command))
                self.assertFalse(any(str(p).endswith(".deb") for p in command))
                import tarfile
                with tarfile.open(next(Path("build").glob("packages-*.tar"))) as archive:
                    self.assertEqual(set(archive.getnames()), {"rust.deb", "seed.deb"})
                    self.assertEqual(archive.extractfile("rust.deb").read(), b"own-source-rust")
            finally:
                os.chdir(previous)
