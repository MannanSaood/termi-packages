import json, os, pathlib, shutil, subprocess, tempfile, unittest
import catalog_repairs

SOURCE = 'termux_step_pre_configure() {\n\ttermux_setup_proot\n\tlocal protoc_wrapper="${TERMUX_PKG_TMPDIR}/protoc-proot"\n\tprintf \'#!/bin/bash\\nexec termux-proot-run %s/bin/protoc "$@"\\n\' "${TERMUX_PREFIX}" > "${protoc_wrapper}"\n\tchmod +x "${protoc_wrapper}"\n}\n'

def prepared():
    class Captured(Exception): pass
    result=[]
    def change(name, edit, **kwargs):
        if name=='mapserver': result.append(edit(SOURCE)); raise Captured
    def hook(text, name, body):
        anchor=name+'() {\n'; assert text.count(anchor)==1
        return text.replace(anchor,anchor+body,1)
    try: catalog_repairs.apply(change, hook, {})
    except Captured: pass
    assert len(result)==1
    return result[0]

@unittest.skipUnless(os.name=='posix' and shutil.which('bash'), 'POSIX shell required')
class MapserverProotBindingTest(unittest.TestCase):
    def test_private_binding_preserves_generator_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);prefix=root/'prefix';work=root/'work with spaces';bin=root/'bin';work.mkdir();bin.mkdir();(prefix/'opt/aosp/bin').mkdir(parents=True);(prefix/'opt/aosp/bin/linker64').write_text('source-built linker fixture')
            runner=bin/'termux-proot-run';original='#!/bin/bash\nexec proot -R / "$@"\n';runner.write_text(original);runner.chmod(0o755)
            stub=bin/'proot';stub.write_text('#!/bin/bash\npython3 -c \'import json,sys; print(json.dumps(sys.argv[1:]))\' "$@"\n');stub.chmod(0o755)
            env={**os.environ,'PATH':str(bin)+os.pathsep+os.environ['PATH'],'TERMUX_PKG_TMPDIR':str(work),'TERMUX_PREFIX':str(prefix),'TERMUX_PKG_EXTRA_CONFIGURE_ARGS':''}
            command='set -e\ntermux_setup_proot() { :; }\n'+prepared()+'\ntermux_step_pre_configure\n"$TERMUX_PKG_TMPDIR/protoc-proot" "--c_out=output directory" "file with spaces.proto"\n'
            result=subprocess.run(['bash','-c',command],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),['-R','/','-b',str(prefix/'opt/aosp')+':/system',str(prefix/'bin/protoc'),'--c_out=output directory','file with spaces.proto'])
            self.assertEqual(runner.read_text(),original)
            self.assertTrue((work/'termi-mapserver-proot-bin/termux-proot-run').is_file())

    def test_missing_completed_linker_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);bin=root/'bin';bin.mkdir();runner=bin/'termux-proot-run';runner.write_text('#!/bin/bash\nexec proot -R / "$@"\n');runner.chmod(0o755)
            env={**os.environ,'PATH':str(bin)+os.pathsep+os.environ['PATH'],'TERMUX_PKG_TMPDIR':str(root),'TERMUX_PREFIX':str(root/'missing')}
            r=subprocess.run(['bash','-c','set -e\ntermux_setup_proot() { :; }\n'+prepared()+'\ntermux_step_pre_configure'],env=env,capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0);self.assertIn('Source-built Android linker missing',r.stderr)
