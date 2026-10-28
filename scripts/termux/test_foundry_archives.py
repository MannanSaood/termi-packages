import subprocess
import sys
import tempfile
from pathlib import Path
import tomllib
import unittest

from recipe_repairs import foundry_unique_native_archives


class FoundryArchivesTests(unittest.TestCase):
    def repair(self, root):
        recipe='\tcargo vendor\n\t\t! -wholename ./vendor/cc \\\n'
        patched=foundry_unique_native_archives(recipe)
        script=patched.split("<<'TERMI_SECP_ARCHIVES'\n",1)[1].split('\nTERMI_SECP_ARCHIVES',1)[0]
        return subprocess.run([sys.executable,'-c',script],cwd=root,capture_output=True,text=True)

    def fixture(self, root, versions):
        (root/'Cargo.toml').write_text('[patch.crates-io]\nexisting={path="vendor/existing"}\n')
        for version in versions:
            directory=root/'vendor'/('secp256k1-sys-'+version)
            directory.mkdir(parents=True)
            (directory/'Cargo.toml').write_text('[package]\nname="secp256k1-sys"\nversion="'+version+'"\n')
            (directory/'build.rs').write_text('base.try_compile("libsecp256k1.a");\nbase.compile("libsecp256k1.a");\n')

    def test_both_crate_versions_use_distinct_names_and_keep_existing_patches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root,['0.10.1','0.11.0'])
            result=self.repair(root);self.assertEqual(result.returncode,0,result.stderr)
            patches=tomllib.loads((root/'Cargo.toml').read_text())['patch']['crates-io']
            self.assertIn('existing',patches)
            for version in ['0.10.1','0.11.0']:
                key='termi_secp_'+version.replace('.','_')
                self.assertEqual(patches[key]['package'],'secp256k1-sys')
                build=(root/patches[key]['path']/'build.rs').read_text()
                self.assertNotIn('"libsecp256k1.a"',build)
                self.assertIn('libtermi_secp256k1_'+version.replace('.','_')+'.a',build)

    def test_missing_pinned_version_stops_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root,['0.11.0'])
            result=self.repair(root);self.assertNotEqual(result.returncode,0)
            self.assertIn('Missing pinned',result.stderr)


if __name__=='__main__':
    unittest.main()
