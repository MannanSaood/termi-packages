import unittest

import catalog_repairs


class ApacheSemaphoreTest(unittest.TestCase):
    source = ('TERMUX_PKG_DEPENDS="apr, apr-util, libandroid-support, libcrypt"\n'
              'TERMUX_PKG_EXTRA_CONFIGURE_ARGS="--enable-modules=all"\n'
              'termux_step_pre_configure() {\n\tLDFLAGS="$LDFLAGS -lapr-1 -laprutil-1"\n}\n')

    def transform(self, text):
        class Captured(Exception):
            pass
        result = []
        def change(name, transform, tree='packages'):
            if name == 'apache2':
                result.append(transform(text))
                raise Captured
        with self.assertRaises(Captured):
            catalog_repairs.apply(change, lambda *args: '', lambda path: '')
        return result[0]

    def test_provider_is_a_runtime_dependency_and_retained_at_link(self):
        expected = self.source.replace('libandroid-support, ',
            'libandroid-support, libandroid-sysv-semaphore, ').replace('-laprutil-1"',
            '-laprutil-1 -Wl,--push-state,--no-as-needed -landroid-sysv-semaphore -Wl,--pop-state"')
        self.assertEqual(expected, self.transform(self.source))

    def test_changed_contracts_and_repeat_application_fail_closed(self):
        for text in [self.source.replace('-laprutil-1', '-lchanged'),
                     self.source.replace('apr, apr-util, ', ''), self.transform(self.source)]:
            with self.subTest(text=text), self.assertRaises(AssertionError):
                self.transform(text)
