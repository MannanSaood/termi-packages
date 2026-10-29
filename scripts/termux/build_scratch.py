"""Remove only disposable per-recipe compilation products inside Linux builders.

By default source archives and checkouts are preserved. Explicit disposable
hosted mode also drops per-recipe sources/cache after packaging or interruption.
Host tools, shared toolchains, installed prefix, markers, logs and Debian outputs
are always preserved. Never use this on phone/app data.
"""
import os
from pathlib import Path
import re
import shutil
import stat


def configure_diagnostics(top, name, output):
    """Retain bounded original configure logs before failed scratch is removed."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name):
        raise ValueError('Invalid diagnostic recipe')
    top = Path(top)
    if top.is_symlink():
        raise ValueError('Diagnostic source must not be a symlink')
    recipe = top / name
    pieces = []
    for relative in ['src/config.log', 'build/config.log', 'build/CMakeFiles/CMakeConfigureLog.yaml']:
        path = recipe / relative
        chain = [path, *path.parents]
        if any(item.is_symlink() for item in chain[:chain.index(top) + 1]) or not path.is_file():
            continue
        size = path.stat().st_size
        with path.open('rb') as stream:
            body = stream.read(512 * 1024)
            if size > len(body):
                if size > 1024 * 1024:
                    body += b'\nTERMI CONFIGURE LOG MIDDLE OMITTED\n'
                stream.seek(max(512 * 1024, size - 512 * 1024))
                body += stream.read(512 * 1024)
        pieces.append(('\nTERMI CONFIGURE DIAGNOSTIC: ' + relative + '\n').encode() + body)
    if pieces:
        output = Path(output)
        if output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
            raise ValueError('Diagnostic output must not be a symlink')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b''.join(pieces))
    return len(pieces)


def clean(top, name, discard_sources=False):
    if os.name != "posix" or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name):
        raise ValueError("Scratch cleanup requires a Linux builder recipe")
    top = top.resolve()
    recipe = top / name
    if recipe.is_symlink() or not recipe.is_dir():
        return []
    targets = [recipe / part for part in ["build", "multilib-build", "massage", "tmp", "package"]]
    if discard_sources:
        # Hosted builds restart from verified package outputs, not stale source
        # trees. Host tools, shared toolchains and every package archive remain.
        targets += [recipe / part for part in ["src", "cache"]]
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
            # Go module-cache directories are deliberately read-only. Only
            # unlock directories inside this already validated scratch tree;
            # never follow or chmod aliases to source/cache/host-tool paths.
            path.chmod(path.stat().st_mode | stat.S_IRWXU)
            for current, directories, _ in os.walk(path, followlinks=False):
                for name in directories:
                    child = Path(current) / name
                    if child.is_symlink():
                        continue
                    if not child.resolve().is_relative_to(resolved):
                        raise ValueError("Scratch child escaped its validated directory")
                    child.chmod(child.stat().st_mode | stat.S_IRWXU)
            shutil.rmtree(path)
            removed.append(path.relative_to(top).as_posix())
    return removed


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=Path, required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--discard-sources", action="store_true")
    args = parser.parse_args()
    try:
        print("TERMI_DISCARDED_SCRATCH " + json.dumps(clean(args.top, args.recipe,
              args.discard_sources or os.environ.get("TERMI_RECLAIM_RECIPE_CACHE") == "1")), flush=True)
    except OSError as error:
        # Packaging has already succeeded. Keep cleanup visible without
        # reporting its archive as a failed compilation; disk guards still run.
        print("TERMI_SCRATCH_WARNING " + str(error), flush=True)
