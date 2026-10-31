import unittest

import catalog_repairs


class Osm2pgsqlHeadersTest(unittest.TestCase):
    def test_single_scoped_header_order_repair_preserves_recipe(self):
        # Stop after this recipe's real callback, before unrelated repairs.
        class Captured(Exception):
            pass

        source = 'TERMUX_PKG_DEPENDS="boost, libc++, proj"\nTERMUX_PKG_EXTRA_CONFIGURE_ARGS="-DEXTERNAL_FMT=OFF"\n'
        observed = []

        def hook(text, name, body):
            observed.append((text, name, body))
            return text + name + '() {\n' + body + '}\n'

        def change(name, transform):
            if name == 'osm2pgsql':
                result = transform(source)
                self.assertTrue(result.startswith(source))
                self.assertEqual(observed, [(source, 'termux_step_pre_configure',
                    '\tCXXFLAGS+=" -nostdinc++ -I$TERMUX_PREFIX/include/c++/v1"\n')])
                self.assertNotIn('#define', result)
                raise Captured

        with self.assertRaises(Captured):
            catalog_repairs.apply(change, hook, lambda path: '')
