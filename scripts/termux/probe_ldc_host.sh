#!/bin/bash
# Bounded host-tool diagnosis only: no Android output, installs, or credentials.
set -eu
compiler=/inputs/ldc2-1.30.0-linux-x86_64/bin/ldmd2
module=/inputs/ldc-1.30.0-src/cmake/Modules/FindDCompiler.cmake
test -x "$compiler"
test -f "$module"
cat /etc/os-release
cmake=/inputs/cmake-3.31.10-linux-x86_64/bin/cmake
"$cmake" --version
libtoolize --version | head -n 1
automake --version | head -n 1
export TERMUX_PKG_HOSTBUILD_DIR=/tmp/ldc-host TERMUX_PKG_TMPDIR=/tmp TERMUX_PKG_MAKE_PROCESSES=2
termux_download() {
    cp /inputs/libxml2-2.13.9.tar.xz "$2"
    printf '%s  %s\n' "$3" "$2" | sha256sum --check --strict
}
source /inputs/ldc-host-xml.sh
_termi_ldc_host_xml
ldd /inputs/ldc2-1.30.0-linux-x86_64/bin/ldc2 || true
version_status=0
"$compiler" --version >/tmp/ldc-stdout.log 2>/tmp/ldc-stderr.log || version_status=$?
printf '\nHost compiler exit: %s\n--- stdout ---\n' "$version_status"
cat /tmp/ldc-stdout.log
printf '\n--- stderr ---\n'
cat /tmp/ldc-stderr.log
printf 'include("%s")\n' "$module" >/tmp/ldc-detection.cmake
detection_status=0
DMD="$compiler" "$cmake" -P /tmp/ldc-detection.cmake || detection_status=$?
printf '\nCMake detection exit: %s\n' "$detection_status"
test "$version_status" = 0
test "$detection_status" = 0
