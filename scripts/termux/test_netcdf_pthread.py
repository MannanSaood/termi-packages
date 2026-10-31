from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import NETCDF_PTHREAD_PATCH


class NetcdfPthreadTest(unittest.TestCase):
    source = '''#if 0
#include <pthread.h>            /* link with -lpthread */
#endif
'''

    def patch(self,path):
        return subprocess.run([sys.executable,'-c',NETCDF_PTHREAD_PATCH,str(path)],capture_output=True,text=True)

    def test_exact_include_only_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'crc.c';path.write_text(self.source)
            result=self.patch(path);self.assertEqual(0,result.returncode,result.stderr)
            self.assertIn('#include <pthread.h>',path.read_text())
            self.assertNotIn('#if 0',path.read_text())
            self.assertNotEqual(0,self.patch(path).returncode)
            path.write_text(self.source.replace('#if 0','#if UNKNOWN'))
            self.assertNotEqual(0,self.patch(path).returncode)

    @unittest.skipUnless(shutil.which('cc'),'host C compiler unavailable')
    def test_real_pthread_once_initializes_once_under_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'crc.c';path.write_text(self.source)
            self.assertEqual(0,self.patch(path).returncode)
            # Preserve the upstream pthread ONCE branch, with a countable init
            # callback, to check the include doesn't select the unsafe fallback.
            path.write_text(path.read_text()+'''#include <assert.h>
static int initialized;
static void init(void) { ++initialized; }
static void *worker(void *unused) {
    (void)unused;
    do {
        static pthread_once_t once = PTHREAD_ONCE_INIT;
        pthread_once(&once, init);
    } while (0);
    return 0;
}
int main(void) {
    pthread_t workers[32];
    for(int i=0;i<32;++i) assert(pthread_create(&workers[i],0,worker,0)==0);
    for(int i=0;i<32;++i) assert(pthread_join(workers[i],0)==0);
    assert(initialized==1);
    return 0;
}
''')
            binary=Path(tmp)/'probe';result=subprocess.run(['cc','-std=gnu11','-Wall','-Werror','-pthread',str(path),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            subprocess.run([str(binary)],check=True)


if __name__=='__main__':
    unittest.main()
