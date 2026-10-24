#!/bin/bash
# Execute only inside the disposable pinned Termux builder image.
set -euo pipefail
cd /home/builder/termux-packages
mode=${1:-proof}
case "$mode" in proof|bootstrap|catalog|packages|full-catalog) ;; *) echo 'Expected proof, bootstrap, catalog, packages or full-catalog' >&2; exit 64;; esac
shift || true
jobs=${TERMI_BUILD_JOBS:-2}
[[ "$jobs" =~ ^[1-8]$ ]] || { echo 'Invalid compiler worker count' >&2; exit 64; }
if [ "$mode" = packages ]; then
    [ "$#" -ge 1 ] && [ "$#" -le 128 ] || exit 64
    for root in "$@"; do
        [[ "$root" =~ ^[a-z0-9][a-z0-9+.-]*$ ]] || exit 64
        found=0
        for tree in packages root-packages x11-packages; do
            if [ -f "$tree/$root/build.sh" ]; then found=$((found + 1)); fi
        done
        [ "$found" = 1 ] || { echo "Unknown or ambiguous pinned recipe: $root" >&2; exit 64; }
    done
fi
export TERMUX_PKG_API_LEVEL=26
export TERMUX_PKG_MAKE_PROCESSES="$jobs"
export TERMUX_INSTALL_DEPS=false
export TERMUX_PACKAGES_OFFLINE=false
export TERMUX_SCRIPTDIR="$PWD"
export SOURCE_DATE_EPOCH=$(python3 -c 'import json; print(json.load(open("/home/builder/source.json"))["source_date_epoch"])')
# properties.sh assigns this value itself; preparation must patch it before build.
source ./scripts/properties.sh
test "$TERMUX_APP__PACKAGE_NAME" = com.terminal.nextgen
test "$TERMUX_PREFIX" = /data/data/com.terminal.nextgen/files/usr
mkdir -p /home/builder/artifacts
cp /home/builder/upstream.lock.json /home/builder/patches.json /home/builder/source.json /home/builder/artifacts/
exec > >(tee /home/builder/artifacts/build.log) 2>&1
printf 'TERMI_BUILD_START mode=%s prefix=%s arch=aarch64 api=26\n' "$mode" "$TERMUX_PREFIX"
if [ -f /home/builder/seed/seed.json ]; then
    python3 /home/builder/seed.py --seed /home/builder/seed --root "$PWD" --metadata /home/builder \
        --artifacts /home/builder/artifacts
fi
if [ "$mode" = full-catalog ]; then
    # The graph comes from pinned upstream recipe parsing. Cycles/failures stay
    # explicit; independent recipes can continue, never with stock binary deps.
    result=0
    retry=()
    if [ "${TERMI_CATALOG_RETRY_FAILED:-0}" = 1 ]; then retry+=(--retry-failed); fi
      if [ -n "${TERMI_CATALOG_LANE:-}" ]; then retry+=(--lane "$TERMI_CATALOG_LANE"); fi
    if [ -n "${TERMI_CONTINUE_RECIPE:-}" ]; then retry+=(--resume-compile "$TERMI_CONTINUE_RECIPE"); fi
    python3 /home/builder/catalog_build.py --root "$PWD" --metadata /home/builder \
        --state /home/builder/catalog-state --jobs "$jobs" \
        --budget-seconds "${TERMI_CATALOG_BUDGET:-12600}" \
        --minimum-free-gib "${TERMI_CATALOG_MINIMUM_FREE_GIB:-16}" "${retry[@]}" || result=$?
    cp /home/builder/catalog-state/plan.json /home/builder/artifacts/catalog-plan.json
    cp /home/builder/catalog-state/ledger.json /home/builder/artifacts/catalog-ledger.json
    python3 /home/builder/catalog_progress.py --root "$PWD" --state /home/builder/catalog-state \
        --output /home/builder/artifacts/progress.json
    if compgen -G 'output/*.deb' >/dev/null; then
        python3 /home/builder/collect_artifacts.py output /home/builder/artifacts \
            --plan /home/builder/catalog-state/plan.json --resume
    fi
    if [ "$result" -ne 0 ]; then exit "$result"; fi
elif [ "$mode" = packages ]; then
    if python3 -c 'import json,sys; sys.exit(json.load(open("/home/builder/source.json")).get("catalog_scope") != "full-catalog")'; then
        if [ ! -f /home/builder/artifacts/catalog-plan.json ]; then
            python3 /home/builder/catalog_graph.py --root "$PWD" --metadata /home/builder \
                --output /home/builder/artifacts/catalog-plan.json
        fi
    fi
    printf '%s\n' "$@" > /home/builder/artifacts/requested-recipes.txt
    mkdir -p /home/builder/catalog-state/logs
    python3 /home/builder/catalog_progress.py --root "$PWD" --state /home/builder/catalog-state --selected "$@"
    for root in "$@"; do
        recipe=""
        for tree in packages root-packages x11-packages; do
            if [ -f "$tree/$root/build.sh" ]; then recipe="$tree/$root"; fi
        done
        python3 /home/builder/catalog_progress.py --root "$PWD" --state /home/builder/catalog-state \
            --selected "$@" --recipe "$root" --status running
        attempt=$(python3 -c 'import json,sys; print(json.load(open("/home/builder/catalog-state/selected-ledger.json"))["recipes"][sys.argv[1]]["attempts"])' "$root")
        result=0
        continuation=()
        if [ "${TERMI_CONTINUE_RECIPE:-}" = "$root" ]; then continuation+=(-c); fi
        ./build-package.sh -a aarch64 "${continuation[@]}" -j "$jobs" "$recipe" \
            > >(tee "/home/builder/catalog-state/logs/$root-$attempt.log") 2>&1 || result=$?
        status=built
        if [ "$result" -ne 0 ]; then status=failed; fi
        python3 /home/builder/catalog_progress.py --root "$PWD" --state /home/builder/catalog-state \
            --selected "$@" --recipe "$root" --status "$status" --exit-code "$result" \
            --output /home/builder/artifacts/progress.json
        if [ "$result" -ne 0 ]; then exit "$result"; fi
    done
elif [ "$mode" = catalog ]; then
    # Explicit owner-approved expansion; dependencies are source-built and the
    # published runtime closure is selected separately from build-only outputs.
    for root in git gh; do
        ./build-package.sh -a aarch64 -j "$jobs" "$root"
    done
elif [ "$mode" = proof ]; then
    ./build-package.sh -a aarch64 -j "$jobs" hello
else
    # Upstream build-bootstraps extracts every built .deb, including build-only
    # tools. Build the roots here and let host APT select the runtime closure.
    for root in apt bash termux-exec termux-tools hello; do
        ./build-package.sh -a aarch64 -j "$jobs" "$root"
    done
fi
if [ "$mode" != full-catalog ]; then
    if [ -f /home/builder/artifacts/catalog-plan.json ]; then
        python3 /home/builder/collect_artifacts.py output /home/builder/artifacts \
            --plan /home/builder/artifacts/catalog-plan.json --resume
    else
        python3 /home/builder/collect_artifacts.py output /home/builder/artifacts --resume
    fi
fi
if [ "$mode" = bootstrap ]; then
    python3 /home/builder/assemble_bootstrap.py --debs output \
        --hello output/hello_2.12.3-1_aarch64.deb --output /home/builder/artifacts/bootstrap
fi
cd /home/builder/artifacts
sha256sum ./*.deb ./*.json > SHA256SUMS
if [ "$mode" = bootstrap ]; then sha256sum bootstrap/* >> SHA256SUMS; fi
printf 'TERMI_BUILD_CANDIDATE_COMPLETE; no installation or release approval\n'
