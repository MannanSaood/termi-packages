import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import catalog_repairs


def install_hook():
    class Found(Exception):
        pass

    body = []

    def change(name, edit, **kwargs):
        if name == "codex":
            edit('TERMUX_PKG_VERSION="0.163.0"\nTERMUX_PKG_DEPENDS="git, libc++, openssl"\n')
            raise Found

    def hook(text, name, script):
        assert name == "termux_step_post_make_install"
        body.append(f"{name}() {{\n{script}\n}}\n{name}\n")
        return text

    try:
        catalog_repairs.apply(change, hook, {})
    except Found:
        pass
    return body[0]


@unittest.skipUnless(os.name == "posix", "POSIX shell required")
class CodexLauncherTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="termi codex ")
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        self.prefix = root / "usr"
        self.home = root / "home"
        self.home.mkdir()
        self.state = self.prefix / "var/lib/codex"
        self.legacy = self.home / ".codex"
        self.bin = self.prefix / "bin"
        self.bin.mkdir(parents=True)
        for name in ("mkdir", "cp", "mv", "mktemp", "rm"):
            (self.bin / name).symlink_to(shutil.which(name))
        real = self.bin / "codex"
        real.write_text(
            "#!/bin/sh\n"
            '[ -x "${0%/*}/codex-code-mode-host" ] || exit 82\n'
            "exec python3 -c 'import json, os, sys; "
            'print(json.dumps([os.environ.get("CODEX_HOME"), sys.argv[1:]]))\' "$@"\n'
        )
        real.chmod(0o700)
        helper = self.bin / "codex-code-mode-host"
        helper.write_text("#!/bin/sh\nexit 0\n")
        helper.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if key != "CODEX_HOME"}
        self.env.update(HOME=str(self.home), TERMUX_PREFIX=str(self.prefix))
        subprocess.run(["bash", "-ec", install_hook()], env=self.env, check=True)
        self.command = ["sh", str(self.bin / "codex"), "--version", "space in argument"]

    def launch(self, **overrides):
        result = subprocess.run(
            self.command, env={**self.env, **overrides}, text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        home, arguments = json.loads(result.stdout)
        self.assertEqual(arguments, ["--version", "space in argument"])
        return home

    def test_plain_launch_creates_and_reuses_private_default(self):
        self.assertEqual(self.launch(), str(self.state))
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        (self.state / "config.toml").write_text("stable")
        self.assertEqual(self.launch(), str(self.state))
        self.assertEqual((self.state / "config.toml").read_text(), "stable")

    def test_explicit_home_is_forwarded_without_creating_default(self):
        custom = str(self.home / "custom home")
        self.assertEqual(self.launch(CODEX_HOME=custom), custom)
        self.assertEqual(self.launch(CODEX_HOME=""), "")
        self.assertFalse(self.state.exists())

    def test_legacy_copy_preserves_data_and_never_replaces_stable_state(self):
        self.legacy.mkdir()
        (self.legacy / "auth.json").write_text("test fixture")
        (self.legacy / "sessions").mkdir()
        (self.legacy / "sessions/history.jsonl").write_text("history")
        (self.legacy / "history-link").symlink_to("sessions/history.jsonl")
        self.assertEqual(self.launch(), str(self.state))
        self.assertEqual((self.state / "auth.json").read_text(), "test fixture")
        self.assertEqual((self.state / "history-link").readlink(), Path("sessions/history.jsonl"))
        self.assertEqual((self.state / "sessions/history.jsonl").read_text(), "history")
        (self.state / "auth.json").write_text("new state")
        self.assertEqual(self.launch(), str(self.state))
        self.assertEqual((self.state / "auth.json").read_text(), "new state")
        self.assertEqual((self.legacy / "auth.json").read_text(), "test fixture")

    def test_failed_copy_keeps_legacy_and_never_publishes_partial_state(self):
        self.legacy.mkdir()
        (self.legacy / "config.toml").write_text("legacy")
        copy = self.bin / "cp"
        copy.unlink()
        copy.write_text("#!/bin/sh\nexit 1\n")
        copy.chmod(0o700)
        result = subprocess.run(self.command, env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.state.parent.iterdir()), [])
        self.assertEqual((self.legacy / "config.toml").read_text(), "legacy")

    def test_a_concurrent_migration_cannot_be_overwritten(self):
        self.legacy.mkdir()
        (self.legacy / "config.toml").write_text("legacy")
        move = self.bin / "mv"
        move.unlink()
        move.write_text(
            '#!/bin/sh\nmkdir "$5" && echo winner > "$5/config.toml" || exit 1\n'
            'exec /usr/bin/mv "$@"\n'
        )
        move.chmod(0o700)
        self.assertEqual(self.launch(), str(self.state))
        self.assertEqual((self.state / "config.toml").read_text(), "winner\n")
        self.assertEqual(list(self.state.parent.iterdir()), [self.state])
