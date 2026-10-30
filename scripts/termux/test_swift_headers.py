import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from recipe_repairs import swift_target_cxx_headers, SWIFT_ANDROID_STAT_MODULE

class SwiftHeadersTest(unittest.TestCase):
    def test_android_cpp_only(self):
        recipe = swift_target_cxx_headers("termux_step_make() {\n\t--install-swift-driver --install-sourcekit-lsp\n}")
        script = recipe.split("<<'TERMI_SWIFT'\n")[1].split("\nTERMI_SWIFT")[0]
        bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'impl'
            p.write_text('function swift_c_flags() { printf "common-%s" "$1"; }\nfunction common_swift_flags() { printf "original-swift-flags"; }\n' +
                         'flags=(-DCMAKE_C_FLAGS="$(swift_c_flags ${host})" -DCMAKE_CXX_FLAGS="$(swift_c_flags ${host}) ${cross_c_flags}")\n'+
                         ('swift_flags=-DCMAKE_Swift_FLAGS:STRING="$(common_swift_flags)"\n'*5))
            modulemap=(p.parent.parent/'stdlib/public/Platform/android.modulemap').as_posix()
            launcher=Path(tmp)/'launcher'
            subprocess.run([sys.executable,'-c',script,str(p),'/prefix',launcher.as_posix()],check=True)
            s=p.read_text()
            self.assertIn('-DCMAKE_CXX_FLAGS="$(termi_swift_cxx_flags ${host}) ${cross_c_flags}"',s)
            self.assertIn('-DCMAKE_C_FLAGS="$(swift_c_flags ${host})"',s)
            # BasicSwift belongs to the main Swift configure block, separate
            # from the five auxiliary projects' existing Swift flag sites.
            self.assertEqual(5,s.count('-DCMAKE_Swift_FLAGS:STRING="$(termi_swift_importer_flags ${host})"'))
            self.assertEqual(1,s.count('-DCMAKE_Swift_FLAGS:STRING="$(termi_swift_main_importer_flags ${host})"'))
            s=s.split('flags=')[0]
            p.write_text(s+'\nunset TERMUX_PREFIX\ntermi_swift_cxx_flags android-aarch64\nprintf "\\n"\ntermi_swift_cxx_flags linux-x86_64\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),['-nostdinc++ -I/prefix/include/c++/v1 -Wno-error=variadic-macro-arguments-omitted common-android-aarch64','common-linux-x86_64'])
            fake=Path(tmp)/'compiler';fake.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n');fake.chmod(0o755)
            out=subprocess.check_output([bash,str(launcher),fake.as_posix(),'-I/prefix/include','-Werror=gnu'],text=True)
            self.assertEqual(out.splitlines(),['-nostdinc++','-I/prefix/include/c++/v1','-I/prefix/include','-Werror=gnu','-Wno-error=variadic-macro-arguments-omitted','-Wno-error=gnu-include-next'])
            p.write_text(s+'\nunset TERMUX_PREFIX\ntermi_swift_importer_flags android-aarch64\nprintf "\\n"\ntermi_swift_importer_flags linux-x86_64\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),[f'-Xfrontend -strict-implicit-module-context -Xcc -nostdinc++ -Xcc -nostdlibinc -Xcc -I/prefix/include/c++/v1 -Xcc -isystem/prefix/include -Xcc -isystem/prefix/include/aarch64-linux-android -Xcc -fmodule-map-file={modulemap} original-swift-flags','original-swift-flags'])
            p.write_text(s+'\nunset TERMUX_PREFIX\ntermi_swift_main_importer_flags android-aarch64\nprintf "\\n"\ntermi_swift_main_importer_flags linux-x86_64\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),[f'-Xfrontend -strict-implicit-module-context -Xcc -nostdinc++ -Xcc -nostdlibinc -Xcc -I/prefix/include/c++/v1 -Xcc -isystem/prefix/include -Xcc -isystem/prefix/include/aarch64-linux-android -Xcc -fmodule-map-file={modulemap} '])
            p.write_text(s+'\nprintf "<%s>\\n" $(termi_swift_runtime_importer_option android-aarch64)\nprintf "HOST:<%s>\\n" "$(termi_swift_runtime_importer_option linux-x86_64)"\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),[f'<-DSWIFT_RUNTIME_SWIFT_COMPILE_FLAGS:STRING=-Xfrontend;-strict-implicit-module-context;-Xcc;-nostdinc++;-Xcc;-nostdlibinc;-Xcc;-I/prefix/include/c++/v1;-Xcc;-isystem/prefix/include;-Xcc;-isystem/prefix/include/aarch64-linux-android;-Xcc;-fmodule-map-file={modulemap}>','HOST:<>'])
            self.assertIn('termi_swift_cxx_launcher_option',s)

    def test_module_headers_share_prefix_but_resource_headers_stay_relative(self):
        script=SWIFT_ANDROID_STAT_MODULE.split("<<'TERMI_SWIFT_STAT_MODULE'\n")[1].split('\nTERMI_SWIFT_STAT_MODULE')[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefix=root/'prefix';(prefix/'include/sys').mkdir(parents=True)
            (prefix/'include/sys/stat.h').write_text('stat fixture')
            (prefix/'include/fcntl.h').write_text('fcntl fixture')
            path=prefix.as_posix();path=path[2:] if os.name=='nt' else path
            module=root/'android.modulemap'
            module.write_text('header "sys/stat.h"\nheader "fcntl.h"\nheader "SwiftAndroidNDK.h"\nheader "SwiftBionic.h"\nheader "missing.h"\n')
            subprocess.run([sys.executable,'-c',script,str(module),path],check=True)
            self.assertEqual(module.read_text(),f'header "{path}/include/sys/stat.h"\nheader "{path}/include/fcntl.h"\nheader "SwiftAndroidNDK.h"\nheader "SwiftBionic.h"\nheader "missing.h"\n')
    def test_source_drift(self):
        with self.assertRaises(ValueError): swift_target_cxx_headers('changed')

    @unittest.skipUnless(shutil.which('cmake'), 'CMake unavailable')
    def test_llbuild_matching_headers_precede_existing_cross_flags(self):
        recipe=swift_target_cxx_headers("termux_step_make() {\n\t--install-swift-driver --install-sourcekit-lsp\n}")
        script=recipe.split("<<'TERMI_SWIFT_LLBUILD_CXX'\n")[1].split('\nTERMI_SWIFT_LLBUILD_CXX')[0]
        anchor='project(llbuild LANGUAGES CXX)'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'CMakeLists.txt';p.write_text(anchor+'\noption(BUILD_TESTING "Build tests" ON)\n')
            subprocess.run([sys.executable,'-c',script,str(p),'/prefix'],check=True)
            patched=p.read_text().replace(anchor,'')
            for platform in ['Android','Linux']:
                old='--target=aarch64-linux-android26 -isystem/prefix/include/c++/v1 -isystem/prefix/include'
                p.write_text(f'set(CMAKE_SYSTEM_NAME {platform})\nset(CMAKE_CXX_FLAGS "{old}")\n'+patched+'\nfile(WRITE "${CMAKE_CURRENT_LIST_DIR}/flags.txt" "${CMAKE_CXX_FLAGS}")\nif(NOT BUILD_TESTING)\n message(FATAL_ERROR "Tests disabled")\nendif()\n')
                subprocess.run(['cmake','-P',str(p)],check=True)
                flags=(Path(tmp)/'flags.txt').read_text()
                self.assertEqual(('-nostdinc++ -I/prefix/include/c++/v1 '+old) if platform=='Android' else old,flags)

    @unittest.skipUnless(shutil.which('cmake'), 'CMake unavailable')
    def test_testing_product_keeps_target_flags_and_host_unchanged(self):
        recipe=swift_target_cxx_headers("termux_step_make() {\n\t--install-swift-driver --install-sourcekit-lsp\n}")
        script=recipe.split("<<'TERMI_SWIFT_TESTING_IMPORTERS'\n")[1].split('\nTERMI_SWIFT_TESTING_IMPORTERS')[0]
        anchor='project(SwiftTesting\n  LANGUAGES CXX Swift)'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'CMakeLists.txt'
            p.write_text(anchor+'\n')
            subprocess.run([sys.executable,'-c',script,str(p),'/prefix','/source/android.modulemap'],check=True)
            patched=p.read_text().replace(anchor,'')
            # Evaluate the real generated conditional while avoiding unrelated
            # compiler discovery. Existing target/sdk flags must survive.
            for platform in ['Android','Linux']:
                p.write_text(f'set(CMAKE_SYSTEM_NAME {platform})\nset(CMAKE_Swift_FLAGS "-target android26 -sdk /ndk")\n'+patched+'\nfile(WRITE "${CMAKE_CURRENT_LIST_DIR}/flags.txt" "${CMAKE_Swift_FLAGS}")\n')
                subprocess.run(['cmake','-P',str(p)],check=True)
                flags=(Path(tmp)/'flags.txt').read_text()
                self.assertTrue(flags.startswith('-target android26 -sdk /ndk'))
                if platform=='Android':
                    self.assertIn('-Xcc -nostdlibinc',flags)
                    self.assertIn('-Xcc -isystem/prefix/include',flags)
                    self.assertIn('-Xcc -fmodule-map-file=/source/android.modulemap',flags)
                else:
                    self.assertEqual('-target android26 -sdk /ndk',flags)
            p.write_text('project(Changed)')
            failed=subprocess.run([sys.executable,'-c',script,str(p),'/prefix','/source/android.modulemap'],capture_output=True)
            self.assertNotEqual(0,failed.returncode)

    def test_swiftpm_destination_uses_matching_cxx_without_changing_sdk_or_links(self):
        import json
        import types
        recipe=swift_target_cxx_headers("termux_step_make() {\n\t--install-swift-driver --install-sourcekit-lsp\n}")
        script=recipe.split("<<'TERMI_SWIFTPM_DESTINATION'\n")[1].split('\nTERMI_SWIFTPM_DESTINATION')[0]
        fixture=Path(__file__).with_name('fixtures')/'swift-android-destination.py'
        source=fixture.read_text()
        # Preserve upstream indentation and execute the actual JSON writer.
        wrapped='class AndroidPlatform:\n'+''.join('    '+line+'\n' for line in source.splitlines())
        args=types.SimpleNamespace(android_arch='aarch64',android_api_level=26,cross_compile_deps_path='/prefix-parent')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'targets.py';p.write_text(wrapped)
            before={};exec(compile(wrapped,str(p),'exec'),dict(os=os),before)
            old=before['AndroidPlatform']();old.ndk_toolchain_path=lambda _: '/ndk'
            old_dir=Path(tmp)/'before';old_dir.mkdir()
            original=json.loads(Path(old.swiftpm_config(args,str(old_dir),'/host','/resources')).read_text())
            subprocess.run([sys.executable,'-c',script,str(p),'/prefix-parent/usr','/src/android.modulemap'],check=True)
            after={};exec(compile(p.read_text(),str(p),'exec'),dict(os=os),after)
            new=after['AndroidPlatform']();new.ndk_toolchain_path=lambda _: '/ndk'
            new_dir=Path(tmp)/'after';new_dir.mkdir()
            updated=json.loads(Path(new.swiftpm_config(args,str(new_dir),'/host','/resources')).read_text())
            for key in ['target','sdk','toolchain-bin-dir','version']:
                self.assertEqual(original[key],updated[key])
            self.assertEqual(['-fPIC','-isystem/prefix-parent/usr/include'],updated['extra-cc-flags'])
            self.assertEqual(['-nostdinc++','-I/prefix-parent/usr/include/c++/v1',*original['extra-cpp-flags']],updated['extra-cpp-flags'])
            self.assertIn('-fmodule-map-file=/src/android.modulemap',updated['extra-swiftc-flags'])
            self.assertIn('-resource-dir',updated['extra-swiftc-flags'])
            self.assertIn('/resources',updated['extra-swiftc-flags'])
            self.assertIn('-L/prefix-parent/usr/lib',updated['extra-swiftc-flags'])
            p.write_text('changed source')
            failed=subprocess.run([sys.executable,'-c',script,str(p),'/prefix-parent/usr','/src/android.modulemap'],capture_output=True)
            self.assertNotEqual(0,failed.returncode)
