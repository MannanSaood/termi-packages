"""Audit own-source .pc provider closure without installing or executing packages."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import tarfile

from seed import compatibility, expand_bundles, pinned, selected_recipes

PREFIX = 'data/data/com.terminal.nextgen/files/usr/'
REQUIREMENT = re.compile(r'([A-Za-z0-9_+.\-]+)(?:\s*([<>=!]+)\s*([A-Za-z0-9_+.~:\-]+))?')


def requirements(text):
    variables, fields = {}, {}
    for line in text.replace('\\\n', '').splitlines():
        line = line.split('#', 1)[0].strip()
        variable = re.fullmatch(r'([A-Za-z0-9_]+)\s*=\s*(.*)', line)
        field = re.fullmatch(r'([A-Za-z][A-Za-z.]*):\s*(.*)', line)
        if variable:
            variables[variable[1]] = variable[2]
        elif field:
            fields[field[1]] = field[2]
    result = set()
    for key in ('Requires', 'Requires.private'):
        value = fields.get(key, '')
        for _ in range(32):
            updated = re.sub(r'\$\{([^}]+)\}', lambda m: variables.get(m[1], m[0]), value)
            if updated == value:
                break
            value = updated
        if '${' in value:
            raise ValueError('Unresolved pkg-config requirement variable: ' + value)
        while value.strip(' ,\t'):
            value = value.lstrip(' ,\t')
            match = REQUIREMENT.match(value)
            if not match or (match.end() < len(value) and value[match.end()] not in ' ,\t'):
                raise ValueError('Unrecognized pkg-config requirement: ' + value)
            result.add(match[1])
            value = value[match.end():]
    return sorted(result)


def archive_metadata(path, record):
    """Read bounded metadata through Linux dpkg; never extract payload paths."""
    entries, size = [], 0
    with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(path)], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                for member in archive:
                    name = member.name.removeprefix('./').lstrip('/')
                    if not name.startswith(PREFIX) or not name.endswith('.pc'):
                        continue
                    if '..' in PurePosixPath(name).parts:
                        raise ValueError('Unsafe pkg-config payload path')
                    entry = dict(path=name, recipe=record['recipe'], archive=record['file'],
                                 archive_sha256=record['sha256'])
                    if member.isfile():
                        size += member.size
                        if member.size > 256 * 1024 or size > 8 * 1024**2:
                            raise ValueError('Package metadata exceeds bound')
                        raw = archive.extractfile(member).read()
                        entry.update(text=raw.decode('utf-8'), sha256=hashlib.sha256(raw).hexdigest())
                    elif member.issym() or member.islnk():
                        target = member.linkname
                        if member.issym() and not target.startswith('/'):
                            target = posixpath.join(posixpath.dirname(name), target)
                        target = posixpath.normpath(target.lstrip('/').removeprefix('./'))
                        if not target.startswith(PREFIX):
                            raise ValueError('Pkg-config alias escapes Termi prefix')
                        entry['target'] = target
                    else:
                        continue
                    entries.append(entry)
            # Drain tar padding before waiting for dpkg to finish writing.
            while process.stdout.read(1024 * 1024):
                pass
            if process.wait() != 0:
                raise ValueError('Unable to read pinned Debian payload')
        except BaseException:
            process.kill()
            process.wait()
            raise
    return entries


def provider_graph(entries):
    paths = {}
    for entry in entries:
        paths.setdefault(entry['path'], []).append(entry)

    def resolve(path, seen):
        if path in seen or len(seen) >= 32:
            raise ValueError('Cyclic pkg-config alias')
        records = paths.get(path)
        if not records:
            raise ValueError('Missing pkg-config alias target: ' + path)
        values = []
        for record in records:
            if 'text' in record:
                values.append((record['text'], {record['recipe']}))
            else:
                text, owners = resolve(record['target'], seen | {path})
                values.append((text, owners | {record['recipe']}))
        if len({v[0] for v in values}) != 1:
            raise ValueError('Conflicting pkg-config payload path: ' + path)
        return values[0][0], set().union(*(v[1] for v in values))

    graph = {}
    for path, records in paths.items():
        if posixpath.dirname(path) not in (PREFIX + 'lib/pkgconfig', PREFIX + 'share/pkgconfig'):
            continue
        text, owners = resolve(path, set())
        name = PurePosixPath(path).stem
        node = dict(recipes=sorted(owners), requires=requirements(text),
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    sources=[{k: v for k, v in r.items() if k != 'text'} for r in records])
        if name in graph:
            if graph[name]['text_sha256'] != node['text_sha256']:
                raise ValueError('Conflicting pkg-config provider name: ' + name)
            node['recipes'] = sorted(set(node['recipes']) | set(graph[name]['recipes']))
            node['sources'] += graph[name]['sources']
        graph[name] = node
    return graph


def closure(graph, recipes):
    """Find all known providers needed by metadata in the requested prefix."""
    owners, missing, visited = set(recipes), set(), set()
    pending = [n for n, r in graph.items() if owners.intersection(r['recipes'])]
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        if name not in graph:
            missing.add(name)
            continue
        node = graph[name]
        new = set(node['recipes']) - owners
        owners.update(new)
        pending.extend(node['requires'])
        if new:
            pending.extend(n for n, r in graph.items() if new.intersection(r['recipes']))
    return dict(recipes=sorted(owners), additional_recipes=sorted(owners - set(recipes)),
                missing_providers=sorted(missing), pkgconfig_names=sorted(visited))


def supplemented_closure(graph, plan, built, initial):
    selected = set(initial)
    for _ in range(len(built) + 1):
        report = closure(graph, selected)
        required = set(report['recipes'])
        if required:
            required.update(selected_recipes(plan, built, sorted(required)))
        if required == selected:
            report['additional_recipes'] = sorted(selected - set(initial))
            return report
        selected = required
    raise ValueError('Provider closure did not converge')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--inventory-sha256', required=True)
    parser.add_argument('--ledger-sha256', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recipes', nargs='+', required=True)
    args = parser.parse_args()
    pins = {'inventory.json': args.inventory_sha256, 'catalog-ledger.json': args.ledger_sha256,
            'catalog-plan.json': args.plan_sha256}
    data = {name: json.loads(pinned(args.raw, name, pin).read_text()) for name, pin in pins.items()}
    inventory, ledger, plan = [data[n] for n in pins]
    built = compatibility(plan, plan, ledger)[0]
    if built != {r['recipe'] for r in inventory['packages']}:
        raise ValueError('Completed seed recipe inventory differs')
    expand_bundles(args.raw, inventory)
    entries = []
    for index, record in enumerate(inventory['packages']):
        path = pinned(args.raw, record['file'], record['sha256'])
        entries += archive_metadata(path, record)
        if sum(len(r.get('text', '')) for r in entries) > 64 * 1024**2:
            raise ValueError('Total pkg-config metadata exceeds bound')
        if index % 200 == 0:
            print('Verified package metadata', index, flush=True)
    graph = provider_graph(entries)
    reports = {}
    for root in args.recipes:
        initial = selected_recipes(plan, built, [root])
        reports[root] = supplemented_closure(graph, plan, built, initial)
        reports[root]['initial_recipes'] = sorted(initial)
    result = dict(schema=1, source_pins=pins, verified_archives=len(inventory['packages']),
                  verified_recipes=len(built), providers=graph, requested=reports,
                  approved=False, scope='build-pkgconfig-metadata-only')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({n: {k: r[k] for k in ('additional_recipes', 'missing_providers')}
                      for n, r in reports.items()}), flush=True)


if __name__ == '__main__':
    main()
