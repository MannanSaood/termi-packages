"""Repairs grounded in the first completed four-lane catalog failure logs."""
import re


def apply(change, hook, prepared):
    # binutils/Makefile.am compiles sysinfo with Linux CC_FOR_BUILD but its
    # default CPPFLAGS_FOR_BUILD otherwise inherits the Android include path.
    change('binutils', lambda t: hook(t, 'termux_step_pre_configure',
        '''\texport CPPFLAGS_FOR_BUILD=" "
\tpython3 - "$TERMUX_PKG_SRCDIR/binutils" <<'TERMI_BINUTILS_HOST'
from pathlib import Path
import sys
for name in ('Makefile.am', 'Makefile.in'):
    p=Path(sys.argv[1])/name;s=p.read_text()
    old='AM_CFLAGS_FOR_BUILD = $(WARN_CFLAGS_FOR_BUILD) $(ZLIBINC) $(ZSTD_CFLAGS)'
    assert s.count(old)==1, 'binutils host compression flags anchor changed'
    s=s.replace(old,'AM_CFLAGS_FOR_BUILD = $(WARN_CFLAGS_FOR_BUILD)')
    old='$(CC_FOR_BUILD) -o $@ $(AM_CPPFLAGS) $(AM_CFLAGS_FOR_BUILD)'
    assert s.count(old)==1, 'binutils host bin2c flags anchor changed'
    p.write_text(s.replace(old,'$(CC_FOR_BUILD) -o $@ $(AM_CFLAGS_FOR_BUILD)'))
TERMI_BINUTILS_HOST'''))

    # These native failures show prefix C headers before implicit NDK libc++.
    # A compiler wrapper also precedes dependency-generated -I options.
    for name in ['libavif', 'libopenmpt']:
        change(name, lambda t, cmake=name=='libavif': hook(t, 'termux_step_pre_configure', '''\tlocal termi_cxx="$TERMUX_PKG_TMPDIR/termi-matching-cxx"
\tprintf '#!/bin/bash\\nexec %q -nostdinc++ -I%q "$@"\\n' "$CXX" "$TERMUX_PREFIX/include/c++/v1" > "$termi_cxx"
\tchmod 755 "$termi_cxx"
\texport CXX="$termi_cxx"'''+ ('\n\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER=$termi_cxx"' if cmake else '')))

    # libsvn_subr directly uses the Android System V semaphore shim. LIBS
    # keeps the shim after objects on --as-needed link lines.
    change('subversion', lambda t: hook(t.replace(
        'utf8proc, zlib, libmagic"', 'utf8proc, zlib, libmagic, libandroid-sysv-semaphore"'),
        'termux_step_pre_configure', '\texport LIBS="${LIBS:-} -landroid-sysv-semaphore"'))

    # HOST manpage/completion generators must never inherit Android cgo flags.
    for name in ['restic', 'scc', 'tdl']:
        change(name, lambda t: t.replace('unset GOOS GOARCH CGO_LDFLAGS',
            'unset GOOS GOARCH CGO_LDFLAGS CGO_CFLAGS CGO_CPPFLAGS CGO_CXXFLAGS').replace(
            'unset CC CXX CFLAGS CXXFLAGS LDFLAGS',
            'unset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS\n\texport CC=gcc CXX=g++ PKG_CONFIG=/usr/bin/pkg-config'))

    def syncthing(t):
        t=t.replace('\tunset GOOS GOARCH CGO_LDFLAGS CC', '')
        native='''\t(
\t\tunset GOOS GOARCH CGO_LDFLAGS CGO_CFLAGS CGO_CPPFLAGS CGO_CXXFLAGS
\t\tunset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
\t\texport CC=gcc CXX=g++ PKG_CONFIG=/usr/bin/pkg-config
\t\tgo build -o "$TERMUX_PKG_TMPDIR/syncthing-build-tool" build.go
\t)
\t"$TERMUX_PKG_TMPDIR/syncthing-build-tool" -goos'''
        return t.replace('\tgo run build.go -goos',native)
    change('syncthing',syncthing)

    for name in ['upx','yoga']:
        change(name,lambda t:hook(t,'termux_step_pre_configure','\tCXXFLAGS+=" -nostdinc++"'))
    change('libobjc2',lambda t:t.replace('local target="$CCTERMUX_HOST_PLATFORM"',
        'local target="${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}"').replace(
        'export OBJCFLAGS="$CFLAGS --target=$target"','export OBJCFLAGS="$CFLAGS $CPPFLAGS --target=$target"').replace(
        'export OBJCXXFLAGS="$CXXFLAGS --target=$target"','export OBJCXXFLAGS="$CXXFLAGS $CPPFLAGS -nostdinc++ --target=$target"'))

    runtime=re.search(r'termux_step_pre_configure\(\) \{\n(.*?)\n\}',prepared['arpack-ng'],re.S).group(1)
    change('suitesparse',lambda t:t.replace('TERMUX_PKG_LICENSE="GPL-3.0"',
        'TERMUX_PKG_LICENSE="GPL-3.0, Apache-2.0"').replace('\ttermux_setup_flang',
        '\tCXXFLAGS+=" -nostdinc++"\n'+runtime))
    change('stag',lambda t:hook(t,'termux_step_pre_configure',
        '\tsed -i \'s/char unitprefixes\\[9\\]/char unitprefixes[]/\' "$TERMUX_PKG_SRCDIR/view.c"'))
    change('gifsicle',lambda t:t.replace('TERMUX_PKG_BUILD_DEPENDS="libx11"',
        'TERMUX_PKG_BUILD_DEPENDS="libx11, libsm"').replace('TERMUX_PKG_SUGGESTS="libx11"',
        'TERMUX_PKG_SUGGESTS="libx11, libsm"'))
    change('termux-gui-bash',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_C_COMPILER_TARGET=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL} -DCMAKE_CXX_COMPILER_TARGET=${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}"'))

    # QEMU needs the loader and libc from our own source-built AOSP package.
    # Bind them inside proot; never install or mutate the builder's /system.
    change('libntl',lambda t:t.replace(
        'termux_proot_run=(termux-proot-run env LD_PRELOAD= LD_LIBRARY_PATH=)',
        '''termux_proot_run=("$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH/proot"
            -q "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH/qemu-$TERMUX_ARCH"
            -R / -b "$TERMUX_PREFIX/opt/aosp:/system"
            /usr/bin/env LD_PRELOAD= LD_LIBRARY_PATH= ANDROID_ROOT=/system ANDROID_DATA=/data)'''))

    def btop(t):
        start=t.index('\tprintf ')
        end=t.index('\n\tchmod',start)
        return t[:start]+'''\tprintf '#!/bin/sh\\nexec /usr/bin/env -u LD_PRELOAD -u LD_LIBRARY_PATH "%s/proot" -q "%s/qemu-%s" -R / -b "%s/opt/aosp:/system" "%s/bin/lowdown" "$@"\\n' \\
\t\t"$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH" "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH" "$TERMUX_ARCH" "$TERMUX_PREFIX" "$TERMUX_PREFIX" > "$TERMUX_PKG_TMPDIR/bin/lowdown"'''+t[end:]
    change('btop',btop,tree='root-packages')

    change('unicode-data',lambda t:t.replace(
        'c961d4405edd144b5052cfaf8bf7db54af44ebc5db7181f83c6c52df99e9363a',
        '7b3e555514060b92290d154f53655c5eb0fa62b16eb04c03434ff72d1a66a0d8').replace(
        '835593ec1ca206486cdef6860a41930343ac014d7d61f7f7ef2b25084fadbdd4',
        '4c93ea9c1f636451729a840978f1667a53886af37ba854fdcce109721c63d43e'))
    change('xsettingsd',lambda t:t.replace(
        'https://codeberg.org/derat/xsettingsd/archive/v${TERMUX_PKG_VERSION}.tar.gz',
        'https://codeberg.org/derat/xsettingsd/archive/fd8029153ad2c9bcc0342b6c337034912093d6cf.tar.gz').replace(
        'fe56ced940390f97d08bbdad677eee8470387388e1cb54aea0dbff3308294a76',
        '3a36ce39bfadb3804c76b986c0654d211bb70ba85f900742dd3bb3403d17175f'),tree='x11-packages')
    change('libfakekey',lambda t:t.replace('TERMUX_PKG_VERSION=0.3',
        'TERMUX_PKG_VERSION=0.3+git20170516').replace(
        'https://git.yoctoproject.org/cgit/cgit.cgi/libfakekey/snapshot/libfakekey-${TERMUX_PKG_VERSION}.tar.gz',
        'https://deb.debian.org/debian/pool/main/libf/libfakekey/libfakekey_${TERMUX_PKG_VERSION}.orig.tar.xz').replace(
        'd282fa6481a5b85f71e36e8bad4cfa938cc8eaac4c42ffa27f9203ac634813f4',
        'ddbd308dc7f20390b2a6cb88bd077a62061a40533e209a14a94bdb36b32a0446'),tree='x11-packages')

    # The unavailable tutorial fork is replaced by the canonical project's
    # maintained release, mirrored as ORIGINAL source by Debian. Epoch ensures
    # upgrading from the old date-based version remains possible.
    def robot(t):
        t=t.replace('TERMUX_PKG_VERSION=2022.05.21','TERMUX_PKG_VERSION="1:2.8284271.702"').replace(
            'TERMUX_PKG_HOMEPAGE=https://github.com/noncombatant/robotfindskitten',
            'TERMUX_PKG_HOMEPAGE=https://robotfindskitten.org/').replace(
            'TERMUX_PKG_SRCURL=git+https://github.com/noncombatant/robotfindskitten',
            'TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/r/robotfindskitten/robotfindskitten_${TERMUX_PKG_VERSION#*:}.orig.tar.gz').replace(
            '58d9403ba1d3303b68a8fe82357d2c5ca69bf45c032670bf9b28d8c4a149496d',
            '020172e4f4630f7c4f62c03b6ffe2eeeba5637b60374d3e6952ae5816a9f99af')
        t=re.sub(r'^_COMMIT=.*\n|^TERMUX_PKG_GIT_BRANCH=.*\n','',t,flags=re.M)
        t=re.sub(r'termux_step_post_get_source\(\) \{.*?^\}\n','',t,flags=re.S|re.M)
        t=re.sub(r'termux_step_make_install\(\) \{.*?^\}\n','',t,flags=re.S|re.M)
        t=t.replace('TERMUX_PKG_EXTRA_MAKE_ARGS="-e"',
                    'TERMUX_PKG_EXTRA_MAKE_ARGS="-e execgamesdir=$TERMUX_PREFIX/bin"')
        return t
    change('robotfindskitten',robot)

    # Debian mirrors the identical pinned source; publisher blocks GitHub IPs.
    change('xvkbd', lambda t: t.replace('http://t-sato.in.coocan.jp/',
        'https://t-sato.in.coocan.jp/').replace(
        'https://t-sato.in.coocan.jp/xvkbd/xvkbd-${TERMUX_PKG_VERSION}.tar.gz',
        'https://deb.debian.org/debian/pool/main/x/xvkbd/xvkbd_${TERMUX_PKG_VERSION}.orig.tar.gz'), tree='x11-packages')
    change('thin-provisioning-tools', lambda t: hook(t, 'termux_step_pre_configure',
        '''\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\tsed -i '/#include <iosfwd>/a #include <stddef.h>' "$TERMUX_PKG_SRCDIR/persistent-data/hex_dump.h"'''), tree='root-packages')
    # Abseil pulled in by protobuf requires C++17. Fail rather than silently
    # missing a changed upstream standard setting.
    change('monero', lambda t: hook(t, 'termux_step_pre_configure',
        '''\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\tgrep -Fqx 'set(CMAKE_CXX_STANDARD 14)' "$TERMUX_PKG_SRCDIR/CMakeLists.txt" || return 1
\tsed -i 's/set(CMAKE_CXX_STANDARD 14)/set(CMAKE_CXX_STANDARD 17)/' "$TERMUX_PKG_SRCDIR/CMakeLists.txt"
\tgrep -q -- '-DCMAKE_CXX_STANDARD=14' "$TERMUX_PKG_SRCDIR/cmake/CheckTrezor.cmake" || return 1
\tsed -i 's/-DCMAKE_CXX_STANDARD=14/-DCMAKE_CXX_STANDARD=17/' "$TERMUX_PKG_SRCDIR/cmake/CheckTrezor.cmake"
\tpython3 - "$TERMUX_PKG_SRCDIR/src/device_trezor/trezor/messages_map.cpp" <<'TERMI_PROTOBUF_NAME'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
for accessor in ('msg->GetDescriptor()->name()', 'msg.GetDescriptor()->name()'):
    old='get_message_wire_number('+accessor+')'
    assert s.count(old)==1, 'Monero protobuf name anchor changed'
    s=s.replace(old,'get_message_wire_number(std::string('+accessor+'))')
p.write_text(s)
p=p.with_suffix('.hpp');s=p.read_text()
old='get_message_wire_number(t_message::default_instance().GetDescriptor()->name())'
assert s.count(old)==1, 'Monero protobuf template anchor changed'
p.write_text(s.replace(old,'get_message_wire_number(std::string(t_message::default_instance().GetDescriptor()->name()))'))
TERMI_PROTOBUF_NAME'''))
    # Android's link probe can see reallocarray without its API-level header
    # declaration. Use Xwayland's overflow-checked bundled implementation.
    change('xwayland', lambda t: hook(t, 'termux_step_pre_configure',
        '''\tgrep -q "conf_data.set('HAVE_REALLOCARRAY'," "$TERMUX_PKG_SRCDIR/include/meson.build" || return 1
\tsed -i "/conf_data.set('HAVE_REALLOCARRAY',/c\\conf_data.set('HAVE_REALLOCARRAY', false)" "$TERMUX_PKG_SRCDIR/include/meson.build"'''), tree='x11-packages')
    # Same verified source-built AOSP loader binding used by libntl/btop.
    change('sbcl', lambda t: hook(t, 'termux_step_make',
        '''\tcase "$TERMUX_ARCH" in
\t\taarch64) export SBCL_ARCH=arm64;;
\t\tx86_64) export SBCL_ARCH=x86-64;;
\t\t*) echo "Unsupported SBCL target: $TERMUX_ARCH" >&2; return 1;;
\tesac''').replace('termux-proot-run env LD_PRELOAD= LD_LIBRARY_PATH=',
        '''"$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH/proot" -q "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH/qemu-$TERMUX_ARCH" -R / -b "$TERMUX_PREFIX/opt/aosp:/system" /usr/bin/env LD_PRELOAD= LD_LIBRARY_PATH= ANDROID_ROOT=/system ANDROID_DATA=/data'''))

    # Vulkan-Hpp 1.4.365 uses per-command IS_DISPATCHED checks and no longer
    # declares isDispatchLoader. Keep legacy specializations for older headers.
    def vkmark(t):
        t=t.replace('TERMUX_PKG_BUILD_DEPENDS="glm, vulkan-headers"',
                    'TERMUX_PKG_BUILD_DEPENDS="glm, vulkan-headers, libwayland-cross-scanner"')
        t=t.replace('TERMUX_PKG_BUILD_DEPENDS="libwayland-cross-scanner"\n', '')
        return hook(t, 'termux_step_pre_configure', '''\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\tfor source in src/vulkan_state.cpp src/ws/kms_window_system.cpp; do
\t\tgrep -q '^#if VK_HEADER_VERSION >= 333$' "$TERMUX_PKG_SRCDIR/$source" || return 1
\t\tsed -i 's/^#if VK_HEADER_VERSION >= 333$/#if VK_HEADER_VERSION >= 333 \\&\\& VK_HEADER_VERSION < 365/' "$TERMUX_PKG_SRCDIR/$source"
\tdone''')
    change('vkmark', vkmark, tree='x11-packages')

    # GCC15 defaults to C23, where () means no arguments rather than K&R.
    # Only the Linux host generator needs the legacy C dialect.
    change('motif', lambda t: hook(t, 'termux_step_host_build',
        '''\texport CC="gcc -std=gnu17"
\tsed -i '1i#include <string.h>' "$TERMUX_PKG_SRCDIR/lib/Xm/XpmI.h"
\tpython3 - "$TERMUX_PKG_SRCDIR/tools/wml" <<'TERMI_WML_DECLARATIONS'
from pathlib import Path
import sys
for name in ('wmlparse.y', 'wmlparse.c'):
    p=Path(sys.argv[1])/name;s=p.read_text()
    anchor='#include "wml.h"'
    assert s.count(anchor)==1, 'Motif WML declaration anchor changed'
    s=s.replace(anchor,anchor+'\\nint yylex(void);\\nint yyerror(const char *s);')
    old='int yyerror (s)\\nchar *s;'
    assert s.count(old)==1, 'Motif WML error definition anchor changed'
    p.write_text(s.replace(old,'int yyerror(const char *s)'))
TERMI_WML_DECLARATIONS'''), tree='x11-packages')

    # GGML auto-detects the Android sccache in the target prefix, then invokes
    # its bare name as a Linux compiler launcher. Its own option disables it.
    change('groonga', lambda t: hook(t, 'termux_step_pre_configure',
        '''\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DGGML_CCACHE=OFF"'''))

    # libnl's pkg-config flags reference its private compatibility archive.
    # A seeded libnl has no old scratch tree; build this consumer's own copy
    # from the same pinned source rather than dropping the link requirement.
    change('nfs-utils', lambda t: hook(t, 'termux_step_pre_configure', '''\tlocal termi_getsubopt="$TERMUX_PKG_TMPDIR/getsubopt"
\tmkdir -p "$termi_getsubopt"
\t$CC $CFLAGS $CPPFLAGS -fvisibility=hidden -c "$TERMUX_PKG_BUILDER_DIR/../../packages/libnl/getsubopt.c" -o "$termi_getsubopt/getsubopt.o"
\t$AR crs "$termi_getsubopt/libgetsubopt.a" "$termi_getsubopt/getsubopt.o"
\tLDFLAGS+=" -L$termi_getsubopt"'''), tree='root-packages')
    # Auto-detection otherwise finds the target Android sccache in the seed.
    change('libdart', lambda t: hook(t, 'termux_step_pre_configure',
        '''\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DDART_DISABLE_COMPILER_CACHE=ON"'''))

    # Arrow's separate Python extension configure also needs the matching
    # target libc++ headers ahead of the prefix C headers.
    change('libarrow-cpp', lambda t: hook(hook(t, 'termux_step_pre_configure',
        '\texport CXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"'),
        'termux_step_post_make_install',
        '''\texport CXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\t# PyArrow puts target include directories before CMAKE_CXX_FLAGS.
\t# Prepend matching libc++ headers at compiler invocation instead.
\tlocal termi_arrow_cxx="$TERMUX_PKG_TMPDIR/termi-arrow-cxx"
\tprintf '#!/bin/bash\\nexec %q -nostdinc++ -I%q "$@"\\n' "$CXX" "$TERMUX_PREFIX/include/c++/v1" > "$termi_arrow_cxx"
\tchmod 755 "$termi_arrow_cxx"''').replace(
        '-C cmake.args="-DCMAKE_PREFIX_PATH=$TERMUX_PREFIX/lib/cmake"',
        '-C cmake.args="-DCMAKE_CXX_COMPILER=$termi_arrow_cxx" \\\n\t\t-C cmake.args="-DCMAKE_PREFIX_PATH=$TERMUX_PREFIX/lib/cmake"'))

    # Replace global-state strtok with the equivalent per-invocation state.
    # Android's declaration is deprecated, and upstream enables -Werror.
    change('xrdp', lambda t: hook(t, 'termux_step_pre_configure', '''\tpython3 - "$TERMUX_PKG_SRCDIR/common/string_calls.c" <<'TERMI_XRDP'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
for old,new in [
    ('p = strtok(properties, delim);', 'char *token_state = NULL;\\n    p = strtok_r(properties, delim, &token_state);'),
    ('p = strtok(NULL, delim);', 'p = strtok_r(NULL, delim, &token_state);')]:
    assert s.count(old)==1, 'xrdp tokenizer anchor changed'
    s=s.replace(old,new)
p.write_text(s)
TERMI_XRDP'''), tree='x11-packages')

    # GHC's Android interpreter needs the same own-AOSP binding as libntl.
    # Regenerate only this recipe's iserv wrappers after setup, not global tools.
    change('git-annex', lambda t: t.replace('\t\ttermux_setup_ghc_iserv\n', '''\t\ttermux_setup_ghc_iserv
\t\tlocal termi_iserv="$TERMUX_PKG_TMPDIR/termi-iserv"
\t\tmkdir -p "$termi_iserv"
\t\tlocal ghc_bin_dir="$(ghc --print-libdir)/../bin" suffix
\t\tfor suffix in "" -dyn; do
\t\t\tprintf '#!/bin/bash\\nexec /usr/bin/env -u LD_PRELOAD -u LD_LIBRARY_PATH "%s/proot" -q "%s/qemu-%s" -R / -b "%s/opt/aosp:/system" /usr/bin/env LD_PRELOAD= LD_LIBRARY_PATH="%s/lib" ANDROID_ROOT=/system ANDROID_DATA=/data "%s/ghc-iserv%s" "$@"\\n' \\
\t\t\t    "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH" "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH" "$TERMUX_ARCH" "$TERMUX_PREFIX" "$TERMUX_PREFIX" "$ghc_bin_dir" "$suffix" > "$termi_iserv/termux-ghc-iserv$suffix"
\t\t\tchmod 755 "$termi_iserv/termux-ghc-iserv$suffix"
\t\tdone
\t\texport PATH="$termi_iserv:$PATH"
'''))

    # libbpf-sys also builds for a Linux-host build dependency. Its Makefile
    # otherwise inherits Android CPPFLAGS/pkg-config paths from the recipe.
    change('below', lambda t: t.replace('\tcargo fetch --target $CARGO_TARGET_NAME\n', '''\tcargo fetch --target $CARGO_TARGET_NAME
\tpython3 - "$CARGO_HOME" <<'TERMI_LIBBPF'
from pathlib import Path
import sys
files=list(Path(sys.argv[1]).glob('registry/src/*/libbpf-sys-*/build.rs'))
assert files, 'libbpf-sys source missing'
setup = """
    if let (Ok(host), Ok(target)) = (env::var("HOST"), env::var("TARGET")) {
        if host == target && target.ends_with("-linux-gnu") {
            for key in ["CPPFLAGS", "LDFLAGS", "CFLAGS", "CXXFLAGS", "CPATH",
                        "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH",
                        "PKG_CONFIG_PATH", "PKG_CONFIG_LIBDIR", "PKG_CONFIG_SYSROOT_DIR",
                        "LIBBPF_SYS_EXTRA_CFLAGS", "BINDGEN_EXTRA_CLANG_ARGS"] {
                env::remove_var(key);
            }
            env::set_var("CC", "/usr/bin/gcc");
            env::set_var("CXX", "/usr/bin/g++");
            env::set_var("HOST_CFLAGS", "-O2");
            env::set_var("HOST_CXXFLAGS", "-O2");
            env::set_var("PKG_CONFIG", "/usr/bin/pkg-config");
        }
    }
"""
for p in files:
    s=p.read_text()
    assert s.count('fn main() {')==1, 'libbpf-sys main anchor changed'
    p.write_text(s.replace('fn main() {', 'fn main() {'+setup))
TERMI_LIBBPF
'''), tree='root-packages')
