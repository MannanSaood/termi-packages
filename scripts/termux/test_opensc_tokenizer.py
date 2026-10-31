from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from catalog_repairs import OPENSC_TOKENIZER_PATCH


class OpenScTokenizerTest(unittest.TestCase):
    # Exact profile-options block from pinned OpenSC 0.27.1.
    source = '\tif (strchr(profile->name, \'+\') != NULL) {\n\t\tchar\t*s;\n\n\t\ti = 0;\n\t\t(void) strtok(profile->name, "+");\n\t\twhile ((s = strtok(NULL, "+")) != NULL) {\n\t\t\tif (i < SC_PKCS15INIT_MAX_OPTIONS-1)\n\t\t\t\tprofile->options[i++] = strdup(s);\n\t\t}\n\t}\n'

    def patch(self, path):
        return subprocess.run([sys.executable, '-c', OPENSC_TOKENIZER_PATCH,
                               str(path)], capture_output=True, text=True)

    def test_drift_and_reapplication_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.c'
            path.write_text(self.source.replace('strtok(profile->name', 'changed(profile->name'))
            self.assertNotEqual(0, self.patch(path).returncode)
            path.write_text(self.source)
            result = self.patch(path)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotEqual(0, self.patch(path).returncode)

    @unittest.skipUnless(shutil.which('cc'), 'host C compiler unavailable')
    def test_option_order_bounds_and_surrounding_tokenizer_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'profile.c'
            path.write_text(self.source)
            result = self.patch(path)
            self.assertEqual(0, result.returncode, result.stderr)
            fixed = path.read_text()
            prefix = """#define _POSIX_C_SOURCE 200809L
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#define SC_PKCS15INIT_MAX_OPTIONS 16
struct profile { char *name; char *options[SC_PKCS15INIT_MAX_OPTIONS]; };
"""
            body = prefix + 'static void original(struct profile *profile) { int i;\n' + self.source + '}\n'
            body += 'static void repaired(struct profile *profile) { int i;\n' + fixed + '}\n'
            body += """
static void release(struct profile *p) {
    for (int i=0; i<SC_PKCS15INIT_MAX_OPTIONS; ++i) free(p->options[i]);
    free(p->name);
}
static void compare(const char *input) {
    struct profile a={0}, b={0}; a.name=strdup(input); b.name=strdup(input);
    assert(a.name && b.name); original(&a); repaired(&b);
    assert(memcmp(a.name,b.name,strlen(input)+1)==0);
    for (int i=0; i<SC_PKCS15INIT_MAX_OPTIONS; ++i) {
        assert((a.options[i]==NULL)==(b.options[i]==NULL));
        if (a.options[i]) assert(strcmp(a.options[i],b.options[i])==0);
    }
    assert(a.options[15]==NULL && b.options[15]==NULL); release(&a); release(&b);
}
int main(void) {
    const char *cases[]={"base", "base+one", "base++one+++two+", "+base+one", "+++", ""};
    for (size_t i=0;i<sizeof(cases)/sizeof(cases[0]);++i) compare(cases[i]);
    char many[1024]="base", part[32];
    for (int i=0;i<30;++i) { snprintf(part,sizeof(part),"+option%d",i); strcat(many,part); }
    compare(many);
    char outer[]="left:right"; assert(strcmp(strtok(outer,":"),"left")==0);
    struct profile p={0}; p.name=strdup("base+one+two"); assert(p.name); repaired(&p);
    char *next=strtok(NULL,":"); assert(next && strcmp(next,"right")==0); release(&p);
}
"""
            path.write_text(body)
            exe = root / 'probe'
            result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                     str(path), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
