from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from catalog_repairs import PROJ_EPSILON_REPAIR


class ProjEpsilonTest(unittest.TestCase):
    source = '#include <float.h>\n#include <math.h>\nstatic const double eps_ = 0.01 * sqrt(DBL_EPSILON);\n'
    converter = '#include <limits>\nif ((exponent < DBL_MIN_EXP) || (exponent > DBL_MAX_EXP)) { errno = ERANGE; }\n'

    def converter_source(self, root, text=None):
        source = root / 'src/apps/proj_strtod.cpp'
        source.parent.mkdir(parents=True)
        source.write_text(self.converter if text is None else text)
        return source

    def repair(self, root):
        with patch.object(sys, 'argv', ['inject', str(root)]):
            exec(PROJ_EPSILON_REPAIR, {})

    def test_exact_double_threshold_is_retained_without_global_macro_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'src/projections/gnom.cpp'
            source.parent.mkdir(parents=True)
            source.write_text(self.source)
            converter = self.converter_source(root)
            self.repair(root)
            changed = source.read_text()
            self.assertEqual(self.source.replace('#include <math.h>', '#include <math.h>\n#include <limits>').replace(
                '0.01 * sqrt(DBL_EPSILON)', '0.01 * sqrt(std::numeric_limits<double>::epsilon())'), changed)
            self.assertNotIn('#define', changed)
            self.assertEqual(self.converter.replace('DBL_MIN_EXP', 'std::numeric_limits<double>::min_exponent').replace(
                'DBL_MAX_EXP', 'std::numeric_limits<double>::max_exponent'), converter.read_text())
            self.assertNotIn('exponent10', converter.read_text())
            with self.assertRaises(AssertionError):
                self.repair(root)

    def test_changed_threshold_or_header_fails_closed_without_modifying_source(self):
        for text in [self.source.replace('0.01', '0.02'), self.source.replace('math.h', 'cmath'),
                     self.source + 'double another = DBL_EPSILON;\n']:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'src/projections/gnom.cpp'
                source.parent.mkdir(parents=True)
                source.write_text(text)
                self.converter_source(root)
                with self.assertRaises(AssertionError):
                    self.repair(root)
                self.assertEqual(text, source.read_text())

    def test_converter_bounds_drift_is_rejected(self):
        for text in [self.converter.replace('DBL_MIN_EXP', 'CHANGED'), self.converter.replace('<limits>', '<cmath>')]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'src/projections/gnom.cpp'
                source.parent.mkdir(parents=True)
                source.write_text(self.source)
                converter = self.converter_source(root, text)
                with self.assertRaises(AssertionError):
                    self.repair(root)
                self.assertEqual(text, converter.read_text())
