"""Exercise the actual focused loop with successful and failed compilers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class FocusedCleanupTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Linux builder shell')
    def test_both_outcomes_record_progress_then_reclaim_scratch(self):
        source=Path(__file__).with_name('build-in-container.sh').read_text()
        branch=source.split('elif [ "$mode" = packages ]; then',1)[1]
        loop='for root in "$@"; do\n'+branch.split('    for root in "$@"; do\n',1)[1].split('\nelif [ "$mode" = catalog ];',1)[0]
        loop=loop.replace('./build-package.sh','fake_build').replace('"/home/builder/catalog-state/logs/$root-$attempt.log"','/dev/null')
        loop=loop.replace('if [ -f "$tree/$root/build.sh" ]; then','if [ "$tree" = packages ]; then')
        setup='''set -euo pipefail
jobs=2;batch_result=0;HOME=/fixture
fake_build() { [[ "${@: -1}" != */bad ]]; }
python3() {
 case "$1" in
 -c) echo 1;;
 */build_scratch.py) echo "cleanup:${@: -1}" >> "$TRACE";;
 */catalog_progress.py)
 if [[ "$*" == *'--status built'* ]]; then echo built >> "$TRACE"; fi
 if [[ "$*" == *'--status failed'* ]]; then echo failed >> "$TRACE"; fi;;
 *) return 99;;
 esac
}
tee() { cat; }
df() { :; }
mkdir() { :; }
'''
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'probe.sh';trace=Path(tmp)/'trace'
            script.write_text(setup+loop+'\n[[ "$batch_result" == 1 ]]\n')
            subprocess.run([shutil.which('bash'),str(script),'good','bad'],check=True,env={**os.environ,'TRACE':str(trace)})
            self.assertEqual(['built','cleanup:good','failed','cleanup:bad'],trace.read_text().splitlines())
