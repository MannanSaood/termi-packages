import unittest

import catalog_repairs


class FloatingHeadersTest(unittest.TestCase):
    def test_single_scoped_header_order_repair_preserves_recipe(self):
        for recipe in ('osm2pgsql', 'libprotobuf-c', 'libvigra', 'xerces-c', 'gdal', 'lnav', 'libpinyin', 'lensfun', 'darktable', 'rawtherapee', 'libdevil', 'dosbox-x', 'xmoto', 'llama-cpp'):
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
        observed = []

        def hook(text, name, body):
            observed.append((text, name, body))
            return text + name + '() {\n' + body + '}\n'

        def change(name, transform, tree='packages'):
            if name == recipe:
                result = transform(source)
                self.assertIn('TERMUX_PKG_DEPENDS="boost, libc++, proj"\n', result)
                self.assertIn('TERMUX_PKG_EXTRA_CONFIGURE_ARGS="-DEXTERNAL_FMT=OFF"\n', result)
                prepared_source = source + ('\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot, zstd"\n' if recipe == 'xerces-c' else '\nTERMUX_PKG_BUILD_DEPENDS="ndk-sysroot"\n' if recipe in {'lnav', 'libpinyin', 'lensfun', 'libdevil', 'dosbox-x', 'xmoto'} else '')
                if recipe == 'rawtherapee':
                    prepared_source += '\nTERMUX_PKG_BUILD_DEPENDS="libdeflate, libxres"\n'
                elif recipe == 'darktable':
                    prepared_source = source.replace('="libllvm-static"', '="libdeflate, libxres, libllvm-static"')
                elif recipe == 'llama-cpp':
                    prepared_source = source.replace('="ocl-icd,', '="ndk-sysroot, ocl-icd,')
                self.assertEqual(observed, [(prepared_source, 'termux_step_pre_configure',
                    '\tCXXFLAGS+=" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"\n')])
                self.assertNotIn('#define', result)
                raise Captured

        with self.assertRaises(Captured):
            catalog_repairs.apply(change, hook, lambda path: '')
