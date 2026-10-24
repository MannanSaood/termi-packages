"""Narrow, revisioned repairs from the first complete parallel build diagnostics."""
import re


def apply(patch, original):
    def change(name, edit):
        path=f"packages/{name}/build.sh"
        before=original(path)
        after=edit(before)
        revision=re.search(r"^TERMUX_PKG_REVISION=(\d+)$",after,re.M)
        if revision:
            after=after[:revision.start()]+f"TERMUX_PKG_REVISION={int(revision[1])+1}"+after[revision.end():]
        else:
            after=re.sub(r"^(TERMUX_PKG_VERSION=.*)$",r"\1\nTERMUX_PKG_REVISION=1",after,count=1,flags=re.M)
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
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_STANDARD=17"
\tCXXFLAGS+=" -std=c++17 -include float.h"'''))
    change("gnucap",lambda t:hook(t,"termux_step_pre_configure",'\tCXXFLAGS+=" -include float.h"'))
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
        '\tsed -i \'1i#include <sys/vfs.h>\' "$TERMUX_PKG_SRCDIR/env/io_posix.cc"'))
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
