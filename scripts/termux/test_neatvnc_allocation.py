from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import NEATVNC_ALLOCATION_PATCH


class NeatvncAllocationTest(unittest.TestCase):
    # The pinned 1.0.3 constructor's allocation and cleanup contract.
    source = '''#define _GNU_SOURCE
#include <stdlib.h>
#include <stdint.h>
struct nvnc_buffer { int ref, type; void *addr; };
struct nvnc_buffer *nvnc_buffer_new(size_t size) {
\tstruct nvnc_buffer* buffer = calloc(1, sizeof(*buffer));
\tif (!buffer) return NULL;
\tbuffer->ref = 1;
\tbuffer->type = 1;
\tsize_t alignment = sizeof(void*);
\tsize_t aligned_size = ((size + alignment - 1) / alignment) * alignment;
\tbuffer->addr = aligned_alloc(alignment, aligned_size);
\tif (!buffer->addr) {
\t\tfree(buffer);
\t\treturn NULL;
\t}
\treturn buffer;
}
'''

    def patch(self, path):
        return subprocess.run([sys.executable, '-c', NEATVNC_ALLOCATION_PATCH, str(path)],
                              capture_output=True, text=True)

    def test_drift_and_reapplication_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'buffer.c'
            path.write_text(self.source.replace('aligned_size);', 'changed_size);'))
            self.assertNotEqual(0, self.patch(path).returncode)
            path.write_text(self.source)
            self.assertEqual(0, self.patch(path).returncode)
            self.assertNotEqual(0, self.patch(path).returncode)

    @unittest.skipUnless(shutil.which('cc'), 'host C compiler unavailable')
    def test_alignment_rounded_size_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'buffer.c'
            path.write_text(self.source)
            result = self.patch(path)
            self.assertEqual(0, result.returncode, result.stderr)
            # Exercise the constructor with real aligned memory, then inject
            # failures in each allocator. No Android execution is claimed.
            body = path.read_text()
            prefix = '''#define _GNU_SOURCE
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <assert.h>
static int fail_buffer, fail_aligned, frees;
static size_t requested_size;
static void *checked_calloc(size_t a, size_t b) {
    if (fail_buffer) return NULL;
    return calloc(a,b);
}
static void checked_free(void *p) { ++frees; free(p); }
static int checked_aligned(void **p, size_t alignment, size_t size) {
    requested_size=size;
    if (fail_aligned) return ENOMEM;
    return posix_memalign(p,alignment,size);
}
#define calloc checked_calloc
#define free checked_free
#define posix_memalign checked_aligned
'''
            body += '''
#undef calloc
#undef free
#undef posix_memalign
int main(void) {
    size_t sizes[]={0,1,7,8,9,4097};
    for (size_t i=0;i<sizeof(sizes)/sizeof(sizes[0]);++i) {
        struct nvnc_buffer *b=nvnc_buffer_new(sizes[i]);
        assert(b && b->ref==1 && b->type==1);
        assert((uintptr_t)b->addr % sizeof(void*)==0);
        assert(requested_size>=sizes[i] && requested_size%sizeof(void*)==0);
        free(b->addr); free(b);
    }
    fail_aligned=1; errno=0; frees=0;
    assert(nvnc_buffer_new(9)==NULL && errno==ENOMEM && frees==1);
    fail_buffer=1; frees=0;
    assert(nvnc_buffer_new(9)==NULL && frees==0);
    return 0;
}
'''
            path.write_text(prefix + body)
            binary=Path(tmp)/'probe'
            result=subprocess.run(['cc','-std=gnu11','-Wall','-Werror',str(path),'-o',str(binary)], capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            subprocess.run([str(binary)],check=True)


if __name__ == '__main__':
    unittest.main()
