import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pkgconfig_audit import (PREFIX, archive_metadata, closure, provider_graph, requirements,
                             supplemented_closure)


class MetadataTests(unittest.TestCase):
    def test_versions_continuations_and_private_variables(self):
        self.assertEqual(['bar', 'baz', 'foo'], requirements(
            'v=2.0\nRequires: foo >= ${v}, bar\\\n < 4.1\nRequires.private: baz = 1.3\n'))

    def test_unknown_requirement_variable_is_not_silently_dropped(self):
        with self.assertRaises(ValueError):
            requirements('Requires: foo >= ${undefined}\n')

    def test_malformed_requirement_is_rejected(self):
        with self.assertRaises(ValueError):
            requirements('Requires: foo; execute-this\n')

    def test_private_provider_closure_and_missing_names(self):
        graph = {'gtk': dict(recipes=['gtk3'], requires=['atspi']),
                 'atspi': dict(recipes=['at-spi2-core'], requires=['xres', 'unknown']),
                 'xres': dict(recipes=['libxres'], requires=[])}
        result = closure(graph, {'gtk3'})
        self.assertEqual(['at-spi2-core', 'libxres'], result['additional_recipes'])
        self.assertEqual(['unknown'], result['missing_providers'])

    def test_alias_keeps_both_recipe_owners(self):
        base = PREFIX + 'lib/pkgconfig/'
        graph = provider_graph([
            dict(path=base + 'foo.pc', target=base + 'foo-1.pc', recipe='foo-alias'),
            dict(path=base + 'foo-1.pc', text='Requires.private: bar\n', recipe='foo')])
        self.assertEqual(['foo', 'foo-alias'], graph['foo']['recipes'])
        self.assertEqual(['bar'], graph['foo']['requires'])

    def test_added_provider_also_imports_its_declared_and_metadata_dependencies(self):
        graph = {'gtk': dict(recipes=['gtk3'], requires=['xres']),
                 'xres': dict(recipes=['libxres'], requires=[]),
                 'x11': dict(recipes=['libx11'], requires=['xau']),
                 'xau': dict(recipes=['libxau'], requires=[])}
        plan = dict(recipes={'gtk3': dict(dependencies=[]),
                             'libxres': dict(dependencies=['libx11']),
                             'libx11': dict(dependencies=[]), 'libxau': dict(dependencies=[])})
        report = supplemented_closure(graph, plan, set(plan['recipes']), {'gtk3'})
        self.assertEqual(['libx11', 'libxau', 'libxres'], report['additional_recipes'])

    def test_alias_cycle_is_rejected(self):
        base = PREFIX + 'lib/pkgconfig/'
        with self.assertRaises(ValueError):
            provider_graph([dict(path=base + 'a.pc', target=base + 'b.pc', recipe='a'),
                            dict(path=base + 'b.pc', target=base + 'a.pc', recipe='b')])

    def test_conflicting_providers_are_not_arbitrarily_selected(self):
        path = PREFIX + 'lib/pkgconfig/foo.pc'
        with self.assertRaises(ValueError):
            provider_graph([dict(path=path, text='Version: 1\n', recipe='foo'),
                            dict(path=path, text='Version: 2\n', recipe='other')])

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Linux dpkg-deb unavailable')
    def test_real_deb_reads_metadata_and_alias_without_executing_scripts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / 'package'
            control = package / 'DEBIAN'
            control.mkdir(parents=True)
            (control / 'control').write_text('Package: own-test\nVersion: 1\nArchitecture: all\n'
                                           'Maintainer: Test\nDescription: Metadata fixture\n')
            marker = root / 'must-not-exist'
            script = control / 'postinst'
            script.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
            script.chmod(0o755)
            directory = package / PREFIX / 'lib/pkgconfig'
            directory.mkdir(parents=True)
            (directory / 'real.pc').write_text('Name: own\nVersion: 1\nRequires.private: bar\n')
            (directory / 'alias.pc').symlink_to('real.pc')
            archive = root / 'own.deb'
            subprocess.run(['dpkg-deb', '--build', str(package), str(archive)],
                           check=True, stdout=subprocess.DEVNULL)
            record = dict(recipe='own', file=archive.name,
                          sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
            graph = provider_graph(archive_metadata(archive, record))
            self.assertEqual(['bar'], graph['alias']['requires'])
            self.assertEqual(['own'], graph['real']['recipes'])
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
