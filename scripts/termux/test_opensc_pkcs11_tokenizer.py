from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from catalog_repairs import OPENSC_PKCS11_TOKENIZER_PATCH

# Exact pinned OpenSC 0.27.1 tokenizer fragments.
FIXTURES = {'src/pkcs11/misc.c': 'char *create_slots_for_pins = NULL, *op, *tmp;\n\top = strtok(tmp, " ,");\n\twhile (op) {\n\t\tif (!strcmp(op, "user"))\n\t\t\tconf->create_slots_flags |= SC_PKCS11_SLOT_FOR_PIN_USER;\n\t\telse if (!strcmp(op, "sign"))\n\t\t\tconf->create_slots_flags |= SC_PKCS11_SLOT_FOR_PIN_SIGN;\n\t\telse if (!strcmp(op, "all"))\n\t\t\tconf->create_slots_flags |= SC_PKCS11_SLOT_CREATE_ALL;\n\t\top = strtok(NULL, " ,");\n\t}\n', 'src/tools/pkcs11-tool.c': 'char *s = NULL;\n\t\t\ts = strtok(optarg, ",");\n\t\t\twhile (s != NULL) {\n\t\t\t\tif (opt_allowed_mechanisms_len > MAX_ALLOWED_MECHANISMS) {\n\t\t\t\t\tfprintf(stderr, "Too many mechanisms provided"\n\t\t\t\t\t\t" (max %d). Skipping the rest.", MAX_ALLOWED_MECHANISMS);\n\t\t\t\t\tbreak;\n\t\t\t\t}\n\n\t\t\t\topt_allowed_mechanisms[opt_allowed_mechanisms_len] =\n\t\t\t\t\tp11_name_to_mechanism(s);\n\t\t\t\topt_allowed_mechanisms_len++;\n\t\t\t\ts = strtok(NULL, ",");\n\t\t\t}', 'src/tools/pkcs11_uri.c': 'char *path, *query, *token;\npath = strtok(path, "?");\nquery = strtok(NULL, "?");\ntoken = strtok(path, ";");\ntoken = strtok(NULL, ";");\ntoken = strtok(query, ";");\ntoken = strtok(NULL, ";");\n'}

class OpenScPkcs11TokenizerTest(unittest.TestCase):
    def patch(self, root):
        return subprocess.run([sys.executable, '-c', OPENSC_PKCS11_TOKENIZER_PATCH, str(root)], capture_output=True, text=True)

    def prepare(self, root):
        for name, source in FIXTURES.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(source)

    def test_all_anchors_validated_before_mutation_and_repeat_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            bad = root / 'src/tools/pkcs11_uri.c'
            bad.write_text(bad.read_text().replace('strtok(query,', 'changed(query,'))
            before = {p: p.read_text() for p in root.rglob('*.c')}
            self.assertNotEqual(0, self.patch(root).returncode)
            self.assertEqual(before, {p: p.read_text() for p in root.rglob('*.c')})
            self.prepare(root)
            result = self.patch(root)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotEqual(0, self.patch(root).returncode)
            for p in root.rglob('*.c'):
                self.assertNotIn('strtok(', p.read_text())

    @unittest.skipUnless(shutil.which('cc'), 'host C compiler unavailable')
    def test_slot_and_mechanism_lists_preserve_results_and_outer_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            result = self.patch(root)
            self.assertEqual(0, result.returncode, result.stderr)
            code = '#define _POSIX_C_SOURCE 200809L\n#include <assert.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n'
            code += '#define SC_PKCS11_SLOT_FOR_PIN_USER 1\n#define SC_PKCS11_SLOT_FOR_PIN_SIGN 2\n#define SC_PKCS11_SLOT_CREATE_ALL 3\n#define MAX_ALLOWED_MECHANISMS 2\n'
            code += 'static unsigned p11_name_to_mechanism(const char *s) { unsigned n=0; while(*s) n=n*31+(unsigned char)*s++; return n; }\n'
            for name in ['slots', 'mechanisms']:
                file = 'src/pkcs11/misc.c' if name == 'slots' else 'src/tools/pkcs11-tool.c'
                for variant, source in [('original', FIXTURES[file]), ('fixed', (root/file).read_text())]:
                    # Declarations and bodies are exact source statements. Only harness inputs/providers differ.
                    if name == 'slots':
                        decl, fragment = source.split('\n', 1)
                        code += 'static unsigned '+variant+'_slots(char *input) { struct {unsigned create_slots_flags;} config={0}, *conf=&config; '+decl+' (void)create_slots_for_pins; tmp=input;\n'+fragment+'return conf->create_slots_flags; }\n'
                    else:
                        decl, fragment = source.split('\n', 1)
                        code += 'static unsigned '+variant+'_mechanisms(char *optarg, unsigned *out) { unsigned opt_allowed_mechanisms_len=0; unsigned *opt_allowed_mechanisms=out; '+decl+'\n'+fragment+'return opt_allowed_mechanisms_len; }\n'
            code += r"""
int main(void) {
 const char *cases[]={"", "user", "user,sign", " ,user,, sign  ,", "all,unknown,user", "one,two,three,four,five", ",,,"};
 for(size_t i=0;i<sizeof(cases)/sizeof(cases[0]);++i) {
  char *a=strdup(cases[i]),*b=strdup(cases[i]); assert(a&&b);
  assert(original_slots(a)==fixed_slots(b)); assert(memcmp(a,b,strlen(cases[i])+1)==0); free(a);free(b);
  a=strdup(cases[i]);b=strdup(cases[i]); unsigned x[4]={0},y[4]={0};
  assert(original_mechanisms(a,x)==fixed_mechanisms(b,y));assert(memcmp(x,y,sizeof(x))==0);free(a);free(b);
 }
 char outer[]="left:right", slots[]="user,sign", mechanisms[]="one,two"; unsigned out[4]={0};
 assert(strcmp(strtok(outer,":"),"left")==0);assert(fixed_slots(slots)==3);fixed_mechanisms(mechanisms,out);
 char *next=strtok(NULL,":");assert(next&&strcmp(next,"right")==0);
}
"""
            p = root/'probe.c'; p.write_text(code)
            result = subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p),'-o',str(root/'probe')],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            result = subprocess.run([str(root/'probe')],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
