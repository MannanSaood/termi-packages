#!/usr/bin/env python3
"""Prepare pinned upstream build inputs. This is NOT a device package installer."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"Upstream contract changed: {path.name}: {old[:80]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def read_lock(path):
    lock = json.loads(path.read_text(encoding="utf-8"))
    if (lock["schema"] != 1 or not re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
            or not re.fullmatch(r"ghcr.io/termux/package-builder@sha256:[0-9a-f]{64}", lock["builder_image"])
            or lock["repository"] != "https://github.com/termux/termux-packages.git"
            or lock["application_id"] != "com.terminal.nextgen"
            or lock["prefix"] != "/data/data/com.terminal.nextgen/files/usr"
            or lock["architecture"] != "aarch64" or lock["package_api"] != 26
            or lock["bootstrap_roots"] != ["apt", "bash", "termux-exec", "termux-tools"]
            or lock["proof_package"] != "hello"):
        raise ValueError("Unsupported or unpinned build configuration")
    return lock


def validate_source(archive):
    """Validate git's tree without extracting Unix symlinks onto a Windows host."""
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        members = source.getmembers()
        total = 0
        seen = set()
        non_directories = {m.name.rstrip("/") for m in members if not m.isdir()}
        aliases = {m.name: m.linkname for m in members if m.issym()}
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.name or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or ":" in member.name
                    or not (member.isdir() or member.isfile() or member.issym())
                    or member.name.casefold().rstrip("/") in seen):
                raise ValueError(f"Unsafe source archive entry: {member.name!r}")
            seen.add(member.name.casefold().rstrip("/"))
            total += member.size
            if total > 128 * 1024 * 1024 or len(members) > 20000:
                raise ValueError("Source archive exceeds build input bounds")
        for member in members:
            if member.issym():
                link = member.linkname
                if not link or link.startswith("/") or "\\" in link or ":" in link:
                    raise ValueError("Unsafe source alias target")
                # Resolve aliases before '..', as the filesystem does. Lexical
                # normalization alone misses e.g. a -> '.', b -> 'a/../outside'.
                pending = list(PurePosixPath(member.name).parent.parts) + link.split("/")
                resolved = []
                hops = 0
                while pending:
                    part = pending.pop(0)
                    if part in ("", "."):
                        continue
                    if part == "..":
                        if not resolved:
                            raise ValueError("Source alias escapes archive")
                        resolved.pop()
                        continue
                    resolved.append(part)
                    target = aliases.get("/".join(resolved))
                    if target is not None:
                        hops += 1
                        if hops > 40 or not target or target.startswith("/") or "\\" in target or ":" in target:
                            raise ValueError("Unsafe or cyclic source alias chain")
                        resolved.pop()
                        pending = target.split("/") + pending
            # git trees cannot contain files underneath a symlink. Enforce that
            # property as well before Docker unpacks this committed source tree.
            for parent in PurePosixPath(member.name).parents:
                if str(parent) in non_directories:
                    raise ValueError("Source entry has a non-directory ancestor")


def prepare(upstream, output, lock, full_catalog=False):
    # Archive committed objects, never the caller's possibly modified checkout.
    actual = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if actual != lock["commit"]:
        raise ValueError(f"Wrong upstream revision: {actual}")
    if output.exists():
        raise ValueError("Output already exists; use a new build directory")
    archive = subprocess.check_output(
        ["git", "-C", str(upstream), "archive", "--format=tar", lock["commit"]])
    epoch = int(subprocess.check_output(
        ["git", "-C", str(upstream), "show", "-s", "--format=%ct", lock["commit"]], text=True).strip())
    validate_source(archive)
    output.mkdir(parents=True)
    (output / "source.tar").write_bytes(archive)
    (output / "source.json").write_text(json.dumps({
        "commit": lock["commit"], "source_date_epoch": epoch,
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "catalog_scope": "full-catalog" if full_catalog else "proof",
    }, indent=2) + "\n", encoding="utf-8")
    tree = output / "overlay"
    tree.mkdir()
    patches = []

    def original(relative):
        return subprocess.check_output(["git", "-C", str(upstream), "show",
                                        lock["commit"] + ":" + relative]).decode("utf-8")

    def patch(relative, old, new):
        path = tree / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(original(relative), encoding="utf-8", newline="\n")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        replace_once(path, old, new)
        patches.append({"path": relative, "before_sha256": before,
                        "after_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    patch("scripts/properties.sh", 'TERMUX_APP__PACKAGE_NAME="com.termux"',
          'TERMUX_APP__PACKAGE_NAME="com.terminal.nextgen"')
    # The pinned builder includes API24/28/35, while Termi targets API26.
    # Install the official SDK platform on demand and supply its matching
    # launcher; never substitute a different Android API jar silently.
    patch("packages/ecj/build.sh", 'TERMUX_PKG_REVISION=5', 'TERMUX_PKG_REVISION=6')
    patch("packages/ecj/build.sh", 'termux_step_make() {', '''termux_step_make() {
	if [ ! -f "$ANDROID_HOME/platforms/android-$TERMUX_PKG_API_LEVEL/android.jar" ]; then
		local sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
		if [ ! -x "$sdkmanager" ]; then sdkmanager="$ANDROID_HOME/cmdline-tools/bin/sdkmanager"; fi
		"$sdkmanager" --sdk_root="$ANDROID_HOME" "platforms;android-$TERMUX_PKG_API_LEVEL"
	fi
	test -s "$ANDROID_HOME/platforms/android-$TERMUX_PKG_API_LEVEL/android.jar"
	sed "s/android-24.jar/android-$TERMUX_PKG_API_LEVEL.jar/g" "$TERMUX_PKG_BUILDER_DIR/ecj-24" > "$TERMUX_PKG_TMPDIR/ecj-$TERMUX_PKG_API_LEVEL"
''')
    patch("packages/ecj/build.sh", 'install $TERMUX_PKG_BUILDER_DIR/ecj-$TERMUX_PKG_API_LEVEL',
          'install $TERMUX_PKG_TMPDIR/ecj-$TERMUX_PKG_API_LEVEL')
    from recipe_repairs import apply as apply_recipe_repairs
    apply_recipe_repairs(patch, original)
    # lrzsz0.13.1 incorporates the old K&R/gettext/syslog fixes. These patches
    # target the vanished development commit and must not be applied to stable.
    obsolete_lrzsz = ["configure.ac.patch", "lib-long-options.c.patch", "locale.patch", "log.patch", "src-Makefile.am.patch"]
    for name in obsolete_lrzsz:
        relative = "packages/lrzsz/" + name
        patches.append(dict(path=relative, before_sha256=hashlib.sha256(original(relative).encode()).hexdigest(),
                            after_sha256=hashlib.sha256(b"").hexdigest(), action="remove",
                            reason="Superseded by official lrzsz0.13.1; symlink install retained in recipe"))
    # mpg123 upstream explicitly supports splitting libraries/programs from
    # output modules to break the PulseAudio -> libsndfile -> decoder cycle.
    # Keep the player feature through an exact-version runtime dependency;
    # only the output module needs PulseAudio headers during compilation.
    mpg = "packages/libmpg123/build.sh"
    patch(mpg, 'TERMUX_PKG_VERSION="1.33.7"',
          'TERMUX_PKG_VERSION="1.33.7"\nTERMUX_PKG_REVISION=1')
    patch(mpg, 'TERMUX_PKG_BUILD_DEPENDS="pulseaudio"',
          'TERMUX_PKG_ANTI_BUILD_DEPENDS="pulseaudio, mpg123-pulse"\n'
          'TERMUX_PKG_EXTRA_CONFIGURE_ARGS="\n'
          '--disable-components\n--enable-programs\n--enable-libmpg123\n'
          '--enable-libsyn123\n--enable-libout123\n--with-default-audio=pulse\n"')
    patch("packages/libmpg123/mpg123.subpackage.sh", 'TERMUX_SUBPKG_DEPENDS="pulseaudio"',
          'TERMUX_SUBPKG_DEPENDS="pulseaudio, mpg123-pulse (= 1.33.7-1)"')
    module_recipe = '''TERMUX_PKG_HOMEPAGE=https://mpg123.org/
TERMUX_PKG_DESCRIPTION="PulseAudio output module for mpg123"
TERMUX_PKG_LICENSE="LGPL-2.1"
TERMUX_PKG_MAINTAINER="Termi"
TERMUX_PKG_VERSION="1.33.7"
TERMUX_PKG_REVISION=1
TERMUX_PKG_SRCURL=https://downloads.sourceforge.net/sourceforge/mpg123/mpg123-${TERMUX_PKG_VERSION}.tar.bz2
TERMUX_PKG_SHA256=31d0e35a4ca567ec9b5ebda6c3062bb4435d6d3eacd6ef0d95cadd7854dc03ee
TERMUX_PKG_DEPENDS="libmpg123 (= 1.33.7-1), pulseaudio"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--disable-components
--enable-libout123-modules
--with-audio=pulse
"
'''
    module_path = tree / "packages/mpg123-pulse/build.sh"
    if subprocess.run(["git", "-C", str(upstream), "cat-file", "-e", lock["commit"] + ":packages/mpg123-pulse/build.sh"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError("Upstream now supplies mpg123-pulse; review the split instead of replacing it")
    module_path.parent.mkdir(parents=True)
    module_path.write_text(module_recipe, encoding="utf-8", newline="\n")
    patches.append(dict(path="packages/mpg123-pulse/build.sh", action="add",
                        before_sha256=None, after_sha256=hashlib.sha256(module_path.read_bytes()).hexdigest()))
    # Xlib's shared-font paths include SysV SHM interfaces absent from bionic.
    # Build/link the Android implementation rather than using host headers.
    patch("packages/libx11/build.sh", 'TERMUX_PKG_VERSION="1.8.14"',
          'TERMUX_PKG_VERSION="1.8.14"\nTERMUX_PKG_REVISION=1')
    patch("packages/libx11/build.sh", 'TERMUX_PKG_DEPENDS="libandroid-support, libxcb, xorgproto"',
          'TERMUX_PKG_DEPENDS="libandroid-support, libandroid-shmem, libxcb, xorgproto"')
    patch("packages/libx11/build.sh", 'termux_step_post_massage() {',
          'termux_step_pre_configure() {\n\tLDFLAGS+=" -landroid-shmem"\n}\n\ntermux_step_post_massage() {')
    # A single Biome release compiler/link step plus parallel workers exceeded
    # the free runner's memory limit. Keep release functionality, bound Cargo
    # concurrency and disable memory-heavy LTO; new bytes get a new revision.
    patch("packages/biome2/build.sh", 'TERMUX_PKG_VERSION="2.5.15"',
          'TERMUX_PKG_VERSION="2.5.15"\nTERMUX_PKG_REVISION=1')
    patch("packages/biome2/build.sh", '\ttermux_setup_rust\n',
          '\ttermux_setup_rust\n'
          '\texport CARGO_PROFILE_RELEASE_LTO=off\n'
          '\texport CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16\n'
          '\texport CARGO_PROFILE_RELEASE_DEBUG=0\n')
    patch("packages/biome2/build.sh", '--jobs "$TERMUX_PKG_MAKE_PROCESSES"', '--jobs 1')
    patch("scripts/build/termux_step_finish_build.sh", '\texit 0\n',
          '\t# The Debian archives, prefix, source/cache and markers already exist.\n'
          '\tpython3 /home/builder/build_scratch.py --top "$TERMUX_TOPDIR" --recipe "$TERMUX_PKG_NAME"\n'
          '\texit 0\n')
    # Even without -i, upstream may download an old binary to break a build cycle.
    # Such binaries belong to com.termux, not this prefix. Fail instead.
    for name, relative in (
            ("termux_download_repo_file", "scripts/build/termux_step_get_dependencies.sh"),
            ("termux_download_deb_pac", "scripts/build/termux_download_deb_pac.sh")):
        patch(relative, name + "() {", name + "() {\n"
              '\ttermux_error_exit "Termi candidate forbids prebuilt repository dependencies; rebuild for its prefix"\n')

    apt = "packages/apt/build.sh"
    patch("packages/dpkg/build.sh", 'TERMUX_PKG_AUTO_UPDATE=false',
          'TERMUX_PKG_AUTO_UPDATE=false\n\n'
          'termux_step_post_get_source() {\n'
          '\t[ "$(git -C "$TERMUX_PKG_SRCDIR" rev-parse HEAD)" = "b2f9600ead232a2dd3c27f8b52807a9ca5854d17" ] || termux_error_exit "dpkg source tag moved"\n'
          '}\n')
    patch(apt, 'echo "deb https://packages-cf.termux.dev/apt/termux-main/ stable main"',
          'echo "# Termi: no compatible signed repository configured; installation is not enabled"')
    # APT's optional manpage toolchain drags Python/Tk/X11 into a CLI bootstrap.
    # Keep the actual manager; omit documentation generation and optional Tor.
    patch(apt, 'TERMUX_PKG_BUILD_DEPENDS="docbook-xsl,libdb"',
          'TERMUX_PKG_BUILD_DEPENDS="libdb"')
    patch(apt, '-DWITH_DOC_MANPAGES=ON', '-DWITH_DOC_MANPAGES=OFF')
    # Berkeley DB's optional SysV-memory backend is unavailable with this NDK
    # API26 surface. APT's build helper uses the ordinary file-backed database.
    patch("packages/libdb/build.sh", 'db_cv_atomic=gcc-builtin',
          'db_cv_atomic=gcc-builtin\nac_cv_func_shmget=no')
    for relative in ("packages/apt/apt-transport-tor.subpackage.sh",
                     "packages/libunbound/pyunbound.subpackage.sh",
                     "packages/libunbound/unbound.subpackage.sh"):
        patch(relative, original(relative), 'TERMUX_SUBPKG_EXCLUDED_ARCHES="aarch64"\n')
    # Upstream validates the entire recipe index before selecting the roots.
    # This optional Python DNS utility requires the binding omitted above.
    patch("packages/hash-slinger/build.sh", 'TERMUX_PKG_PLATFORM_INDEPENDENT=true',
          'TERMUX_PKG_PLATFORM_INDEPENDENT=true\nTERMUX_PKG_EXCLUDED_ARCHES="aarch64"')
    unbound = "packages/libunbound/build.sh"
    patch(unbound, 'TERMUX_PKG_BUILD_DEPENDS="python, swig"', 'TERMUX_PKG_BUILD_DEPENDS=""')
    patch(unbound, 'TERMUX_PKG_PYTHON_COMMON_BUILD_DEPS="wheel"', 'TERMUX_PKG_PYTHON_COMMON_BUILD_DEPS=""')
    patch(unbound, 'TERMUX_PKG_PYTHON_CROSS_BUILD_DEPS="swig"', 'TERMUX_PKG_PYTHON_CROSS_BUILD_DEPS=""')
    patch(unbound, '--with-pyunbound', '--without-pyunbound')
    # APT needs the resolver library, not its daemon/CLI. The latter's shared
    # memory statistics assume SysV APIs unavailable in the API26 NDK headers.
    patch(unbound, '--without-pythonmodule', '--without-pythonmodule\n--with-libunbound-only')
    patch("packages/bash/build.sh", 'TERMUX_PKG_DEPENDS="libandroid-support, libiconv, readline (>= 8.3), termux-tools"',
          'TERMUX_PKG_DEPENDS="libandroid-support, libiconv, readline (>= 8.3)"')
    # This fork ships the upstream pkg frontend only. Android companion tools,
    # mirrors, profile hooks and their optional dependency trees are not enabled.
    pkgtools = "packages/termux-tools/build.sh"
    text = original(pkgtools)
    dependencies = next(line for line in text.splitlines() if line.startswith('TERMUX_PKG_DEPENDS='))
    patch(pkgtools, dependencies, 'TERMUX_PKG_DEPENDS="apt, bash, coreutils, dash, grep, sed, termux-exec"')
    patch(pkgtools, 'TERMUX_PKG_RECOMMENDS="ed, dos2unix, inetutils, net-tools, patch, unzip"',
          'TERMUX_PKG_RECOMMENDS=""')
    start = text.index('termux_step_pre_configure() {')
    patch(pkgtools, text[start:], '''termux_step_configure() { :; }
termux_step_make() { :; }
termux_step_make_install() {
    python3 - "$TERMUX_PKG_SRCDIR/scripts/pkg.in" "$TERMUX_PREFIX" "$TERMUX_CACHE_DIR" <<'PY'
import pathlib, sys
p, prefix, cache = sys.argv[1:]
cache = prefix + '/var/cache'
s = pathlib.Path(p).read_text()
old = 'source "@TERMUX_PREFIX@/bin/termux-setup-package-manager" || exit 1'
assert s.count(old) == 1
s = s.replace(old, 'TERMUX_APP_PACKAGE_MANAGER=apt')
start = s.index('select_mirror() {')
end = s.index('\\nupdate_apt_cache() {', start)
s = s[:start] + 'select_mirror() { :; }\\n' + s[end:]
s = s.replace('#!/bin/bash', '#!' + prefix + '/bin/bash', 1)
s = s.replace('@TERMUX_PREFIX@', prefix).replace('@TERMUX_CACHE_DIR@', cache)
s = s.replace('@PACKAGE_VERSION@', '1.45.0-termi').replace('@TERMUX_APP_PACKAGE@', 'com.terminal.nextgen')
path = pathlib.Path(prefix) / 'bin/pkg'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(s)
path.chmod(0o700)
PY
}
''')
    # No stock keys are authoritative for a different application prefix.
    keyring = "packages/termux-keyring/build.sh"
    text = original(keyring)
    start = text.index('termux_step_make_install() {')
    patch(keyring, text[start:], '''termux_step_make_install() {
    install -d "$TERMUX_PREFIX/share/termux-keyring"
    printf '%s\\n' 'Termi uses an APK-provisioned, repository-scoped signed-by key.' > "$TERMUX_PREFIX/share/termux-keyring/README.termi"
}
''')
    # GH's Go subprocess path bypasses libc/LD_PRELOAD. Use the installed
    # Termux exec adapter through system sh, guarded by explicit linker mode.
    patch("packages/gh/build.sh", "\ttermux_setup_golang\n",
          '\ttermux_setup_golang\n\tpython3 /home/builder/patch_go_exec.py "$GOROOT"\n')
    patch("packages/gh/build.sh", 'TERMUX_PKG_VERSION="2.102.0"',
          'TERMUX_PKG_VERSION="2.102.0"\nTERMUX_PKG_REVISION=1')
    patch("packages/gh/build.sh", '\tcd "$TERMUX_PKG_SRCDIR"\n\t(',
          '\tcd "$TERMUX_PKG_SRCDIR"\n'
          '\t# v1.4.15 was retracted for quadratic CDF parsing; pin the upstream fix.\n'
          '\tgo mod edit -require=github.com/gabriel-vasile/mimetype@v1.4.16\n'
          '\tprintf \'%s\\n\' '
          "'github.com/gabriel-vasile/mimetype v1.4.16 h1:5izNFuvA37st1dDRAcA7TtmngBmRgiIPDmTtiEvjx1E=' "
          "'github.com/gabriel-vasile/mimetype v1.4.16/go.mod h1:3oFFwxX8kTklZwzIl2aQEDZT0lKY8xH92ST88bAwba4=' >> go.sum\n"
          '\tgo mod download github.com/gabriel-vasile/mimetype\n\t(')
    if not full_catalog:
        for name in ("git-gitk", "git-gui", "git-svn"):
            relative = f"packages/git/{name}.subpackage.sh"
            patch(relative, original(relative), 'TERMUX_SUBPKG_EXCLUDED_ARCHES="aarch64"\n')
        patch("packages/git/build.sh", "--with-tcltk=$TERMUX_PREFIX/bin/wish", "--without-tcltk")
        patch("packages/git/build.sh", "NO_NSEC=1", "NO_NSEC=1\nNO_TCLTK=1\nNO_PERL=1")
    # Full builds restore the GUI/SVN subpackages. Different package bytes must
    # have a new revision rather than replacing the published proof identity.
    revision = 2 if full_catalog else 1
    patch("packages/git/build.sh", 'TERMUX_PKG_VERSION="2.56.0"',
          f'TERMUX_PKG_VERSION="2.56.0"\nTERMUX_PKG_REVISION={revision}')
    patch("packages/git/build.sh", "NO_NSEC=1", "NO_NSEC=1\nNO_MMAP=1")
    patch("packages/git/build.sh", "DEFAULT_PAGER=pager", "DEFAULT_PAGER=less")
    bootstrap = "scripts/build-bootstraps.sh"
    text = original(bootstrap)
    start = text.index("\t\t# Package manager.")
    end = text.index("\t\t# Handle additional packages.", start)
    roots = " ".join('"' + p + '"' for p in lock["bootstrap_roots"])
    patch(bootstrap, text[start:end],
          f"\t\t# Termi: bounded upstream manager and its dependency closure.\n\t\tPACKAGES=({roots})\n\n")
    # A missing root package must fail the build, not create a partial bootstrap.
    patch(bootstrap, "IGNORE_BUILD_SCRIPT_NOT_FOUND_ERROR=1", "IGNORE_BUILD_SCRIPT_NOT_FOUND_ERROR=0")
    # Upstream mounts a writable NDK overlay through /dev/fuse. Keep this build
    # device-free: make a private copy instead, never hardlink the original NDK.
    toolchain = "scripts/build/toolchain/termux_setup_toolchain_30.sh"
    text = original(toolchain)
    start = text.index('\t[ -d "$TERMUX_STANDALONE_TOOLCHAIN" ]')
    end = text.index('\tif [ -f "${TERMUX_STANDALONE_TOOLCHAIN}/.termux-standalone-toolchain" ]; then', start)
    patch(toolchain, text[start:end],
          '\tif [ ! -f "${TERMUX_STANDALONE_TOOLCHAIN}/.termi-ndk-copy" ]; then\n'
          '\t\tmkdir -p "$TERMUX_STANDALONE_TOOLCHAIN"\n'
          '\t\tcp -a --reflink=auto "${NDK}/toolchains/llvm/prebuilt/linux-x86_64/." "$TERMUX_STANDALONE_TOOLCHAIN/"\n'
          '\t\ttouch "${TERMUX_STANDALONE_TOOLCHAIN}/.termi-ndk-copy"\n'
          '\tfi\n\n')
    (output / "upstream.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    (output / "patches.json").write_text(json.dumps(patches, indent=2) + "\n", encoding="utf-8")
    driver = ROOT / "scripts/termux/build-in-container.sh"
    (output / "build-in-container.sh").write_bytes(driver.read_bytes())
    (output / "collect_artifacts.py").write_bytes((ROOT / "scripts/termux/collect_artifacts.py").read_bytes())
    (output / "assemble_bootstrap.py").write_bytes((ROOT / "scripts/termux/assemble_bootstrap.py").read_bytes())
    (output / "patch_go_exec.py").write_bytes((ROOT / "scripts/termux/patch_go_exec.py").read_bytes())
    (output / "seed").mkdir()
    for name in ["catalog_graph.py", "catalog_build.py", "catalog_progress.py", "seed.py", "build_scratch.py"]:
        (output / name).write_bytes((ROOT / "scripts/termux" / name).read_bytes())
    (output / "Dockerfile").write_text(
        f'FROM {lock["builder_image"]}\n'
        'USER root\n'
        'ADD --chown=builder:builder source.tar /home/builder/termux-packages/\n'
        'COPY --chown=builder:builder overlay/ /home/builder/termux-packages/\n'
          'RUN rm -- ' + ' '.join('/home/builder/termux-packages/packages/lrzsz/' + n for n in obsolete_lrzsz) + '\n'
        'COPY --chown=builder:builder build-in-container.sh collect_artifacts.py assemble_bootstrap.py patch_go_exec.py catalog_graph.py catalog_build.py catalog_progress.py seed.py build_scratch.py upstream.lock.json patches.json source.json /home/builder/\n'
        'COPY --chown=builder:builder seed/ /home/builder/seed/\n'
        # Windows checkout permissions are not executable-bit authority.
        'RUN find /home/builder/termux-packages -name "*.sh" -exec chmod u+x {} +\n'
        'USER builder\nWORKDIR /home/builder/termux-packages\n'
        'ENTRYPOINT ["/bin/bash", "/home/builder/build-in-container.sh"]\n',
        encoding="utf-8", newline="\n")
    return patches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-catalog", action="store_true")
    args = parser.parse_args()
    lock = read_lock(ROOT / "packages/termux/upstream.lock.json")
    patches = prepare(args.upstream.resolve(), args.output.resolve(), lock, full_catalog=args.full_catalog)
    print(f"Prepared {lock['commit']}; {len(patches)} checked patches; candidate only")


if __name__ == "__main__":
    main()
