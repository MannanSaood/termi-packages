"""Narrow, revisioned repairs from the first complete parallel build diagnostics."""
import re


def llvm_native_host_flags(text):
    """Keep LLVM's nested Linux generators out of the Android compiler env."""
    old = '-DCROSS_TOOLCHAIN_FLAGS_LLVM_NATIVE=-DLLVM_NATIVE_TOOL_DIR=$TERMUX_PKG_HOSTBUILD_DIR/bin'
    if text.count(old) != 1:
        raise ValueError("LLVM native toolchain anchor changed")
    flags = [
        '-DCMAKE_C_COMPILER=/usr/bin/gcc',
        '-DCMAKE_CXX_COMPILER=/usr/bin/g++',
        '-DCMAKE_ASM_COMPILER=/usr/bin/gcc',
        '-DCMAKE_C_FLAGS=', '-DCMAKE_CXX_FLAGS=', '-DCMAKE_ASM_FLAGS=',
        '-DCMAKE_EXE_LINKER_FLAGS=', '-DCMAKE_SHARED_LINKER_FLAGS=',
        '-DCMAKE_MODULE_LINKER_FLAGS=',
    ]
    return text.replace(old, old + ';' + ';'.join(flags))


def rust_target_cxx_headers(text):
    anchor = '\tunset CC CFLAGS CFLAGS_${env_host} CPP CPPFLAGS CXX CXXFLAGS LD LDFLAGS PKG_CONFIG RANLIB'
    if text.count(anchor) != 1:
        raise ValueError('Rust compiler environment anchor changed')
    setup = r'''	# LLVM's -I$PREFIX/include must follow the matching libc++ headers.
	# Bootstrap clears CXXFLAGS; persist this only in the Android target compiler.
	local termi_cxx="$TERMUX_PKG_TMPDIR/termi-rust-cxx"
	printf '#!/bin/bash\nexec %q -nostdinc++ -I%q "$@" --target=%q\n' "$CXX" "$TERMUX_PREFIX/include/c++/v1" "${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}" > "$termi_cxx"
	chmod 755 "$termi_cxx"
	sed -i "/^\[target\.${CARGO_TARGET_NAME}\]$/a cxx = \"$termi_cxx\"" bootstrap.toml
'''
    return text.replace(anchor, setup + anchor)


def swift_target_cxx_headers(text):
    anchor = 'termux_step_make() {'
    if text.count(anchor) != 1:
        raise ValueError('Swift target build anchor changed')
    setup = r"""
	# Host generators have already built; change only Android C++ flags.
	python3 - "$TERMUX_PKG_SRCDIR/swift/utils/build-script-impl" <<'TERMI_SWIFT'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = '-DCMAKE_CXX_FLAGS="$(swift_c_flags ${host}) ${cross_c_flags}"'
assert s.count(old) == 1, 'Swift C++ flag anchor changed'
replacement = '-DCMAKE_CXX_FLAGS="$(termi_swift_cxx_flags ${host}) ${cross_c_flags}"'
helper = '''
function termi_swift_cxx_flags() {
    case "$1" in android-*) printf '%s' "-nostdinc++ -I${TERMUX_PREFIX}/include/c++/v1 ";; esac
    swift_c_flags "$1"
}
'''
assert s.count('function swift_c_flags() {') == 1
s = s.replace('function swift_c_flags() {', helper + '\nfunction swift_c_flags() {')
p.write_text(s.replace(old, replacement))
TERMI_SWIFT
"""
    return text.replace(anchor, anchor + setup)


def mesa_bindgen_headers(text):
    anchor = '\tmkdir -p $_WRAPPER_BIN'
    if text.count(anchor) != 1:
        raise ValueError('Mesa wrapper anchor changed')
    setup = r'''
	# Only Rusticl's LLVM C++ bindings need the prefix libc++ headers first.
	local termi_bindgen="$(command -v bindgen)"
	{
		printf '#!/bin/bash\nreal=%q\nprefix=%q\n' "$termi_bindgen" "$TERMUX_PREFIX"
		cat <<'TERMI_BINDGEN'
args=()
llvm_bindings=false
for arg in "$@"; do
    case "$arg" in *rusticl_llvm_bindings*) llvm_bindings=true;; esac
done
for arg in "$@"; do
    args+=("$arg")
    if "$llvm_bindings" && [[ "$arg" == -- ]]; then
        args+=(-nostdinc++ "-I$prefix/include/c++/v1")
    fi
done
exec "$real" "${args[@]}"
TERMI_BINDGEN
	} > "$_WRAPPER_BIN/bindgen"
	chmod 755 "$_WRAPPER_BIN/bindgen"
'''
    return text.replace(anchor, anchor + setup)


def apply(patch, original):
    prepared = {}
    def change(name, edit, tree="packages"):
        path=f"{tree}/{name}/build.sh"
        before=original(path)
        after=edit(before)
        revision=re.search(r"^TERMUX_PKG_REVISION=(\d+)$",after,re.M)
        if revision:
            after=after[:revision.start()]+f"TERMUX_PKG_REVISION={int(revision[1])+1}"+after[revision.end():]
        else:
            after=re.sub(r"^(TERMUX_PKG_VERSION=.*)$",r"\1\nTERMUX_PKG_REVISION=1",after,count=1,flags=re.M)
        prepared[name] = after
        patch(path,before,after)

    def hook(text,name,body):
        existing = re.search(r"(?m)^"+re.escape(name)+r"\s*\(\)\s*\{", text)
        if existing:
            return text[:existing.end()]+"\n"+body+text[existing.end():]
        anchor=f"{name}() {{"
        if anchor in text:
            return text.replace(anchor,anchor+"\n"+body,1)
        return text+f"\n{anchor}\n{body}\n}}\n"

    change("etsh",lambda t:t.replace("https://etsh.nl/src/","https://etsh.dev/src/"))
    # Freetz's source cache serves the exact original release, independently
    # downloaded from two mirrors and checked against the existing source pin.
    # The separate fortune-data archive also retains its original SHA256.
    change("fortune",lambda t:t.replace("http://dl.fefe.de/","https://freetz.magenbrot.net/")
           .replace("http://http.debian.net/debian/","https://deb.debian.org/debian/"))
    # The old development commit is no longer served by the author. Use the
    # maintained official stable release, not an unrelated fork or old binary.
    change("lrzsz",lambda t:hook(t.replace('TERMUX_PKG_VERSION=0.12.21-rc1','TERMUX_PKG_VERSION=0.13.1')
        .replace('https://github.com/UweOhse/lrzsz/archive/$_COMMIT.tar.gz','https://www.ohse.de/uwe/releases/lrzsz-$TERMUX_PKG_VERSION.tar.gz')
        .replace('56f79c3eb8f6b140693667802d516824c2e115a83d15e1b4d5adbe1deab7c2e0','112f91059fbd118e016d800c1a5c5a1702e965d8b9bfbda6015e44e20bfb93c9'),
        'termux_step_post_get_source', '\tsed -i \'s/^\tln /\tln -s /\' "$TERMUX_PKG_SRCDIR/src/Makefile.am"'))
    change("renameutils",lambda t:t.replace("https://savannah.nongnu.org/download/","https://download.savannah.nongnu.org/releases/"))
    # Official project release, identical version with original gzip packaging.
    change("lzop",lambda t:t.replace("https://fossies.org/linux/misc/lzop-$TERMUX_PKG_VERSION.tar.xz",
                                    "https://www.lzop.org/download/lzop-$TERMUX_PKG_VERSION.tar.gz")
           .replace("dd294d2425a646952e5a316907356ea3c6bddab0f47d5f88ac808c89b290467b","7e72b62a8a60aff5200a047eea0773a8fb205caf7acbe1774d95147f305a2f41"))
    # Debian's original-source digest is independently recorded in its .dsc.
    change("libgfshare",lambda t:t.replace("https://www.digital-scurf.org/files/libgfshare/libgfshare-$TERMUX_PKG_VERSION.tar.bz2",
                                          "https://deb.debian.org/debian/pool/main/libg/libgfshare/libgfshare_${TERMUX_PKG_VERSION}.orig.tar.gz")
           .replace("86f602860133c828356b7cf7b8c319ba9b27adf70a624fe32275ba1ed268331f","04442efb602a5fc8d79604845816811ab2d970e07e9aa5c8962b86b88e284838"))
    change("libceres-solver",lambda t:t.replace("http://ceres-solver.org/ceres-solver-$TERMUX_PKG_VERSION.tar.gz",
                                              "https://github.com/ceres-solver/ceres-solver/archive/refs/tags/$TERMUX_PKG_VERSION.tar.gz")
           .replace("48b2302a7986ece172898477c3bcd6deb8fb5cf19b3327bc49969aad4cede82d","12efacfadbfdc1bbfa203c236e96f4d3c210bed96994288b3ff0c8e7c6f350d4"))
    # The publisher's GitHub release API independently reports this asset digest.
    change("luv",lambda t:t.replace("c06bbb62f1059acfeb36093d78a1af6df48cd2386db52286dbd36971cac9f840",
                                   "fccabc7bb37fcc3b84ab258a19a862c55f67abc2059af0a744a1ae64119dfc6c"))
    # Mirror exact historical bytes: retain every original per-file SHA256.
    for package,commit in [("hunspell-en-us","67032ee957631908098a72edf48dc81cac27e369"),
                           ("hunspell-ru","67032ee957631908098a72edf48dc81cac27e369"),
                           ("hunspell-fr","e808afadc2ead6b98b40026f6eec15ae669de37c"),
                           ("hunspell-hu","c5b2a36bde02841590b8ccc490ca88bfdb69f153")]:
        change(package,lambda t,c=commit:t.replace("https://cgit.freedesktop.org/libreoffice/dictionaries/plain/",
                                                   f"https://raw.githubusercontent.com/LibreOffice/dictionaries/{c}/"))
    # Keep diagnostics, but don't fail legacy single-thread tokenization code on
    # the NDK's new deprecation annotation. Other -Werror diagnostics remain.
    for package in ["distcc","liblo"]:
        change(package,lambda t:hook(t,"termux_step_pre_configure",'\tCFLAGS+=" -Wno-error=deprecated-declarations"'))
    # Current Eigen headers require C++14 or later; preserve FCL functionality.
    change("libfcl",lambda t:hook(t,"termux_step_pre_configure",'''\tsed -i -E 's/-std=(gnu|c)\\+\\+11/-std=c++17/g; s/CXX_STANDARD 11/CXX_STANDARD 17/g' "$TERMUX_PKG_SRCDIR/CMakeLists.txt"
\tfind "$TERMUX_PKG_SRCDIR" -name CMakeLists.txt -exec sed -i -E 's/-std=(gnu|c)\\+\\+11/-std=c++17/g' {} +
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_STANDARD=17"
\tCXXFLAGS+=" -std=c++17 -nostdinc++"'''))
    # Two copies of libc++/float.h share an include guard. include_next hits
    # the second wrapper and never reaches Clang's actual floating constants.
    # Retain the prefix's explicit libc++ include, suppress its implicit twin.
    for package in ["gnucap", "alembic", "polyml", "quick-lint-js", "libprotobuf", "libxisf", "openexr", "z3", "minizinc", "libimtui", "libmediainfo", "asymptote", "frobtads", "wabt", "openxr", "oidn", "lfortran"]:
        change(package,lambda t:hook(t,"termux_step_pre_configure",'\tCXXFLAGS+=" -nostdinc++"'))
    change("libllvm", lambda t: llvm_native_host_flags(
        hook(t, "termux_step_pre_configure", '\tCXXFLAGS+=" -nostdinc++"')))
    # LLVM's source hook requires the separate Flang recipe revision to match.
    # change() bumps the revision even when the source body is unchanged.
    change("flang", lambda t: t)
    # Native diagnostics: Boost b2 and elfutils debuginfod use prefix C
    # headers alongside implicit NDK libc++; use the matching prefix C++ set.
    change("boost",lambda t:hook(t,"termux_step_make_install",'\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"'))
    change("libelf",lambda t:hook(t,"termux_step_pre_configure",'\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"'))
    change("rust", rust_target_cxx_headers)
    change("swift", swift_target_cxx_headers)
    change("mesa", mesa_bindgen_headers)
    def revision(text):
        return re.search(r"^TERMUX_PKG_REVISION=(\d+)$", text, re.M).group(1)
    if revision(prepared["libllvm"]) != revision(prepared["flang"]):
        raise ValueError("Termi LLVM/Flang repair revisions must match")
    # libnl .la references a private convenience archive in its discarded build
    # tree. Rebuild that exact tiny source locally for this consumer, no cache
    # path dependency and no installed-prefix mutation.
    change("net-snmp",lambda t:hook(t.replace('TERMUX_PKG_EXTRA_CONFIGURE_ARGS="',
        'TERMUX_PKG_DEPENDS="libnl, openssl"\nTERMUX_PKG_EXTRA_CONFIGURE_ARGS="',1),"termux_step_pre_configure",'''\tlocal compatibility_lib="$TERMUX_PKG_TMPDIR/compatlib"
\tmkdir -p "$compatibility_lib"
\t$CC $CFLAGS -fvisibility=hidden -c "$TERMUX_SCRIPTDIR/packages/libnl/getsubopt.c" -o "$compatibility_lib/getsubopt.o"
\t$AR crs "$compatibility_lib/libgetsubopt.a" "$compatibility_lib/getsubopt.o"
\tLDFLAGS+=" -L$compatibility_lib"'''))
    change("lowdown",lambda t:hook(t.replace('TERMUX_PKG_BUILD_IN_SRC=true',
        'TERMUX_PKG_BUILD_IN_SRC=true\nTERMUX_PKG_DEPENDS="libmd"').replace(
        '\t\tCPPFLAGS="$CPPFLAGS"', '\t\tCFLAGS="$CFLAGS $CPPFLAGS -I$TERMUX_PREFIX/include" \\\n\t\tCPPFLAGS="$CPPFLAGS"'),"termux_step_configure",'\tLDFLAGS+=" -lmd"'))
    change("librocksdb",lambda t:hook(t,"termux_step_pre_configure",
        '\tCXXFLAGS+=" -nostdinc++"\n\tsed -i \'1i#include <sys/vfs.h>\' "$TERMUX_PKG_SRCDIR/env/io_posix.cc"'))
    change("hugo",lambda t:t.replace('unset GOOS GOARCH CGO_LDFLAGS',
        'unset GOOS GOARCH CGO_LDFLAGS CGO_CFLAGS CGO_CPPFLAGS CGO_CXXFLAGS').replace(
        'unset CC CXX CFLAGS CXXFLAGS LDFLAGS',
        'unset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS\n\texport CC=gcc CXX=g++ PKG_CONFIG=/usr/bin/pkg-config'))
    # Source-build a PIC runtime with its matching official LLVM HOST compiler.
    # Never link the old non-PIC Android archives from the Termux toolchain.
    change("arpack-ng",lambda t:t.replace('TERMUX_PKG_LICENSE="BSD"','TERMUX_PKG_LICENSE="BSD, Apache-2.0"').replace(
        '\ttermux_setup_flang', '''\ttermux_setup_cmake
\ttermux_setup_ninja
\tlocal version=21.1.8
\tlocal work="$TERMUX_PKG_TMPDIR/termi-fortran"
\tmkdir -p "$work"
\ttermux_download "https://github.com/llvm/llvm-project/releases/download/llvmorg-$version/llvm-project-$version.src.tar.xz" "$work/source.tar.xz" 4633a23617fa31a3ea51242586ea7fb1da7140e426bd62fc164261fe036aa142
\ttermux_download "https://github.com/llvm/llvm-project/releases/download/llvmorg-$version/LLVM-$version-Linux-X64.tar.xz" "$work/host.tar.xz" b3b7f2801d15d50736acea3c73982994d025b01c2f035b91ae3b49d1b575732b
\ttar -xf "$work/source.tar.xz" -C "$work"
\ttar -xf "$work/host.tar.xz" -C "$work"
\tlocal host="$work/LLVM-$version-Linux-X64"
\tlocal source="$work/llvm-project-$version.src"
\t# NDK timespec_get is API29; the identical TIME_UTC clock is available
\t# through clock_gettime(CLOCK_REALTIME) on our existing API26 minimum.
\tsed -i 's/timespec_get(\\&tspec, TIME_UTC)/clock_gettime(CLOCK_REALTIME, \\&tspec)/' "$source/flang-rt/lib/runtime/time-intrinsic.cpp"
\t# Official NDK compiler builtins supply the Android target, while the
\t# matching official LLVM archive supplies only the Linux-host frontend.
\tcp -a "$TERMUX_STANDALONE_TOOLCHAIN/lib/clang/21/lib/." "$host/lib/clang/21/lib/"
\tlocal wrapper="$work/termi-flang"
\tprintf '#!/bin/sh\\nexec "%s/bin/flang-new" --target=%s%s --sysroot="%s/sysroot" "$@"\\n' "$host" "$TERMUX_HOST_PLATFORM" "$TERMUX_PKG_API_LEVEL" "$TERMUX_STANDALONE_TOOLCHAIN" > "$wrapper"
\tchmod 755 "$wrapper"
\texport FC="$wrapper" FCFLAGS="--target=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL} -fPIC"
\t(
\t\tTERMUX_PKG_SRCDIR="$source/runtimes"
\t\tTERMUX_PKG_BUILDDIR="$work/runtime-build"
\t\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS="-DLLVM_ENABLE_RUNTIMES=flang-rt -DFLANG_RT_INCLUDE_TESTS=OFF -DCMAKE_Fortran_COMPILER=$wrapper -DCMAKE_Fortran_COMPILER_WORKS=yes -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DLLVM_DEFAULT_TARGET_TRIPLE=${TERMUX_HOST_PLATFORM/-/-unknown-}${TERMUX_PKG_API_LEVEL} -DLLVM_RUNTIMES_TARGET=${TERMUX_HOST_PLATFORM/-/-unknown-}${TERMUX_PKG_API_LEVEL}"
\t\tCXXFLAGS+=" -nostdinc++"
\t\tmkdir -p "$TERMUX_PKG_BUILDDIR"
\t\tcd "$TERMUX_PKG_BUILDDIR"
\t\ttermux_step_configure_cmake
\t\tcmake --build . --parallel "$TERMUX_PKG_MAKE_PROCESSES"
\t)
\ttest -f "$work/runtime-build/flang-rt/lib/libflang_rt.runtime.a"
\tLDFLAGS+=" -L$work/runtime-build/flang-rt/lib"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_Fortran_COMPILER=$wrapper -DCMAKE_Fortran_FLAGS=-fPIC -DCMAKE_POSITION_INDEPENDENT_CODE=ON"
\tinstall -Dm600 "$source/LICENSE.TXT" "$TERMUX_PREFIX/share/doc/$TERMUX_PKG_NAME/llvm-runtime-LICENSE.TXT"
'''))
    for package in ["gcal", "recutils"]:
        change(package,lambda t:hook(t.replace('ac_cv_header_spawn_h=no','ac_cv_header_spawn_h=yes'),
            "termux_step_pre_configure",'''\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" ac_cv_func_posix_spawn=yes ac_cv_func_posix_spawnp=yes"
\tLDFLAGS+=" -landroid-spawn"''').replace('TERMUX_PKG_DEPENDS="ncurses"',
            'TERMUX_PKG_DEPENDS="ncurses, libandroid-spawn"') +
            ('\nTERMUX_PKG_DEPENDS="libandroid-spawn"\n' if 'TERMUX_PKG_DEPENDS=' not in t else ''))
    # Pluto's PHP launcher ignores failed compiler exits and otherwise spawns
    # one process per visible host CPU, despite the container's two-CPU quota.
    change("libpluto",lambda t:hook(t,"termux_step_pre_configure",'''\tCXXFLAGS+=" -nostdinc++"
\tsed -i 's/$nthreads = 8;/$nthreads = 2;/; s/$nthreads = (int)substr_count(file_get_contents("\\/proc\\/cpuinfo"), "processor");/$nthreads = max(1, (int)getenv("TERMUX_PKG_MAKE_PROCESSES"));/' "$TERMUX_PKG_SRCDIR/scripts/common.php" "$TERMUX_PKG_SRCDIR/src/vendor/Soup/build_common.php"
\tsed -i 's/$flags .= " -L$srcdir/$flags = " -L$srcdir/' "$TERMUX_PKG_SRCDIR/scripts/common.php"'''))
    change("oils-for-unix",lambda t:hook(t,"termux_step_pre_configure",'''\tCXXFLAGS+=" -nostdinc++"
\tCXXFLAGS+=" $CPPFLAGS"
\texport OILS_PARALLEL_BUILD=0 OILS_CXX_VERBOSE=1'''))
    # Debian mirrors the original upstream tarball byte-for-byte; pin unchanged.
    change("pari",lambda t:t.replace('https://pari.math.u-bordeaux.fr/pub/pari/unix/pari-${TERMUX_PKG_VERSION}.tar.gz',
        'https://deb.debian.org/debian/pool/main/p/pari/pari_${TERMUX_PKG_VERSION}.orig.tar.gz'))
    # Publisher tag APIs and full per-file archive comparisons verified these
    # immutable commits. Freeze commits instead of accepting mutable tarballs.
    for package,old_url,new_url,old_hash,new_hash in [
        ("dte",'https://gitlab.com/craigbarnes/dte/-/archive/v${TERMUX_PKG_VERSION}/dte-v${TERMUX_PKG_VERSION}.tar.gz',
         'https://gitlab.com/craigbarnes/dte/-/archive/892aade3b33fce047b89d5daaff3c5775b50452f/dte-892aade3b33fce047b89d5daaff3c5775b50452f.tar.gz',
         '68c25bc4e8792da33529626e23102cd5fb34186479049f5480fd9f3e9ffb1171','3bc99da4bf55733bd09abae1ad4a4940d70d73f9ee0e366872f1643e38900aab'),
        ("diff-so-fancy",'https://github.com/so-fancy/diff-so-fancy/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz',
         'https://github.com/so-fancy/diff-so-fancy/archive/7dca929b2468ccb296a08c92e7e39b7754d63a8e.tar.gz',
         '7ebdaaac4aade23a9b5296f560484e42a864331903febe92314b530380a34734','238637ca27824b1a83e0c408cc75de639af548c25f75096ff3cd304931c57742'),
        ("inxi",'https://codeberg.org/smxi/inxi/archive/${TERMUX_PKG_VERSION}.tar.gz',
         'https://codeberg.org/smxi/inxi/archive/d9941a4ed84fdc20737cc44e987a92d4cd0d8d5c.tar.gz',
         '2f3b16d099fde1b250a4bf6500b0c8e32b13d77469625c5cfc7a5d195a0c8585','e08d92550a0f10890e722cc7db1e6d6cbde7e9fb47e61a8c6cec51f54a0b63d8')]:
        change(package,lambda t,u=old_url,v=new_url,h=old_hash,k=new_hash:t.replace(u,v).replace(h,k))
    # Upstream's native compiler probes call exit() without stdlib.h. GCC15
    # rejects that in its default dialect; scope the legacy dialect to HOST CC.
    change("libgf2x",lambda t:hook(t,"termux_step_pre_configure",'''\texport CC_FOR_BUILD="gcc -std=gnu89"
\texport CFLAGS_FOR_BUILD="-O2" CPPFLAGS_FOR_BUILD="" LDFLAGS_FOR_BUILD=""'''))
    # Legacy host generators must use a host C dialect, not GCC15's C23 default.
    change("gforth",lambda t:t.replace('CC="gcc -m$TERMUX_ARCH_BITS"',
        'CC="gcc -std=gnu11 -Wno-error=incompatible-pointer-types -m$TERMUX_ARCH_BITS"').replace(
        '\tlocal _PREFIX_FOR_BUILD=$TERMUX_PKG_HOSTBUILD_DIR/prefix',
        '''\t# Upstream permits absent Emacs during byte-compilation. Install the
\t# equivalent .el source regardless, and .elc only when actually generated.
\tsed -i 's@$(INSTALL_DATA) gforth.elc $(DESTDIR)$(emacssitelispdir);@if test -f gforth.elc; then $(INSTALL_DATA) gforth.elc $(DESTDIR)$(emacssitelispdir); fi;@' "$TERMUX_PKG_SRCDIR/Makefile.in"
\tlocal _PREFIX_FOR_BUILD=$TERMUX_PKG_HOSTBUILD_DIR/prefix''',1))
    change("cccc",lambda t:t.replace('export CC="gcc -m${TERMUX_ARCH_BITS}"',
        'export CC="gcc -std=gnu89 -Wno-error=incompatible-pointer-types -m${TERMUX_ARCH_BITS}"')
           .replace('export CCC="g++ -m${TERMUX_ARCH_BITS}"','export CCC="g++ -std=gnu++11 -m${TERMUX_ARCH_BITS}"'))
    change("libforestdb",lambda t:hook(t,"termux_step_pre_configure",'''\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_C_COMPILER_TARGET=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL} -DCMAKE_CXX_COMPILER_TARGET=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}"
\tCFLAGS+=" --target=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}"
\tCXXFLAGS+=" --target=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}"'''))
    change("mdbook-cat-prep",lambda t:hook(t,"termux_step_pre_configure",'''\tlocal api_cc="$TERMUX_PKG_TMPDIR/termi-api-cc"
\tprintf '#!/bin/sh\\nexec %s "$@" --target=%s\\n' "$CC" "${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}" > "$api_cc"
\tchmod 755 "$api_cc"
\texport CC_aarch64_linux_android="$api_cc"'''))
    # Proton deliberately checks its build-time Bun version. Pin that official
    # Linux HOST tool and its publisher digest within this one recipe.
    change("proton-drive-cli",lambda t:t.replace('\ttermux_setup_bun\n','''\tlocal helper="$TERMUX_PKG_TMPDIR/termi-bun-setup.sh"
\tsed -e 's/1.4.3/1.4.2/g' -e 's/3e730528d89775f03f87f05c06787c4df4099d0a37f3f252e7b829cb23816e18/36368faef7527875d5ffa52e53cd48021741f2a83eb6208a8dd64068d422a913/g' "$TERMUX_SCRIPTDIR/scripts/build/setup/termux_setup_bun.sh" > "$helper"
\tsource "$helper"
\tTERMUX_BUN_VERSION=1.4.2 termux_setup_bun
''').replace('CLI_APP_VERSION_NAME="cli-drive-termux"','CLI_APP_VERSION_NAME="cli-drive-termi"'))

    from catalog_repairs import apply as apply_catalog_repairs
    apply_catalog_repairs(change, hook, prepared)
