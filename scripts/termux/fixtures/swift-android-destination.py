# From swiftlang/swift swift-6.4.1-RELEASE targets.py AndroidPlatform.swiftpm_config
# Copyright Swift project authors; Apache-2.0 with Runtime Library Exception.
def swiftpm_config(self, args, output_dir, swift_toolchain, resource_path):
    config_file = '%s/swiftpm-android-%s.json' % (output_dir, args.android_arch)

    if os.path.exists(config_file):
        print("Using existing config at %s" % config_file)
        return config_file

    spm_json = '{\n'
    spm_json += '  "version": 1,\n'
    spm_json += '  "target": "%s-unknown-linux-android%s",\n' % (
                args.android_arch, args.android_api_level)
    spm_json += '  "toolchain-bin-dir": "%s/bin",\n' % swift_toolchain
    spm_json += '  "sdk": "%s/sysroot",\n' % self.ndk_toolchain_path(args)

    spm_json += '  "extra-cc-flags": [ "-fPIC", "-I%s/usr/include" ],\n' % (
                args.cross_compile_deps_path)

    spm_json += '  "extra-swiftc-flags": [\n'
    spm_json += '    "-resource-dir", "%s",\n' % resource_path
    spm_json += '    "-tools-directory", "%s/bin",\n' % (
                self.ndk_toolchain_path(args))
    spm_json += '    "-Xcc", "-I%s/usr/include",\n' % args.cross_compile_deps_path
    spm_json += '    "-L%s/usr/lib"\n' % args.cross_compile_deps_path
    spm_json += '  ],\n'

    spm_json += '  "extra-cpp-flags": [ "-lstdc++" ]\n'
    spm_json += '}'

    with open(config_file, 'w') as f:
        f.write(spm_json)
    return config_file
