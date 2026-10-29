"""Reclaim only generated host-side tar copies after their publication succeeds."""
from pathlib import Path
import re


def reclaim(build, bundles):
    build = Path(build)
    upload = build / 'release-upload'
    if build.is_symlink() or upload.is_symlink():
        raise ValueError('Publication directories must not be symlinks')
    build = build.resolve()
    targets = []
    for item in bundles:
        item = Path(item)
        if (item.is_symlink() or item.parent.resolve() != build
                or not re.fullmatch(r'packages-[0-9]{4}\.tar', item.name)
                or not item.is_file()):
            raise ValueError('Only generated publication bundles may be reclaimed')
        targets.append(item)
        for link in upload.glob('*-' + item.name):
            if (not re.fullmatch(r'[0-9]{4}-' + re.escape(item.name), link.name)
                    or link.is_symlink() or not link.is_file()
                    or not link.samefile(item)):
                raise ValueError('Publication bundle link differs from its source')
            targets.append(link)
    # Validate the entire set before deleting any copy. Original Debian files,
    # container state, metadata and logs are never included in this list.
    for target in targets:
        target.unlink()
    return len(bundles)
