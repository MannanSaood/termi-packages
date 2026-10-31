import pathlib, shutil, subprocess, sys, tempfile, unittest
import catalog_repairs

RULE = 'ifeq ($(TARGET),win32)\n$(ERL_CALL): $(ERLCALL) ../include/ei.h $(MD_EILIB)\n\t$(ld_verbose) $(CC) -MD $(PROG_CFLAGS) $(THR_DEFS) -o $@ $(ERLCALL) \\\n\t\t-L$(OBJDIR) -lei_md $(THR_LIBS) $(LIBS) -lsocket\nelse\nifdef THR_DEFS\n$(ERL_CALL): $(ERLCALL) ../include/ei.h $(MT_EILIB)\n\t$(ld_verbose) $(CC) $(PROG_CFLAGS) $(THR_DEFS) $(LDFLAGS) -o $@ $(ERLCALL) \\\n\t\t-L$(OBJDIR) -lei $(THR_LIBS) $(LIBS)\nelse\n$(ERL_CALL): $(ERLCALL) ../include/ei.h $(ST_EILIB)\n\t$(ld_verbose) $(CC) $(PROG_CFLAGS) $(LDFLAGS) -o $@ $(ERLCALL) \\\n\t\t-L$(OBJDIR) -lei $(LIBS)\nendif\nendif\n'

def patch_program():
    class Captured(Exception): pass
    body = []
    def change(name, edit, **kwargs):
        if name == 'erlang': edit('original recipe\n')
    def hook(text, name, script):
        body.append(script)
        raise Captured
    try: catalog_repairs.apply(change, hook, lambda _: '')
    except Captured: pass
    assert len(body) == 1
    return body[0].split("<<'TERMI_ERLANG_EI'\n",1)[1].rsplit('\nTERMI_ERLANG_EI',1)[0]

class ErlangArchiveLinkTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('ar') and shutil.which('make'), 'host C archive tools unavailable')
    def test_catalog_name_collision_selects_exact_local_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);src=root/'src';src.mkdir();(root/'include').mkdir();(root/'include/ei.h').write_text('')
            prefix=root/'prefix';prefix.mkdir();obj=root/'obj';obj.mkdir()
            (src/'wrong.c').write_text('int input_emulation(void) { return 1; }\n')
            (src/'ei.c').write_text('int ei_init(void) { return 0; }\n')
            (src/'main.c').write_text('int ei_init(void); int main(void) { return ei_init(); }\n')
            subprocess.run(['cc','-shared','-fPIC',str(src/'wrong.c'),'-o',str(prefix/'libei.so')],check=True,capture_output=True)
            subprocess.run(['cc','-c',str(src/'ei.c'),'-o',str(obj/'ei.o')],check=True,capture_output=True)
            subprocess.run(['ar','rcs',str(obj/'libei.a'),str(obj/'ei.o')],check=True,capture_output=True)
            for threaded in [False,True]:
                with self.subTest(threaded=threaded):
                    target=root/('erl_call_mt' if threaded else 'erl_call_st')
                    header=f'TARGET=android\nERL_CALL={target}\nERLCALL=main.c\nCC=cc\nOBJDIR={obj}\nMT_EILIB={obj}/libei.a\nST_EILIB={obj}/libei.a\nLDFLAGS=-L{prefix}\n'
                    if threaded: header += 'THR_DEFS=-D_THREAD_SAFE\nTHR_LIBS=-pthread\n'
                    makefile=src/'Makefile';makefile.write_text(header+RULE)
                    before=subprocess.run(['make','-f',str(makefile),str(target)],cwd=src,capture_output=True,text=True)
                    self.assertNotEqual(before.returncode,0)
                    self.assertIn('ei_init',before.stderr)
                    subprocess.run([sys.executable,'-c',patch_program(),str(makefile)],check=True,capture_output=True)
                    after=subprocess.run(['make','-f',str(makefile),str(target)],cwd=src,capture_output=True,text=True)
                    self.assertEqual(after.returncode,0,after.stdout+after.stderr)
                    self.assertEqual(subprocess.run([str(target)]).returncode,0)

    def test_rejects_source_drift_and_reapplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=pathlib.Path(tmp)/'Makefile.in';original=RULE;f.write_text(original)
            subprocess.run([sys.executable,'-c',patch_program(),str(f)],check=True,capture_output=True)
            repaired=f.read_text();self.assertIn('$(MT_EILIB) $(THR_LIBS) $(LIBS)',repaired)
            again=subprocess.run([sys.executable,'-c',patch_program(),str(f)],capture_output=True)
            self.assertNotEqual(again.returncode,0);self.assertEqual(f.read_text(),repaired)
            f.write_text(original.replace('-L$(OBJDIR) -lei $(THR_LIBS) $(LIBS)','changed'))
            drift=subprocess.run([sys.executable,'-c',patch_program(),str(f)],capture_output=True)
            self.assertNotEqual(drift.returncode,0)
