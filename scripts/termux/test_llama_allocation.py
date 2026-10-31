from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import LLAMA_VULKAN_ALLOCATION_PATCH


class LlamaAllocationTest(unittest.TestCase):
    # Exact private helpers from the pinned llama.cpp 0.7.0 Vulkan source.
    source = '''static void * portable_aligned_malloc(size_t align, size_t size) {
#ifdef _WIN32
    return _aligned_malloc(size, align);
#else
    return std::aligned_alloc(align, size);
#endif
}

static void portable_aligned_free(void * ptr) {
#ifdef _WIN32
    _aligned_free(ptr);
#else
    std::free(ptr);
#endif
}
'''

    def patch(self, path):
        return subprocess.run([sys.executable, '-c', LLAMA_VULKAN_ALLOCATION_PATCH,
                               str(path)], capture_output=True, text=True)

    def test_drift_and_reapplication_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'buffers.cpp'
            for changed in [self.source.replace('std::aligned_alloc', 'changed'),
                            self.source.replace('std::free(ptr)', 'changed(ptr)')]:
                path.write_text(changed)
                self.assertNotEqual(0, self.patch(path).returncode)
            path.write_text(self.source)
            self.assertEqual(0, self.patch(path).returncode)
            self.assertNotEqual(0, self.patch(path).returncode)

    @unittest.skipUnless(shutil.which('c++'), 'host C++ compiler unavailable')
    def test_alignment_failure_and_existing_platform_branches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'buffers.cpp'
            path.write_text(self.source)
            result = self.patch(path)
            self.assertEqual(0, result.returncode, result.stderr)
            body = path.read_text()
            prefix = '''#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cerrno>
#if defined(__ANDROID__) && __ANDROID_API__ < 28
static bool fail_alloc;
static unsigned calls;
static int checked_posix_memalign(void **ptr, size_t align, size_t size) {
    ++calls;
    if (fail_alloc) return ENOMEM;
    return posix_memalign(ptr, align, size);
}
#define posix_memalign checked_posix_memalign
#endif
'''
            main = '''
#undef posix_memalign
int main() {
    for (size_t align : {size_t(8), size_t(64), size_t(4096)}) {
        for (size_t blocks : {size_t(1), size_t(3), size_t(17)}) {
            size_t size = align * blocks;
            void *ptr = portable_aligned_malloc(align, size);
            assert(ptr && reinterpret_cast<uintptr_t>(ptr) % align == 0);
            std::memset(ptr, 0x5a, size);
            portable_aligned_free(ptr);
        }
    }
    portable_aligned_free(nullptr);
#if defined(__ANDROID__) && __ANDROID_API__ < 28
    assert(calls == 9);
    fail_alloc = true;
    assert(portable_aligned_malloc(64, 64) == nullptr);
    fail_alloc = false;
    assert(portable_aligned_malloc(3, 64) == nullptr);
#endif
}
'''
            path.write_text('#include <initializer_list>\n' + prefix + body + main)
            # Native memory tests simulate the preprocessor branches only;
            # they do not claim Android or Vulkan device execution.
            for api in [None, 26, 28]:
                with self.subTest(api=api):
                    exe = root / ('probe-' + str(api))
                    flags = [] if api is None else ['-D__ANDROID__',
                                                    '-D__ANDROID_API__=' + str(api)]
                    result = subprocess.run(['c++', '-std=c++17', *flags, str(path),
                                             '-o', str(exe)], capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                    result = subprocess.run([str(exe)], capture_output=True, text=True)
                    self.assertEqual(0, result.returncode, result.stderr)
