import unittest

import catalog_repairs


class FloatingHeadersTest(unittest.TestCase):
    def test_single_scoped_header_order_repair_preserves_recipe(self):
        for recipe in ('osm2pgsql', 'libprotobuf-c', 'libvigra', 'xerces-c', 'gdal', 'lnav', 'libpinyin', 'lensfun', 'darktable', 'rawtherapee', 'libdevil', 'dosbox-x', 'xmoto', 'llama-cpp', 'codon', 'steghide', 'taskwarrior', 'pkgfile', 'glmark2', 'mangohud', 'krfb', 'okular'):
            with self.subTest(recipe=recipe):
                self.check_recipe(recipe)

    def check_recipe(self, recipe):
        # Stop after this recipe's real callback, before unrelated repairs.
        class Captured(Exception):
            pass

        source = 'TERMUX_PKG_DEPENDS="boost, libc++, proj"\nTERMUX_PKG_EXTRA_CONFIGURE_ARGS="-DEXTERNAL_FMT=OFF"\n'
        if recipe == 'darktable':
            source += 'TERMUX_PKG_BUILD_DEPENDS="libllvm-static"\n'
        if recipe == 'llama-cpp':
            source += 'TERMUX_PKG_BUILD_DEPENDS="ocl-icd, opencl-headers, spirv-headers, vulkan-headers"\n'
        if recipe == 'mangohud':
            source += 'TERMUX_PKG_BUILD_DEPENDS="dbus, libandroid-wordexp, nlohmann-json"\n'
        kde_deps = {
            'krfb': 'extra-cmake-modules, kf6-kdoctools, libxdamage, plasma-wayland-protocols',
            'okular': 'ebook-tools, extra-cmake-modules, kdegraphics-mobipocket',
        }
        if recipe in kde_deps:
            source += 'TERMUX_PKG_BUILD_DEPENDS="' + kde_deps[recipe] + '"\n'
        observed = []

        def hook(text, name, body):
            observed.append((text, name, body))
            return text + name + '() {\n' + body + '}\n'

        def change(name, transform, tree='packages'):
            if name == recipe:
                result = transform(source)
                self.assertIn('TERMUX_PKG_DEPENDS="boost, libc++, proj"\n', result)
                self.assertIn('TERMUX_PKG_EXTRA_CONFIGURE_ARGS="-DEXTERNAL_FMT=OFF"\n', result)
                prepared_source = source + ('\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, zstd"\n' if recipe == 'xerces-c' else '\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot"\n' if recipe in {'lnav', 'libpinyin', 'lensfun', 'libdevil', 'dosbox-x', 'xmoto', 'codon', 'steghide', 'taskwarrior', 'pkgfile', 'glmark2'} else '')
                if recipe == 'rawtherapee':
                    prepared_source += '\nTERMUX_PKG_BUILD_DEPENDS="libdeflate, libxres"\n'
                elif recipe == 'darktable':
                    prepared_source = source.replace('="libllvm-static"', '="libdeflate, libxres, libllvm-static"')
                elif recipe == 'llama-cpp':
                    prepared_source = source.replace('="ocl-icd,', '="ndk-sysroot, ocl-icd,')
                elif recipe == 'mangohud':
                    prepared_source = source.replace('="dbus,', '="ndk-sysroot, dbus,')
                elif recipe in kde_deps:
                    prepared_source = source.replace('="' + kde_deps[recipe] + '"', '="ndk-sysroot, ' + kde_deps[recipe] + '"')
                self.assertEqual(observed, [(prepared_source, 'termux_step_pre_configure',
                    '\tCXXFLAGS+=" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"\n' + (catalog_repairs.LLAMA_VULKAN_SETUP if recipe == 'llama-cpp' else catalog_repairs.STEGHIDE_FLAGS_SETUP if recipe == 'steghide' else ''))])
                self.assertNotIn('#define', result)
                raise Captured

        with self.assertRaises(Captured):
            catalog_repairs.apply(change, hook, lambda path: '')
