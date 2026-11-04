import subprocess
import unittest
from recipe_repairs import revisioned

class RevisionTests(unittest.TestCase):
    def evaluate(self, recipe):
        return subprocess.check_output(['bash', '-c', recipe + '\nprintf "%s\\n" "${TERMUX_PKG_VERSION[@]}" "$TERMUX_PKG_REVISION" "${TERMUX_PKG_SRCURL[@]}"'], text=True).splitlines()

    def test_multiline_versions_keep_source_urls(self):
        recipe = 'TERMUX_PKG_VERSION=(\n 12.2\n 8.1.3.1\n)\nTERMUX_PKG_SRCURL=("v${TERMUX_PKG_VERSION[0]}" "v${TERMUX_PKG_VERSION[1]%.*}-${TERMUX_PKG_VERSION[1]##*.}")\n'
        self.assertEqual(self.evaluate(revisioned(recipe)), ['12.2', '8.1.3.1', '1', 'v12.2', 'v8.1.3-1'])
        self.assertNotIn('TERMUX_PKG_VERSION=(\nTERMUX_PKG_REVISION', revisioned(recipe))

    def test_scalar_and_existing_revision(self):
        self.assertEqual(revisioned('TERMUX_PKG_VERSION="1.2"\n'), 'TERMUX_PKG_VERSION="1.2"\nTERMUX_PKG_REVISION=1\n')
        self.assertEqual(revisioned('TERMUX_PKG_VERSION=(1 2)\nTERMUX_PKG_REVISION=4\n'), 'TERMUX_PKG_VERSION=(1 2)\nTERMUX_PKG_REVISION=5\n')

    def test_missing_version_fails_closed(self):
        with self.assertRaises(ValueError):
            revisioned('TERMUX_PKG_DESCRIPTION="missing"\n')

if __name__ == '__main__':
    unittest.main()
