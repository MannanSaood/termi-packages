#!/bin/bash
set -euo pipefail
[[ "$PILOT_TAG" =~ ^apt-pilot-[0-9]+-[0-9]+$ ]]
work=$(mktemp -d)
mkdir -p "$work/lists/partial" "$work/cache/archives/partial" "$work/empty"
touch "$work/status"
keyring="$PWD/packages/termux/repository/repository-keyring.gpg"
test -s "$keyring"
url="https://github.com/MannanSaood/termi-packages/releases/download/$PILOT_TAG"
printf 'deb [arch=aarch64 signed-by=%s] %s ./\n' "$keyring" "$url" > "$work/sources.list"
apt_options=(-o "Dir::Etc::sourcelist=$work/sources.list" -o "Dir::Etc::sourceparts=$work/empty"
    -o "Dir::State::lists=$work/lists" -o "Dir::State::status=$work/status"
    -o "Dir::Cache=$work/cache" -o APT::Architecture=aarch64 -o APT::Architectures::=aarch64
    -o APT::Sandbox::User="$(id -un)" -o Acquire::Retries=3)
apt-get "${apt_options[@]}" update
mapfile -t packages < <(python3 -c 'import json; print(*(f"{k}={v}" for k,v in json.load(open("packages/termux/apt-pilot.json"))["roots"].items()), sep="\n")')
test "${#packages[@]}" -eq 3
apt-get "${apt_options[@]}" --yes --download-only --no-install-recommends install "${packages[@]}"
python3 - "$work/cache/archives" <<'PY'
from pathlib import Path
import sys
count = len(list(Path(sys.argv[1]).glob("*.deb")))
assert count == 128, f"Expected 128 verified package downloads; found {count}"
print("Verified signed APT update, dependency resolution, and all 128 archive downloads")
PY
