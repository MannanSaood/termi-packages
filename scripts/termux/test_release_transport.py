"""Actual host APT transport probe; no packages are installed or executed."""
import email.utils
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest


@unittest.skipUnless(os.name == "posix" and all(shutil.which(x) for x in ["apt-get", "dpkg-deb", "dpkg-scanpackages", "gpg"]), "Linux APT transport tools")
class ReleaseTransport(unittest.TestCase):
    def test_signed_relative_index_downloads_through_asset_redirect(self):
        self.probe(False)

    def test_host_apt_does_not_accept_absolute_filename_urls(self):
        self.probe(True)

    def probe(self, absolute):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            (package / "DEBIAN").mkdir(parents=True)
            (package / "DEBIAN/control").write_text("Package: transport-fixture\nVersion: 1.0\nArchitecture: aarch64\nMaintainer: Fixture\nDescription: test only\n")
            (root / "downloads").mkdir()
            archive = root / "downloads/transport-fixture_1.0_aarch64.deb"
            subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(package), str(archive)], check=True, capture_output=True)
            class Handler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=str(root), **kwargs)
                def do_GET(self):
                    if self.path.startswith("/release/tag/") or self.path.startswith("/repo/pool/"):
                        self.send_response(302)
                        self.send_header("Location", "/downloads/" + archive.name)
                        self.end_headers()
                    else:
                        super().do_GET()
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                release_dir = root / "repo/dists/stable"
                index = release_dir / "main/binary-aarch64/Packages"
                index.parent.mkdir(parents=True)
                data = subprocess.check_output(["dpkg-scanpackages", "downloads", "/dev/null"], cwd=root, stderr=subprocess.DEVNULL).decode()
                filename = origin + "/release/tag/" + archive.name if absolute else "pool/" + archive.name
                data = data.replace("Filename: downloads/" + archive.name, "Filename: " + filename)
                index.write_text(data)
                checksum = hashlib.sha256(index.read_bytes()).hexdigest()
                (release_dir / "Release").write_text("Origin: Transport test\nSuite: stable\nCodename: stable\nArchitectures: aarch64\nComponents: main\n"
                    + "Date: " + email.utils.formatdate(time.time(), usegmt=True) + "\nSHA256:\n "
                    + checksum + f" {index.stat().st_size} main/binary-aarch64/Packages\n")
                home = root / "gpg"
                home.mkdir(mode=0o700)
                environment = {**os.environ, "GNUPGHOME": str(home), "LC_ALL": "C"}
                subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-generate-key", "Transport fixture", "ed25519", "sign", "1d"], env=environment, check=True, capture_output=True)
                keyring = root / "keyring.gpg"
                keyring.write_bytes(subprocess.check_output(["gpg", "--export"], env=environment))
                subprocess.run(["gpg", "--batch", "--yes", "--output", str(release_dir / "InRelease"), "--clearsign", str(release_dir / "Release")], env=environment, check=True, capture_output=True)
                apt = root / "apt"
                for path in ["etc/apt.conf.d", "etc/trusted.gpg.d", "etc/preferences.d", "state/lists/partial", "cache/archives/partial", "log", "received"]:
                    (apt / path).mkdir(parents=True, exist_ok=True)
                (apt / "state/status").write_text("")
                (apt / "etc/sources.list").write_text(f"deb [arch=aarch64 signed-by={keyring}] {origin}/repo stable main\n")
                config = apt / "config"
                config.write_text(f'Dir "{apt}"; Dir::Etc "etc"; Dir::State "state"; Dir::State::status "{apt}/state/status"; Dir::Cache "cache"; Dir::Log "log";\n'
                    '#clear APT::Architectures; APT::Architecture "aarch64"; APT::Architectures {{ "aarch64"; }};\n'.replace('{{', '{').replace('}}', '}')
                    + 'Acquire::Languages "none"; Acquire::Retries "0"; Acquire::http::Timeout "5";\n')
                environment["APT_CONFIG"] = str(config)
                for arguments in [["update"], ["download", "transport-fixture"]]:
                    result = subprocess.run(["apt-get", *arguments], cwd=apt / "received", env=environment, text=True, capture_output=True, timeout=30)
                    if absolute and arguments[0] == "download":
                        self.assertNotEqual(0, result.returncode)
                        self.assertIn("/repo/http://127.0.0.1:", result.stdout + result.stderr)
                        return
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                received = apt / "received" / archive.name
                self.assertEqual(archive.read_bytes(), received.read_bytes())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
