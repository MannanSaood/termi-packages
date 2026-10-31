import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import WESTON_MEMFD_PATCH


class WestonMemfdTest(unittest.TestCase):
    paths=['shared/client-buffer-util.c','libweston/backend-pipewire/pipewire.c']
    shim='''#if defined(__ANDROID__) && __ANDROID_API__ < 26
#include <sys/syscall.h>
#define memfd_create(name, flags) syscall(SYS_memfd_create, name, flags)
#endif
'''

    def apply(self,root):
        return subprocess.run([sys.executable,'-c',WESTON_MEMFD_PATCH,str(root)],capture_output=True,text=True)

    def populate(self,root):
        for name in self.paths:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(self.shim)

    def test_both_existing_shims_only_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.populate(root);result=self.apply(root)
            self.assertEqual(0,result.returncode,result.stderr)
            for name in self.paths:
                self.assertEqual(self.shim.replace('< 26','< 30'),(root/name).read_text())
            self.assertNotEqual(0,self.apply(root).returncode)
            self.populate(root);(root/self.paths[0]).write_text(self.shim.replace('< 26','< 25'))
            self.assertNotEqual(0,self.apply(root).returncode)

    @unittest.skipUnless(shutil.which('cc') and sys.platform.startswith('linux'),'Linux C compiler unavailable')
    def test_real_memfd_mapping_and_cloexec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.populate(root);self.assertEqual(0,self.apply(root).returncode)
            source=root/'probe.c';source.write_text('''#define _GNU_SOURCE
#define __ANDROID__ 1
#define __ANDROID_API__ 26
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <assert.h>
#include <string.h>
'''+(root/self.paths[1]).read_text()+'''
int main(void) {
    int fd=memfd_create("weston-pipewire",MFD_CLOEXEC);
    assert(fd>=0);
    assert((fcntl(fd,F_GETFD)&FD_CLOEXEC)!=0);
    assert(ftruncate(fd,4096)==0);
    char *map=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    assert(map!=MAP_FAILED);
    memcpy(map,"weston",7);
    char buffer[7]; assert(pread(fd,buffer,7,0)==7);
    assert(memcmp(buffer,"weston",7)==0);
    assert(munmap(map,4096)==0);
    assert(close(fd)==0);
    return 0;
}
''');binary=root/'probe'
            result=subprocess.run(['cc','-std=gnu11','-Wall','-Werror',str(source),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            # A host policy can deny this syscall; do not treat denial as a pass.
            self.assertEqual(0,result.returncode,result.stderr)


if __name__=='__main__':
    unittest.main()
