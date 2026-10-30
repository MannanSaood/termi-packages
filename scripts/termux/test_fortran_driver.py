import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from recipe_repairs import FORTRAN_DRIVER, FORTRAN_HOST_EXTRACTOR


BASH='C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else shutil.which('bash')


class FortranDriverTest(unittest.TestCase):
    @unittest.skipUnless(BASH, 'Bash required for host wrapper')
    def test_linker_is_explicit_and_static_openmp_follows_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);host=root/'host';toolchain=root/'ndk'
            (host/'bin').mkdir(parents=True);(toolchain/'bin').mkdir(parents=True)
            linker=toolchain/'bin/ld.lld';linker.write_bytes(b'fixture linker')
            omp=toolchain/'lib/clang/21/lib/linux/aarch64/libomp.a';omp.parent.mkdir(parents=True);omp.write_bytes(b'fixture archive')
            compiler=host/'bin/flang-new';compiler.write_text('#!/bin/bash\nprintf "%s\n" "$@"\n');compiler.chmod(0o755)
            wrapper=root/'driver'
            subprocess.run([sys.executable,'-c',FORTRAN_DRIVER,host.as_posix(),wrapper.as_posix(),toolchain.as_posix(),'aarch64-linux-android26','aarch64'],check=True)
            base=['--target=aarch64-linux-android26','--sysroot='+(toolchain/'sysroot').as_posix(),'-fuse-ld='+linker.as_posix()]
            def invoke(args):
                return subprocess.run([BASH,wrapper.as_posix(),*args],capture_output=True,text=True)
            compile_args=['-fPIC','-c','source with space.f90','-o','out.o']
            compiled=invoke(compile_args);self.assertEqual(0,compiled.returncode,compiled.stderr)
            self.assertEqual(base+compile_args,compiled.stdout.splitlines())
            args=['-L/prefix/lib','-fopenmp','-static-openmp','-Wl,--as-needed','out.o','-o','program']
            linked=invoke(args);self.assertEqual(0,linked.returncode,linked.stderr)
            self.assertEqual(base+[a for a in args if a!='-static-openmp']+[omp.as_posix()],linked.stdout.splitlines())
            omp.unlink();missing=invoke(args)
            self.assertEqual(2,missing.returncode)
            self.assertIn('Missing Android static OpenMP runtime',missing.stderr)
            self.assertEqual('',missing.stdout)
            linker.unlink()
            failed=subprocess.run([sys.executable,'-c',FORTRAN_DRIVER,host.as_posix(),wrapper.as_posix(),toolchain.as_posix(),'aarch64-linux-android26','aarch64'],capture_output=True)
            self.assertNotEqual(0,failed.returncode)

    def test_host_extraction_retains_driver_shared_modules_and_ndk_resources(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'host.tar.xz';name='LLVM-21.1.8-Linux-X64'
            kept=['bin/flang-new','bin/flang-21','lib/libLLVM.so.21.1','lib/clang/21/include/iso_fortran_env.mod','lib/clang/21/lib/linux/libclang_rt.builtins.a','include/flang/ISO_Fortran_binding.h','lib/cmake/llvm/LLVMConfig.cmake']
            omitted=['bin/clang','bin/llvm-opt','lib/libLLVMCore.a','lib/libclangCodeGen.a']
            with tarfile.open(archive,'w:xz') as t:
                for path in kept+omitted:
                    body=path.encode();m=tarfile.TarInfo(name+'/'+path);m.size=len(body);t.addfile(m,io.BytesIO(body))
            out=root/'out';out.mkdir()
            result=subprocess.run([sys.executable,'-c',FORTRAN_HOST_EXTRACTOR,str(archive),str(out),name],check=True,capture_output=True,text=True)
            self.assertIn('skipped_bytes',result.stdout)
            for path in kept:self.assertEqual(path.encode(),(out/name/path).read_bytes())
            for path in omitted:self.assertFalse((out/name/path).exists())
            # Input archive remains until the caller has verified extraction;
            # the recipe only then reclaims these disposable compressed inputs.
            self.assertTrue(archive.is_file())

    def test_host_extraction_rejects_namespace_escape(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'host.tar.xz';out=root/'out';out.mkdir()
            with tarfile.open(archive,'w:xz') as t:
                m=tarfile.TarInfo('LLVM-21.1.8-Linux-X64/../escape');m.size=1;t.addfile(m,io.BytesIO(b'x'))
            failed=subprocess.run([sys.executable,'-c',FORTRAN_HOST_EXTRACTOR,str(archive),str(out),'LLVM-21.1.8-Linux-X64'],capture_output=True)
            self.assertNotEqual(0,failed.returncode)
            self.assertFalse((root/'escape').exists())
