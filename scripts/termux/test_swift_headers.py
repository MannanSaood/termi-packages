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
            self.assertEqual(out.splitlines(),[f'-Xfrontend -strict-implicit-module-context -Xcc -nostdinc++ -Xcc -nostdlibinc -Xcc -I/prefix/include/c++/v1 -Xcc -I/prefix/include -Xcc -I/prefix/include/aarch64-linux-android -Xcc -fmodule-map-file={modulemap} original-swift-flags','original-swift-flags'])
            p.write_text(s+'\nunset TERMUX_PREFIX\ntermi_swift_main_importer_flags android-aarch64\nprintf "\\n"\ntermi_swift_main_importer_flags linux-x86_64\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),[f'-Xfrontend -strict-implicit-module-context -Xcc -nostdinc++ -Xcc -nostdlibinc -Xcc -I/prefix/include/c++/v1 -Xcc -I/prefix/include -Xcc -I/prefix/include/aarch64-linux-android -Xcc -fmodule-map-file={modulemap} '])
            p.write_text(s+'\nprintf "<%s>\\n" $(termi_swift_runtime_importer_option android-aarch64)\nprintf "HOST:<%s>\\n" "$(termi_swift_runtime_importer_option linux-x86_64)"\n')
            out=subprocess.check_output([bash,str(p)],text=True)
            self.assertEqual(out.splitlines(),[f'<-DSWIFT_RUNTIME_SWIFT_COMPILE_FLAGS:STRING=-Xfrontend;-strict-implicit-module-context;-Xcc;-nostdinc++;-Xcc;-nostdlibinc;-Xcc;-I/prefix/include/c++/v1;-Xcc;-I/prefix/include;-Xcc;-I/prefix/include/aarch64-linux-android;-Xcc;-fmodule-map-file={modulemap}>','HOST:<>'])
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
