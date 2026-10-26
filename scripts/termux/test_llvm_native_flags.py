import unittest

from recipe_repairs import llvm_native_host_flags


class NativeHostFlagsTests(unittest.TestCase):
    def test_nested_build_gets_host_compilers_without_target_flags(self):
        anchor = '-DCROSS_TOOLCHAIN_FLAGS_LLVM_NATIVE=-DLLVM_NATIVE_TOOL_DIR=$TERMUX_PKG_HOSTBUILD_DIR/bin'
        target = '-DCMAKE_C_COMPILER=$CC\n-DCMAKE_CXX_FLAGS=$CXXFLAGS\n'
        result = llvm_native_host_flags(target + anchor + '\n')
        self.assertTrue(result.startswith(target))
        arguments = result.splitlines()[-1].split('=', 1)[1].split(';')
        self.assertIn('-DCMAKE_C_COMPILER=/usr/bin/gcc', arguments)
        self.assertIn('-DCMAKE_CXX_COMPILER=/usr/bin/g++', arguments)
        self.assertIn('-DCMAKE_ASM_COMPILER=/usr/bin/gcc', arguments)
        for name in ('C', 'CXX', 'ASM', 'EXE_LINKER', 'SHARED_LINKER', 'MODULE_LINKER'):
            self.assertIn('-DCMAKE_' + name + '_FLAGS=', arguments)

    def test_changed_upstream_fails_closed(self):
        with self.assertRaises(ValueError):
            llvm_native_host_flags('no native build anchor')


if __name__ == '__main__':
    unittest.main()
