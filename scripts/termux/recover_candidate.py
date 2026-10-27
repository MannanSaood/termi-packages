"""Recover only completed artifacts from an explicitly pinned own checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

from parallel_catalog import merge
from seed import digest


class VerifiedParts:
    def __init__(self, records, fetch):
        if not 1 <= len(records) <= 256:
            raise ValueError('Invalid part count')
        self.records, self.fetch, self.index = records, fetch, 0
        self.stream = self.path = None

    def read(self, size):
        if size < 0:
            raise ValueError('Bounded reads required')
        while True:
            if self.stream:
                data = self.stream.read(size)
                if data:
                    return data
                self.stream.close()
                self.path.unlink()
                self.stream = None
            if self.index == len(self.records):
                return b''
            record = self.records[self.index]
            if record['file'] != f'checkpoint-{self.index:04d}.gz.part' or not 0 < record['bytes'] <= 1024**3:
                raise ValueError('Invalid checkpoint part')
            self.path = self.fetch(record['file'])
            if self.path.stat().st_size != record['bytes'] or digest(self.path) != record['sha256']:
                raise ValueError('Checkpoint part hash mismatch')
            self.stream = self.path.open('rb')
            self.index += 1


def extract_artifacts(stream, output):
    output.mkdir(parents=True, exist_ok=False)
    total = 0
    with tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if parts[:3] != ('home', 'builder', 'artifacts'):
                continue
            if len(parts) != 4 or parts[3] in ('.', '..'):
                continue
            if not parts[3].endswith(('.json', '.deb')):
                continue
            if not member.isfile() or member.size < 0:
                raise ValueError('Artifact must be a regular file')
            total += member.size
            if total > 32 * 1024**3:
                raise ValueError('Artifact size budget exceeded')
            with archive.extractfile(member) as source, (output / parts[3]).open('xb') as target:
                shutil.copyfileobj(source, target, 1024**2)
    # Verify even parts following the tar end marker before publishing anything.
    while stream.read(1024**2):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    repo = 'MannanSaood/termi-packages'
    if not re.fullmatch(r'checkpoint-[0-9]+-[0-9]+', spec['tag']) or not re.fullmatch(r'candidate-[0-9]+-[0-9]+-0', args.tag):
        raise ValueError('Invalid own release tag')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        def fetch(name):
            subprocess.run(['gh', 'release', 'download', spec['tag'], '--repo', repo, '--pattern', name, '--dir', str(tmp)], check=True)
            return tmp / name
        manifest = fetch('checkpoint.json')
        if digest(manifest) != spec['manifest_sha256']:
            raise ValueError('Checkpoint manifest hash mismatch')
        data = json.loads(manifest.read_text())
        if data['schema'] != 1 or data['input_identity'] != spec['input_identity']:
            raise ValueError('Checkpoint identity mismatch')
        source = Path('build/recovered')
        extract_artifacts(VerifiedParts(data['parts'], fetch), source)
    output = Path('build/verified')
    _, inventory = merge([[str(source), digest(source/'inventory.json'), digest(source/'catalog-ledger.json'), digest(source/'catalog-plan.json')]], output)
    # Only this disposable job's verified input copy; remote checkpoint retained.
    shutil.rmtree(source)
    bundles = []
    archive = None
    size = 0
    try:
        for record in inventory['packages']:
            path = output / record['file']
            if archive is None or size + path.stat().st_size > 512*1024**2:
                if archive:
                    archive.close()
                bundle = output / f'packages-{len(bundles):04d}.tar'
                bundles.append(bundle)
                archive = tarfile.open(bundle, 'w')
                size = 0
            archive.add(path, arcname=path.name, recursive=False)
            size += path.stat().st_size
    finally:
        if archive:
            archive.close()
    files = [output/name for name in ('inventory.json', 'catalog-ledger.json', 'catalog-plan.json')] + bundles
    subprocess.run(['gh', 'release', 'create', args.tag, *map(str, files), '--repo', repo, '--prerelease', '--latest=false', '--title', args.tag, '--notes', 'Recovered hash-verified Termi source candidates. Unsigned; not device verified.'], check=True)
    print(json.dumps({name: digest(output/name) for name in ('inventory.json', 'catalog-ledger.json', 'catalog-plan.json')}), flush=True)


if __name__ == '__main__':
    main()
