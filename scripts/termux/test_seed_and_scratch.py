import copy
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import unittest

import build_scratch
import seed


class PayloadAliasResolution(unittest.TestCase):
    prefix = "/data/data/com.terminal.nextgen/files/usr"

    def resolver(self, links):
        def readlink(path):
            if path not in links:
                raise FileNotFoundError(2, "not a link", path)
            return links[path]
        return readlink

    def test_relative_platform_chain_does_not_follow_builder_system_shim(self):
        library = self.prefix + "/opt/eglinfo-system/lib"
        links = {library + "/libEGL.so": "/system/lib64/libEGL.so",
                 "/system": "/data/data/com.termux/aosp"}
        self.assertEqual(PurePosixPath("/system/lib64/libEGL.so"),
                         seed.resolve_payload_alias(library + "/libEGL.so", self.resolver(links)))
        links[library + "/libEGL.so.1"] = "libEGL.so"
        self.assertEqual(PurePosixPath("/system/lib64/libEGL.so"),
                         seed.resolve_payload_alias(library + "/libEGL.so.1", self.resolver(links)))

    def test_foreign_namespace_and_platform_parent_escape_are_not_platform_links(self):
        links = {self.prefix + "/foreign": "/data/data/com.termux/aosp/lib64/libEGL.so",
                 self.prefix + "/escape": "/system/../etc/passwd"}
        for name in ["foreign", "escape"]:
            resolved = seed.resolve_payload_alias(self.prefix + "/" + name, self.resolver(links))
            self.assertFalse(resolved.is_relative_to(PurePosixPath(self.prefix)))
            self.assertFalse(resolved.is_relative_to(PurePosixPath("/system")))

    def test_prefix_alias_chain_and_cycle(self):
        links = {self.prefix + "/a": "b", self.prefix + "/b": "lib/real.so"}
        self.assertEqual(PurePosixPath(self.prefix + "/lib/real.so"),
                         seed.resolve_payload_alias(self.prefix + "/a", self.resolver(links)))
        links[self.prefix + "/b"] = "a"
        with self.assertRaisesRegex(ValueError, "alias cycle"):
            seed.resolve_payload_alias(self.prefix + "/a", self.resolver(links))

    def test_double_slash_root_is_absolute_and_relative_input_is_rejected(self):
        readlink = self.resolver({})
        for root in ["/", "//", "///"]:
            self.assertEqual(PurePosixPath(self.prefix + "/lib/real.so"),
                             seed.resolve_payload_alias(root + self.prefix.lstrip("/") + "/lib/real.so", readlink))
            self.assertEqual(PurePosixPath("/system/lib64/libEGL.so"),
                             seed.resolve_payload_alias(root + "system/lib64/libEGL.so", readlink))
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            seed.resolve_payload_alias("relative/file", readlink)


class SeedCompatibility(unittest.TestCase):
    def plan(self):
        return dict(identity="old-graph", configuration=dict(lock={"application_id": "com.terminal.nextgen"},
                    source={"commit": "pinned"}, patches=[], graph_sha256="resolver", upstream_graph_sha256="upstream"),
                    recipes={"a":dict(path="packages/a",dependencies=[]), "b":dict(path="packages/b",dependencies=["a"]),
                             "c":dict(path="packages/c",dependencies=[])})

    def test_changed_recipe_and_reverse_dependencies_are_rebuilt_not_relabelled(self):
        old = self.plan()
        new = copy.deepcopy(old)
        new["configuration"]["patches"] = [dict(path="packages/a/build.sh", after_sha256="new-source")]
        ledger = dict(identity=["old-graph", "old-runner"], recipes={n:dict(status="built") for n in "abc"})
        allowed, invalid = seed.compatibility(old, new, ledger)
        self.assertEqual({"c"}, allowed)
        self.assertEqual({"a", "b"}, invalid)
        new["configuration"]["patches"].append(dict(path="scripts/properties.sh", after_sha256="foreign-prefix"))
        with self.assertRaisesRegex(ValueError,"Global build patch"):
            seed.compatibility(old,new,ledger)
        new = copy.deepcopy(old)
        new["configuration"]["lock"]["application_id"] = "com.termux"
        with self.assertRaisesRegex(ValueError,"configuration differs"):
            seed.compatibility(old,new,ledger)

    def test_hash_pins_are_checked_before_using_seed_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "0001-inventory.json").write_text("{}")
            pin = seed.digest(root / "0001-inventory.json")
            self.assertEqual("0001-inventory.json",seed.pinned(root,"inventory.json",pin).name)
            (root / "0002-inventory.json").write_text("{}")
            self.assertEqual("0001-inventory.json",seed.pinned(root,"inventory.json",pin).name)
            (root / "0002-inventory.json").unlink()
            (root / "0001-inventory.json").write_text('{"changed":true}')
            with self.assertRaises(ValueError):
                seed.pinned(root,"inventory.json",pin)
            archive = root / "0002-example_1.3A2_all.deb"
            archive.write_bytes(b"hash-pinned epoch fixture")
            self.assertEqual(archive,seed.pinned(root,"example_1%3A2_all.deb",seed.digest(archive)))


@unittest.skipUnless(os.name == "posix", "Linux builder cache policy")
class ScratchTests(unittest.TestCase):
    def test_hosted_source_reclamation_keeps_host_tools_and_output_pool(self):
        with tempfile.TemporaryDirectory() as folder:
            top=Path(folder)
            for part in ['example/src','example/cache','example/host-build','_cache/toolchain','output']:
                (top/part).mkdir(parents=True)
                (top/part/'fixture').write_text(part)
            removed=build_scratch.clean(top,'example',discard_sources=True)
            self.assertIn('example/src',removed)
            self.assertIn('example/cache',removed)
            for part in ['example/host-build','_cache/toolchain','output']:
                self.assertTrue((top/part/'fixture').exists())

    def test_readonly_go_module_directories_are_removed_without_chmodding_aliases(self):
        with tempfile.TemporaryDirectory() as folder:
            top = Path(folder)
            cache = top / "example/build/go/pkg/mod/module@v1/nested"
            cache.mkdir(parents=True)
            (cache / "source.go").write_text("fixture")
            outside = top / "source-cache"
            outside.mkdir()
            (outside / "untouched").write_text("preserve")
            (cache / "external").symlink_to(outside,target_is_directory=True)
            mode = outside.stat().st_mode
            for directory in [cache,cache.parent,cache.parent.parent]:
                directory.chmod(0o555)
            self.assertIn("example/build",build_scratch.clean(top,"example"))
            self.assertFalse((top / "example/build").exists())
            self.assertEqual(mode,outside.stat().st_mode)
            self.assertEqual("preserve",(outside / "untouched").read_text())

    def test_only_disposable_compile_products_are_removed_and_sources_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            top = Path(folder)
            root = top / "example"
            for name in ["build","massage","tmp","package","src/target","host-build","cache"]:
                (root / name).mkdir(parents=True)
                (root / name / "keep-or-discard").write_text(name)
            (root / "src/Cargo.toml").write_text("[package]")
            (root / "src/target/CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
            removed = build_scratch.clean(top,"example")
            self.assertIn("example/src/target",removed)
            self.assertFalse((root / "build").exists())
            for name in ["src/Cargo.toml","host-build/keep-or-discard","cache/keep-or-discard"]:
                self.assertTrue((root / name).exists())
            with self.assertRaises(ValueError):
                build_scratch.clean(top,"../escape")

    def test_source_target_without_cargo_cache_marker_and_aliases_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            top = Path(folder)
            (top / "example/src/target").mkdir(parents=True)
            (top / "example/src/Cargo.toml").write_text("[package]")
            outside = top / "outside"
            outside.mkdir()
            (outside / "untouched").write_text("fixture")
            (top / "example/build").symlink_to(outside,target_is_directory=True)
            self.assertEqual([],build_scratch.clean(top,"example"))
            self.assertTrue((outside / "untouched").exists())
            self.assertTrue((top / "example/src/target").is_dir())


@unittest.skipUnless(os.name == "posix" and shutil.which("dpkg-deb"), "Linux Debian payload extraction")
class PayloadTests(unittest.TestCase):
    def test_data_only_extraction_stays_in_prefix_and_never_runs_postinst(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            prefix = root / "prefix"
            prefix.mkdir()
            package = root / "pkg"
            (package / "DEBIAN").mkdir(parents=True)
            (package / "DEBIAN/control").write_text("Package: seed-fixture\nVersion: 1.0\nArchitecture: all\nMaintainer: Fixture\nDescription: test only\n")
            (package / "DEBIAN/postinst").write_text("#!/bin/sh\nexit 99\n")
            (package / "DEBIAN/postinst").chmod(0o755)
            path = package / prefix.relative_to("/") / "include/test.h"
            path.parent.mkdir(parents=True)
            path.write_text("exact fixture")
            (path.parent / "absolute-link").symlink_to(prefix / "include/test.h")
            (path.parent / "platform-link").symlink_to("/system/bin/sh")
            (path.parent / "relative-platform-link").symlink_to("platform-link")
            deb = root / "fixture.deb"
            subprocess.run(["dpkg-deb","--build",str(package),str(deb)],check=True,capture_output=True)
            seed.unpack(deb,prefix)
            self.assertEqual("exact fixture",(prefix / "include/test.h").read_text())
            self.assertEqual("exact fixture",(prefix / "include/absolute-link").read_text())
            self.assertEqual("/system/bin/sh",os.readlink(prefix / "include/platform-link"))
            self.assertEqual("platform-link",os.readlink(prefix / "include/relative-platform-link"))
            (path.parent / "foreign-link").symlink_to("/data/data/com.termux/aosp/lib64/libEGL.so")
            subprocess.run(["dpkg-deb","--build",str(package),str(deb)],check=True,capture_output=True)
            with self.assertRaisesRegex(ValueError,"Unsafe source-cache payload alias"):
                seed.unpack(deb,prefix)
            (path.parent / "foreign-link").unlink()
            (package / prefix.relative_to("/") / "include/unsafe-link").symlink_to("/etc/passwd")
            subprocess.run(["dpkg-deb","--build",str(package),str(deb)],check=True,capture_output=True)
            with self.assertRaisesRegex(ValueError,"Unsafe source-cache payload alias"):
                seed.unpack(deb,prefix)
            (package / prefix.relative_to("/") / "include/unsafe-link").unlink()
            (package / "etc").mkdir()
            (package / "etc/forbidden-fixture").write_text("must not extract")
            subprocess.run(["dpkg-deb","--build",str(package),str(deb)],check=True,capture_output=True)
            with self.assertRaisesRegex(ValueError,"outside the Termi prefix"):
                seed.unpack(deb,prefix)


if __name__ == "__main__":
    unittest.main()
