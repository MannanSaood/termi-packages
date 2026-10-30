"""Read immutable stopped-container artifacts without copying the full pool."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


def member_name(member):
    path=PurePosixPath(member.name)
    if member.isdir() and str(path)=='.':
        return None
    if (path.is_absolute() or len(path.parts)!=1 or path.name in ('.','..')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]',path.name) or not member.isfile()):
        raise ValueError('Unsafe container artifact entry: '+member.name)
    return path.name


@contextmanager
def stream(container):
    if not re.fullmatch(r'[0-9a-f]{64}',container):
        raise ValueError('Invalid retained container ID')
    process=subprocess.Popen(['docker','cp',container+':/home/builder/artifacts/.','-'],stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
            yield archive
        # Drain padding before waiting, otherwise a full pipe can deadlock.
        while process.stdout.read(1024*1024):
            pass
        code=process.wait(timeout=60)
        if code:
            raise subprocess.CalledProcessError(code,process.args)
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def metadata(container,destination):
    destination=Path(destination);seen=set();total=0
    with stream(container) as archive:
        for member in archive:
            name=member_name(member)
            if name is None:
                continue
            if name.casefold() in seen:
                raise ValueError('Duplicate container artifact')
            seen.add(name.casefold())
            if name.endswith('.deb'):
                continue
            total+=member.size
            if member.size>256*1024**2 or total>512*1024**2:
                raise ValueError('Container metadata exceeds bounds')
            target=destination/name
            with target.open('xb') as out, archive.extractfile(member) as source:
                import shutil
                shutil.copyfileobj(source,out,1024*1024)


def inventory(path):
    expected={};folded=set()
    for package in json.loads(Path(path).read_text())['packages']:
        name=package['file'];pin=package['sha256'];member=tarfile.TarInfo(name)
        if (member_name(member)!=name or not name.endswith('.deb') or name.casefold() in folded
                or not re.fullmatch(r'[0-9a-f]{64}',pin)):
            raise ValueError('Invalid streamed package inventory')
        folded.add(name.casefold());expected[name]=pin
    if not expected:
        raise ValueError('Empty streamed package inventory')
    return expected


class HashReader:
    def __init__(self,source):
        self.source=source;self.hash=hashlib.sha256()
    def read(self,size=-1):
        body=self.source.read(size);self.hash.update(body);return body
