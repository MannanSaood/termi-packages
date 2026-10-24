"""Remove only disposable per-recipe compilation products inside Linux builders.

Source archives, source checkouts, host tools, installed prefix, built markers,
logs and Debian outputs are preserved. Never use this on phone/app data.
"""
import os
from pathlib import Path
import re
import shutil


def clean(top, name):
    if os.name != "posix" or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name):
        raise ValueError("Scratch cleanup requires a Linux builder recipe")
    top = top.resolve()
    recipe = top / name
    if recipe.is_symlink() or not recipe.is_dir():
        return []
    targets = [recipe / part for part in ["build", "multilib-build", "massage", "tmp", "package"]]
    cargo = recipe / "src/target"
    marker = cargo / "CACHEDIR.TAG"
    if ((recipe / "src/Cargo.toml").is_file() and not cargo.is_symlink()
            and marker.is_file() and "Signature: 8a477f597d28d172789f06886806bc55" in marker.read_text(errors="replace")[:512]):
        targets.append(cargo)
    removed = []
    for path in targets:
        if path.is_symlink():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(recipe.resolve()) or resolved == recipe.resolve():
            raise ValueError("Scratch target escaped its recipe directory")
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(path.relative_to(top).as_posix())
    return removed


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=Path, required=True)
    parser.add_argument("--recipe", required=True)
    args = parser.parse_args()
    print("TERMI_DISCARDED_SCRATCH " + json.dumps(clean(args.top, args.recipe)), flush=True)
