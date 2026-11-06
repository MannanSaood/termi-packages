"""Repairs grounded in the first completed four-lane catalog failure logs."""
import re

SIMULAVR_ARCH_PATCH = r'''from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1]) / 'debian/CMakeLists.txt'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '8ec6796364fad6e377f23f0309faac82b30a53a4f0da71d8abe12f3ba981d8e4', 'SimulAVR pinned architecture mapping changed'
anchor = b'else()\n  message(SEND_ERROR "unknown system architecture: ${CMAKE_SYSTEM_PROCESSOR}")'
assert raw.count(anchor) == 1, 'SimulAVR architecture fallback changed'
p.write_bytes(raw.replace(anchor, b'elseif(${CMAKE_SYSTEM_PROCESSOR} MATCHES "^(aarch64|arm64)$")\n  set(PACKAGE_ARCHITECTURE "arm64")\n' + anchor))
'''
SIMULAVR_ARCH_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" <<\'TERMI_SIMULAVR_ARCH\'\n' + SIMULAVR_ARCH_PATCH + 'TERMI_SIMULAVR_ARCH\n'

FIO_STATIC_FLEX_PATCH = r'''from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1]) / 'configure'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'df3f5666b53a1491c1dc15cf7288a3110e7a913d195c8842afd4361758c1f277', 'fio pinned configure changed'
anchor = b'if compile_prog "" "-lfl" "flex"; then\n  LIBS="-lfl $LIBS"'
assert raw.count(anchor) == 1, 'fio flex probe changed'
static = str(Path(sys.argv[2]) / 'lib/libfl.a').encode()
assert Path(static.decode()).is_file(), 'Source-built static flex provider missing'
p.write_bytes(raw.replace(anchor, b'if compile_prog "" "'+static+b'" "flex"; then\n  LIBS="'+static+b' $LIBS"'))
'''
FIO_STATIC_FLEX_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" "$TERMUX_PREFIX" <<\'TERMI_FIO_FLEX\'\n' + FIO_STATIC_FLEX_PATCH + 'TERMI_FIO_FLEX\n'

LIBIME_ANDROID_LOADER_SETUP = r'''		local termi_proot_bin="$TERMUX_PKG_TMPDIR/termi-proot-bin"
		mkdir -p "$termi_proot_bin"
		python3 - "$(command -v termux-proot-run)" "$termi_proot_bin/termux-proot-run" "$TERMUX_PREFIX" <<'TERMI_LIBIME_PROOT'
from pathlib import Path
import shlex, sys
source, target, prefix = map(Path, sys.argv[1:])
assert (prefix/'opt/aosp/bin/linker64').is_file(), 'Source-built Android linker missing'
s = source.read_text()
anchor = '-R / "$@"'
assert s.count(anchor) == 1, 'LibIME proot root contract changed'
target.write_text(s.replace(anchor, '-R / -b '+shlex.quote(str(prefix/'opt/aosp')+':/system')+' "$@"'))
target.chmod(0o755)
TERMI_LIBIME_PROOT
		export PATH="$termi_proot_bin:$PATH"
'''

ICES_SOUNDCARD_PATCH = r'''from pathlib import Path
import hashlib
import sys
root = Path(sys.argv[1])
outputs = {}
for name, digest in [('im_alsa.c', '9b8774aa62b5ae9894496a06bf7e40087c3c58dc7c176095b7d47a54b94a33a7'), ('im_oss.c', '6fc5b9c9fa6060ac186fa910676b8be28a45b9947315aca79d0bad081f2bb567')]:
    p = root / 'src' / name
    raw = p.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, 'IceS pinned sound input changed: ' + name
    anchor = b'#include <sys/soundcard.h>'
    assert raw.count(anchor) == 1, 'IceS soundcard include changed: ' + name
    outputs[p] = raw.replace(anchor, b'#include <linux/soundcard.h>')
for p, raw in outputs.items():
    p.write_bytes(raw)
'''
ICES_SOUNDCARD_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" <<\'TERMI_ICES_SOUNDCARD\'\n' + ICES_SOUNDCARD_PATCH + 'TERMI_ICES_SOUNDCARD\n'

CHROMIUM_TARGET_PREFIX_PATCH = r'''from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1])
prefix = sys.argv[2].encode()
assert prefix == b'/data/data/com.terminal.nextgen/files/usr', 'Chromium requires the Termi prefix'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '344ec5292cdd240892b9ad37d529d22b0afc9c3f416ca10104320802f2b34f3f', 'Chromium pinned SwiftShader override changed'
old = b'/data/data/com.termux/files/usr'
assert raw.count(old) == 2 and prefix not in raw, 'Chromium SwiftShader prefix contract changed'
p.write_bytes(raw.replace(old, prefix))
'''


SYNCTHING_NATIVE_GENERATE_PATCH = r"""from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1]) / 'build.go'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '58c41a6b262b7c1aa81514b19f9b5310ff9c7af9bd6ec7f2b76e0be7b67a8948', 'Syncthing 2.1.6 build driver changed'
anchor = b'\tecmd := exec.Command(cmd, args...)\n\tecmd.Stdout = os.Stdout\n'
assert raw.count(anchor) == 1, 'Syncthing printed command contract changed'
replacement = b'''\tecmd := exec.Command(cmd, args...)
\tif cmd == goCmd && len(args) > 0 && args[0] == "generate" {
\t\tfor _, entry := range os.Environ() {
\t\t\tkey := strings.SplitN(entry, "=", 2)[0]
\t\t\tif key == "GOOS" || key == "GOARCH" || key == "CC" || key == "CXX" || key == "CFLAGS" || key == "CXXFLAGS" || key == "CPPFLAGS" || key == "LDFLAGS" || strings.HasPrefix(key, "CGO_") {
\t\t\t\tcontinue
\t\t\t}
\t\t\tecmd.Env = append(ecmd.Env, entry)
\t\t}
\t\tecmd.Env = append(ecmd.Env, "GOOS="+runtime.GOOS, "GOARCH="+runtime.GOARCH, "CGO_ENABLED=0")
\t}
\tecmd.Stdout = os.Stdout
'''
p.write_bytes(raw.replace(anchor, replacement))
"""

SYNCTHING_NATIVE_GENERATE_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_SYNCTHING_NATIVE_GENERATE'\n" + SYNCTHING_NATIVE_GENERATE_PATCH + "TERMI_SYNCTHING_NATIVE_GENERATE\n"

WLR_NATIVE_SCDOC_SETUP = r'''
	if [ "$TERMUX_ON_DEVICE_BUILD" = false ]; then
		local _termi_scdoc="$TERMUX_PKG_CACHEDIR/termi-native-scdoc-1.11.5"
		if [ ! -x "$_termi_scdoc/bin/scdoc" ] || [ ! -f "$_termi_scdoc/share/pkgconfig/scdoc.pc" ]; then
			local _termi_scdoc_archive="$TERMUX_PKG_TMPDIR/scdoc-1.11.5.tar.gz"
			termux_download https://git.sr.ht/~sircmpwn/scdoc/archive/1.11.5.tar.gz "$_termi_scdoc_archive" 98780bbdf16c1bce89ef3a8c0f537ac6e4ea77087b609e7698857614488a2a62
			mkdir -p "$_termi_scdoc/src" "$_termi_scdoc/bin" "$_termi_scdoc/share/pkgconfig"
			tar -xf "$_termi_scdoc_archive" -C "$_termi_scdoc/src" --strip-components=1
			(
				unset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH
				export CC=gcc CFLAGS=-O2
				make -C "$_termi_scdoc/src" scdoc scdoc.pc PREFIX="$_termi_scdoc" OUTDIR="$_termi_scdoc/obj"
			)
			cp "$_termi_scdoc/src/scdoc" "$_termi_scdoc/bin/scdoc"
			cp "$_termi_scdoc/src/scdoc.pc" "$_termi_scdoc/share/pkgconfig/scdoc.pc"
		fi
		termux_setup_pkg_config_wrapper "$_termi_scdoc/share/pkgconfig"
	fi
'''

QT5_PERFETTO_INTEGER_PATCH = r'''from pathlib import Path
import hashlib
import sys
root = Path(sys.argv[1])
outputs = {}
for name, digest, anchor in (
    ('include/perfetto/ext/tracing/core/slice.h', 'b9b0eab08331aa50cedd79b59e76a622bee19dbd5794b994e6b0711e3abfb50c', b'#include <stddef.h>\n'),
    ('src/trace_processor/importers/gzip/gzip_utils.h', '5901cf92b506cae0ea070822feaaea64a6651cef5de741af52bf7162d8f2c1a2', b'#include <memory>\n'),
):
    p = root / name
    raw = p.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, 'Qt5 pinned Perfetto integer header changed: ' + name
    assert raw.count(anchor) == 1 and b'#include <stdint.h>' not in raw, 'Qt5 Perfetto integer include contract changed'
    outputs[p] = raw.replace(anchor, anchor + b'#include <stdint.h>\n')
# The old Perfetto revision has more headers that rely on transitive integer
# declarations. Its private default config reaches every Perfetto target but
# is not propagated to Chromium embedders. Fix Linux host compilation together,
# retaining Android target flags and the two already verified header repairs.
p = root / 'gn/BUILD.gn'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '5eab2bef990322bcccacd77f5ff55b89559ec29ad54dae1014575cdcdba4c977', 'Qt5 pinned Perfetto GN config changed'
anchor = b'config("default_config") {\n  configs = [ ":public_config" ]\n'
assert raw.count(anchor) == 1, 'Qt5 Perfetto private config contract changed'
addition = b'  if (current_toolchain == host_toolchain && !is_win) {\n    cflags_cc = [ "-include", "stdint.h" ]\n  }\n'
outputs[p] = raw.replace(anchor, anchor + addition)
# Chromium's other old native generators have the same integer-header
# assumptions. Use toolchain identity: Qt5's Android target is Linux-labelled.
# This hash includes the recipe's existing Android-target compiler patch.
p = root.parent.parent / 'build/config/compiler/BUILD.gn'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '69fe1a23781b90b73073be98dd30360046cb5e8f57d16a545108807d2abc11af', 'Qt5 post-upstream Chromium compiler config changed'
anchor = b'config("compiler") {\n  asmflags = []\n  cflags = []\n  cflags_c = []\n  cflags_cc = []\n'
assert raw.count(anchor) == 1, 'Qt5 Chromium host compiler config contract changed'
addition = b'  if (current_toolchain == host_toolchain && !is_win) {\n    cflags_cc += [ "-include", "stdint.h" ]\n  }\n'
outputs[p] = raw.replace(anchor, anchor + addition)
# New gperf already emits its own conditional fallthrough attribute. The old
# wrapper must not append a second annotation before the same switch label.
p = root.parent.parent / 'third_party/blink/renderer/build/scripts/gperf.py'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'de7d6c0577dffc1d84778ec5d45c0058c0e688560ef52e383e492adb6772275e', 'Qt5 pinned gperf wrapper changed'
anchor = b"        gperf_output = gperf_output.replace('/*FALLTHROUGH*/',\n                                            '  FALLTHROUGH;')\n"
assert raw.count(anchor) == 1, 'Qt5 gperf fallthrough contract changed'
outputs[p] = raw.replace(anchor, b"        if '[[fallthrough]]' not in gperf_output:\n" + b''.join(b'    ' + line for line in anchor.splitlines(keepends=True)))
# Do not instantiate value-construction traits for an Optional's own copy
# assignment. Eager && substitution recurses through LayoutUnit's constructor
# on Clang21; the existing conjunction preserves the original eligibility.
p = root.parent.parent / 'base/optional.h'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '1cb7210bddde45ec35801273565f4a386b35073942d35370539efe53d97b4dc5', 'Qt5 pinned Optional header changed'
anchor = b"""      !std::is_same<internal::RemoveCvRefT<U>, Optional<T>>::value &&
          std::is_constructible<T, U>::value &&
          std::is_assignable<T&, U>::value &&
          (!std::is_scalar<T>::value ||
           !std::is_same<std::decay_t<U>, T>::value),"""
replacement = b"""      conjunction<
          negation<std::is_same<internal::RemoveCvRefT<U>, Optional<T>>>,
          std::is_constructible<T, U>,
          std::is_assignable<T&, U>,
          disjunction<negation<std::is_scalar<T>>,
                      negation<std::is_same<std::decay_t<U>, T>>>>::value,"""
assert raw.count(anchor) == 1, 'Qt5 Optional forwarding-assignment contract changed'
outputs[p] = raw.replace(anchor, replacement)
# Qt's Chromium targets do not consume the qmake CXXFLAGS. Put the explicit
# C++ header policy in their compiler command, before pkg-config's C -I paths.
# The native host and v8_snapshot commands retain their system headers.
p = root.parent.parent / 'build/toolchain/gcc_toolchain.gni'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '8730a4075eacb34203db0c40b5a6d5104eab552e87df987e40e3e40739a8f422', 'Qt5 pinned GCC toolchain template changed'
anchor = b'    cxx = compiler_prefix + invoker.cxx\n'
addition = b"""    if (target_name == "target") {
      assert(invoker_toolchain_args.current_cpu == "arm64")
      cxx += " -nostdinc++ -I/data/data/com.terminal.nextgen/files/usr/include/c++/v1"
    }
"""
assert raw.count(anchor) == 1, 'Qt5 target C++ compiler contract changed'
outputs[p] = raw.replace(anchor, anchor + addition)
# Android's private alignment macro is absent from current NDK headers.
# Preserve the shim's unsigned page rounding and existing overflow check.
p = root.parents[3] / 'core/api/qtbug-61521.cpp'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'c3c6bbb79dd2efece285c1dbe727aae387dd0403337a71b19b412906a7ad268d', 'Qt5 post-patch allocator shim changed'
anchor = b'    size_t bytes = __BIONIC_ALIGN(size, pagesize);'
assert raw.count(anchor) == 1, 'Qt5 page alignment contract changed'
outputs[p] = raw.replace(anchor, b'    size_t bytes = (size + pagesize - 1) & ~(pagesize - 1);')
# Check every pinned input before modifying any source file.
for p, raw in outputs.items():
    p.write_bytes(raw)
'''
QT5_PERFETTO_INTEGER_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR/src/3rdparty/chromium/third_party/perfetto" <<\'TERMI_QT5_PERFETTO_INTEGER\'\n' + QT5_PERFETTO_INTEGER_PATCH + 'TERMI_QT5_PERFETTO_INTEGER\n'

CHROMIUM_SKIA_FLOAT_PATCH = r'''from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1]) / 'third_party/skia/src/utils/SkFloatUtils.h'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'eacd25581a236bb26d8120eb6a154618f4d022819e9116771b421ec7b3369b83', 'Chromium155 pinned Skia float helper changed'
for anchor in (b'#include <float.h>', b'const int digits = DBL_MANT_DIG;', b'const int digits = FLT_MANT_DIG;'):
    assert raw.count(anchor) == 1, 'Skia numeric precision contract changed'
raw = raw.replace(b'#include <float.h>', b'#include <limits>')
raw = raw.replace(b'const int digits = DBL_MANT_DIG;', b'const int digits = std::numeric_limits<double>::digits;')
raw = raw.replace(b'const int digits = FLT_MANT_DIG;', b'const int digits = std::numeric_limits<float>::digits;')
p.write_bytes(raw)
'''
CHROMIUM_SKIA_FLOAT_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" <<\'TERMI_CHROMIUM_SKIA_FLOAT\'\n' + CHROMIUM_SKIA_FLOAT_PATCH + 'TERMI_CHROMIUM_SKIA_FLOAT\n'

CODE_OSS_REMOTE_ENV_PATCH = r'''from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1]) / 'build/npm/postinstall.ts'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '38ce19931f2fe825d31e870c68346d60ab16df81270d9988e4b5b617118c9283', 'Code OSS post-patch npm environment source changed'
anchor = b"\t\t\t\tsetNpmrcConfig('remote', env);\n"
assert raw.count(anchor) == 1, 'Code OSS remote npm configuration contract changed'
addition = b"""\t\t\t\tif (!process.env['VSCODE_REMOTE_CC'] && !process.env['VSCODE_REMOTE_CXX']) {
\t\t\t\t\tdelete env['CPPFLAGS'];
\t\t\t\t\tenv['npm_config_nodedir'] = '';
\t\t\t\t}
"""
p.write_bytes(raw.replace(anchor, anchor + addition))
'''
CODE_OSS_REMOTE_ENV_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" <<\'TERMI_CODE_OSS_REMOTE_ENV\'\n' + CODE_OSS_REMOTE_ENV_PATCH + 'TERMI_CODE_OSS_REMOTE_ENV\n'

CODE_OSS_COPILOT_SDK_PATCH = r'''from pathlib import Path
import hashlib
import sys
p = Path(sys.argv[1]) / 'build/lib/extensions.ts'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '57281576d6ac70f0dbc0ad238952a8e489f4edf3bab886df59b94d497e81f583', 'Code OSS pinned extension packaging source changed'
rules = (Path(sys.argv[1]) / 'build/.moduleignore').read_bytes()
assert rules.splitlines().count(b'@github/copilot/sdk/index.js') == 1, 'Code OSS app-wide SDK exclusion contract changed'
anchor = b"\t\t\t.pipe(util2.cleanNodeModules(path.join(root, 'build', `.moduleignore.${process.platform}`)))\n\t).pipe(util2.setExecutableBit(['**/*.sh']));\n}\n\nexport function packageMarketplaceExtensionsStream"
replacement = b"""\t\t\t.pipe(util2.cleanNodeModules(path.join(root, 'build', `.moduleignore.${process.platform}`))),
\t\t// The app-wide cleaner strips sdk/index.js. The built-in extension
\t\t// needs its own SDK entry point before platform files are materialized.
\t\tgulp.src('extensions/copilot/node_modules/@github/copilot/sdk/index.js', { base: '.', allowEmpty: false })
\t).pipe(util2.setExecutableBit(['**/*.sh']));
}

export function packageMarketplaceExtensionsStream"""
assert raw.count(anchor) == 1, 'Code OSS built-in Copilot dependency stream contract changed'
p.write_bytes(raw.replace(anchor, replacement))
'''
CODE_OSS_COPILOT_SDK_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" <<\'TERMI_CODE_OSS_COPILOT_SDK\'\n' + CODE_OSS_COPILOT_SDK_PATCH + 'TERMI_CODE_OSS_COPILOT_SDK\n'

ELECTRON42_PREFIX_PATCH = r'''from pathlib import Path
import hashlib
import sys
root = Path(sys.argv[1])
prefix = sys.argv[2].encode()
assert prefix == b'/data/data/com.terminal.nextgen/files/usr', 'Electron42 requires the Termi prefix'
old = b'/data/data/com.termux/files/usr'
outputs = {}
for name, digest in (
    ('third_party/swiftshader/src/Vulkan/BUILD.gn', '543265f631be647857dd2cf4595ca9ce982c795d349272db188dec88b6d6a632'),
    ('third_party/electron_node/deps/cares/src/lib/ares_private.h', '27bb6479b657f67455a6afcef33c14014312c9ff6c27b5535262e3da5adc9f85'),
):
    p = root / name
    raw = p.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, 'Electron42 pinned post-patch prefix input changed: ' + name
    assert raw.count(old) == 2 and prefix not in raw, 'Electron42 prefix occurrence contract changed: ' + name
    outputs[p] = raw.replace(old, prefix)
# Check both pinned inputs before changing either file.
for p, raw in outputs.items():
    p.write_bytes(raw)
'''
ELECTRON42_PREFIX_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" "$TERMUX_PREFIX" <<\'TERMI_ELECTRON42_PREFIX\'\n' + ELECTRON42_PREFIX_PATCH + 'TERMI_ELECTRON42_PREFIX\n'

CODE_OSS_ELECTRON_PREFIX_PATCH = r'''from pathlib import Path
import hashlib
import sys
root = Path(sys.argv[1])
prefix = sys.argv[2].encode()
assert prefix == b'/data/data/com.terminal.nextgen/files/usr', 'Code OSS Electron requires the Termi prefix'
outputs = {}
p = root / 'third_party/swiftshader/src/Vulkan/BUILD.gn'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '175ec858d32bd5acad8cc3a138503530654832de1bdaa2a3f1038ef263efe863', 'Code OSS Electron pinned SwiftShader override changed'
old = b'/data/data/com.termux/files/usr'
assert raw.count(old) == 2 and prefix not in raw, 'Code OSS Electron SwiftShader prefix contract changed'
outputs[p] = raw.replace(old, prefix)
# Node 24.18 predates the Termux-specific paths in Node 24.19. Change only
# its two default-platform resolver paths, preserving other OS branches.
p = root / 'third_party/electron_node/deps/cares/src/lib/ares_private.h'
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '70280e6e5b5b664d3dda55816411ec49bb9a350c52b60b8b61318f5e157e7275', 'Code OSS Electron pinned resolver header changed'
for name in (b'resolv.conf', b'hosts'):
    anchor = b'"/etc/' + name + b'"'
    assert raw.count(anchor) == 1, 'Code OSS Electron resolver path contract changed'
    raw = raw.replace(anchor, b'"' + prefix + b'/etc/' + name + b'"')
outputs[p] = raw
for p, raw in outputs.items():
    p.write_bytes(raw)
'''
CODE_OSS_ELECTRON_PREFIX_SETUP = '\tpython3 - "$TERMUX_PKG_SRCDIR" "$TERMUX_PREFIX" <<\'TERMI_CODE_OSS_ELECTRON_PREFIX\'\n' + CODE_OSS_ELECTRON_PREFIX_PATCH + 'TERMI_CODE_OSS_ELECTRON_PREFIX\n'

NTL_GMP_DIAGNOSTICS = r'''from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
anchor = '   if (!CheckGMP()) {\n'
assert s.count(anchor) == 1, 'NTL GMP probe anchor changed'
# DoConfig redirects compiler errors into this file, then hides it on failure.
# Keep the original probe and fatal error; expose a bounded diagnostic only.
s = s.replace(anchor, anchor + '      print STDERR "TERMI_NTL_GMP_PROBE_LOG\\n";\n'
              + '      system("tail -c 65536 OneCompilerOutput.log >&2");\n')
p.write_text(s)
'''

NTL_GMP_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR/src/DoConfig\" <<'TERMI_NTL_GMP_DIAGNOSTICS'\n" + NTL_GMP_DIAGNOSTICS + "TERMI_NTL_GMP_DIAGNOSTICS\n"
NTL_CXX_HEADERS = '\tCXXFLAGS+=" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"\n'

STEGHIDE_FLAGS_PATCH = r'''from pathlib import Path
import sys
root = Path(sys.argv[1])
outputs = {}
for name in ('configure', 'configure.in'):
    p = root / name
    s = p.read_text()
    for flags, count in (('-std=c++11 -O2 -Wall -g', 1), ('-std=c++11 -O2 -Wall', 2)):
        old = 'CXXFLAGS="' + flags + '"'
        assert s.count(old) == count, 'Steghide configure flags contract changed: ' + name
        s = s.replace(old, 'CXXFLAGS="$CXXFLAGS ' + flags + '"')
    outputs[p] = s
for p, s in outputs.items():
    p.write_text(s)
'''
STEGHIDE_FLAGS_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_STEGHIDE_FLAGS'\n" + STEGHIDE_FLAGS_PATCH + "TERMI_STEGHIDE_FLAGS\n"

LLAMA_VULKAN_ALLOCATION_PATCH = r"""from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
anchor = '#else\n    return std::aligned_alloc(align, size);\n#endif'
cleanup = 'static void portable_aligned_free(void * ptr) {\n#ifdef _WIN32\n    _aligned_free(ptr);\n#else\n    std::free(ptr);\n#endif\n}'
assert s.count(anchor) == 1 and s.count(cleanup) == 1, 'llama.cpp aligned allocation contract changed'
assert '#elif defined(__ANDROID__) && __ANDROID_API__ < 28' not in s, 'llama.cpp allocation repair already present'
replacement = '''#elif defined(__ANDROID__) && __ANDROID_API__ < 28
    void * ptr = nullptr;
    return posix_memalign(&ptr, align, size) == 0 ? ptr : nullptr;
#else
    return std::aligned_alloc(align, size);
#endif'''
p.write_text(s.replace(anchor, replacement))
"""
LLAMA_VULKAN_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR/ggml/src/ggml-vulkan/ggml-vulkan-buffers.cpp\" <<'TERMI_LLAMA_ALIGNED'\n" + LLAMA_VULKAN_ALLOCATION_PATCH + "TERMI_LLAMA_ALIGNED\n"

# Ollama's upstream 0006 patch must run first. Replace its API<26 branch
# after patching, retaining the same checked API<28 allocator used above.
OLLAMA_VULKAN_ALLOCATION_PATCH = LLAMA_VULKAN_ALLOCATION_PATCH.replace(
    's = p.read_text()\n',
    's = p.read_text()\n' +
    "upstream = '#elif defined(__ANDROID__) && __ANDROID_API__ < 26\\n\\tvoid *result = nullptr;\\n\\t(void)::posix_memalign(&result, align, size);\\n\\treturn result;\\n'\n" +
    "assert s.count(upstream) == 1, 'Ollama upstream allocator patch changed'\n" +
    "s = s.replace(upstream, '')\n")

OPENSC_TOKENIZER_PATCH = r"""from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
anchor = '\tif (strchr(profile->name, \'+\') != NULL) {\n\t\tchar\t*s;\n\n\t\ti = 0;\n\t\t(void) strtok(profile->name, "+");\n\t\twhile ((s = strtok(NULL, "+")) != NULL) {'
assert s.count(anchor) == 1, 'OpenSC profile tokenization contract changed'
replacement = anchor.replace('char\t*s;', 'char\t*s, *termi_profile_save = NULL;')
replacement = replacement.replace('strtok(profile->name, "+")', 'strtok_r(profile->name, "+", &termi_profile_save)')
replacement = replacement.replace('strtok(NULL, "+")', 'strtok_r(NULL, "+", &termi_profile_save)')
p.write_text(s.replace(anchor, replacement))
"""
OPENSC_TOKENIZER_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR/src/pkcs15init/pkcs15-lib.c\" <<'TERMI_OPENSC_PROFILE'\n" + OPENSC_TOKENIZER_PATCH + "TERMI_OPENSC_PROFILE\n"

FOOT_OSC_TOKENIZER_PATCH = r'''from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
headers = [
    '        for (const char *s_idx = strtok(string, ";"), *s_color = strtok(NULL, ";");\n             s_idx != NULL && s_color != NULL;\n             s_idx = strtok(NULL, ";"), s_color = strtok(NULL, ";"))',
    '            for (const char *s_idx = strtok(string, ";");\n                 s_idx != NULL;\n                 s_idx = strtok(NULL, ";"))',
]
assert s.count('strtok(') == 6 and 'termi_osc_save' not in s, 'Foot OSC tokenizer contract changed'
for header in headers:
    assert s.count(header) == 1, 'Foot OSC loop changed'
    indent = header[:len(header) - len(header.lstrip())]
    replacement = header.replace('strtok(string, ";")', 'strtok_r(string, ";", &termi_osc_save)').replace('strtok(NULL, ";")', 'strtok_r(NULL, ";", &termi_osc_save)')
    s = s.replace(header, indent + 'char *termi_osc_save = NULL;\n' + replacement)
p.write_text(s)
'''
FOOT_OSC_TOKENIZER_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR/osc.c\" <<'TERMI_FOOT_OSC'\n" + FOOT_OSC_TOKENIZER_PATCH + "TERMI_FOOT_OSC\n"

FOOT_CONFIG_TOKENIZER_PATCH = r'''from pathlib import Path
import sys
root = Path(sys.argv[1])
sites = {
    'config.c': [
        ('    for (const char *conf_dir = strtok(xdg_config_dirs_copy, ":");\n         conf_dir != NULL;\n         conf_dir = strtok(NULL, ":"))', 'termi_conf_dirs_save', 'xdg_config_dirs_copy', ':'),
        ('    const char *first_as_str = strtok(value_copy, " ");\n    const char *second_as_str = strtok(NULL, " ");', 'termi_color_save', 'value_copy', ' '),
        ('    for (const char *font = strtok(copy, ",");\n         font != NULL;\n         font = strtok(NULL, ","))', 'termi_fonts_save', 'copy', ','),
    ],
    'slave.c': [
        ('    for (const char *path = strtok(path_list, ":");\n         path != NULL;\n         path = strtok(NULL, ":"))', 'termi_paths_save', 'path_list', ':'),
    ],
    'utils/xtgettcap.c': [
        ('                const char *key = strtok(key_value, "=");\n                const char *value = strtok(NULL, "=");', 'termi_key_value_save', 'key_value', '='),
    ],
}
outputs = {}
for name, entries in sites.items():
    p = root / name
    s = p.read_text()
    assert s.count('strtok(') == 2 * len(entries), 'Foot tokenizer count changed: ' + name
    for anchor, state, initial, delimiter in entries:
        assert s.count(anchor) == 1 and state not in s, 'Foot tokenizer scope changed: ' + name
        replacement = anchor
        for argument in [initial, 'NULL']:
            replacement = replacement.replace('strtok(' + argument + ', "' + delimiter + '")', 'strtok_r(' + argument + ', "' + delimiter + '", &' + state + ')')
        indent = anchor[:len(anchor) - len(anchor.lstrip())]
        s = s.replace(anchor, indent + 'char *' + state + ' = NULL;\n' + replacement)
    outputs[p] = s
for p, s in outputs.items():
    p.write_text(s)
'''
FOOT_OSC_TOKENIZER_SETUP += "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_FOOT_CONFIG'\n" + FOOT_CONFIG_TOKENIZER_PATCH + "TERMI_FOOT_CONFIG\n"

OPENSC_PKCS11_TOKENIZER_PATCH = r'''from pathlib import Path
import sys
root = Path(sys.argv[1])
changes = {
    'src/pkcs11/misc.c': [
        ('char *create_slots_for_pins = NULL, *op, *tmp;', 'char *create_slots_for_pins = NULL, *op, *tmp, *termi_slots_save = NULL;'),
        ('strtok(tmp, " ,")', 'strtok_r(tmp, " ,", &termi_slots_save)'),
        ('strtok(NULL, " ,")', 'strtok_r(NULL, " ,", &termi_slots_save)'),
    ],
    'src/tools/pkcs11-tool.c': [
        ('char *s = NULL;', 'char *s = NULL, *termi_mechanisms_save = NULL;'),
        ('strtok(optarg, ",")', 'strtok_r(optarg, ",", &termi_mechanisms_save)'),
        ('strtok(NULL, ",")', 'strtok_r(NULL, ",", &termi_mechanisms_save)'),
    ],
    'src/tools/pkcs11_uri.c': [
        ('char *path, *query, *token;', 'char *path, *query, *token, *termi_uri_save = NULL;'),
        ('strtok(path, "?")', 'strtok_r(path, "?", &termi_uri_save)'),
        ('strtok(NULL, "?")', 'strtok_r(NULL, "?", &termi_uri_save)'),
        ('strtok(path, ";")', 'strtok_r(path, ";", &termi_uri_save)'),
        ('strtok(query, ";")', 'strtok_r(query, ";", &termi_uri_save)'),
        ('strtok(NULL, ";")', 'strtok_r(NULL, ";", &termi_uri_save)'),
    ],
}
# Validate every original anchor before writing any file. URI path/query scans
# are sequential, just as in the original parser, and can share local state.
outputs = {}
for name, replacements in changes.items():
    p = root / name
    s = p.read_text()
    assert 'termi_' not in s, 'OpenSC tokenizer repair already present'
    for old, new in replacements:
        expected = 2 if name.endswith('pkcs11_uri.c') and old == 'strtok(NULL, ";")' else 1
        assert s.count(old) == expected, 'OpenSC tokenizer contract changed: ' + name + ': ' + old
        s = s.replace(old, new)
    assert 'strtok(' not in s, 'Unreviewed OpenSC tokenizer remains: ' + name
    outputs[p] = s
for p, s in outputs.items():
    p.write_text(s)
'''
OPENSC_TOKENIZER_SETUP += "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_OPENSC_PKCS11'\n" + OPENSC_PKCS11_TOKENIZER_PATCH + "TERMI_OPENSC_PKCS11\n"

OCTAVE_FORTRAN_LINK = r'''
	export F77="$FC"
	# Autoconf links a C main against the Fortran runtime directly. Use this
	# attempt's source-built PIC archive and its Android C++/backtrace providers.
	export ac_cv_f77_libs="$work/runtime-build/flang-rt/lib/libflang_rt.runtime.a -Wl,--push-state,--no-as-needed -lc++ -landroid-execinfo -Wl,--pop-state -lm"
'''

OCTAVE_CONFIG_DIAGNOSTICS = r'''
termux_step_configure_autotools_failure_hook() {
	if [ -f "$TERMUX_PKG_SRCDIR/config.log" ]; then
		printf '%s\n' TERMI_OCTAVE_CONFIG_LOG >&2
		tail -c 65536 "$TERMUX_PKG_SRCDIR/config.log" >&2
	fi
	false
}
'''

OCTAVE_EPSILON_REPAIR = r'''from pathlib import Path
import sys
p = Path(sys.argv[1]) / 'liboctave/external/Faddeeva/Faddeeva.cc'
s = p.read_text()
assert s.count('DBL_EPSILON') == 4, 'Faddeeva epsilon sites/comment changed'
assert s.count('#  include <limits>') == 1 and s.count('#  include <float.h>') == 1, 'Faddeeva header branches changed'
# The Android/gnulib C++ header chain does not expose DBL_EPSILON here.
# Use the standard typed value in C++; retain the original C99 macro branch.
s = s.replace('DBL_EPSILON', 'TERMI_FADDEEVA_EPSILON')
s = s.replace('#  include <limits>', '#  include <limits>\n#  define TERMI_FADDEEVA_EPSILON (std::numeric_limits<double>::epsilon())')
s = s.replace('#  include <float.h>', '#  include <float.h>\n#  define TERMI_FADDEEVA_EPSILON DBL_EPSILON')
p.write_text(s)
'''

OCTAVE_EPSILON_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_OCTAVE_EPSILON'\n" + OCTAVE_EPSILON_REPAIR + "TERMI_OCTAVE_EPSILON\n"

PROJ_EPSILON_REPAIR = r'''from pathlib import Path
import sys
p = Path(sys.argv[1]) / 'src/projections/gnom.cpp'
s = p.read_text()
anchor = '0.01 * sqrt(DBL_EPSILON)'
assert s.count(anchor) == 1 and s.count('DBL_EPSILON') == 1, 'PROJ gnomonic epsilon changed'
assert s.count('#include <math.h>') == 1, 'PROJ gnomonic headers changed'
# Preserve the double-precision convergence threshold when Android's C header
# chain does not expose DBL_EPSILON to this C++ translation unit.
s = s.replace('#include <math.h>', '#include <math.h>\n#include <limits>')
s = s.replace(anchor, '0.01 * sqrt(std::numeric_limits<double>::epsilon())')
p.write_text(s)
p = Path(sys.argv[1]) / 'src/apps/proj_strtod.cpp'
s = p.read_text()
assert s.count('#include <limits>') == 1, 'PROJ converter limits header changed'
for old, new in [('DBL_MIN_EXP', 'std::numeric_limits<double>::min_exponent'),
                 ('DBL_MAX_EXP', 'std::numeric_limits<double>::max_exponent')]:
    assert s.count(old) == 1, 'PROJ converter exponent bounds changed'
    s = s.replace(old, new)
p.write_text(s)
'''

PROJ_EPSILON_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_PROJ_EPSILON'\n" + PROJ_EPSILON_REPAIR + "TERMI_PROJ_EPSILON\n"


def octave_fortran_recipe(text, runtime):
    # CMake options belong to the runtime's subshell, not Octave's configure.
    runtime, count = re.subn(r'^\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS\+=.*CMAKE_Fortran_COMPILER.*\n?',
                            '', runtime, flags=re.M)
    assert count == 1, 'Fortran runtime outer CMake options changed'
    pattern = r'\ttermux_setup_flang\n.*?\texport ac_cv_f77_libs="[^\n]*"\n'
    matches = list(re.finditer(pattern, text, re.S))
    assert len(matches) == 1, 'Octave legacy runtime setup changed'
    old = matches[0].group()
    assert 'libFortranRuntime.a' in old and 'libFortranDecimal.a' in old
    text = text[:matches[0].start()] + OCTAVE_EPSILON_SETUP + runtime + OCTAVE_FORTRAN_LINK + text[matches[0].end():]
    def dependencies(match):
        names = match[1].split(', ')
        names += [n for n in ['libc++', 'libandroid-execinfo'] if n not in names]
        return 'TERMUX_PKG_DEPENDS="' + ', '.join(names) + '"'
    text, count = re.subn(r'^TERMUX_PKG_DEPENDS="([^"]*)"$', dependencies, text, flags=re.M)
    assert count == 1, 'Octave dependency declaration changed'
    assert text.count('TERMUX_PKG_LICENSE="GPL-3.0"') == 1
    return text.replace('TERMUX_PKG_LICENSE="GPL-3.0"',
                        'TERMUX_PKG_LICENSE="GPL-3.0, Apache-2.0"') + OCTAVE_CONFIG_DIAGNOSTICS

AWS_PRIVATE_CRYPTO = r"""
	local termi_crypto_cc="$TERMUX_PKG_TMPDIR/termi-aws-crypto-cc"
	python3 - "$CC" "$termi_crypto_cc" <<'TERMI_AWS_CRYPTO_CC'
from pathlib import Path
import shlex, sys
compiler=shlex.split(sys.argv[1])
assert len(compiler)==1, 'Unexpected AWS C compiler command'
body=r'''#!/bin/bash
set -euo pipefail
args=("$@")
crypto=0
for argument in "${args[@]}"; do
    [[ "$argument" != "-l:libcrypto.a" ]] || crypto=1
done
if (( crypto )); then
    bundled=()
    for argument in "${args[@]}"; do
        case "$argument" in
            -L*/deps/install/lib)
                directory="${argument#-L}"
                [[ -f "$directory/libcrypto.a" ]] && bundled+=("$directory/libcrypto.a")
                ;;
        esac
    done
    [[ "${#bundled[@]}" == 1 ]] || { echo "Cannot identify private AWS-LC archive" >&2; exit 2; }
    archive="$(realpath -- "${bundled[0]}")"
    for index in "${!args[@]}"; do
        [[ "${args[index]}" != "-l:libcrypto.a" ]] || args[index]="$archive"
    done
fi
exec @COMPILER@ "${args[@]}"
'''
p=Path(sys.argv[2]);p.write_text(body.replace('@COMPILER@',shlex.quote(compiler[0])));p.chmod(0o755)
TERMI_AWS_CRYPTO_CC
	export CC="$termi_crypto_cc"
"""


QT5_HOST_HEADERS = r'''
_termi_qt5_host_headers() {
    python3 - "$TERMUX_PREFIX/include" "$TERMUX_PKG_TMPDIR/termi-qt5-host-headers" <<'TERMI_QT5_HOST_HEADERS'
from pathlib import Path
import re, shutil, sys
prefix=Path(sys.argv[1]);private=Path(sys.argv[2]);private.mkdir(parents=True,exist_ok=True)
assert not any(c.isspace() for c in str(private)), 'Unexpected Qt host include path'
# Host tools need Qt's portable headers, never the Android C sysroot.
for source in prefix.glob('Qt*'):
    if source.is_dir() and not (private/source.name).exists():
        shutil.copytree(source,private/source.name)
files=[p for p in Path.cwd().glob('Makefile*') if p.is_file() and not p.is_symlink()]
assert files, 'Qt host qmake produced no makefile'
pattern=r'(?<!\S)(?:-I|-isystem)\s*'+re.escape(str(prefix))+r'(?=\s|$)'
for p in files:
    s=re.sub(pattern,'',p.read_text())
    s,n=re.subn(r'(?m)^(INCPATH\s*=.*)$',lambda m:m[1]+' -I'+str(private),s)
    assert n==1, 'Qt host INCPATH assignment changed'
    p.write_text(s)
TERMI_QT5_HOST_HEADERS
}
'''

LDC_HOST_XML_SETUP = r'''
# LDC 1.30's official Linux host bootstrap needs the older libxml2 SONAME.
# Keep this source-built compatibility library private to the host recipe.
_termi_ldc_host_xml() {
    local base="$TERMUX_PKG_HOSTBUILD_DIR/termi-host-xml"
    local install="$base/install"
    if [ ! -f "$install/lib/libxml2.so.2" ]; then
        local archive="$TERMUX_PKG_TMPDIR/libxml2-2.13.9.tar.xz"
        termux_download https://download.gnome.org/sources/libxml2/2.13/libxml2-2.13.9.tar.xz \
            "$archive" a2c9ae7b770da34860050c309f903221c67830c86e4a7e760692b803df95143a
        mkdir -p "$base"
        tar -xf "$archive" -C "$base"
        (
            cd "$base/libxml2-2.13.9"
            unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH
            unset PKG_CONFIG_PATH PKG_CONFIG_SYSROOT_DIR
            export CC=gcc CXX=g++ CFLAGS=-O2 CXXFLAGS=-O2 CPPFLAGS= LDFLAGS=
            export PKG_CONFIG_LIBDIR=/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig
            ./configure --build=x86_64-pc-linux-gnu --host=x86_64-pc-linux-gnu \
                --prefix="$install" --libdir="$install/lib" --enable-shared --disable-static \
                --without-python --without-lzma --without-zlib --without-icu
            make -j "$TERMUX_PKG_MAKE_PROCESSES"
            make install
        )
    fi
    export LD_LIBRARY_PATH="$install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}
'''


NEATVNC_ALLOCATION_PATCH = r'''from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old = """\tbuffer->addr = aligned_alloc(alignment, aligned_size);
\tif (!buffer->addr) {
\t\tfree(buffer);
\t\treturn NULL;
\t}"""
new = """\tint allocation_error = posix_memalign(&buffer->addr, alignment, aligned_size);
\tif (allocation_error || !buffer->addr) {
\t\tfree(buffer);
\t\tif (allocation_error)
\t\t\terrno = allocation_error;
\t\treturn NULL;
\t}"""
assert s.count(old)==1 and s.count('#include <stdlib.h>')==1, 'neatvnc allocation contract changed'
p.write_text(s.replace('#include <stdlib.h>', '#include <stdlib.h>\n#include <errno.h>').replace(old,new))
'''


NETCDF_PTHREAD_PATCH = r'''from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
old = '#if 0\n#include <pthread.h>            /* link with -lpthread */\n#endif'
assert s.count(old)==1, 'netcdf CRC pthread include contract changed'
p.write_text(s.replace(old, '/* Termi: declare pthread_once explicitly for Android CRC table initialization. */\n#include <pthread.h>'))
'''


WESTON_MEMFD_PATCH = r'''from pathlib import Path
import sys
root=Path(sys.argv[1])
for name in ['shared/client-buffer-util.c', 'libweston/backend-pipewire/pipewire.c']:
    p=root/name; s=p.read_text()
    old='#if defined(__ANDROID__) && __ANDROID_API__ < 26'
    assert s.count(old)==1 and '#define memfd_create(' in s, 'Weston memfd compatibility contract changed: '+name
    p.write_text(s.replace(old, '#if defined(__ANDROID__) && __ANDROID_API__ < 30'))
'''


def neatvnc_build_prerequisites(text):
    anchor = 'TERMUX_PKG_AUTO_UPDATE=true'
    assert text.count(anchor) == 1 and 'TERMUX_PKG_BUILD_DEPENDS=' not in text, 'neatvnc build prerequisites changed'
    # GnuTLS publishes Requires.private: libzstd. Meson needs that metadata
    # even for a shared consumer; the source-built zstd provider is required.
    return text.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="zstd"\n' + anchor)


def netcdf_build_prerequisites(text):
    anchor = 'TERMUX_PKG_BUILD_IN_SRC=true'
    assert text.count(anchor) == 1 and 'TERMUX_PKG_BUILD_DEPENDS=' not in text, 'netcdf build prerequisites changed'
    # The seeded curl link metadata references -lzstd when NetCDF links its
    # utilities. Import the completed source provider into the focused seed.
    return text.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="zstd"\n' + anchor)


def redland_build_prerequisites(text):
    anchor = 'TERMUX_PKG_AUTO_UPDATE=true'
    assert text.count(anchor) == 1 and 'TERMUX_PKG_BUILD_DEPENDS=' not in text, 'Redland build prerequisites changed'
    # Rasqal's retained libtool metadata names libmpfr.la. The focused build
    # must import the completed MPFR provider, including its static metadata.
    return text.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libmpfr"\n' + anchor)


def libreoffice_build_prerequisites(text):
    anchor = 'TERMUX_PKG_BUILD_DEPENDS="ant, boost-headers, cppunit, gtk3, kf6-kconfig, kf6-kcoreaddons, kf6-ki18n, kf6-kio, kf6-kwindowsystem, qt6-qtbase, qt6-qtbase-cross-tools, qt6-qtmultimedia, postgresql, openjdk-21, openjdk-21-x, unixodbc, mariadb, libc++"'
    assert text.count(anchor) == 1, 'LibreOffice build prerequisites changed'
    # Retained pkg-config metadata needs libdeflate through libtiff, XRes
    # through at-spi2, and ORC through GStreamer's video/audio modules.
    return text.replace(anchor, anchor.replace('"ant,', '"ndk-sysroot, libdeflate, libxres, liborc, ant,'))


def webkitgtk6_header_provider(text):
    deps = 'TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, xorgproto"'
    anchor = '\ttermux_setup_gir\n'
    assert text.count(deps) == text.count(anchor) == 1, 'WebKitGTK 6 build anchors changed'
    # This recipe resets its CMake arguments from webkit2gtk-4.1 first. Add
    # the launcher afterwards so the effective compiler keeps one C++ tree.
    launcher = '''\tlocal termi_webkit_launcher="$TERMUX_PKG_TMPDIR/termi-webkit-cxx-launcher"
\tprintf '#!/bin/bash\\ncompiler="$1"\\nshift\\nexec "$compiler" -nostdinc++ -I%q "$@"\\n' "$TERMUX_PREFIX/include/c++/v1" > "$termi_webkit_launcher"
\tchmod 755 "$termi_webkit_launcher"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER_LAUNCHER=$termi_webkit_launcher"
'''
    # GTK4/TIFF and GStreamer retain private pkg-config requirements too.
    return text.replace(deps, deps.replace('"g-ir-scanner,', '"ndk-sysroot, libdeflate, libxres, liborc, g-ir-scanner,')).replace(anchor, anchor + launcher)


def fossil_host_flags(text):
    anchor = 'CC="$CC $CPPFLAGS $CFLAGS $LDFLAGS"\n\tunset CFLAGS LDFLAGS'
    assert text.count(anchor) == 1, 'Fossil cross/native flag boundary changed'
    # Target flags are already captured in CC. Fossil also substitutes
    # CPPFLAGS into BCCFLAGS for its Linux translate/mkindex generators.
    return text.replace(anchor, anchor.replace('unset CFLAGS', 'unset CPPFLAGS CFLAGS'))



EMACS_SECCOMP_TARGET_PATCH = r'''from pathlib import Path
import sys
p = Path(sys.argv[1]) / "lib-src/Makefile.in"
s = p.read_text()
anchor = 'ifeq ($(shell uname -m),x86_64)'
assert s.count(anchor) == 1, 'Emacs seccomp architecture gate changed'
assert '# Currently, we can only generate seccomp filter files for x86-64.' in s
# The generator uses x86 arch_prctl and runs the target-built executable.
# Select it by configure's target host CPU, not the cross-builder's uname.
p.write_text(s.replace(anchor, 'ifeq (@host_cpu@,x86_64)'))
'''
EMACS_SECCOMP_TARGET_SETUP = "\tpython3 - \"$TERMUX_PKG_SRCDIR\" <<'TERMI_EMACS_SECCOMP_TARGET'\n" + EMACS_SECCOMP_TARGET_PATCH + "TERMI_EMACS_SECCOMP_TARGET\n"


QT6_WEBENGINE_CXX_LAUNCHER = r'''	local termi_qt_cxx termi_qt_launcher
	termi_qt_cxx="$(command -v "$CXX")"
	termi_qt_launcher="$TERMUX_PKG_TMPDIR/termi-qtwebengine-cxx-launcher"
	printf '#!/bin/bash\ncompiler="$1"\nshift\ntarget=%q\nheaders=%q\ncase "$compiler" in\n  "$target"|"${target##*/}") exec "$compiler" -nostdinc++ -I "$headers" "$@";;\n  *) exec "$compiler" "$@";;\nesac\n' "$termi_qt_cxx" "$TERMUX_PREFIX/include/c++/v1" > "$termi_qt_launcher"
	chmod 755 "$termi_qt_launcher"
	TERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER_LAUNCHER=$termi_qt_launcher"
'''


def apply(change, hook, prepared):
    def megacmd_target_headers(text):
        version = 'TERMUX_PKG_VERSION=(\n\t"2.6.0"\n\t"10.19.0"\n)\n'
        anchor = '\nTERMUX_PKG_DEPENDS='
        assert text.count(version) == 1 and text.count(anchor) == 1 and 'TERMUX_PKG_BUILD_DEPENDS=' not in text, 'MEGAcmd source/provider contract changed'
        text = text.replace(anchor, '\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot"\nTERMUX_PKG_DEPENDS=')
        return hook(text, 'termux_step_pre_configure', '\tCXXFLAGS+=" -nostdinc++"\n')
    change('megacmd', megacmd_target_headers)
    def seafile_immutable_source(text):
        url = 'https://github.com/haiwen/seafile/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz'
        checksum = '60d79e7933d15da3f8aad17888aeab5fcad9e2e9ec5ecc1ec76f7aef1b3bd91f'
        assert 'TERMUX_PKG_VERSION="9.0.22"\n' in text and text.count(url) == text.count(checksum) == 1, 'Seafile source contract changed'
        # Official v9.0.22 commit; all 217 exported files match Git objects.
        return text.replace(url, 'https://codeload.github.com/haiwen/seafile/tar.gz/0a4ec322cc654b903c163d52a019f798a0db5739').replace(checksum, 'b896a960af96f01c8329686a5ce22995b854e64cb8c5f01811b82fd6c04fc4bb')
    change('seafile-client', seafile_immutable_source)
    def coherent_target_headers(text, version, provider=None, after_python=False):
        assert text.count('TERMUX_PKG_VERSION=' + version + '\n') == 1, 'C++ header repair source version changed'
        if provider is not None:
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="' + provider + '"'
            assert text.count(anchor) == 1, 'C++ header providers changed'
            text = text.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, ' + provider + '"')
        else:
            anchor = '\nTERMUX_PKG_DEPENDS='
            assert 'TERMUX_PKG_BUILD_DEPENDS=' not in text and text.count(anchor) == 1, 'C++ header dependency anchor changed'
            text = text.replace(anchor, '\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot"\nTERMUX_PKG_DEPENDS=')
        # The standard target CMake step already uses the prefix C++ headers.
        # Host generators run before this hook and keep their native flags.
        body = '\tCXXFLAGS+=" -nostdinc++"\n'
        if after_python:
            anchor = '\tfi\n}\n'
            assert text.count(anchor) == 1 and text.count('\t\ttermux_setup_build_python\n') == 1, 'Glaxnimate host Python boundary changed'
            return text.replace(anchor, '\tfi\n' + body + '}\n')
        return hook(text, 'termux_step_pre_configure', body)
    for name, tree, version, provider, after_python in [
        ('libduckdb', 'packages', '"1.5.6"', None, False),
        ('openttd', 'x11-packages', '"15.3"', None, False),
        ('supertux', 'x11-packages', '"0.7.0"', 'glm', False),
        ('lenmus', 'x11-packages', '6.0.1', None, False),
        ('transmission', 'packages', '"4.1.3"', None, False),
        ('glaxnimate', 'x11-packages', '"0.6.0"', 'extra-cmake-modules', True),
    ]:
        change(name, lambda text, version=version, provider=provider, after_python=after_python: coherent_target_headers(text, version, provider, after_python), tree=tree)
    change('foot', lambda text: hook(text, 'termux_step_pre_configure', FOOT_OSC_TOKENIZER_SETUP), tree='x11-packages')
    def libsearpc_immutable_source(text):
        url = 'https://github.com/haiwen/libsearpc/archive/refs/tags/v${TERMUX_PKG_VERSION:2:3}-latest.tar.gz'
        checksum = '7f800339ff712dbea024e7bd8b8aca989cd235f0a366dde3b56936192d358ad3'
        assert 'TERMUX_PKG_VERSION=1:3.3.0\n' in text and text.count(url) == text.count(checksum) == 1, 'libsearpc source contract changed'
        # Official v3.3-latest commit; all 72 files match verified Git objects.
        return text.replace(url, 'https://codeload.github.com/haiwen/libsearpc/tar.gz/3a4548697a498c951bd421248bcbdb1873f7616d').replace(checksum, '6f8b76a86a50bec3bb74519d8361ae9af8248d3d570ad8382125bbe72c031cac')
    change('libsearpc', libsearpc_immutable_source)
    # Pin release Git trees verified independently of mutable tag archive hashes.
    for package, tree, repository, commit, before, after in [
        ('libfcft', 'x11-packages', 'dnkl/fcft', 'ccd1afaad891d77c040bad04120e9f602438fc33',
         'f18bf79562e06d41741690cd1e07a02eb2600ae39eb5752eef8a698f603a482c', '9949fbce0826669369c3b9361ac04b0459fdc51037e2ccf2e2483794909903f4'),
        ('wallust', 'packages', 'explosion-mental/wallust', 'b689616d630bb2e541695f101d313699464aac09',
         '46c2592217f0de968437850b14b2e844f2af4158b70135b2b448dc426c0309a1', '8609d27162975777797f2f625d884a6475c766ed943393219d585577ac8bfcfe')]:
        old_url = 'https://codeberg.org/' + repository + '/archive/${TERMUX_PKG_VERSION}.tar.gz'
        new_url = 'https://codeberg.org/' + repository + '/archive/' + commit + '.tar.gz'
        def pin_release(text, old=old_url, new=new_url, old_hash=before, new_hash=after):
            assert text.count(old) == 1 and text.count(old_hash) == 1, 'Codeberg release source changed'
            return text.replace(old, new).replace(old_hash, new_hash)
        change(package, pin_release, tree=tree)
    def icoutils_download(text):
        old = 'https://savannah.nongnu.org/download/icoutils/icoutils-$TERMUX_PKG_VERSION.tar.bz2'
        assert text.count(old) == 1, 'icoutils source URL changed'
        return text.replace(old, 'https://download.savannah.nongnu.org/releases/icoutils/icoutils-$TERMUX_PKG_VERSION.tar.bz2')
    change('icoutils', icoutils_download)
    def ollama_target_headers(text):
        providers = 'TERMUX_PKG_BUILD_DEPENDS="spirv-headers, vulkan-headers"'
        flags = r'set(CMAKE_CXX_FLAGS "\${CMAKE_CXX_FLAGS} --target=${CCTERMUX_HOST_PLATFORM} ${CPPFLAGS} ${CXXFLAGS}")'
        assert text.count(providers) == 1 and text.count(flags) == 1, 'Ollama target toolchain changed'
        text = text.replace(providers, providers.replace('spirv-headers', 'ndk-sysroot, spirv-headers')).replace(
            flags, flags.replace('${CXXFLAGS}")', '${CXXFLAGS} -nostdinc++")'))
        repair = '\tpython3 - "$TERMUX_PKG_SRCDIR/llama-cpp-source/ggml/src/ggml-vulkan/ggml-vulkan-buffers.cpp" <<\'TERMI_OLLAMA_ALIGNED\'\n' + OLLAMA_VULKAN_ALLOCATION_PATCH + 'TERMI_OLLAMA_ALIGNED\n'
        return hook(text, 'termux_step_pre_configure', repair)
    change('ollama', ollama_target_headers)
    def gotify_browser_install(text):
        old = '\t(cd ui && yarn install && yarn build)\n'
        assert text.count(old) == 1, 'Gotify UI build commands changed'
        return text.replace(old, '\t(cd ui && PUPPETEER_SKIP_DOWNLOAD=true yarn install && yarn build)\n')
    change('gotify', gotify_browser_install)
    change('kstars', lambda text: hook(text, 'termux_step_pre_configure',
        '\tCXXFLAGS+=" -nostdinc++"\n'), tree='x11-packages')
    def qb64_headers(text):
        old = 'exec $TERMUX_STANDALONE_TOOLCHAIN/bin/$CXX -I$TERMUX_PREFIX/include "\\$@"'
        new = 'exec "$TERMUX_STANDALONE_TOOLCHAIN/bin/$CXX" -nostdinc++ -I"$TERMUX_STANDALONE_TOOLCHAIN/sysroot/usr/include/c++/v1" -I"$TERMUX_PREFIX/include" "\\$@"'
        assert text.count(old) == 1, 'QB64 target C++ wrapper changed'
        return text.replace(old, new)
    change('qb64', qb64_headers, tree='x11-packages')
    def qt6_webengine_headers(text):
        assert text.count('\ttermux_step_configure_cmake\n') == 1 and 'CMAKE_CXX_COMPILER_LAUNCHER' not in text, 'Qt6 WebEngine CMake launcher contract changed'
        # Qt forwards this launcher to Chromium's GN cc_wrapper. Select only
        # its target C++ compiler, leaving host tools and C commands unchanged.
        return hook(text, 'termux_step_pre_configure', QT6_WEBENGINE_CXX_LAUNCHER)
    change('qt6-qtwebengine', qt6_webengine_headers, tree='x11-packages')
    def netpbm_host_language(text):
        anchor = '\techo "CFLAGS_FOR_BUILD = " >> config.mk'
        assert text.count(anchor) == 1, 'Netpbm host language flags anchor changed'
        return text.replace(anchor, anchor.replace('CFLAGS_FOR_BUILD = ', 'CFLAGS_FOR_BUILD = -std=gnu17'))
    change('netpbm', netpbm_host_language)
    def mpv_aaudio_platform_gate(text):
        line = next(line for line in text.splitlines() if '\tsed -i ' in line and 'aaudio_opt =' in line)
        anchor = line + '\n\tfi\n'
        assert text.count(anchor) == 1 and line.startswith('\t\t'), 'mpv AAudio fallback boundary changed'
        # Both recipes mark Android false to avoid mpv's Android application
        # path. Keep AAudio's real header check on API26 too, not just below it.
        text = text.replace(anchor, '\tfi\n' + line[1:] + '\n')
        # libass and libplacebo retain private pkg-config requirements. Import
        # their completed source-built providers into each focused prefix.
        deps = 'TERMUX_PKG_BUILD_DEPENDS="vulkan-headers, vulkan-loader-generic"'
        if 'TERMUX_PKG_BUILD_DEPENDS=' in text:
            assert text.count(deps) == 1, 'mpv-X build providers changed'
            return text.replace(deps, deps.replace('"vulkan-headers,', '"libunibreak, libdeflate, vulkan-headers,'))
        return text + '\nTERMUX_PKG_BUILD_DEPENDS="libunibreak, libdeflate, vulkan-headers, vulkan-loader-generic"\n'
    for name, tree in [('mpv', 'packages'), ('mpv-x', 'x11-packages')]:
        change(name, mpv_aaudio_platform_gate, tree=tree)
    for name, tree in [('emacs', 'packages'), ('emacs-x', 'x11-packages')]:
        change(name, lambda t: hook(t, 'termux_step_post_get_source', EMACS_SECCOMP_TARGET_SETUP), tree=tree)
    def httrack_spawn_provider(text):
        anchor = 'TERMUX_PKG_DEPENDS="httrack-data, libandroid-execinfo, libiconv, openssl, zlib"'
        assert text.count(anchor) == 1, 'HTTrack runtime dependency anchor changed'
        # The crash symbolizer retains backtraces on API26 through the
        # source-built spawn compatibility library, as in the MuPDF repair.
        text = text.replace(anchor, anchor.replace('libandroid-execinfo,', 'libandroid-execinfo, libandroid-spawn,'))
        return hook(text, 'termux_step_pre_configure', '\tLDFLAGS+=" -landroid-spawn"')
    change('httrack', httrack_spawn_provider)
    change('fossil', fossil_host_flags)
    change('webkitgtk-6.0', webkitgtk6_header_provider, tree='x11-packages')
    change('libreoffice', lambda t: hook(libreoffice_build_prerequisites(t), 'termux_step_pre_configure', NTL_CXX_HEADERS), tree='x11-packages')
    change('redland', redland_build_prerequisites)
    change('proj', lambda t: hook(t, 'termux_step_pre_configure', PROJ_EPSILON_SETUP))
    # Two libc++ wrapper trees share include guards. Their include_next chain
    # can stop before Clang's float.h, hiding the macros Boost uses to select
    # floating-point types. Use the seeded libc++ tree consistently.
    def xerces_header_provider(t):
        # libc++ ships only its runtime. The focused seed must also import
        # the completed NDK sysroot that supplies include/c++/v1/new, etc.
        # Curl link metadata also needs the completed zstd provider.
        assert 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'Xerces build prerequisites changed'
        return t + '\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, zstd"\n'
    def focused_cxx_header_provider(t):
        assert 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'C++ header prerequisites changed'
        return t + '\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot"\n'
    for name in ('osm2pgsql', 'libprotobuf-c', 'libvigra', 'xerces-c', 'gdal', 'lnav', 'libpinyin', 'lensfun', 'libdevil', 'codon', 'steghide', 'taskwarrior', 'pkgfile', 'mariadb'):
        change(name, lambda t, name=name: hook(
            xerces_header_provider(t) if name == 'xerces-c' else focused_cxx_header_provider(t) if name in {'lnav', 'libpinyin', 'lensfun', 'libdevil', 'codon', 'steghide', 'taskwarrior', 'pkgfile', 'mariadb'} else t,
            'termux_step_pre_configure', NTL_CXX_HEADERS + (STEGHIDE_FLAGS_SETUP if name == 'steghide' else '')))
    for name in ('dosbox-x', 'xmoto', 'glmark2'):
        change(name, lambda t: hook(focused_cxx_header_provider(t), 'termux_step_pre_configure', NTL_CXX_HEADERS), tree='x11-packages')
    def mangohud_header_provider(t):
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="dbus, libandroid-wordexp, nlohmann-json"'
        assert t.count(anchor) == 1, 'MangoHud build prerequisites changed'
        return hook(t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, dbus, libandroid-wordexp, nlohmann-json"'), 'termux_step_pre_configure', NTL_CXX_HEADERS)
    change('mangohud', mangohud_header_provider, tree='x11-packages')
    def godot_header_provider(t):
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="pulseaudio, yasm"'
        assert t.count(anchor) == 1, 'Godot build prerequisites changed'
        return hook(t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, pulseaudio, yasm"'), 'termux_step_pre_configure', NTL_CXX_HEADERS)
    change('godot', godot_header_provider, tree='x11-packages')
    for name, deps in (
        ('krfb', 'extra-cmake-modules, kf6-kdoctools, libxdamage, plasma-wayland-protocols'),
        ('okular', 'ebook-tools, extra-cmake-modules, kdegraphics-mobipocket'),
        ('calligra', 'boost, eigen, extra-cmake-modules, kf6-kconfig-cross-tools, kf6-kdoctools, kf6-kdoctools-cross-tools, qt6-qttools'),
    ):
        def kde_header_provider(t, deps=deps):
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="' + deps + '"'
            assert t.count(anchor) == 1, 'KDE consumer build prerequisites changed'
            return hook(t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, ' + deps + '"'), 'termux_step_pre_configure', NTL_CXX_HEADERS)
        change(name, kde_header_provider, tree='x11-packages')
    def llama_header_provider(t):
        anchor='TERMUX_PKG_BUILD_DEPENDS="ocl-icd, opencl-headers, spirv-headers, vulkan-headers"'
        assert t.count(anchor)==1, 'llama.cpp build prerequisites changed'
        return hook(t.replace(anchor,anchor.replace('="','="ndk-sysroot,',1).replace('ndk-sysroot,ocl','ndk-sysroot, ocl')), 'termux_step_pre_configure', NTL_CXX_HEADERS + LLAMA_VULKAN_SETUP)
    change('llama-cpp', llama_header_provider)
    change('opensc', lambda t: hook(t, 'termux_step_pre_configure', OPENSC_TOKENIZER_SETUP))
    change('vitetris', lambda t: hook(t, 'termux_step_pre_configure', r'''	python3 - "$TERMUX_PKG_SRCDIR/src/netw/tty_socket.c" <<'TERMI_VITETRIS_TIME'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
anchor='#include <errno.h>\n'
assert s.count(anchor)==1 and '#include <time.h>' not in s, 'vitetris time declaration anchor changed'
p.write_text(s.replace(anchor,anchor+'#include <time.h>\n'))
TERMI_VITETRIS_TIME
'''))
    # A catalog prefix may also contain libei (input emulation). Resolve
    # erl_call's EI symbols from the exact archive built by this recipe.
    change('erlang', lambda t: hook(t, 'termux_step_pre_configure', r'''	python3 - "$TERMUX_PKG_SRCDIR/lib/erl_interface/src/Makefile.in" <<'TERMI_ERLANG_EI'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
for archive, tail in [('MT_EILIB', ' $(THR_LIBS) $(LIBS)'), ('ST_EILIB', ' $(LIBS)')]:
    prefix='$(ERL_CALL): $(ERLCALL) ../include/ei.h $('+archive+')\n'
    start=s.find(prefix)
    assert start >= 0 and s.count(prefix)==1, 'Erlang erl_call archive rule changed'
    end=s.index('\nendif', start)
    block=s[start:end]
    anchor='-L$(OBJDIR) -lei'+tail
    assert block.count(anchor)==1, 'Erlang erl_call link anchor changed'
    s=s[:start]+block.replace(anchor,'$('+archive+')'+tail)+s[end:]
p.write_text(s)
TERMI_ERLANG_EI
'''))

    def postgis_metadata_provider(t):
        assert 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'PostGIS build prerequisites changed'
        return t + '\nTERMUX_PKG_BUILD_DEPENDS="libdeflate"\n'
    change('postgis', postgis_metadata_provider)
    change('ibus-libpinyin', postgis_metadata_provider, tree='x11-packages')
    def nemo_metadata_providers(t):
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross"'
        assert 'TERMUX_PKG_VERSION="6.6.4"' in t and t.count(anchor) == 1, 'Nemo build provider contract changed'
        # Own-source GTK/TinySPARQL metadata requires these private .pc
        # providers in a dependency-only prefix; retain all Nemo features.
        return t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross, libdeflate, libxres"')
    change('nemo', nemo_metadata_providers, tree='x11-packages')
    def musescore_isolated_host_tools(t):
        assert 'TERMUX_PKG_VERSION="4.7.5"' in t, 'MuseScore source version changed'
        # CMake previously autodetected an unrelated Android ccache binary
        # in the full catalog prefix. A focused dependency seed excludes it.
        return hook(t, 'termux_step_pre_configure', '''
    [[ ! -e "$TERMUX_PREFIX/bin/ccache" ]] || termux_error_exit "MuseScore focused seed contains an unrelated target ccache executable"
''')
    change('musescore', musescore_isolated_host_tools, tree='x11-packages')
    def gtk_metadata_provider(t):
        assert 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'GTK consumer build prerequisites changed'
        return t + '\nTERMUX_PKG_BUILD_DEPENDS="libdeflate, libxres"\n'
    change('rawtherapee', lambda t: hook(gtk_metadata_provider(t), 'termux_step_pre_configure', NTL_CXX_HEADERS), tree='x11-packages')
    def darktable_metadata_provider(t):
        anchor='TERMUX_PKG_BUILD_DEPENDS="libllvm-static"'
        assert t.count(anchor)==1, 'Darktable build prerequisites changed'
        return t.replace(anchor,'TERMUX_PKG_BUILD_DEPENDS="libdeflate, libxres, libllvm-static"')
    change('darktable', lambda t: hook(darktable_metadata_provider(t), 'termux_step_pre_configure', NTL_CXX_HEADERS), tree='x11-packages')

    def mapserver_aosp_proot(t):
        anchor='\ttermux_setup_proot\n'
        assert t.count(anchor)==1, 'MapServer proot setup anchor changed'
        return t.replace(anchor, anchor+r'''	local termi_mapserver_proot_bin="$TERMUX_PKG_TMPDIR/termi-mapserver-proot-bin"
	mkdir -p "$termi_mapserver_proot_bin"
	python3 - "$(command -v termux-proot-run)" "$termi_mapserver_proot_bin/termux-proot-run" "$TERMUX_PREFIX" <<'TERMI_MAPSERVER_PROOT'
from pathlib import Path
import shlex, sys
source, target, prefix=map(Path,sys.argv[1:])
assert (prefix/'opt/aosp/bin/linker64').is_file(), 'Source-built Android linker missing'
s=source.read_text()
anchor='-R / "$@"'
assert s.count(anchor)==1, 'Proot wrapper root anchor changed'
s=s.replace(anchor,'-R / -b '+shlex.quote(str(prefix/'opt/aosp')+':/system')+' "$@"')
target.write_text(s)
target.chmod(0o755)
TERMI_MAPSERVER_PROOT
	export PATH="$termi_mapserver_proot_bin:$PATH"
''')
    change('mapserver', lambda t: hook(mapserver_aosp_proot(t), 'termux_step_pre_configure', NTL_CXX_HEADERS))

    def apache_semaphore_provider(t):
        dependency = 'TERMUX_PKG_DEPENDS="apr, apr-util, libandroid-support, '
        link = '\tLDFLAGS="$LDFLAGS -lapr-1 -laprutil-1"'
        assert t.count(dependency) == 1 and t.count(link) == 1, 'Apache APR link contract changed'
        assert 'libandroid-sysv-semaphore' not in t, 'Apache semaphore provider already declared'
        # APR references the compatibility API exported by this source-built
        # library. Keep it in each consumer's DT_NEEDED even with --as-needed.
        return t.replace(dependency, dependency + 'libandroid-sysv-semaphore, ').replace(
            link, '\tLDFLAGS="$LDFLAGS -lapr-1 -laprutil-1 -Wl,--push-state,--no-as-needed '
                  '-landroid-sysv-semaphore -Wl,--pop-state"')
    change('apache2', apache_semaphore_provider)
    def php_pkgconfig_dependencies(t):
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="postgresql"'
        assert t.count(anchor) == 1, 'PHP build dependency contract changed'
        # gdlib.pc and its TIFF/HEIF requirements refer to these metadata
        # providers even for shared linking. A focused prefix must declare
        # them instead of relying on unrelated packages installed earlier.
        return t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libdeflate, libxpm, openh264, postgresql"')
    change('php', php_pkgconfig_dependencies)
    # These recipes compile a Linux host helper after an Android target build.
    # Keep target include paths out of GCC and preserve the target environment.
    def tcc_host_environment(t):
        anchor='\t\tunset CC CFLAGS LDFLAGS\n'
        assert t.count(anchor)==1, 'TCC host environment anchor changed'
        t=t.replace(anchor,'''\t\tunset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH
\t\texport CC=/usr/bin/gcc CFLAGS="-O2 -std=gnu11"
''')
        runtime='\tmake -j ${TERMUX_PKG_MAKE_PROCESSES} libtcc1.a\n'
        assert t.count(runtime)==1, 'TCC runtime bootstrap command changed'
        # The Linux-hosted helper targets Android headers but has Linux builtins.
        # Pass versioned Android context to this runtime build explicitly.
        t=t.replace(runtime, '\tmake -j ${TERMUX_PKG_MAKE_PROCESSES} libtcc1.a '+
            '"XFLAGS=-B.. -I../include -I.. -D__ANDROID__ -D__ANDROID_API__=$TERMUX_PKG_API_LEVEL '+
            '-D__ANDROID_MIN_SDK_VERSION__=$TERMUX_PKG_API_LEVEL"\n')
        return hook(t,'termux_step_pre_configure','''
\t# TinyCC predates the NDK's required versioned-target macro. Define the
\t# configured SDK in its own predefined header, keeping explicit overrides.
\tpython3 - "$TERMUX_PKG_SRCDIR/include/tccdefs.h" "$TERMUX_PKG_API_LEVEL" <<'TERMI_TCC_ANDROID_API'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]);s=p.read_text();api=sys.argv[2]
assert re.fullmatch(r'[0-9]+',api) and 21<=int(api)<=10000, 'Invalid TinyCC Android API'
anchor='#elif defined __ANDROID__'
assert s.count(anchor)==1, 'TinyCC Android predefined header changed'
extra="""
#ifndef __ANDROID_MIN_SDK_VERSION__
# ifdef __ANDROID_API__
#  define __ANDROID_MIN_SDK_VERSION__ __ANDROID_API__
# else
#  define __ANDROID_MIN_SDK_VERSION__ @API@
# endif
#endif
#ifndef __ANDROID_API__
# define __ANDROID_API__ __ANDROID_MIN_SDK_VERSION__
#endif
""".replace('@API@',api)
# conftest.c embeds only lines indented >=4 into generated tccdefs_.h.
extra="\\n"+"\\n".join("    "+line for line in extra.strip().splitlines())+"\\n"
p.write_text(s.replace(anchor,anchor+extra))
TERMI_TCC_ANDROID_API
''')
    change('tcc',tcc_host_environment)

    def sftpgo_host_documentation(t):
        setup='\ttermux_setup_golang\n'
        assert t.count(setup)==1, 'SFTPGo Go setup changed'
        # Both target compilation and native doc generation populate Go's
        # cache. Keep it in bounded recipe scratch, reclaimed before export.
        t=t.replace(setup,setup+'''\texport GOCACHE="$TERMUX_PKG_TMPDIR/termi-go-cache"
\tmkdir -p "$GOCACHE"
''')
        anchor='\t# borrowed from packages/gh\n\tunset GOOS GOARCH CGO_LDFLAGS\n\tunset CC CXX CFLAGS CXXFLAGS LDFLAGS\n'
        end='\n\t# for sftpgo.db\n'
        assert t.count(anchor)==1 and t.count(end)==1, 'SFTPGo host documentation anchors changed'
        clean='''\t# Documentation needs a Linux executable, with native CGO dependencies.
\t(
\tunset GOOS GOARCH GOARM GOARM64 GO386
\tunset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
\tunset CGO_CFLAGS CGO_CPPFLAGS CGO_CXXFLAGS CGO_LDFLAGS
\tunset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH
\texport CC=/usr/bin/gcc CXX=/usr/bin/g++
'''
        return t.replace(anchor,clean).replace(end,'\n\t)\n'+end)
    change('sftpgo',sftpgo_host_documentation)

    # The pinned development version is rejected by this recipe's own stable
    # release policy. Use the latest supported upstream source, keeping the guard.
    def mate_utils_supported_source(t):
        old_version='TERMUX_PKG_VERSION="1.29.1"'
        old_hash='TERMUX_PKG_SHA256=8b9e882daab76314f8e6518ff8cd6ddd19f727eb1f2e9a985f7fc68bd025bf07'
        assert t.count(old_version)==1 and t.count(old_hash)==1, 'MATE utilities source pin changed'
        return t.replace(old_version,'TERMUX_PKG_VERSION="1.28.3"').replace(old_hash,'TERMUX_PKG_SHA256=ff11a1be12ff563d9a6a4ab1d51030d0994705ab3eeea4ee5a97e89fd61ff11b')
    change('mate-utils',mate_utils_supported_source,tree='x11-packages')

    # Qt Declarative repeatedly exhausts standard-runner disk while emitting
    # many module PCH files. PCH is only a build optimization; keep all modules.
    def qt_declarative_disk(t):
        anchor='\t\t-DCMAKE_BUILD_TYPE=MinSizeRel \\\n'
        assert t.count(anchor)==1, 'Qt Declarative host configure anchor changed'
        assert t.count('TERMUX_PKG_REVISION="1"')==1, 'Qt Declarative revision changed'
        t=t.replace('TERMUX_PKG_REVISION="1"','TERMUX_PKG_REVISION=2')
        t=t.replace(anchor,anchor+'\t\t-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON \\\n')
        return hook(t,'termux_step_pre_configure',
                    '''\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON"
\tlocal termi_qt_launcher="$TERMUX_PKG_TMPDIR/termi-qt-cxx-launcher"
\tprintf '#!/bin/bash\\ncompiler="$1"\\nshift\\nexec "$compiler" -nostdinc++ -I%q "$@"\\n' "$TERMUX_PREFIX/include/c++/v1" > "$termi_qt_launcher"
\tchmod 755 "$termi_qt_launcher"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER_LAUNCHER=$termi_qt_launcher"''')
    change('qt6-qtdeclarative',qt_declarative_disk,tree='x11-packages')

    # The upstream autogen allowlists reject modern host libtool/automake even
    # though they exceed its advertised minimums. Keep the bootstrap sequence.
    change('libgmime', lambda t: hook(t, 'termux_step_pre_configure', '''
\tpython3 - "$TERMUX_PKG_SRCDIR/autogen.sh" <<'TERMI_GMIME_AUTOGEN'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]);s=p.read_text()
old="""\tcase $libtool_version in
\t    1.4*|1.5*|2.2*|2.4*)
\t\thave_libtool=true
\t\t;;
\tesac"""
assert s.count(old)==1, 'GMime libtool version check changed'
s=s.replace(old, """\tif test -n "$libtool_version" && test "$(printf '%s\\n' 1.4 "$libtool_version" | sort -V | head -n 1)" = 1.4; then
\t\thave_libtool=true
\tfi""")
pattern=r'for automake_version in 1\\.9 1\\.10 1\\.11 1\\.12 1\\.13 1\\.14 1\\.15 1\\.16; do\\n.*?\\ndone'
matches=list(re.finditer(pattern,s,re.S))
assert len(matches)==1, 'GMime automake version check changed'
replacement="""if automake --version < /dev/null > /dev/null 2>&1 && aclocal --version < /dev/null > /dev/null 2>&1; then
    automake_version=$(automake --version | sed '/^$/d;s/([^)]*)//g;s/^[^0-9]*//;s/[- ].*//g;q')
    if test -n "$automake_version" && test "$(printf '%s\\n' 1.9 "$automake_version" | sort -V | head -n 1)" = 1.9; then
        AUTOMAKE=automake
        ACLOCAL=aclocal
    fi
fi"""
m=matches[0];p.write_text(s[:m.start()]+replacement+s[m.end():])
TERMI_GMIME_AUTOGEN'''))

    # Upstream's Android pthread workaround sets discovery variables but
    # wxrc now links the modern imported target. Android pthreads are in libc.
    change('wxwidgets', lambda t: hook(t, 'termux_step_pre_configure', '''
\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"
\tpython3 - "$TERMUX_PKG_SRCDIR/build/cmake/init.cmake" <<'TERMI_WX_THREADS'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='        set(Threads_FOUND TRUE)'
assert s.count(old)==1 and '# Android has pthreads' in s, 'wxWidgets Android thread workaround changed'
s=s.replace(old,old+"\\n        if(NOT TARGET Threads::Threads)\\n            add_library(Threads::Threads INTERFACE IMPORTED GLOBAL)\\n        endif()")
p.write_text(s)
TERMI_WX_THREADS'''),tree='x11-packages')

    # Qt5 writes target CXXFLAGS into its cross-qmake spec before clearing
    # compiler environment variables; repair the flags before that capture.
    change('qt5-qtbase', lambda t: hook(t, 'termux_step_pre_configure',
        '\tCXXFLAGS="-nostdinc++ -I$TERMUX_PREFIX/include/c++/v1 $CXXFLAGS"'),tree='x11-packages')

    # These projects auto-detect the Android ccache in the target prefix and
    # try to execute it on Linux. Disable only the optional build cache.
    change('flameshot',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DENABLE_CACHE=OFF"'),tree='x11-packages')

    def qt5_declarative_host_headers(t,expected=4):
        anchor='-spec "${TERMUX_PREFIX}/lib/qt/mkspecs/termux-host"\n'
        assert t.count(anchor)==expected, 'Qt5 host qmake sites changed'
        return t.replace(anchor,anchor+'\t_termi_qt5_host_headers\n') + QT5_HOST_HEADERS
    change('qt5-qtdeclarative',qt5_declarative_host_headers,tree='x11-packages')
    change('qt5-qttools',lambda t:qt5_declarative_host_headers(t,expected=2),tree='x11-packages')

    # KDE's optional compressor discovery selects the Android 7zz from the
    # seed. Its upstream gzip fallback emits the same SVGZ resources using
    # the Linux host tool, without dropping card decks or runtime features.
    change('libkdegames',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_DISABLE_FIND_PACKAGE_7Zip=ON -Dgzip_EXECUTABLE=/usr/bin/gzip"'),tree='x11-packages')

    # These two game resource builds discover the same target-only 7zz.
    for name in ('kmines', 'knights'):
        change(name,lambda t:hook(t,'termux_step_pre_configure',
            '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_DISABLE_FIND_PACKAGE_7Zip=ON -Dgzip_EXECUTABLE=/usr/bin/gzip"'),tree='x11-packages')

    change('libkmahjongg',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_DISABLE_FIND_PACKAGE_7Zip=ON -Dgzip_EXECUTABLE=/usr/bin/gzip"'),tree='x11-packages')
    # PyQt 6.11 still binds two QEvent names removed from the pinned Qt 6.12
    # headers. Retain the supported enum values rather than emitting wrappers
    # that reference nonexistent C++ members.
    change('pyqt6',lambda t:hook(t,'termux_step_pre_configure', '''
\tpython3 - "$TERMUX_PKG_SRCDIR/sip/QtCore/qcoreevent.sip" <<'TERMI_PYQT_EVENTS'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
for name in ('EnterEditFocus', 'LeaveEditFocus'):
    anchor='        '+name+',\\n'
    assert s.count(anchor)==1, 'PyQt obsolete event binding changed'
    s=s.replace(anchor,'')
p.write_text(s)
TERMI_PYQT_EVENTS'''),tree='x11-packages')

    for name in ('kigo', 'lskat', 'kpat'):
        change(name,lambda t:hook(t,'termux_step_pre_configure',
            '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_DISABLE_FIND_PACKAGE_7Zip=ON -Dgzip_EXECUTABLE=/usr/bin/gzip"'),tree='x11-packages')
    # mGBA's optional HTML documentation found an Android markdown executable.
    # Build the catalog's pinned Discount source privately for the Linux host.
    change('mgba',lambda t:hook(t,'termux_step_pre_configure', r'''	if [[ "$TERMUX_ON_DEVICE_BUILD" == "false" ]]; then
		termux_setup_cmake
		local termi_discount="$TERMUX_PKG_TMPDIR/termi-host-discount"
		local termi_archive="$TERMUX_PKG_CACHEDIR/termi-host-discount-3.0.2.0.tar.gz"
		termux_download https://github.com/Orc/discount/archive/refs/tags/v3.0.2.0.tar.gz "$termi_archive" 99f6db36d3fff6c99acd21d4c6096176d4ac8785eab319d0faf77ad995b8b7c5
		mkdir -p "$termi_discount/src"
		tar -xzf "$termi_archive" --strip-components=1 -C "$termi_discount/src"
		(
			unset CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS AR LD RANLIB CMAKE_TOOLCHAIN_FILE CMAKE_PREFIX_PATH PKG_CONFIG_LIBDIR PKG_CONFIG_PATH
			cmake -S "$termi_discount/src/cmake" -B "$termi_discount/build" -G "Unix Makefiles" -DCMAKE_C_COMPILER=/usr/bin/cc -DCMAKE_CXX_COMPILER=/usr/bin/c++ -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DBUILD_SHARED_LIBS=OFF -DCMAKE_C_FLAGS=-DMAX_RECURSION=200
			cmake --build "$termi_discount/build" --target markdown -j "$TERMUX_PKG_MAKE_PROCESSES"
		)
		test -x "$termi_discount/build/markdown"
		TERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DMARKDOWN=$termi_discount/build/markdown"
	fi'''),tree='x11-packages')
    def awscli_proot(t):
        anchor='" termux_setup_proot\n'
        assert t.count(anchor)==1, 'AWS CLI proot setup anchor changed'
        return t.replace(anchor,anchor+r'''	local termi_proot_bin="$TERMUX_PKG_TMPDIR/termi-proot-bin"
	mkdir -p "$termi_proot_bin"
	python3 - "$(command -v termux-proot-run)" "$termi_proot_bin/termux-proot-run" "$TERMUX_PREFIX" <<'TERMI_AWSCLI_PROOT'
from pathlib import Path
import shlex, sys
source, target, prefix=map(Path,sys.argv[1:])
assert (prefix/'opt/aosp/bin/linker64').is_file(), 'Source-built Android linker missing'
s=source.read_text()
anchor='-R / "$@"'
assert s.count(anchor)==1, 'Proot wrapper root anchor changed'
s=s.replace(anchor,'-R / -b '+shlex.quote(str(prefix/'opt/aosp')+':/system')+' "$@"')
target.write_text(s)
target.chmod(0o755)
TERMI_AWSCLI_PROOT
	export PATH="$termi_proot_bin:$PATH"
''')
    change('awscli',lambda t:hook(awscli_proot(t),'termux_step_pre_configure',AWS_PRIVATE_CRYPTO))

    change('putty',lambda t:hook(t,'termux_step_pre_configure',
        '\tCPPFLAGS+=" -D_BSD_SOURCE"'),tree='x11-packages')
    change('synaptic',lambda t:hook(t,'termux_step_pre_configure', r'''	python3 - "$TERMUX_PKG_SRCDIR/meson.build" <<'TERMI_SYNAPTIC_BACKEND'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
anchor="if cpp.has_header('rpm/rpmlib.h', args: ['-I/usr/include/rpm'])"
assert s.count(anchor)==1, 'Synaptic RPM detection anchor changed'
p.write_text(s.replace(anchor,'if false # Termi uses Debian APT/dpkg, not apt-rpm'))
TERMI_SYNAPTIC_BACKEND'''),tree='x11-packages')
    change('tint2',lambda t:hook(t,'termux_step_pre_configure', r'''	python3 - "$TERMUX_PKG_SRCDIR/src/util" <<'TERMI_TINT2_SIZE'
from pathlib import Path
import re, sys
root=Path(sys.argv[1])
for name in ('gradient.h','gradient.c','area.c'):
    p=root/name;s=p.read_text()
    s,count=re.subn(r'\bSIZE_WIDTH\b','TERMI_TINT2_SIZE_WIDTH',s)
    assert count==1, 'Tint2 gradient size enum anchor changed: '+name
    p.write_text(s)
TERMI_TINT2_SIZE'''),tree='x11-packages')
    change('strawberry',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCCACHE_EXECUTABLE=OFF"'),tree='x11-packages')
    # The target ccache is an Android executable, not a Linux build launcher.
    change('openimageio',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DUSE_CCACHE=OFF"'),tree='x11-packages')
    change('melonds',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DUSE_CCACHE=OFF"'),tree='x11-packages')
    change('ktextaddons',lambda t:hook(t,'termux_step_pre_configure',
        '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DUSE_FASTER_LINKER=OFF"'),tree='x11-packages')

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

    # _GNU_SOURCE does not make glibc's program-name global exist on Bionic.
    # Keep the JACK plugin and use its existing BSD-style fallback on Android.
    change('alsa-plugins', lambda t:hook(t,'termux_step_pre_configure',r'''	python3 - "$TERMUX_PKG_SRCDIR/jack/pcm_jack.c" <<'TERMI_ALSA_PROGRAM_NAME'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
anchor='#if defined(_GNU_SOURCE)'
assert s.count(anchor)==1, 'ALSA JACK program-name branch changed'
assert s.count('#include <stdbool.h>')==1, 'ALSA JACK include anchor changed'
s=s.replace(anchor,'#if defined(_GNU_SOURCE) && !defined(__ANDROID__)')
s=s.replace('#include <stdbool.h>','#include <stdbool.h>\n#include <stdlib.h>')
assert s.count('if (!pname[0])')==1, 'ALSA JACK empty-name fallback changed'
s=s.replace('if (!pname[0])','if (!pname || !pname[0])')
p.write_text(s)
TERMI_ALSA_PROGRAM_NAME
	# Upstream ALSA FFmpeg 7.1+ compatibility; retain older FFmpeg.
	python3 - "$TERMUX_PKG_SRCDIR/a52/pcm_a52.c" <<'TERMI_ALSA_SAMPLE_FORMAT'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='\trec->av_format = rec->codec->sample_fmts[0];'
assert s.count(old)==1, 'ALSA A52 sample-format anchor changed'
new='#if LIBAVCODEC_VERSION_INT >= AV_VERSION_INT(61, 13, 100)\n\t{\n\t\tconst enum AVSampleFormat *sample_fmts = NULL;\n\t\terr = avcodec_get_supported_config(NULL, rec->codec,\n\t\t\t\t\t\t   AV_CODEC_CONFIG_SAMPLE_FORMAT,\n\t\t\t\t\t\t   0, (const void **)&sample_fmts,\n\t\t\t\t\t\t   NULL);\n\t\tif (err < 0 || !sample_fmts) {\n\t\t\terr = -EINVAL;\n\t\t\tgoto error;\n\t\t}\n\t\trec->av_format = sample_fmts[0];\n\t}\n#else\n\trec->av_format = rec->codec->sample_fmts[0];\n#endif'
p.write_text(s.replace(old,new))
TERMI_ALSA_SAMPLE_FORMAT
'''))

    # Pinned LGI recipes currently have no patch files. Keep applying real
    # patches, but do not redirect stdin from a literal unmatched glob.
    def awesome_optional_lgi_patches(t):
        anchor='\t\tfor patch in "$TERMUX_SCRIPTDIR/packages/'
        lines=t.splitlines(keepends=True)
        matches=[i for i,line in enumerate(lines) if line.startswith(anchor) and line.rstrip().endswith('/*.patch; do')]
        assert len(matches)==1, 'Awesome host LGI patch loop changed'
        lines.insert(matches[0]+1,'\t\t\t[[ -f "$patch" ]] || continue\n')
        return ''.join(lines)
    for name in ('awesome', 'awesome-luajit'):
        change(name,awesome_optional_lgi_patches,tree='x11-packages')

    # CMake's configure log identifies RAGEL_PROGRAM as the SVG generator.
    # Keep a Linux host tool private; never execute the target-prefix Ragel.
    def inkscape_host_ragel(t):
        return hook(t,'termux_step_pre_configure','''\tif [[ "$TERMUX_ON_DEVICE_BUILD" == "false" ]]; then
\t\tlocal termi_ragel=/usr/bin/ragel
\t\tif [[ ! -x "$termi_ragel" ]]; then
\t\t\ttermux_download_ubuntu_packages ragel
\t\t\ttermi_ragel="$TERMUX_PKG_HOSTBUILD_DIR/ubuntu_packages/usr/bin/ragel"
\t\tfi
\t\t"$termi_ragel" -v
\t\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DRAGEL_PROGRAM=$termi_ragel"
\tfi''')

    def yazi_aosp_proot(t):
        anchor='\t\ttermux_setup_proot\n'
        assert t.count(anchor)==1, 'Yazi proot setup anchor changed'
        t=t.replace(anchor,anchor+r'''		local termi_yazi_proot_bin="$TERMUX_PKG_TMPDIR/termi-yazi-proot-bin"
		mkdir -p "$termi_yazi_proot_bin"
		python3 - "$(command -v termux-proot-run)" "$termi_yazi_proot_bin/termux-proot-run" "$TERMUX_PREFIX" <<'TERMI_YAZI_PROOT'
from pathlib import Path
import shlex, sys
source, target, prefix=map(Path,sys.argv[1:])
assert (prefix/'opt/aosp/bin/linker64').is_file(), 'Source-built Android linker missing'
s=source.read_text()
anchor='-R / "$@"'
assert s.count(anchor)==1, 'Proot wrapper root anchor changed'
s=s.replace(anchor,'-R / -b '+shlex.quote(str(prefix/'opt/aosp')+':/system')+' "$@"')
target.write_text(s)
target.chmod(0o755)
TERMI_YAZI_PROOT
		export PATH="$termi_yazi_proot_bin:$PATH"
''')
        return t
    change('yazi',yazi_aosp_proot)

    # These native failures show prefix C headers before implicit NDK libc++.
    # A compiler wrapper also precedes dependency-generated -I options.
    def matching_cxx(t, cmake=False):
        return hook(t, 'termux_step_pre_configure', '''\tlocal termi_cxx="$TERMUX_PKG_TMPDIR/termi-matching-cxx"
\tprintf '#!/bin/bash\\nexec %q -nostdinc++ -I%q "$@"\\n' "$CXX" "$TERMUX_PREFIX/include/c++/v1" > "$termi_cxx"
\tchmod 755 "$termi_cxx"
\texport CXX="$termi_cxx"'''+ ('\n\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER=$termi_cxx"' if cmake else ''))
    def api_pin_matching_cxx(t):
        anchor = "\tprintf '#!/bin/bash\\nexec %q -nostdinc++ -I%q \"$@\"\\n' \"$CXX\" \"$TERMUX_PREFIX/include/c++/v1\" > \"$termi_cxx\""
        replacement = "\tprintf '#!/bin/bash\\nexec %q -nostdinc++ -I%q \"$@\" --target=%q\\n' \"$CXX\" \"$TERMUX_PREFIX/include/c++/v1\" \"${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}\" > \"$termi_cxx\""
        assert t.count(anchor) == 1, 'Target C++ wrapper API contract changed'
        return t.replace(anchor, replacement)
    def configure_consumer(t, name):
        if name == 'tectonic':
            t = focused_cxx_header_provider(t)
        if name == 'luanti':
            t=focused_cxx_header_provider(t)
        if name == 'inkscape':
            t=inkscape_host_ragel(t)
        # Qt6's public dialect bits predate md4c 0.6's new default flags (one
        # collides with Qt's front-matter bit). Build Qt's matching bundled
        # source parser using its documented input; retain Markdown support.
        if name == 'telegram-desktop':
            anchor='-DTDE2E_INSTALL_INCLUDES=ON\n'
            assert t.count(anchor)==1, 'Telegram libtd configure anchor changed'
            t=t.replace(anchor,anchor+'-DCCACHE_FOUND=OFF\n')
            anchor='\t\ttermux_setup_proot\n'
            assert t.count(anchor)==1, 'Telegram proot setup anchor changed'
            t=t.replace(anchor,anchor+r'''		local termi_proot_bin="$TERMUX_PKG_TMPDIR/termi-proot-bin"
		mkdir -p "$termi_proot_bin"
		python3 - "$(command -v termux-proot-run)" "$termi_proot_bin/termux-proot-run" "$TERMUX_PREFIX" <<'TERMI_TELEGRAM_PROOT'
from pathlib import Path
import shlex, sys
source, target, prefix=map(Path,sys.argv[1:])
assert (prefix/'opt/aosp/bin/linker64').is_file(), 'Source-built Android linker missing'
s=source.read_text()
anchor='-R / "$@"'
assert s.count(anchor)==1, 'Proot wrapper root anchor changed'
s=s.replace(anchor,'-R / -b '+shlex.quote(str(prefix/'opt/aosp')+':/system')+' "$@"')
target.write_text(s)
target.chmod(0o755)
TERMI_TELEGRAM_PROOT
		export PATH="$termi_proot_bin:$PATH"
''')
        if name == 'openscad-x':
            t=hook(t,'termux_step_pre_configure','\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCCACHE_PATH=OFF -DEIGEN3_INCLUDE_DIR=$TERMUX_PREFIX/include/eigen3"')
            # Geometry.h uses assert directly; current libc++ no longer
            # provides that declaration through unrelated transitive headers.
            t=hook(t,'termux_step_pre_configure',r'''	python3 - "$TERMUX_PKG_SRCDIR/src/Geometry.h" <<'TERMI_OPENSCAD_ASSERT'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
anchor='#include <stddef.h>'
assert s.count(anchor)==1 and '#include <cassert>' not in s, 'OpenSCAD Geometry header changed'
p.write_text(s.replace(anchor,anchor+'\n#include <cassert>'))
TERMI_OPENSCAD_ASSERT
''')
        if name == 'tenacity':
            t=hook(t,'termux_step_pre_configure','\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCCACHE_PROGRAM=OFF -DSCCACHE_PROGRAM=OFF -DCCACHE=OFF -DSCCACHE=OFF"')
        if name == 'opencv':
            t=hook(t,'termux_step_pre_configure','\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DENABLE_CCACHE=OFF"')
        if name == 'mixxx':
            t=hook(t,'termux_step_pre_configure','\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCCACHE_SUPPORT=OFF"')
        if name == 'qt6-qtbase':
            t=hook(t,'termux_step_pre_configure','\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DINPUT_libmd4c=qt"')
        if name == 'mupdf':
            # Its GL viewer calls posix_spawnp, absent from API26 libc. Link
            # our source-built compatibility library and declare runtime use.
            anchor='libandroid-shmem, libc++'
            assert t.count(anchor)==1, 'MuPDF dependency anchor changed'
            t=t.replace(anchor,'libandroid-shmem, libandroid-spawn, libc++')
            t=hook(t,'termux_step_pre_configure','\tLDFLAGS+=" -landroid-spawn"')
        if name == 'webkit2gtk-4.1':
            # Its CMake invocation chooses the NDK compiler directly. The
            # failing ANGLE file already includes cfloat: fix header order at
            # the effective compiler invocation, not the source declaration.
            return hook(t,'termux_step_pre_configure', '''\tlocal termi_webkit_launcher="$TERMUX_PKG_TMPDIR/termi-webkit-cxx-launcher"
\tprintf '#!/bin/bash\\ncompiler="$1"\\nshift\\nexec "$compiler" -nostdinc++ -I%q "$@"\\n' "$TERMUX_PREFIX/include/c++/v1" > "$termi_webkit_launcher"
\tchmod 755 "$termi_webkit_launcher"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER_LAUNCHER=$termi_webkit_launcher"''')
        result = matching_cxx(t,name in {'libavif', 'libjxl', 'poppler', 'box2d', 'tesseract', 'qt6-qtbase', 'fcitx5-gtk-common', 'recastnavigation', 'ffmpegthumbnailer', 'luanti', 'libkexiv2', 'poppler-qt', 'qt6-qtsvg', 'yosys', 'qt6-qtmultimedia', 'gpsbabel', 'analitza', 'opencv', 'kolourpaint', 'kpipewire', 'libksysguard', 'qt6-qtwayland', 'kseexpr', 'calligraplan', 'mlt', 'mixxx', 'quickshell', 'spectacle', 'libncnn', 'keepassxc', 'telegram-desktop', 'wireshark-qt', 'audacity', 'tenacity', 'openscad-x', 'krita', 'kf6-kimageformats', 'transmission-gtk', 'inkscape'})
        return api_pin_matching_cxx(result) if name == 'tectonic' else result
    for name, tree in [(n, 'packages') for n in ['openjdk-17', 'openjdk-21', 'openjdk-25', 'gegl', 'libavif', 'libopenmpt', 'libxapian', 'libraw', 'libglibmm-2.4', 'libglibmm-2.68', 'harfbuzz', 'libjxl', 'poppler', 'go-findimagedupes', 'graphviz', 'tesseract', 'tectonic', 'ffmpegthumbnailer', 'gmic', 'mupdf', 'python-pymupdf', 'yosys']]+[(n, 'x11-packages') for n in ['gimp', 'transmission-gtk', 'inkscape', 'pavucontrol', 'ardour', 'gtkmm4', 'krita', 'kf6-kimageformats', 'box2d', 'dia', 'deadbeef', 'qt6-qtbase', 'fcitx5-gtk-common', 'love', 'recastnavigation', 'praat', 'luanti', 'libvte', 'webkit2gtk-4.1', 'libaccounts-qt', 'libkexiv2', 'poppler-qt', 'qt6-qtsvg', 'qt6-qtmultimedia', 'gpsbabel', 'analitza', 'opencv', 'kolourpaint', 'kpipewire', 'libksysguard', 'qt6-qtwayland', 'kseexpr', 'calligraplan', 'mlt', 'mixxx', 'quickshell', 'spectacle', 'libncnn', 'keepassxc', 'telegram-desktop', 'wireshark-qt', 'audacity', 'tenacity', 'openscad-x', 'audacious-plugins', 'mkvtoolnix', 'qscintilla-qt6', 'signond', 'leocad', 'signon-plugin-oauth2']]:
        change(name, lambda t, name=name: configure_consumer(t,name),tree=tree)

    # Keep the legacy tokenizer's warning visible without treating the NDK's
    # newly added deprecation annotation as a build error.
    change('sway',lambda t:hook(t,'termux_step_pre_configure','\tCFLAGS+=" -Wno-error=deprecated-declarations"'),tree='x11-packages')

    # Avahi's include_next malloc patch can jump over the prefix's malloc.h
    # into its NDK twin. Use a private header copy for this consumer only.
    change('pipewire', lambda t: matching_cxx(hook(t,'termux_step_pre_configure', '''
\tpython3 - "$TERMUX_PREFIX" "$TERMUX_PKG_SRCDIR" <<'TERMI_PIPEWIRE_AVAHI'
from pathlib import Path
import sys
prefix=Path(sys.argv[1]);root=Path(sys.argv[2])
header=prefix/'include/avahi-common/malloc.h'
if not header.is_file():
    sys.exit(0)
s=header.read_text()
assert s.count('#include_next <malloc.h>')==1, 'Avahi malloc shim changed'
private=root/'src/termi-avahi-malloc.h'
private.write_text(s.replace('#include_next <malloc.h>','#include "'+str(prefix/'include/malloc.h')+'"'))
changed=0
for p in root.rglob('*.c'):
    s=p.read_text()
    old='#include <avahi-common/malloc.h>'
    if old in s:
        p.write_text(s.replace(old,'#include "'+str(private)+'"'));changed+=1
assert changed>0, 'PipeWire Avahi consumer includes changed'
TERMI_PIPEWIRE_AVAHI''')))

    # These consumers hit the same prefix/NDK malloc include_next collision
    # as PipeWire. Keep the installed Avahi header and all features intact.
    def avahi_consumer_malloc(t, version):
        assert ('TERMUX_PKG_VERSION='+version+'\n' in t or
                'TERMUX_PKG_VERSION="'+version+'"\n' in t), 'Avahi consumer version changed'
        t, count = re.subn(r'^TERMUX_PKG_DEPENDS="([^"]*)"$',
                           lambda m: 'TERMUX_PKG_DEPENDS="avahi, '+m[1]+'"', t, flags=re.M)
        assert count == 1, 'Avahi consumer dependency anchor changed'
        return hook(t, 'termux_step_pre_configure', r'''	python3 - "$TERMUX_PREFIX" "$TERMUX_PKG_SRCDIR" "$TERMUX_STANDALONE_TOOLCHAIN" <<'TERMI_CONSUMER_AVAHI'
from pathlib import Path
import sys
prefix=Path(sys.argv[1]);root=Path(sys.argv[2])
header=prefix/'include/avahi-common/malloc.h'
assert header.is_file(), 'Installed Avahi malloc header missing'
s=header.read_text()
assert s.count('#include_next <malloc.h>')==1, 'Avahi malloc shim changed'
malloc=prefix/'include/malloc.h'
if not malloc.is_file():
    malloc=Path(sys.argv[3])/'sysroot/usr/include/malloc.h'
assert malloc.is_file(), 'Pinned Android malloc header missing'
private=root/'src/termi-avahi-malloc.h'
private.write_text(s.replace('#include_next <malloc.h>', '#include "'+str(malloc)+'"'))
changed=0
for p in root.rglob('*'):
    if not p.is_file() or p.suffix not in ('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp') or p==private:
        continue
    s=p.read_text()
    old='#include <avahi-common/malloc.h>'
    if old in s:
        p.write_text(s.replace(old, '#include "'+str(private)+'"'));changed+=1
assert changed>0, 'Avahi consumer includes changed'
TERMI_CONSUMER_AVAHI''')
    change('mpd', lambda t: avahi_consumer_malloc(t, '0.24.16'))
    change('tinysparql', lambda t: avahi_consumer_malloc(t, '3.12.0'))

    # Old cc/backtrace-sys emits an unversioned target after inherited flags.
    # Append the configured Android API in a target-only private C wrapper.
    def termplay_api_compiler(t):
        assert 'TERMUX_PKG_VERSION=2.0.6\n' in t, 'Termplay version changed'
        return hook(t, 'termux_step_pre_configure', r'''	local termi_api_cc="$TERMUX_PKG_TMPDIR/termi-api-cc"
	printf '#!/bin/bash\nexec %q "$@" --target=%q\n' "$CC" "${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}" > "$termi_api_cc"
	chmod 755 "$termi_api_cc"
	local termi_cc_key="CC_${CARGO_TARGET_NAME//-/_}"
	export "$termi_cc_key=$termi_api_cc"''')
    change('termplay', termplay_api_compiler)

    # ICU's public LocalPointer template uses C++17 auto non-type parameters.
    # Keep Qt's flags/features and force that dialect last at this compiler.
    def qtlocation_icu_dialect(t):
        assert 'TERMUX_PKG_VERSION="5.15.18"\n' in t, 'Qt Location version changed'
        dep='TERMUX_PKG_BUILD_DEPENDS="qt5-qtbase-cross-tools"'
        assert t.count(dep)==1, 'Qt Location header provider changed'
        t=t.replace(dep, 'TERMUX_PKG_BUILD_DEPENDS="qt5-qtbase-cross-tools, ndk-sysroot"')
        anchor='\t\t-spec "${TERMUX_PREFIX}/lib/qt/mkspecs/termux-cross"'
        assert t.count(anchor)==1, 'Qt Location qmake anchor changed'
        t=t.replace(anchor, anchor+' \\\n\t\t"QMAKE_CXX=$termi_location_cxx"')
        setup=r'''	[[ -f "$TERMUX_PREFIX/include/c++/v1/vector" ]] || termux_error_exit "Source-built NDK C++ headers missing"
	local termi_location_cxx="$TERMUX_PKG_TMPDIR/termi-location-cxx"
	printf '#!/bin/bash\nexec %q "$@" -std=c++17\n' "$CXX" > "$termi_location_cxx"
	chmod 755 "$termi_location_cxx"'''
        return hook(t, 'termux_step_configure', setup)
    change('qt5-qtlocation', qtlocation_icu_dialect, tree='x11-packages')

    # A focused seed must not replay unrelated Emscripten cyclic test data.
    # Fail visibly if the original full-catalog contamination is present.
    def bazel_isolated_prefix(t):
        assert 'TERMUX_PKG_VERSION="9.3.0"\n' in t, 'Bazel version changed'
        return hook(t, 'termux_step_pre_configure', r'''	if [[ -e "$TERMUX_PREFIX/opt/emscripten/test/third_party/wasi-test-suite/fixtures/symlink_to_parent_directory" ]]; then
		termux_error_exit "Bazel focused seed contains unrelated Emscripten cyclic test fixture"
	fi''')
    change('bazel', bazel_isolated_prefix)

    # The original dependency list omits librhash. A full-catalog prefix
    # accidentally enabled its non-cross-aware runtime probe; a focused seed
    # must follow the recipe's declared dependency boundary.
    def dar_isolated_prefix(t):
        assert 'TERMUX_PKG_VERSION="2.8.6"\n' in t, 'Dar version changed'
        return hook(t, 'termux_step_pre_configure', r'''	[[ ! -e "$TERMUX_PREFIX/include/rhash.h" ]] || termux_error_exit "Dar focused seed contains undeclared librhash header"''')
    change('dar', dar_isolated_prefix)

    # Cross-executed RPython probes need the existing AOSP loader mounted at
    # /system. Keep Android library paths inside the guest, never on host PyPy.
    def pypy_android_execution(t, version):
        assert ('TERMUX_PKG_VERSION="'+version+'"\n' in t or
                'TERMUX_PKG_VERSION='+version+'\n' in t), 'PyPy version changed'
        dep='TERMUX_PKG_BUILD_DEPENDS="aosp-libs, tk, xorgproto"'
        assert t.count(dep)==1, 'PyPy builder import provider changed'
        t=t.replace(dep, 'TERMUX_PKG_BUILD_DEPENDS="aosp-libs, libandroid-stub, tk, xorgproto"')
        bind='-b /proc -b /dev -b /sys\n'
        assert t.count(bind)==1, 'PyPy proot mount anchor changed'
        t=t.replace(bind, bind+'-b $TERMUX_PREFIX/opt/aosp:/system\n')
        guest='\t$PROOT_TARGET env -i \\\n'
        assert t.count(guest)==1, 'PyPy guest packaging environment changed'
        t=t.replace(guest,guest+'\t\tLD_PRELOAD= \\\n\t\tLD_LIBRARY_PATH="$TERMUX_PREFIX/lib" \\\n\t\tANDROID_ROOT=/system \\\n\t\tANDROID_DATA=/data \\\n')
        return hook(t, 'termux_step_pre_configure', r'''	local termi_pypy_loader=linker
	[[ "$TERMUX_ARCH_BITS" != 64 ]] || termi_pypy_loader=linker64
	[[ -x "$TERMUX_PREFIX/opt/aosp/bin/$termi_pypy_loader" ]] || termux_error_exit "Source-built AOSP loader missing"
	[[ -f "$TERMUX_PREFIX/lib/libandroid.so" && -f "$TERMUX_PREFIX/lib/libtermux-platform-ns.so" ]] || termux_error_exit "Source-built Android import helpers missing"
	python3 - "$TERMUX_PKG_SRCDIR/rpython/translator/platform/termux.py" "$TERMUX_PREFIX" <<'TERMI_PYPY_EXEC'
from pathlib import Path
import sys
p=Path(sys.argv[1]);prefix=sys.argv[2];s=p.read_text()
anchor='        args = PROOT_TARGET_ARGS[1:] + args'
assert s.count(anchor)==1, 'RPython guest execution anchor changed'
guest=["/usr/bin/env", "LD_PRELOAD=", "LD_LIBRARY_PATH="+prefix+"/lib", "ANDROID_ROOT=/system", "ANDROID_DATA=/data"]
s=s.replace(anchor, '        args = PROOT_TARGET_ARGS[1:] + '+repr(guest)+' + args')
anchor='        returncode, stdout, stderr = _run_subprocess(proot_exec, args, env)'
assert s.count(anchor)==1, 'RPython host execution anchor changed'
clean='\n'.join(['        host_env = dict(os.environ if env is None else env)', '        host_env.pop("LD_PRELOAD", None)', '        host_env.pop("LD_LIBRARY_PATH", None)', '        returncode, stdout, stderr = _run_subprocess(proot_exec, args, host_env)'])
s=s.replace(anchor,clean)
p.write_text(s)
TERMI_PYPY_EXEC''')
    change('pypy', lambda t: pypy_android_execution(t, '8.0.1'))
    change('pypy3', lambda t: pypy_android_execution(t, '8.0.0'))

    # A full-catalog prefix mixed system glslang headers with the bundled
    # subproject. The recipe's declared dependency-only seed has no glslang.
    def vapoursynth_isolated_headers(t):
        assert 'TERMUX_PKG_VERSION="81"\n' in t, 'VapourSynth version changed'
        return hook(t, 'termux_step_pre_configure', r'''	[[ ! -e "$TERMUX_PREFIX/include/glslang/MachineIndependent/localintermediate.h" ]] || termux_error_exit "VapourSynth focused seed contains unrelated glslang headers"''')
    change('vapoursynth', vapoursynth_isolated_headers)

    # LLVM 14's SmallVector uses uint32_t/uint64_t but relies on transitive
    # includes removed by newer host standard libraries. Fix the owning header.
    change('ldc', lambda t: matching_cxx(hook(t, 'termux_step_host_build', '''
\tpython3 - "$TERMUX_PKG_SRCDIR/llvm/include/llvm/ADT/SmallVector.h" "$TERMUX_PKG_SRCDIR/tools/CMakeLists.txt" <<'TERMI_LDC_STDINT'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
assert s.count('#include <cstddef>')==1 and '#include <cstdint>' not in s, 'LDC LLVM14 header changed'
p.write_text(s.replace('#include <cstddef>','#include <cstddef>\\n#include <cstdint>'))
p=Path(sys.argv[2]);s=p.read_text()
anchor='    target_link_libraries(ldc-profdata ${LLVM_LIBRARIES} ${CMAKE_DL_LIBS} ${LLVM_LDFLAGS})'
assert s.count(anchor)==1, 'LDC profiler link anchor changed'
p.write_text(s.replace(anchor,anchor+'\\n    if(ANDROID)\\n        target_link_libraries(ldc-profdata android-execinfo)\\n    endif()'))
TERMI_LDC_STDINT
\t_termi_ldc_host_xml
\t"$TERMUX_PKG_SRCDIR/ldc2-$TERMUX_PKG_VERSION-linux-x86_64/bin/ldmd2" --version'''), True).replace('termux_step_configure() {', '''termux_step_configure() {
\tlocal termi_ldc_launcher="$TERMUX_PKG_TMPDIR/termi-ldc-cxx-launcher"
\tprintf '#!/bin/bash\\ncompiler="$1"\\nshift\\nexec "$compiler" -nostdinc++ -I%q "$@"\\n' "$TERMUX_PREFIX/include/c++/v1" > "$termi_ldc_launcher"
\tchmod 755 "$termi_ldc_launcher"
\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DCMAKE_CXX_COMPILER_LAUNCHER=$termi_ldc_launcher"
''').replace('termux_step_post_configure() {', 'termux_step_post_configure() {\n\t_termi_ldc_host_xml').replace('termux_step_make() {', 'termux_step_make() {\n\t_termi_ldc_host_xml').replace('libcurl, zlib"','libcurl, libandroid-execinfo, zlib"').replace('-lphobos2-ldc;-ldruntime-ldc;', '-lphobos2-ldc;-ldruntime-ldc;-landroid-execinfo;') + LDC_HOST_XML_SETUP)

    # API-26 libc headers omit RWF_DSYNC; Linux AIO still needs its kernel
    # UAPI constant. Include the defining kernel header rather than invent it.
    change('qemu-system-x86-64-headless', lambda t: hook(t, 'termux_step_pre_configure', '''
\tpython3 - "$TERMUX_PKG_SRCDIR/block/linux-aio.c" <<'TERMI_QEMU_RWF'
from pathlib import Path
import sys
import re
p=Path(sys.argv[1]);s=p.read_text()
anchor='#include "qemu/osdep.h"'
assert s.count(anchor)==1, 'QEMU Linux AIO include anchor changed'
p.write_text(s.replace(anchor,anchor+'\\n#ifndef RWF_DSYNC\\n#include <linux/fs.h>\\n#endif'))
# Keep the existing direct-syscall implementations without colliding with
# newer Bionic declarations. Rename only this translation unit's helpers.
p=p.parents[1]/'linux-user/syscall.c';s=p.read_text()
aliases=[]
for name in ('msgctl','msgget','setdomainname'):
    assert len(re.findall(r'_syscall[23]\\(int,\\s*'+name+r',',s))==1, 'QEMU syscall helper changed: '+name
    unique='termi_qemu_'+name
    s=re.sub(r'\\b'+name+r'\\b',unique,s)
    aliases.append('#define __NR_'+unique+' __NR_'+name)
anchor='_syscall0(int, vhangup)'
assert s.count(anchor)==1, 'QEMU helper insertion anchor changed'
p.write_text(s.replace(anchor,'\\n'.join(aliases)+'\\n'+anchor))
TERMI_QEMU_RWF'''))

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
        assert 'TERMUX_PKG_VERSION="2.1.6"' in t and t.count('\tgo run build.go -goos') == 1, 'Syncthing native driver contract changed'
        return hook(t.replace('\tgo run build.go -goos',native), 'termux_step_pre_configure', SYNCTHING_NATIVE_GENERATE_SETUP)
    change('syncthing',syncthing)

    def wlr_native_scdoc(t):
        anchor = '\ttermux_setup_wayland_cross_pkg_config_wrapper\n'
        assert 'TERMUX_PKG_VERSION=0.5.0\n' in t and t.count(anchor) == 1, 'wlr-randr native documentation contract changed'
        return t.replace(anchor, anchor + WLR_NATIVE_SCDOC_SETUP)
    change('wlr-randr', wlr_native_scdoc, tree='x11-packages')

    for name in ['upx','yoga']:
        change(name,lambda t:hook(t,'termux_step_pre_configure','\tCXXFLAGS+=" -nostdinc++"'))
    change('libobjc2',lambda t:t.replace('local target="$CCTERMUX_HOST_PLATFORM"',
        'local target="${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}"').replace(
        'export OBJCFLAGS="$CFLAGS --target=$target"','export OBJCFLAGS="$CFLAGS $CPPFLAGS --target=$target"').replace(
        'export OBJCXXFLAGS="$CXXFLAGS --target=$target"','export OBJCXXFLAGS="$CXXFLAGS $CPPFLAGS -nostdinc++ --target=$target"'))

    runtime=re.search(r'termux_step_pre_configure\(\) \{\n(.*?)\n\}',prepared['arpack-ng'],re.S).group(1)
    change('octave',lambda t:octave_fortran_recipe(t,runtime))
    change('octave-x',lambda t:octave_fortran_recipe(t,runtime),tree='x11-packages')
    change('suitesparse',lambda t:t.replace('libandroid-complex-math, libgmp, libmpfr, libopenblas', 'libandroid-complex-math, libgmp, libmpfr, libopenblas, libandroid-execinfo').replace('TERMUX_PKG_LICENSE="GPL-3.0"',
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
    change('libntl',lambda t:hook(t.replace(
        'TERMUX_PKG_DEPENDS="libgf2x, libgmp"',
        'TERMUX_PKG_DEPENDS="libgf2x, libgmp, libc++"').replace(
        'termux_proot_run=(termux-proot-run env LD_PRELOAD= LD_LIBRARY_PATH=)',
        '''termux_proot_run=("$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH/proot"
            -q "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH/qemu-$TERMUX_ARCH"
            -R / -b "$TERMUX_PREFIX/opt/aosp:/system"
            /usr/bin/env LD_PRELOAD= LD_LIBRARY_PATH= ANDROID_ROOT=/system ANDROID_DATA=/data)'''),
        'termux_step_pre_configure',NTL_CXX_HEADERS + NTL_GMP_SETUP))

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

    # libnl's private libtool link dependency requires this source-built shim.
    def libnl_private_link_support(t, name):
        if name == 'mate-applets':
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="autoconf-archive, mate-common, glib"'
            assert t.count(anchor) == 1, 'MATE applets build providers changed'
            t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="autoconf-archive, mate-common, glib, libdeflate, libxpm, libxres, libxt, openh264"')
        return hook(t, 'termux_step_pre_configure', '''\tlocal termi_getsubopt="$TERMUX_PKG_TMPDIR/getsubopt"
\tmkdir -p "$termi_getsubopt"
\t$CC $CFLAGS $CPPFLAGS -fvisibility=hidden -c "$TERMUX_PKG_BUILDER_DIR/../../packages/libnl/getsubopt.c" -o "$termi_getsubopt/getsubopt.o"
\t$AR crs "$termi_getsubopt/libgetsubopt.a" "$termi_getsubopt/getsubopt.o"
\tLDFLAGS+=" -L$termi_getsubopt"''')
    def chromium_host_build_provider(t, host=True):
        if host:
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="libffi-static"'
            assert t.count(anchor) == 1 and 'TERMUX_PKG_VERSION="155.0.8059.84"' in t, 'Chromium host build provider contract changed'
            t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libffi-static, googletest, libbsd, libcap-ng, libdeflate, libice, libmd, libsm, libunibreak, libxres, libxt, util-linux"')
        else:
            # Use the exact source release already verified for our host tools.
            old_version = 'TERMUX_PKG_VERSION=155.0.8059.79\n'
            old_hash = 'TERMUX_PKG_SHA256=a13680be9cd424a6f47cc7656186ab9334ea64cb8aa59c0134ed021d7dc76d12\n'
            assert t.count(old_version) == t.count(old_hash) == 1, 'Chromium target source contract changed'
            t = t.replace(old_version, 'TERMUX_PKG_VERSION="155.0.8059.84"\n')
            t = t.replace(old_hash, 'TERMUX_PKG_SHA256=927e7813bbe4c35e28e31b376a1eb17057068d329dc780722ec21b37186a0507\n')
            anchor = 'libc++, libevdev'
            assert t.count(anchor) == 1, 'Chromium curl runtime providers changed'
            t = t.replace(anchor, 'libc++, libcurl, libevdev')
            assert t.count('ninja -C out/Release') == 5, 'Chromium target Ninja commands changed'
            t = t.replace('ninja -C out/Release', 'ninja -j 1 -C out/Release')
        if not host:
            # The override consumes SwiftShader built from Termi's pinned host
            # source. Rewrite its two literal paths after installing it.
            anchor = '\tcp -Rf $TERMUX_PKG_BUILDER_DIR/third_party_override/swiftshader/* $TERMUX_PKG_SRCDIR/third_party/swiftshader/\n'
            assert t.count(anchor) == 1, 'Chromium SwiftShader override hook changed'
            fix = '\tpython3 - "$TERMUX_PKG_SRCDIR/third_party/swiftshader/src/Vulkan/BUILD.gn" "$TERMUX_PREFIX" <<\'TERMI_CHROMIUM_PREFIX\'\n' + CHROMIUM_TARGET_PREFIX_PATCH + 'TERMI_CHROMIUM_PREFIX\n'
            t = t.replace(anchor, anchor + fix)
        # The unbundle toolchain emits pkg-config C system paths before
        # CPPFLAGS. Remove the duplicate system entry so libc++'s normal -I
        # path keeps priority over those C headers.
        headers = '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\t[[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]] || termux_error_exit "Chromium155 C++ system include contract changed"
\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Chromium155 duplicate C++ system include"
'''
        t = hook(t, 'termux_step_pre_configure', headers + NTL_CXX_HEADERS + '\n' + CHROMIUM_SKIA_FLOAT_SETUP)
        # Continued builds skip pre_configure but regenerate GN in configure.
        # Restore its repeatable environment before GN consumes it, and again
        # before make; never reapply the already-patched source helper.
        resumed_headers = '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\tif [[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]]; then
\t\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Chromium155 duplicate resumed C++ system include"
\tfi
\tif [[ "$CXXFLAGS" != *" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"* ]]; then
\t\tCXXFLAGS+=" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"
\tfi
'''
        for step in ['termux_step_configure', 'termux_step_make']:
            anchor = step + '() {\n'
            assert t.count(anchor) == 1, 'Chromium155 continued build hook changed'
            t = t.replace(anchor, anchor + resumed_headers)
        return t
    change('chromium-host-tools', chromium_host_build_provider, tree='x11-packages')
    change('chromium', lambda t: chromium_host_build_provider(t, False), tree='x11-packages')

    # Own-source GTK .pc audit: retain the complete private provider closure
    # when these consumers use a dependency-only seed prefix.
    gtk_seed_consumers = {
        'vala-panel-appmenu': ('25.04', 'libdeflate, libxpm, libxres, libxt, openh264'),
        'xfce4-eyes-plugin': ('4.7.0', 'libdeflate, libxpm, libxres, libxt, openh264'),
        'xfce4-places-plugin': ('1.9.0', 'libdeflate, libxpm, libxres, libxt, openh264'),
        'xfce4-taskmanager': ('1.6.0', 'libdeflate, libxpm, libxres, openh264'),
    }
    def gtk_seed_providers(t, name):
        version, providers = gtk_seed_consumers[name]
        assert f'TERMUX_PKG_VERSION="{version}"' in t, 'GTK seed consumer version changed'
        if name == 'vala-panel-appmenu':
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross, gtk3, valac"'
            assert t.count(anchor) == 1, 'Vala panel build providers changed'
            return t.replace(anchor, anchor[:-1] + ', ' + providers + '"')
        anchor = '\nTERMUX_PKG_DEPENDS='
        assert t.count(anchor) == 1 and 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'XFCE build providers changed'
        return t.replace(anchor, '\nTERMUX_PKG_BUILD_DEPENDS="' + providers + '"' + anchor)
    for name in gtk_seed_consumers:
        change(name, lambda t, name=name: gtk_seed_providers(t, name), tree='x11-packages')

    # Hash-verified own-source .pc metadata audit 41334206651: include the
    # complete Requires/Requires.private provider closure in isolated prefixes.
    # These are build providers, with native tools/features preserved intact.
    electron_providers = {
        'electron42-host-tools': ('42.11.12', 'libcap-ng, libdeflate, libice, libsm, libxres, libxt, util-linux'),
        'electron43-host-tools': ('43.7.11', 'googletest, libbsd, libcap-ng, libdeflate, libice, libmd, libsm, libunibreak, libxres, libxt, util-linux'),
        'electron-host-tools-for-code-oss': ('42.7.1', 'libcap-ng, libdeflate, libice, libsm, libxres, libxt, util-linux'),
    }
    def electron_build_providers(t, name):
        version, providers = electron_providers[name]
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="libnotify, libffi-static"'
        assert t.count(anchor) == 1 and f'TERMUX_PKG_VERSION={version}\n' in t, 'Electron host build provider contract changed: ' + name
        t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libnotify, libffi-static, ' + providers + '"')
        if name in ('electron42-host-tools', 'electron43-host-tools', 'electron-host-tools-for-code-oss'):
            # The default Ninja worker count killed Blink's large host jumbo
            # compile on the free runner. Bound only this recipe's invocations;
            # retain every target, compiler flag and jumbo source grouping.
            command = 'ninja -C out/Release'
            assert t.count(command) == 8, 'Electron Ninja invocation contract changed: ' + name
            t = ''.join(line if line.lstrip().startswith('#') else line.replace(command, 'ninja -j 1 -C out/Release') for line in t.splitlines(keepends=True))
            assert t.count('ninja -j 1 -C out/Release') == 6, 'Electron active Ninja commands changed: ' + name
        return t
    for name in electron_providers:
        change(name, lambda t, name=name: electron_build_providers(t, name), tree='x11-packages')

    # The target consumer uses the same source and Ninja entry points as its
    # verified host tools. Keep their worker bound and single C++ header tree.
    def electron42_consumer(t, version='42.11.12', prefix_setup=ELECTRON42_PREFIX_SETUP):
        assert f'TERMUX_PKG_VERSION={version}\n' in t, 'Electron42 consumer version changed'
        command = 'ninja -C out/Release'
        assert t.count(command) == 8, 'Electron42 consumer Ninja commands changed'
        t = t.replace(command, 'ninja -j 1 -C out/Release')
        # GN emits pkg-config C system paths before CPPFLAGS. A duplicate
        # -isystem for libc++ makes Clang disregard our -I priority, so its
        # C wrappers can be bypassed. Keep one ordinary C++ include entry.
        headers = '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\t[[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]] || termux_error_exit "Electron42 C++ system include contract changed"
\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Electron42 duplicate C++ system include"
'''
        anchor = 'TERMUX_PKG_DEPENDS="atk, cups, dbus, fontconfig, gtk3, krb5, libc++, libevdev, libxkbcommon, libminizip, libnss, libx11, mesa, openssl, pango, pulseaudio, zlib"'
        assert t.count(anchor) == 1, 'Electron curl runtime providers changed'
        t = t.replace(anchor, anchor.replace('libc++, ', 'libc++, libcurl, '))
        t = hook(t, 'termux_step_pre_configure', headers + NTL_CXX_HEADERS + '\n' + prefix_setup + CHROMIUM_SKIA_FLOAT_SETUP)
        # Continued builds regenerate GN before make. Restore the repeatable
        # environment at entry to both hooks, without reapplying source patches.
        resume_headers = '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\tif [[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]]; then
\t\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Electron42 duplicate resumed C++ system include"
\tfi
\tif [[ "$CXXFLAGS" != *" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"* ]]; then
\t\tCXXFLAGS+=" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"
\tfi
'''
        anchor = 'termux_step_configure() {\n'
        assert t.count(anchor) == 1, 'Electron continued configure hook changed'
        t = t.replace(anchor, anchor + resume_headers)
        return hook(t, 'termux_step_make', resume_headers)
    change('electron42', electron42_consumer, tree='x11-packages')

    # VSCode 1.132.0 explicitly checks Electron42.7.1. Its native modules must
    # use the matching source-built header provider and that provider's path.
    def code_oss_headers(t):
        assert 'TERMUX_PKG_VERSION="1.132.0"' in t, 'Code OSS version changed'
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="electron42-headers"'
        path = 'npm_config_nodedir=$TERMUX_PREFIX/opt/electron42-host-tools/node_headers'
        assert t.count(anchor) == t.count(path) == 1, 'Code OSS header provider contract changed'
        t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="electron-headers-for-code-oss, libxpm, openh264"')
        t = t.replace(path, 'npm_config_nodedir=$TERMUX_PREFIX/lib/code-oss/node_headers')
        return hook(t, 'termux_step_pre_configure', CODE_OSS_REMOTE_ENV_SETUP + CODE_OSS_COPILOT_SDK_SETUP)
    change('code-oss', code_oss_headers, tree='x11-packages')

    # Use the same Electron revision as Code OSS's verified host tools and
    # headers. Bound the matching large target build on standard free runners.
    def code_oss_electron_target(t):
        anchor = 'TERMUX_PKG_VERSION=42.7.0\n'
        assert t.count(anchor) == 1 and '_CHROMIUM_VERSION=148.0.7778.280\n' in t, 'Code OSS Electron target version changed'
        assert 'TERMUX_PKG_BUILD_DEPENDS="electron-host-tools-for-code-oss, libnotify, libffi-static"' in t, 'Code OSS Electron host provider changed'
        command = 'ninja -C out/Release'
        assert t.count(command) == 8, 'Code OSS Electron Ninja commands changed'
        t = t.replace(anchor, 'TERMUX_PKG_VERSION=42.7.1\n')
        return electron42_consumer(t, '42.7.1', CODE_OSS_ELECTRON_PREFIX_SETUP).replace('Electron42', 'Code OSS Electron')
    change('electron-for-code-oss', code_oss_electron_target, tree='x11-packages')

    # Hash-audited private FFmpeg/image providers for isolated Torch consumers.
    def torch_consumer_providers(t, name):
        if name == 'python-torchcodec':
            assert 'TERMUX_PKG_VERSION="0.17.0"' in t, 'Torchcodec version changed'
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="pybind11"'
            replacement = 'TERMUX_PKG_BUILD_DEPENDS="pybind11, googletest, libbsd, libdeflate, libmd, libunibreak, openh264"'
        else:
            assert 'TERMUX_PKG_VERSION="0.29.1"' in t and 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'Torchvision build metadata changed'
            anchor = 'TERMUX_PKG_SETUP_PYTHON=true'
            replacement = anchor + '\nTERMUX_PKG_BUILD_DEPENDS="googletest, libbsd, libdeflate, libmd, libunibreak"'
        assert t.count(anchor) == 1, 'Torch consumer provider anchor changed'
        return hook(t.replace(anchor, replacement), 'termux_step_pre_configure', NTL_CXX_HEADERS)
    for name in ('python-torchcodec', 'python-torchvision'):
        change(name, lambda t, name=name: torch_consumer_providers(t, name))

    # Torchaudio uses the same Torch CppExtension backend as Torchvision.
    # Preserve its features while selecting the verified single C++ header tree.
    def torchaudio_headers(t):
        assert 'TERMUX_PKG_VERSION="2.11.0"' in t and '\texport USE_CUDA=0\n' in t, 'Torchaudio preconfigure contract changed'
        return hook(t, 'termux_step_pre_configure', NTL_CXX_HEADERS)
    change('python-torchaudio', torchaudio_headers)

    # Slice uses global uint8_t during the native Chromium tools build. Newer
    # host libstdc++ no longer supplies that C type through unrelated headers.
    # Run after upstream source patches, retaining all host/target build flags.
    def qt5_perfetto_integer_header(t):
        assert 'TERMUX_PKG_VERSION="5.15.19"' in t, 'Qt5 WebEngine source version changed'
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="libdrm, qt5-qtbase-cross-tools, qt5-qtdeclarative-cross-tools"'
        assert t.count(anchor) == 1, 'Qt5 WebEngine header provider contract changed'
        # Qt's Chromium bridge disables implicit C++ includes and uses the
        # prefix header tree. Declare its provider instead of relying on a
        # transitive dependency that the selected build prefix may omit.
        t = t.replace(anchor, anchor.replace('="', '="ndk-sysroot, ', 1))
        return hook(t, 'termux_step_pre_configure', QT5_PERFETTO_INTEGER_SETUP)
    change('qt5-qtwebengine', qt5_perfetto_integer_header, tree='x11-packages')

    # Preserve one seeded libc++ wrapper tree: a second implicit NDK tree has
    # the same float.h guard and hides Clang's FLT_MANT_DIG/DBL_DIG constants.
    # Include the already-built header and complete private .pc providers.
    def float_header_build_providers(t, name):
        if name == 'python-torch':
            version = 'TERMUX_PKG_VERSION="2.14.1"'
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="vulkan-headers, vulkan-loader-android"'
            providers = 'ndk-sysroot, libandroid-glob, libcap-ng, libice, libsm, libxt, util-linux, vulkan-headers, vulkan-loader-android'
        else:
            version = 'TERMUX_PKG_VERSION="26.08.2"'
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="eigen, extra-cmake-modules, kf6-kdoctools"'
            providers = 'ndk-sysroot, libdeflate, libxpm, libxres, libxt, openh264, eigen, extra-cmake-modules, kf6-kdoctools'
        assert version in t and t.count(anchor) == 1, 'Floating header build provider contract changed: ' + name
        return hook(t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="' + providers + '"'),
                    'termux_step_pre_configure', NTL_CXX_HEADERS)
    for name, tree in [('python-torch', 'packages'), ('step', 'x11-packages')]:
        change(name, lambda t, name=name: float_header_build_providers(t, name), tree=tree)

    def panda3d_float_headers(t):
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="libandroid-glob"'
        assert 'TERMUX_PKG_VERSION="1.10.16"' in t and t.count(anchor) == 1, 'Panda3D header provider contract changed'
        t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libandroid-glob, ndk-sysroot, libcap-ng, libice, libsm, libxt, util-linux"')
        return hook(t, 'termux_step_pre_configure', NTL_CXX_HEADERS)
    change('panda3d', panda3d_float_headers)

    def xfce_datetime_archived_source(t):
        old = 'https://archive.xfce.org/src/panel-plugins/xfce4-datetime-plugin/'
        assert '_MAJOR_VERSION=0.8\nTERMUX_PKG_VERSION=${_MAJOR_VERSION}.3\n' in t and t.count(old) == 1, 'Xfce datetime source contract changed'
        assert 'TERMUX_PKG_SHA256=6b2eeb79fb586868737426cbd2a4cd43c7f8c58507d8a2f578e0150187cc00b0\n' in t and 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'Xfce datetime checksum/provider contract changed'
        # The project's official retired-project archive has the exact same
        # release bytes. Keep its version, checksum and generated configure.
        return t.replace(old, 'https://archive.xfce.org/src/archive/xfce4-datetime-plugin/') + '\nTERMUX_PKG_BUILD_DEPENDS="libdeflate, libxpm, libxres, libxt, openh264"\n'
    change('xfce4-datetime-plugin', xfce_datetime_archived_source, tree='x11-packages')

    def rhythmbox_build_provider(t):
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross, valac"'
        assert t.count(anchor) == 1 and 'TERMUX_PKG_VERSION="3.5.1"' in t, 'Rhythmbox build provider contract changed'
        return t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross, valac, libcap-ng, libdeflate, libdrm, libice, liborc, libsm, libxpm, libxres, libxt, openh264, util-linux"')
    change('rhythmbox', rhythmbox_build_provider, tree='x11-packages')

    for name, tree in (('openmpi', 'packages'), ('mate-applets', 'x11-packages')):
        change(name, lambda t, name=name: libnl_private_link_support(t, name), tree=tree)
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

    # aligned_alloc starts at Android API 28; posix_memalign is available at
    # our API 26 floor. Preserve alignment, rounded size and failure cleanup.
    change('libneatvnc', lambda t: hook(neatvnc_build_prerequisites(t), 'termux_step_pre_configure',
        '\tpython3 - "$TERMUX_PKG_SRCDIR/src/buffer.c" <<\'TERMI_NEATVNC_ALLOC\'\n'
        + NEATVNC_ALLOCATION_PATCH + 'TERMI_NEATVNC_ALLOC'), tree='x11-packages')

    # Bionic's inttypes headers expose PTHREAD_ONCE_INIT through pthread_types
    # without the function declaration, selecting the pthread branch anyway.
    change('netcdf-c', lambda t: hook(netcdf_build_prerequisites(t), 'termux_step_pre_configure',
        '\tpython3 - "$TERMUX_PKG_SRCDIR/libdispatch/dcrc64.c" <<\'TERMI_NETCDF_PTHREAD\'\n'
        + NETCDF_PTHREAD_PATCH + 'TERMI_NETCDF_PTHREAD'))

    def samba_stable_source(t):
        old = 'TERMUX_PKG_SRCURL=https://download.samba.org/pub/samba/samba-${TERMUX_PKG_VERSION}.tar.gz'
        assert t.count(old) == 1, 'Samba source URL contract changed'
        # The identical hash-pinned release lives in the official stable tree.
        return t.replace(old, old.replace('/pub/samba/samba-', '/pub/samba/stable/samba-'))
    change('samba', samba_stable_source)

    # Bionic exposes memfd_create from API 30, not 26. Extend the two existing
    # upstream Android syscall shims through API 29 without changing semantics.
    change('weston', lambda t: hook(t, 'termux_step_pre_configure',
        '\tpython3 - "$TERMUX_PKG_SRCDIR" <<\'TERMI_WESTON_MEMFD\'\n'
        + WESTON_MEMFD_PATCH + 'TERMI_WESTON_MEMFD'), tree='x11-packages')

    def caja_pkgconfig_prerequisites(t):
        old = 'TERMUX_PKG_BUILD_DEPENDS="autoconf-archive, glib, mate-common, python, gst-plugins-base"'
        assert t.count(old) == 1, 'Caja extensions build prerequisites changed'
        # libcaja-extension's GTK/TIFF and atspi chains require these private
        # .pc providers even when configure requests a shared consumer.
        return t.replace(old, old.replace('"autoconf-archive,', '"libdeflate, libxres, libdrm, liborc, autoconf-archive,'))
    change('caja-extensions', caja_pkgconfig_prerequisites, tree='x11-packages')

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

    # Independent catalog failures can be repaired and built concurrently.
    def ckermit_host_main(t):
        t = prepared.get('ckermit', t)
        assert 'TERMUX_PKG_VERSION=9.0.302\n' in t, 'C-Kermit source version changed'
        return hook(t, 'termux_step_pre_configure', r'''	python3 - "$TERMUX_PKG_SRCDIR/ckwart.c" <<'TERMI_CKWART_MAIN'
from pathlib import Path
import hashlib, sys
p = Path(sys.argv[1]); raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'b4b07c7f94ee0a2e2c8aa6ef6521e0bad1cd8aecffcaa99b075129fd8c91dd82', 'Pinned C-Kermit generator changed'
anchor = b'main(argc,argv) int argc; char **argv; {'
assert raw.count(anchor) == 1, 'C-Kermit main signature changed'
p.write_bytes(raw.replace(anchor, b'int ' + anchor))
TERMI_CKWART_MAIN
''')
    change('ckermit', ckermit_host_main)

    def python2_c_dialect(t):
        t = prepared.get('python2', t)
        assert 'TERMUX_PKG_VERSION=${_MAJOR_VERSION}.18\n' in t, 'Python2 version changed'
        anchor = '\t$TERMUX_PKG_SRCDIR/configure\n'
        assert t.count(anchor) == 1, 'Python2 native configure changed'
        t = t.replace(anchor, '\tCFLAGS="${CFLAGS:-} -std=gnu17" $TERMUX_PKG_SRCDIR/configure\n')
        return hook(t, 'termux_step_pre_configure', '\tCFLAGS+=" -std=gnu17"')
    change('python2', python2_c_dialect)

    def cadaver_glob(t):
        t = prepared.get('cadaver', t)
        anchor = 'TERMUX_PKG_DEPENDS="libiconv, libneon, readline"'
        assert t.count(anchor) == 1 and 'TERMUX_PKG_VERSION="0.28"' in t, 'Cadaver dependency contract changed'
        t = t.replace(anchor, 'TERMUX_PKG_DEPENDS="libandroid-glob, libiconv, libneon, readline"')
        return hook(t, 'termux_step_pre_configure', '\texport LIBS="${LIBS:-} -landroid-glob"')
    change('cadaver', cadaver_glob)

    def independent_cpp_headers(t, name):
        t = prepared.get(name, t)
        version = {'asymptote': '3.15', 'crawl': '0.34.1'}[name]
        assert f'TERMUX_PKG_VERSION="{version}"' in t, 'Independent C++ consumer version changed'
        if name == 'asymptote':
            t = hook(t, 'termux_step_pre_configure', '\tCXXFLAGS+=" -nostdinc++"')
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="eigen, glm"'
            assert t.count(anchor) == 1, 'Asymptote header providers changed'
            t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="eigen, glm, ndk-sysroot"')
        else:
            t = focused_cxx_header_provider(t)
        t = hook(t, 'termux_step_pre_configure', '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\t[[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]] || termux_error_exit "C++ system header input changed"
\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Duplicate C++ system header input"
''')
        return matching_cxx(t)
    for name in ('asymptote', 'crawl'):
        change(name, lambda t, name=name: independent_cpp_headers(t, name))

    # Completed catalog diagnostics show the same libc++/C header inversion
    # in these independent consumers. Keep native host compilers separate.
    def remaining_cpp_headers(t, name):
        t = prepared.get(name, t)
        versions = {'mosh': '1.4.0', 'newsboat': '2.45', 'python-soxr': '1.1.0', 'libapt-pkg-perl': '0.1.43'}
        assert re.search(r'TERMUX_PKG_VERSION="?' + re.escape(versions[name]) + r'"?\n', t), 'C++ consumer version changed'
        if name == 'newsboat':
            anchor = 'TERMUX_PKG_BUILD_DEPENDS="openssl"'
            assert t.count(anchor) == 1, 'Newsboat build providers changed'
            t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="openssl, ndk-sysroot"')
        else:
            t = focused_cxx_header_provider(t)
        t = hook(t, 'termux_step_pre_configure', '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\t[[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]] || termux_error_exit "C++ system header input changed"
\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Duplicate C++ system header input"
''')
        t = matching_cxx(t)
        if name == 'libapt-pkg-perl':
            anchor = 'make CC="${CC}++" LD="${CC}++"'
            assert t.count(anchor) == 1, 'Perl APT C++ driver contract changed'
            t = t.replace(anchor, 'make CC="$CXX" LD="$CXX"')
        if name == 'mosh':
            anchor = 'TERMUX_PKG_DEPENDS="abseil-cpp, libandroid-support, libc++, libprotobuf, ncurses, openssl, openssh | dropbear"'
            assert t.count(anchor) == 1, 'Mosh execinfo provider contract changed'
            t = t.replace(anchor, anchor.replace('libandroid-support, ', 'libandroid-support, libandroid-execinfo, '))
        if name == 'newsboat':
            t = api_pin_matching_cxx(t)
            anchor = '"$@" --target=%q\\n'
            assert t.count(anchor) == 1, 'Newsboat target wrapper system include changed'
            t = t.replace(anchor, '"$@" --target=%q -isystem%q\\n')
            anchor = '"${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}" > "$termi_cxx"'
            assert t.count(anchor) == 1, 'Newsboat system header path changed'
            t = t.replace(anchor, '"${TERMUX_HOST_PLATFORM}${TERMUX_PKG_API_LEVEL}" "$TERMUX_PREFIX/include" > "$termi_cxx"')
        return t
    for name in ('mosh', 'newsboat', 'python-soxr', 'libapt-pkg-perl'):
        change(name, lambda t, name=name: remaining_cpp_headers(t, name))

    def openscad_eigen(t):
        assert 'TERMUX_PKG_VERSION="2021.01"' in t, 'OpenSCAD version changed'
        assert 'TERMUX_PKG_BUILD_DEPENDS="boost-headers, cgal, eigen"' in t, 'OpenSCAD header providers changed'
        t = hook(t, 'termux_step_pre_configure', '\tTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -DEIGEN3_INCLUDE_DIR=$TERMUX_PREFIX/include/eigen3"')
        return hook(t, 'termux_step_pre_configure', r'''	python3 - "$TERMUX_PKG_SRCDIR/src/Geometry.h" <<'TERMI_OPENSCAD_ASSERT'
from pathlib import Path
import sys
p = Path(sys.argv[1]); s = p.read_text()
anchor = '#include <stddef.h>'
assert s.count(anchor) == 1 and '#include <cassert>' not in s, 'OpenSCAD Geometry header changed'
p.write_text(s.replace(anchor, anchor + '\n#include <cassert>'))
TERMI_OPENSCAD_ASSERT
''')
    change('openscad', openscad_eigen)

    def skia_pathops_headers(t):
        assert 'TERMUX_PKG_VERSION="0.9.2"' in t, 'Skia pathops version changed'
        anchor = r'extra_cflags=[\"-DSK_DISABLE_LEGACY_PNG_WRITEBUFFER\", \"-I${TERMUX_PREFIX}/include\"]'
        assert t.count(anchor) == 1, 'Skia GN include flag contract changed'
        t = t.replace(anchor, r'''extra_cflags=[\"-DSK_DISABLE_LEGACY_PNG_WRITEBUFFER\", \"-isystem${TERMUX_PREFIX}/include\"]
extra_cflags_cc=[\"-nostdinc++\", \"-I${TERMUX_PREFIX}/include/c++/v1\"]''')
        t = focused_cxx_header_provider(t)
        t = hook(t, 'termux_step_pre_configure', '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\t[[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]] || termux_error_exit "Skia pathops C++ header input changed"
\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "Skia pathops duplicate C++ header input"
''')
        return matching_cxx(t)
    change('python-skia-pathops', skia_pathops_headers)

    def skiasharp_headers(t):
        assert 'TERMUX_PKG_VERSION="3.119.4"' in t, 'SkiaSharp version changed'
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="libc++, gn, python"'
        assert t.count(anchor) == 1, 'SkiaSharp header providers changed'
        t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libc++, gn, python, ndk-sysroot"')
        t = hook(t, 'termux_step_pre_configure', '''\tlocal _termi_cpp_system="-isystem$TERMUX_PREFIX/include/c++/v1"
\t[[ "$CPPFLAGS" == *"$_termi_cpp_system"* ]] || termux_error_exit "SkiaSharp C++ header input changed"
\tCPPFLAGS="${CPPFLAGS/$_termi_cpp_system/}"
\t[[ "$CPPFLAGS" != *"$_termi_cpp_system"* ]] || termux_error_exit "SkiaSharp duplicate C++ header input"
''')
        anchor = '\textra_asmflags=[] \\\n'
        assert t.count(anchor) == 2, 'SkiaSharp two GN configuration blocks changed'
        t = t.replace(anchor, anchor + '\textra_cflags_cc=[ \'-nostdinc++\', \'-I${TERMUX_PREFIX}/include/c++/v1\' ] \\\n')
        anchor = '\tlocal LIBS_LDFLAGS="$(pkg-config --libs freetype2 libpng libwebp expat opengl egl)"\n'
        assert t.count(anchor) == 1, 'SkiaSharp GN package flags changed'
        t = t.replace(anchor, anchor + '''\tlocal termi_lib_flags="" termi_flag
\tfor termi_flag in $LIBS_CFLAGS; do
\t\tif [[ "$termi_flag" == "-I$TERMUX_PREFIX/include" ]]; then
\t\t\ttermi_lib_flags+=" -isystem$TERMUX_PREFIX/include"
\t\telse
\t\t\ttermi_lib_flags+=" $termi_flag"
\t\tfi
\tdone
\tLIBS_CFLAGS="${termi_lib_flags# }"
''')
        return matching_cxx(t)
    change('libskiasharp', skiasharp_headers)

    def heimer_cache(t):
        assert 'TERMUX_PKG_VERSION="4.5.0"' in t, 'Heimer version changed'
        anchor = '-DBUILD_WITH_QT6=ON\n'
        assert t.count(anchor) == 1, 'Heimer CMake configuration changed'
        return t.replace(anchor, anchor + '-DENABLE_CCACHE=OFF\n')
    change('heimer', heimer_cache, tree='x11-packages')

    def ices_headers(t):
        assert 'TERMUX_PKG_VERSION=2.0.3\n' in t, 'IceS version changed'
        anchor = 'TERMUX_PKG_DEPENDS="libshout"'
        assert t.count(anchor) == 1, 'IceS ALSA provider changed'
        t = t.replace(anchor, 'TERMUX_PKG_DEPENDS="alsa-lib, libshout"')
        assert 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'IceS private provider declaration changed'
        t += '\nTERMUX_PKG_BUILD_DEPENDS="libtheora, libspeex"\n'
        return hook(t, 'termux_step_pre_configure', ICES_SOUNDCARD_SETUP)
    change('ices', ices_headers)

    def simulavr_architecture(t):
        assert '_VERSION_MAJOR=1\n_VERSION_MINOR=1\n_VERSION_PATCH=0' in t, 'SimulAVR version changed'
        return hook(t, 'termux_step_pre_configure', SIMULAVR_ARCH_SETUP)
    change('simulavr', simulavr_architecture)

    def fio_static_flex(t):
        assert 'TERMUX_PKG_VERSION="3.43"' in t, 'fio version changed'
        assert 'TERMUX_PKG_BUILD_DEPENDS=' not in t, 'fio build providers changed'
        t += '\nTERMUX_PKG_BUILD_DEPENDS="flex"\n'
        return hook(t, 'termux_step_pre_configure', FIO_STATIC_FLEX_SETUP)
    change('fio', fio_static_flex, tree='root-packages')

    def libime_android_loader(t):
        assert 'TERMUX_PKG_VERSION="1.1.17"' in t, 'LibIME version changed'
        anchor = '\t\ttermux_setup_proot\n'
        assert t.count(anchor) == 1, 'LibIME proot setup changed'
        return t.replace(anchor, anchor + LIBIME_ANDROID_LOADER_SETUP)
    change('libime', libime_android_loader, tree='x11-packages')

    # Independent remaining roots: preserve features and isolate compatibility.
    def icewm_android_loader(t):
        assert 'TERMUX_PKG_VERSION="4.1.0"' in t, 'IceWM version changed'
        anchor = '\t\ttermux_setup_proot\n'
        assert t.count(anchor) == 1, 'IceWM proot setup changed'
        return t.replace(anchor, anchor + LIBIME_ANDROID_LOADER_SETUP)
    change('icewm', icewm_android_loader, tree='x11-packages')

    def fcitx_chinese_android_loader(t):
        assert 'TERMUX_PKG_VERSION="5.1.15"' in t, 'fcitx Chinese addons version changed'
        assert 'TERMUX_PKG_BUILD_DEPENDS="aosp-libs, boost-headers, extra-cmake-modules"' in t, 'fcitx loader provider changed'
        anchor = '\t\ttermux_setup_proot\n'
        assert t.count(anchor) == 1, 'fcitx dictionary proot setup changed'
        return t.replace(anchor, anchor + LIBIME_ANDROID_LOADER_SETUP)
    change('fcitx5-chinese-addons', fcitx_chinese_android_loader, tree='x11-packages')

    def jellyfin_private_providers(t):
        assert 'TERMUX_PKG_VERSION=(\n\t12.2\n\t8.1.3.1\n)' in t, 'Jellyfin/FFmpeg versions changed'
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="aspnetcore-targeting-pack-10.0, dotnet-targeting-pack-10.0, libcairo, pango, libjpeg-turbo, giflib, librsvg"'
        assert t.count(anchor) == 1, 'Jellyfin build providers changed'
        providers = 'googletest, libbsd, libcap-ng, libdeflate, libice, libmd, libsm, libunibreak, libxt, util-linux'
        return t.replace(anchor, anchor[:-1] + ', ' + providers + '"')
    change('jellyfin-server', jellyfin_private_providers)

    def erofs_private_getsubopt(t):
        assert 'TERMUX_PKG_VERSION="1.9.4"' in t, 'EROFS version changed'
        return hook(t, 'termux_step_pre_configure', '''\tlocal termi_getsubopt="$TERMUX_PKG_TMPDIR/getsubopt"
\tmkdir -p "$termi_getsubopt"
\t$CC $CFLAGS $CPPFLAGS -fvisibility=hidden -c "$TERMUX_SCRIPTDIR/packages/libnl/getsubopt.c" -o "$termi_getsubopt/getsubopt.o"
\t$AR crs "$termi_getsubopt/libgetsubopt.a" "$termi_getsubopt/getsubopt.o"
\tLDFLAGS+=" -L$termi_getsubopt"''')
    change('erofs-utils', erofs_private_getsubopt, tree='root-packages')

    def hurl_bindgen_api(t):
        assert 'TERMUX_PKG_VERSION="8.0.1"' in t, 'Hurl version changed'
        for anchor in ['--target=arm-linux-androideabi', '--target=${TERMUX_ARCH}-linux-android']:
            assert t.count(anchor + '"') == 1, 'Hurl bindgen target changed'
            t = t.replace(anchor + '"', anchor + '${TERMUX_PKG_API_LEVEL}"')
        return t
    change('hurl', hurl_bindgen_api)

    def qemu_system_kernel_header(t):
        assert 'TERMUX_PKG_VERSION="1:11.1.2"' in t, 'QEMU version changed'
        anchor = 'TERMUX_PKG_BUILD_DEPENDS="libtasn1"'
        assert t.count(anchor) == 1, 'QEMU SDL image providers changed'
        t = t.replace(anchor, 'TERMUX_PKG_BUILD_DEPENDS="libtasn1, libdeflate, libxres"')
        return hook(t, 'termux_step_pre_configure', '''\tpython3 - "$TERMUX_PKG_SRCDIR/block/linux-aio.c" <<'TERMI_QEMU_SYSTEM_RWF'
from pathlib import Path
import sys
p = Path(sys.argv[1]); s = p.read_text()
anchor = '#include "qemu/osdep.h"'
assert s.count(anchor) == 1, 'QEMU Linux AIO include changed'
p.write_text(s.replace(anchor, anchor+'\\n#ifndef RWF_DSYNC\\n#include <linux/fs.h>\\n#endif'))
TERMI_QEMU_SYSTEM_RWF
''')
    change('qemu-system-x86-64', qemu_system_kernel_header, tree='x11-packages')

    def dropbear_bundled_crypto(t):
        assert 'TERMUX_PKG_VERSION="2026.94"' in t, 'Dropbear version changed'
        assert '--enable-bundled-libtom' not in t, 'Dropbear crypto selection changed'
        return t + '\nTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" --enable-bundled-libtom"\n'
    change('dropbear', dropbear_bundled_crypto)

    def git_cliff_cc_deprecation(t):
        assert 'TERMUX_PKG_VERSION="2.14.2"' in t, 'git-cliff version changed'
        anchor = '\tpatch -p1 --ignore-whitespace -d "$dir" < "$patch"\n'
        assert t.count(anchor) == 1, 'git-cliff vendor patch changed'
        return t.replace(anchor, anchor + '''\tpython3 - "$dir/src/parallel/job_token.rs" <<'TERMI_CC_DEPRECATED'
from pathlib import Path
import hashlib, sys
p = Path(sys.argv[1]); raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '6cceffcf0f7e7d82d775287e88a4f9a62dc690c321933204f9b531cf40072bf1', 'Locked cc 1.2.49 token source changed'
anchor = b'        pub(super) async fn acquire(&self) -> JobToken {'
assert raw.count(anchor) == 1, 'cc token acquire changed'
p.write_bytes(raw.replace(anchor, b'        #[allow(deprecated)]\\n' + anchor))
TERMI_CC_DEPRECATED
''')
    change('git-cliff', git_cliff_cc_deprecation)

    def quilt_official_release(t):
        assert 'TERMUX_PKG_VERSION="0.69"' in t, 'Quilt version changed'
        anchor = 'https://savannah.nongnu.org/download/quilt/quilt-${TERMUX_PKG_VERSION}.tar.gz'
        assert t.count(anchor) == 1, 'Quilt release endpoint changed'
        return t.replace(anchor, 'https://download.savannah.nongnu.org/releases/quilt/quilt-${TERMUX_PKG_VERSION}.tar.gz')
    change('quilt', quilt_official_release)

    def ghc_android_loader(t, name, version):
        assert 'TERMUX_PKG_VERSION=' + version + '\n' in t, name + ' version changed'
        assert 'TERMUX_PKG_BUILD_DEPENDS="aosp-libs"' in t, name + ' AOSP provider changed'
        anchor = '\t\ttermux_setup_ghc_iserv\n'
        assert t.count(anchor) == 1, name + ' interpreter setup changed'
        return t.replace(anchor, anchor + r'''		[[ -f "$TERMUX_PREFIX/opt/aosp/bin/linker64" ]] || termux_error_exit "Source-built Android loader missing"
		local termi_iserv="$TERMUX_PKG_TMPDIR/termi-iserv"
		mkdir -p "$termi_iserv"
		local ghc_bin_dir="$(ghc --print-libdir)/../bin" suffix
		for suffix in "" -dyn; do
			printf '#!/bin/bash\nexec /usr/bin/env -u LD_PRELOAD -u LD_LIBRARY_PATH "%s/proot" -q "%s/qemu-%s" -R / -b "%s/opt/aosp:/system" /usr/bin/env LD_PRELOAD= LD_LIBRARY_PATH="%s/lib" ANDROID_ROOT=/system ANDROID_DATA=/data "%s/ghc-iserv%s" "$@"\n' \
			    "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH" "$TERMUX_COMMON_CACHEDIR/proot-bin-$TERMUX_ARCH" "$TERMUX_ARCH" "$TERMUX_PREFIX" "$TERMUX_PREFIX" "$ghc_bin_dir" "$suffix" > "$termi_iserv/termux-ghc-iserv$suffix"
			chmod 755 "$termi_iserv/termux-ghc-iserv$suffix"
		done
		export PATH="$termi_iserv:$PATH"
''')
    for name, version in [('cabal-install', '3.16.1.0'), ('hledger', '"1.52.4"'), ('hledger-ui', '"1.52.4"')]:
        change(name, lambda t, n=name, v=version: ghc_android_loader(t, n, v))

    def ghc_private_cxx(t, name, version):
        t = ghc_android_loader(t, name, version)
        anchor = '\t\ttermux_setup_ghc_iserv\n'
        setup = r'''		python3 - "$CXX" "$TERMUX_STANDALONE_TOOLCHAIN" "$TERMUX_PKG_TMPDIR/termi-ghc-cxx" <<'TERMI_GHC_CXX'
from pathlib import Path
import shlex, sys
compiler, toolchain, target = sys.argv[1:]
headers = Path(toolchain) / 'sysroot/usr/include/c++/v1'
assert (headers/'string').is_file(), 'Pinned NDK libc++ headers missing'
command = shlex.split(compiler)
assert command, 'Missing target C++ compiler'
p = Path(target)
p.write_text('#!/bin/bash\nexec '+shlex.join(command+['-nostdinc++', '-I'+str(headers)])+' "$@"\n')
p.chmod(0o755)
TERMI_GHC_CXX
'''
        options = 'ghc-options: -fexternal-interpreter'
        assert t.count(options) == 1, name + ' GHC options changed'
        return t.replace(anchor, anchor + setup).replace(options, 'ghc-options: -pgmcxx=$TERMUX_PKG_TMPDIR/termi-ghc-cxx -fexternal-interpreter')
    for name, version in [('darcs', '"2.18.5"'), ('pandoc', '"3.12.1"')]:
        change(name, lambda t, n=name, v=version: ghc_private_cxx(t, n, v))

    def clean_host_tools_setup():
        setup = r"""	if [[ "$TERMUX_ON_DEVICE_BUILD" == false ]]; then
		python3 - "$TERMUX_PKG_TMPDIR/termi-host-tools" "$TERMUX_PREFIX" "$TERMUX_STANDALONE_TOOLCHAIN" <<'TERMI_MOZ_HOST'
from pathlib import Path
import json, sys
directory, prefix, toolchain = sys.argv[1:]
d = Path(directory)
d.mkdir(exist_ok=True)
body = r'''import os, sys
roots = ROOTS
def target_path(s):
    return any(s == r or s.startswith(r + '/') for r in roots if r)
args = []
i = 0
while i < len(sys.argv[1:]):
    a = sys.argv[i+1]
    if a in ('-I', '-isystem', '-iquote', '-L', '--sysroot', '-target', '--target') and i+2 < len(sys.argv):
        value = sys.argv[i+2]
        if target_path(value) or (a in ('-target', '--target') and 'android' in value):
            i += 2
            continue
    if any(a.startswith(k) and target_path(a[len(k):]) for k in ('-I', '-isystem', '-iquote', '-L', '--sysroot=')):
        i += 1
        continue
    if a in ('-D__ANDROID__', '-DANDROID', '-landroid-shmem', '-landroid-spawn', '-llog') or (a.startswith('--target=') and 'android' in a):
        i += 1
        continue
    args.append(a)
    i += 1
env = dict(os.environ)
for key in ('CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'CPPFLAGS', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'PKG_CONFIG_PATH', 'PKG_CONFIG_LIBDIR', 'PKG_CONFIG_SYSROOT_DIR'):
    env.pop(key, None)
env['PATH'] = '/usr/bin:/bin:' + env.get('PATH', '')
os.execve(COMPILER, [COMPILER] + args, env)
'''
for name, compiler in [('cc', '/usr/bin/gcc'), ('cxx', '/usr/bin/g++')]:
    assert Path(compiler).is_file(), 'Linux host compiler missing: '+compiler
    p = d/name
    p.write_text('#!/usr/bin/python3\n'+body.replace('ROOTS', repr([prefix, toolchain])).replace('COMPILER', repr(compiler)))
    p.chmod(0o755)
TERMI_MOZ_HOST
		export HOST_CC="$TERMUX_PKG_TMPDIR/termi-host-tools/cc"
		export HOST_CXX="$TERMUX_PKG_TMPDIR/termi-host-tools/cxx"
		export HOST_CFLAGS="-O2" HOST_CXXFLAGS="-O2" HOST_CPPFLAGS=""
	fi
"""
        return setup

    def mozilla_host_tools(t, version):
        assert 'TERMUX_PKG_VERSION="'+version+'"' in t, 'Mozilla version changed'
        anchor = '\t./mach configure\n'
        assert t.count(anchor) == 1, 'Mozilla configure changed'
        setup = clean_host_tools_setup()
        return t.replace(anchor, setup+anchor)
    for name, version in [('firefox', '158.0'), ('librewolf', '158.0-1'), ('thunderbird', '158.0'), ('zen-browser', '1.23.3b')]:
        def browser_providers(t, n=name, v=version):
            t = mozilla_host_tools(t, v)
            if n != 'firefox':
                anchor = 'TERMUX_PKG_BUILD_DEPENDS="libcpufeatures, libice, libsm"'
                assert t.count(anchor) == 1, 'Mozilla build providers changed'
                t = t.replace(anchor, anchor[:-1] + ', googletest, libbsd, libdeflate, libmd, libunibreak, libxres, libxt"')
            if n == 'librewolf':
                t = hook(t, 'termux_step_make', '\tTERMUX_PKG_MAKE_PROCESSES=1\n\texport CARGO_BUILD_JOBS=1\n')
            return t
        change(name, browser_providers, tree='x11-packages')

    change('spidermonkey', lambda t: mozilla_host_tools(t, '140.17.0'))

    def native_helper_compilers(t, guard):
        assert guard in t, 'Native-helper recipe version changed'
        setup = clean_host_tools_setup() + '\tif [[ "$TERMUX_ON_DEVICE_BUILD" == false ]]; then\n\t\texport CC_FOR_BUILD="$HOST_CC" CXX_FOR_BUILD="$HOST_CXX"\n\t\texport CFLAGS_FOR_BUILD="-O2" CXXFLAGS_FOR_BUILD="-O2" CPPFLAGS_FOR_BUILD="" LDFLAGS_FOR_BUILD=""\n\tfi\n'
        return hook(t, 'termux_step_pre_configure', setup)
    change('suite3270', lambda t: native_helper_compilers(t, 'TERMUX_PKG_VERSION=4.1ga11'))
    change('frida', lambda t: native_helper_compilers(t, '_MAJOR_VERSION=17\n_MINOR_VERSION=2\n_MICRO_VERSION=14\n'), tree='root-packages')

    def rust_private_libraries(t, version, libraries, dependencies):
        assert 'TERMUX_PKG_VERSION="'+version+'"' in t, 'Rust consumer version changed'
        match = re.search(r'^TERMUX_PKG_DEPENDS="[^"]*"', t, re.M)
        assert match, 'Rust runtime providers changed'
        t = t[:match.end()-1] + ', '+dependencies + t[match.end()-1:]
        anchor = 'termux_step_make() {\n'
        assert t.count(anchor) == 1, 'Rust build hook changed'
        flags = ''.join(' -C link-arg=-l'+lib for lib in libraries)
        setup = '\tlocal termi_flags="CARGO_TARGET_${CARGO_TARGET_NAME//-/_}_RUSTFLAGS"\n\ttermi_flags="${termi_flags^^}"\n\texport "$termi_flags=${!termi_flags-}'+flags+'"\n'
        return t.replace(anchor, anchor+setup)
    for name, version in [('wezterm', '20240203-110809-5046fc22'), ('wezterm-nightly', '20261005+g37254829')]:
        change(name, lambda t, v=version: rust_private_libraries(t, v, ['bz2', 'brotlidec', 'brotlicommon'], 'libbz2, brotli'), tree='x11-packages')
    change('zellij', lambda t: rust_private_libraries(t, '0.45.1', ['ssh2', 'ngtcp2_crypto_ossl'], 'libssh2, libngtcp2'))

    def vhs_host_documentation(t):
        assert 'TERMUX_PKG_VERSION="0.12.1"' in t, 'VHS version changed'
        anchor = '\tunset CC CXX CFLAGS CXXFLAGS LDFLAGS\n'
        assert t.count(anchor) == 1, 'VHS host documentation environment changed'
        return t.replace(anchor, anchor+'\tunset CPPFLAGS CGO_CFLAGS CGO_CPPFLAGS CGO_CXXFLAGS CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH PKG_CONFIG_PATH PKG_CONFIG_LIBDIR PKG_CONFIG_SYSROOT_DIR\n\texport CC=/usr/bin/gcc CXX=/usr/bin/g++\n')
    change('vhs', vhs_host_documentation)

    def smalltalk_host_dialect(t):
        assert 'TERMUX_PKG_VERSION="3.2.91"' in t, 'Smalltalk version changed'
        anchor = '\t"$TERMUX_PKG_SRCDIR"/configure --disable-gtk --disable-bloxtk\n'
        assert t.count(anchor) == 1, 'Smalltalk host configure changed'
        return t.replace(anchor, '\tCFLAGS="${CFLAGS:-} -std=gnu99 -Wno-error=incompatible-pointer-types" '+anchor.lstrip())
    change('smalltalk', smalltalk_host_dialect)

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
