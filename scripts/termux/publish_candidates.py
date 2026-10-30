"""Upload metadata first, then one bounded package bundle at a time."""
from pathlib import Path
import os
import json
from contextlib import nullcontext
from container_artifacts import stream, member_name, inventory, HashReader
import shutil
import subprocess
import tarfile

from reclaim_bundles import reclaim


def publish(build, repository, run_id, attempt, bundle_limit=512*1024**2):
    build = Path(build)
    artifacts = build / 'candidate/artifacts'
    metadata = sorted([*build.glob('*.log'), *build.glob('*.json')])
    if artifacts.exists():
        metadata += sorted(p for p in artifacts.iterdir() if p.suffix in ('.json', '.log'))
    debs = sorted(artifacts.glob('*.deb'))
    marker=build/'candidate/stream-artifacts.json'
    expected=inventory(artifacts/'inventory.json') if marker.exists() else None
    container=json.loads(marker.read_text())['container'] if expected is not None else None
    upload = build / 'release-upload'
    upload.mkdir()
    # Original metadata and Debian files stay intact, including on upload error.
    paths = []
    for index, source in enumerate(metadata):
        target = upload / f'{index:04d}-{source.name}'
        os.link(source, target)
        paths.append(target)
    tag = None
    used = 0
    release_number = 0

    def create(files):
        nonlocal tag, used, release_number
        tag = f'candidate-{run_id}-{attempt}-{release_number}'
        release_number += 1
        subprocess.run(['gh', 'release', 'create', tag, *map(str, files), '--repo', repository,
            '--title', tag, '--notes', 'Unsigned source-build candidates and diagnostics. Not an approved app or APT release.',
            '--prerelease', '--latest=false'], check=True)
        used = len(files)

    for start in range(0, max(1, len(paths)), 850):
        create(paths[start:start+850])

    def send_bundle(path):
        nonlocal used
        if used == 850:
            create([])
        link = upload / f'{len(paths)+number:04d}-{path.name}'
        os.link(path, link)
        subprocess.run(['gh', 'release', 'upload', tag, str(link), '--repo', repository], check=True)
        used += 1
        # Remote upload succeeded; reclaim only this tar and its hard link.
        reclaim(build, [path])

    number = 0
    archive = None
    size = 0
    try:
        with stream(container) if container else nullcontext(None) as source_archive:
            entries=source_archive if container else debs
            seen=set()
            for deb in entries:
                if container:
                    name=member_name(deb)
                    if name is None or not name.endswith('.deb'):
                        continue
                    if name not in expected or name in seen:
                        raise ValueError('Unexpected or duplicate streamed archive')
                    seen.add(name)
                    length=deb.size
                else:
                    name=deb.name;length=deb.stat().st_size
                if archive is not None and size + length > bundle_limit:
                    archive.close()
                    archive = None
                    send_bundle(target)
                if archive is None:
                    target = build / f'packages-{number:04d}.tar'
                    number += 1
                    archive = tarfile.open(target, 'x')
                    size = 0
                # Retain scratch for the runner and its checkpoint exporter. This
                # does not relax the separate 16GiB compilation reserve.
                if shutil.disk_usage(build).free < 2*1024**3 + length + 1024**2:
                    raise ValueError('Insufficient scratch for bounded candidate publication')
                if container:
                    reader=HashReader(source_archive.extractfile(deb))
                    member=tarfile.TarInfo(name);member.size=length
                    archive.addfile(member,reader)
                    if reader.hash.hexdigest()!=expected[name]:
                        raise ValueError('Streamed archive SHA256 mismatch: '+name)
                else:
                    archive.add(deb, arcname=name, recursive=False)
                size += length
            if container and seen!=set(expected):
                raise ValueError('Stream omitted inventoried archives')
        if archive is not None:
            archive.close()
            archive = None
            send_bundle(target)
    finally:
        if archive is not None:
            archive.close()


if __name__ == '__main__':
    publish(Path('build'), os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'])
