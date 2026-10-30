import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from recipe_repairs import FORTRAN_DRIVER, FORTRAN_HOST_EXTRACTOR, FORTRAN_SOURCE_EXTRACTOR


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
            self.assertEqual(base+['-L'+(root/'runtime-build/flang-rt/lib').as_posix()]+[a for a in args if a!='-static-openmp']+[omp.as_posix(),'-Wl,--push-state,--no-as-needed','-landroid-execinfo','-Wl,--pop-state'],linked.stdout.splitlines())
            # Ordinary links need the backtrace DSO too, even without OpenMP.
            plain=invoke(['-Wl,--as-needed','out.o','-o','program'])
            self.assertEqual(base+['-L'+(root/'runtime-build/flang-rt/lib').as_posix(),'-Wl,--as-needed','out.o','-o','program',
                '-Wl,--push-state,--no-as-needed','-landroid-execinfo','-Wl,--pop-state'],plain.stdout.splitlines())
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

    def test_source_extraction_keeps_full_runtime_inputs_and_omits_unrelated_compilers(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'source.tar.xz';name='llvm-project-21.1.8.src'
            kept=['LICENSE.TXT','runtimes/CMakeLists.txt','flang-rt/CMakeLists.txt','flang-rt/lib/runtime/time-intrinsic.cpp','flang/lib/Common/Fortran.cpp','flang/include/flang/Runtime/header.h','llvm/cmake/modules/AddLLVM.cmake','llvm/include/llvm/Support/header.h','llvm/CMakeLists.txt','cmake/Modules/helper.cmake','third-party/benchmark/helper','compiler-rt/include/header.h','libcxx/include/vector']
            omitted=['clang/lib/AST/Decl.cpp','mlir/lib/IR/Value.cpp','lldb/source/Core.cpp','llvm/lib/CodeGen/Target.cpp','llvm/test/CodeGen/test.ll']
            with tarfile.open(archive,'w:xz') as t:
                for path in kept+omitted:
                    body=path.encode();m=tarfile.TarInfo(name+'/'+path);m.size=len(body);t.addfile(m,io.BytesIO(body))
            out=root/'out';out.mkdir()
            result=subprocess.run([sys.executable,'-c',FORTRAN_SOURCE_EXTRACTOR,str(archive),str(out),name],check=True,capture_output=True,text=True)
            self.assertIn('TERMI_FORTRAN_SOURCE_EXTRACTION',result.stdout)
            for path in kept:self.assertEqual(path.encode(),(out/name/path).read_bytes())
            for path in omitted:self.assertFalse((out/name/path).exists())
